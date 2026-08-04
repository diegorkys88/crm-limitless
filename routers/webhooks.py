from fastapi import APIRouter, Depends, Request, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from db_session import get_db
from database import Contact, Appointment, SyncLog, User
import uuid
from datetime import datetime

router = APIRouter()


# ── Calendly ───────────────────────────────────────────────────────────────────

@router.post("/calendly")
async def calendly_webhook(
    request:          Request,
    background_tasks: BackgroundTasks,
    db:               Session = Depends(get_db)
):
    """
    Calendly fires this when someone books or cancels a meeting.
    Real payload: {"event": "invitee.created", "payload": {"invitee": {...}, "scheduled_event": {...}, "tracking": {...}}}
    """
    payload = await request.json()
    print(f"[Calendly webhook] FULL PAYLOAD: {payload}")

    event = payload.get("event")
    data  = payload.get("payload", {})

    if event == "invitee.created":
        return await _handle_booking(data, background_tasks, db)
    elif event == "invitee.canceled":
        return await _handle_cancellation(data, db)

    return {"status": "ignored", "event": event}


async def _handle_booking(data: dict, background_tasks, db: Session):
    """Someone booked a meeting"""

    # Real Calendly payload structure:
    # data = { "invitee": {...}, "event": "<uri string>", "scheduled_event": {...}, "tracking": {...} }
    invitee  = data.get("invitee", {}) if isinstance(data.get("invitee"), dict) else {}
    tracking = data.get("tracking", {}) if isinstance(data.get("tracking"), dict) else {}

    # Extract contact_id from UTM content (added when we generate the Calendly link)
    contact_id = (
        tracking.get("utm_content") or
        (data.get("utm_params", {}) or {}).get("utm_content")
    )

    # Get email — real payload has it in invitee.email
    email = invitee.get("email") or data.get("email")

    # Find contact by ID first, then by email
    contact = None
    if contact_id:
        contact = db.query(Contact).filter(Contact.id == contact_id).first()

    if not contact and email:
        contact = db.query(Contact).filter(Contact.email == email).first()

    if not contact and email:
        # Create new contact from Calendly booking
        # Name may come split (first_name/last_name) OR whole (name/full_name).
        first = invitee.get("first_name") or data.get("first_name")
        last  = invitee.get("last_name")  or data.get("last_name")

        if not first:
            # Try the combined name field Calendly often sends
            whole = (invitee.get("name") or invitee.get("full_name")
                     or data.get("name") or "").strip()
            if whole:
                parts = whole.split(" ", 1)
                first = parts[0]
                last  = parts[1] if len(parts) > 1 else None
            else:
                # Last resort: derive a readable first name from the email
                local = email.split("@")[0]
                local = local.replace(".", " ").replace("_", " ").replace("-", " ")
                first = local.split(" ")[0].capitalize() if local else email

        contact = Contact(
            id         = str(uuid.uuid4()),
            first_name = first,
            last_name  = last,
            email      = email,
            source     = "calendly",
            status     = "appointment_scheduled",
        )
        db.add(contact)
        db.flush()

    if not contact:
        return {"status": "ignored", "reason": "no email in payload"}

    # Parse scheduled time
    # In real Calendly payload, data["event"] is a URI string not a dict.
    # start_time comes from data["scheduled_event"]["start_time"] (UTC)
    scheduled_at = None
    event_uri    = data.get("event", "")

    event_data = data.get("scheduled_event", {})
    if isinstance(event_data, dict):
        start_time = event_data.get("start_time")
    else:
        start_time = invitee.get("start_time") or data.get("start_time")

    if start_time:
        try:
            scheduled_at = datetime.fromisoformat(str(start_time).replace("Z", "+00:00"))
            # Store as naive UTC for DB consistency
            scheduled_at = scheduled_at.replace(tzinfo=None)
        except Exception:
            scheduled_at = None

    # Assign to first active sales rep, fallback to any user
    assigned_user = db.query(User).filter(
        User.role == "super_admin", User.is_active == "true"
    ).first()
    if not assigned_user:
        assigned_user = db.query(User).first()

    # Create appointment
    appt = Appointment(
        id                = str(uuid.uuid4()),
        contact_id        = contact.id,
        assigned_to_id    = assigned_user.id if assigned_user else None,
        calendly_event_id = event_uri if isinstance(event_uri, str) else str(event_uri),
        scheduled_at      = scheduled_at,
        status            = "scheduled",
    )
    db.add(appt)

    # Update contact status
    contact.status = "appointment_scheduled"

    # Log sync
    db.add(SyncLog(
        id         = str(uuid.uuid4()),
        contact_id = contact.id,
        platform   = "calendly",
        action     = "appointment_booked",
        tag        = "crm-scheduled",
        status     = "success",
    ))
    db.commit()

    # Add crm-scheduled tag in Kajabi if contact has kajabi_id
    if contact.kajabi_id:
        try:
            from services.kajabi import kajabi_service
            kajabi_service.tag_contact_by_name(contact.kajabi_id, "crm-scheduled")
            db.add(SyncLog(
                id=str(uuid.uuid4()), contact_id=contact.id,
                platform="kajabi", action="add_tag",
                tag="crm-scheduled", status="success",
            ))
            db.commit()
        except Exception as e:
            print(f"[Kajabi tag] crm-scheduled error: {e}")

    # Generate AI summary synchronously
    summary = None
    try:
        from agents.scheduler import scheduler_agent
        db.refresh(contact)
        db.refresh(appt)
        summary = scheduler_agent.generate_summary(contact, appt, db)
        print(f"[Scheduler] Summary generated for {contact.first_name} {contact.last_name}")
    except Exception as e:
        print(f"[Scheduler] Error generating summary: {e}")

    # Send briefing email to assigned sales rep
    if assigned_user and summary:
        try:
            from services.email import email_service
            import os
            from zoneinfo import ZoneInfo
            from datetime import timezone as tz

            if scheduled_at:
                # DB stores naive UTC — attach UTC then convert to business timezone
                aware = scheduled_at.replace(tzinfo=tz.utc)
                local = aware.astimezone(ZoneInfo("America/New_York"))
                scheduled_str = local.strftime("%B %d, %Y at %I:%M %p ET")
            else:
                scheduled_str = "TBD"

            contact_name = f"{contact.first_name or ''} {contact.last_name or ''}".strip() or contact.email
            crm_url      = os.getenv("CRM_URL", "https://web-production-5bd62.up.railway.app")

            body = f"""Hi {assigned_user.name},

You have a new meeting scheduled.

Contact: {contact_name}
Email: {contact.email}
Scheduled: {scheduled_str}

--- PRE-MEETING BRIEFING ---

{summary}

---

View contact in CRM: {crm_url}/dashboard

The Leadership Coaching Team"""

            email_service.send(
                to_email    = assigned_user.email,
                to_name     = assigned_user.name,
                subject     = f"📅 Meeting scheduled — {contact_name} ({scheduled_str})",
                body        = body,
                sender_name = "Limitless Leadership CRM",
            )
            print(f"[Scheduler] Briefing email sent to {assigned_user.email}")
        except Exception as e:
            print(f"[Scheduler] Briefing email error: {e}")

    return {
        "status":         "appointment_created",
        "appointment_id": appt.id,
        "contact_id":     contact.id,
        "assigned_to":    assigned_user.name if assigned_user else None,
    }

