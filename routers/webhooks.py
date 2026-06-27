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
    The contact_id comes in utm_content parameter we added to the link.
    """
    payload = await request.json()
    event   = payload.get("event")
    data    = payload.get("payload", {})

    if event == "invitee.created":
        return await _handle_booking(data, background_tasks, db)

    elif event == "invitee.canceled":
        return await _handle_cancellation(data, db)

    return {"status": "ok", "event": event}


async def _handle_booking(data: dict, background_tasks: BackgroundTasks, db: Session):
    """Someone booked a meeting"""

    # Extract contact_id from UTM params
    contact_id = (
        data.get("tracking", {}).get("utm_content") or
        data.get("utm_params", {}).get("utm_content")
    )

    # Find contact by ID or fall back to email
    contact = None
    if contact_id:
        contact = db.query(Contact).filter(Contact.id == contact_id).first()

    if not contact:
        email = data.get("email")
        if email:
            contact = db.query(Contact).filter(Contact.email == email).first()

    if not contact:
        # Create a new contact from the Calendly booking
        contact = Contact(
            id         = str(uuid.uuid4()),
            first_name = data.get("first_name"),
            last_name  = data.get("last_name"),
            email      = data.get("email"),
            source     = "calendly",
            status     = "appointment_scheduled",
        )
        db.add(contact)
        db.flush()

    # Parse scheduled time
    scheduled_at = None
    event_data   = data.get("event", {}) or data.get("scheduled_event", {})
    start_time   = event_data.get("start_time")
    if start_time:
        try:
            scheduled_at = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
        except Exception:
            scheduled_at = None

    # Assign to first available sales rep
    assigned_user = db.query(User).first()

    # Create appointment
    appt = Appointment(
        id                = str(uuid.uuid4()),
        contact_id        = contact.id,
        assigned_to_id    = assigned_user.id if assigned_user else None,
        calendly_event_id = data.get("uri") or data.get("event", {}).get("uri", ""),
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

    # Generate AI summary synchronously — avoids SQLite threading issues
    try:
        from agents.scheduler import scheduler_agent
        # Refresh objects after commit
        db.refresh(contact)
        db.refresh(appt)
        scheduler_agent.generate_summary(contact, appt, db)
        print(f"[Scheduler] Summary generated for {contact.first_name} {contact.last_name}")
    except Exception as e:
        print(f"[Scheduler] Error generating summary: {e}")

    return {
        "status":         "booked",
        "contact_id":     contact.id,
        "appointment_id": appt.id,
        "scheduled_at":   str(scheduled_at),
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
    Payload is an array: [form_submission_object, form_object]
    """
    payload = await request.json()
     print(f"[Kajabi webhook] Raw payload: {payload}")

    # Payload is a list — find the form_submission item
    submission = None
    for item in payload:
        if item.get("type") == "form_submissions":
            submission = item
            break

    if not submission:
        return {"status": "ignored", "reason": "no form_submission in payload"}

    attrs = submission.get("attributes", {})
    email = attrs.get("email")

    if not email:
        return {"status": "ignored", "reason": "no email in submission"}

    # Duplicate check
    from database import Contact, SyncLog
    import uuid

    existing = db.query(Contact).filter(Contact.email == email).first()
    if existing:
        db.add(SyncLog(
            id=str(uuid.uuid4()), contact_id=existing.id,
            platform="kajabi", action="webhook_received",
            tag="duplicate_skipped", status="success",
        ))
        db.commit()
        return {"status": "duplicate", "contact_id": existing.id}

    # Create new contact
    full_name  = (attrs.get("name") or "").strip()
    name_parts = full_name.split(" ", 1) if full_name else ["", ""]

    contact = Contact(
        id         = str(uuid.uuid4()),
        first_name = attrs.get("first_name") or (name_parts[0] if name_parts else None),
        last_name  = attrs.get("last_name")  or (name_parts[1] if len(name_parts) > 1 else None),
        email      = email,
        phone      = attrs.get("phone_number") or attrs.get("mobile_phone_number"),
        source     = "kajabi",
        status     = "pending",
        subscribed = "true",  # if they submitted a form they opted in
    )
    db.add(contact)
    db.add(SyncLog(
        id=str(uuid.uuid4()), contact_id=contact.id,
        platform="kajabi", action="form_submitted",
        tag="new_lead", status="success",
    ))
    db.commit()

    # Auto-classify with Claude in background
    from agents.classifier import classifier_agent
    try:
        classifier_agent.classify(contact, db)
    except Exception as e:
        print(f"[Kajabi webhook] Classifier error: {e}")

    return {"status": "created", "contact_id": contact.id}