async def _handle_cancellation(data: dict, db: Session):
    """Someone cancelled a meeting"""
    event_uri = data.get("uri", "")

    appt = db.query(Appointment).filter(
        Appointment.calendly_event_id == event_uri
    ).first()

    if appt:
        appt.status = "cancelled"
        contact = db.query(Contact).filter(Contact.id == appt.contact_id).first()
        if contact:
            contact.status = "outreach_sent"  # back to previous status
        db.add(SyncLog(
            id         = str(uuid.uuid4()),
            contact_id = appt.contact_id,
            platform   = "calendly",
            action     = "appointment_cancelled",
            tag        = "crm-contacted",
            status     = "success",
        ))
        db.commit()

    return {"status": "cancelled", "appointment_id": appt.id if appt else None}



# ── Simulate webhook for testing (no Calendly account needed) ─────────────────

@router.post("/calendly/simulate")
async def simulate_calendly_booking(
    contact_id:    str,
    scheduled_at:  str = "2026-06-01T14:00:00Z",
    db: Session = Depends(get_db)
):
    """
    Simulate a Calendly booking webhook — for testing without a paid plan.
    Creates a real appointment and generates the AI summary.
    """
    contact = db.query(Contact).filter(Contact.id == contact_id).first()
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")

    # Build a fake Calendly payload
    fake_payload = {
        "event":   "invitee.created",
        "payload": {
            "email":      contact.email,
            "first_name": contact.first_name,
            "last_name":  contact.last_name,
            "uri":        f"https://api.calendly.com/scheduled_events/fake-{contact_id}",
            "tracking":   {"utm_content": contact_id},
            "event":      {"start_time": scheduled_at},
        }
    }

    return await _handle_booking(fake_payload["payload"], None, db)


# ── ClickFunnels ───────────────────────────────────────────────────────────────

@router.post("/clickfunnels")
async def clickfunnels_webhook(request: Request, db: Session = Depends(get_db)):
    """
    ClickFunnels fires this when a visitor submits a form.
    We check for duplicates before creating the contact.
    """
    payload = await request.json()
    data    = payload.get("data", {}) or payload

    email = (
        data.get("email") or
        data.get("contact", {}).get("email")
    )
    if not email:
        raise HTTPException(status_code=400, detail="No email in payload")

    # Duplicate check
    existing = db.query(Contact).filter(Contact.email == email).first()
    if existing:
        db.add(SyncLog(
            id         = str(uuid.uuid4()),
            contact_id = existing.id,
            platform   = "clickfunnels",
            action     = "webhook_received",
            tag        = "duplicate_skipped",
            status     = "success",
        ))
        db.commit()
        return {"status": "duplicate", "contact_id": existing.id}

    contact = Contact(
        id              = str(uuid.uuid4()),
        first_name      = data.get("first_name"),
        last_name       = data.get("last_name"),
        email           = email,
        phone           = data.get("phone"),
        company         = data.get("company"),
        source          = "clickfunnels",
        clickfunnels_id = str(data.get("id", "")),
        status          = "pending",
    )
    db.add(contact)
    db.add(SyncLog(
        id         = str(uuid.uuid4()),
        contact_id = contact.id,
        platform   = "clickfunnels",
        action     = "contact_created",
        tag        = "new_lead",
        status     = "success",
    ))
    db.commit()

    # TODO: auto-trigger classifier + copywriter
    return {"status": "created", "contact_id": contact.id}


# ── Simulate ClickFunnels for testing ─────────────────────────────────────────

@router.post("/clickfunnels/simulate")
async def simulate_clickfunnels(
    email:      str,
    first_name: str = None,
    last_name:  str = None,
    company:    str = None,
    db: Session = Depends(get_db)
):
    """Simulate a ClickFunnels form submission — for testing"""
    from fastapi import Request as FRequest
    fake_data = {
        "email":      email,
        "first_name": first_name,
        "last_name":  last_name,
        "company":    company,
        "id":         "sim-001",
    }
    existing = db.query(Contact).filter(Contact.email == email).first()
    if existing:
        return {"status": "duplicate", "contact_id": existing.id}

    contact = Contact(
        id              = str(uuid.uuid4()),
        first_name      = first_name,
        last_name       = last_name,
        email           = email,
        company         = company,
        source          = "clickfunnels",
        clickfunnels_id = "sim-001",
        status          = "pending",
    )
    db.add(contact)
    db.add(SyncLog(
        id         = str(uuid.uuid4()),
        contact_id = contact.id,
        platform   = "clickfunnels",
        action     = "simulated_webhook",
        tag        = "new_lead",
        status     = "success",
    ))
    db.commit()
    return {"status": "created", "contact_id": contact.id}


# ── Kajabi ─────────────────────────────────────────
@router.post("/kajabi")
async def kajabi_webhook(request: Request, db: Session = Depends(get_db)):
    """
    Kajabi fires this when a form is submitted.
    Real payload format: {"event": "form_submission.created", "payload": {"Email": "...", "Name": "..."}}
    """
    payload = await request.json()
    print(f"[Kajabi webhook] Received: {payload}")

    event = payload.get("event", "")
    data  = payload.get("payload", {})

    if event != "form_submission.created":
        return {"status": "ignored", "event": event}

    email = data.get("Email") or data.get("email")
    if not email:
        return {"status": "ignored", "reason": "no email in payload"}

    from database import Contact, SyncLog
    import uuid

    # Duplicate check
    existing = db.query(Contact).filter(Contact.email == email).first()
    if existing:
        db.add(SyncLog(
            id=str(uuid.uuid4()), contact_id=existing.id,
            platform="kajabi", action="webhook_received",
            tag="duplicate_skipped", status="success",
        ))
        db.commit()
        return {"status": "duplicate", "contact_id": existing.id}

    # Parse name
    full_name  = (data.get("Name") or data.get("name") or "").strip()
    name_parts = full_name.split(" ", 1) if full_name else ["", ""]

    contact = Contact(
        id         = str(uuid.uuid4()),
        first_name = name_parts[0] if name_parts else None,
        last_name  = name_parts[1] if len(name_parts) > 1 else None,
        email      = email,
        phone      = data.get("phone_number") or data.get("Phone"),
        source     = "kajabi",
        status     = "pending",
        subscribed = "true",
    )
    db.add(contact)
    db.add(SyncLog(
        id=str(uuid.uuid4()), contact_id=contact.id,
        platform="kajabi", action="form_submitted",
        tag=data.get("form_title", "unknown_form"),
        status="success",
    ))
    db.commit()

    # Auto-enrich (economic — we already have the email) if corporate domain
    try:
        FREE = {"gmail.com","yahoo.com","hotmail.com","outlook.com","aol.com","icloud.com",
                "live.com","msn.com","protonmail.com","me.com","comcast.net","ymail.com",
                "att.net","verizon.net","gmx.com","mail.com"}
        domain = email.split("@")[1].lower() if "@" in email else ""
        if domain and domain not in FREE:
            from services.apollo import apollo_service
            data = apollo_service.enrich_person(
                email        = contact.email,
                first_name   = contact.first_name,
                last_name    = contact.last_name,
                domain       = domain,
                reveal_email = False,   # economic — email already known
            )
            if data:
                for field in ["title", "company", "industry", "region", "apollo_id", "phone_corporate", "linkedin_url", "city", "state", "website", "num_employees", "annual_revenue"]:
                    if not getattr(contact, field, None) and data.get(field):
                        setattr(contact, field, data[field])
                db.commit()
    except Exception as e:
        print(f"[Kajabi webhook] Auto-enrich error: {e}")

    # Auto-classify
    try:
        from agents.classifier import classifier_agent
        db.refresh(contact)
        classifier_agent.classify(contact, db)
    except Exception as e:
        print(f"[Kajabi webhook] Classifier error: {e}")

    return {"status": "created", "contact_id": contact.id}
