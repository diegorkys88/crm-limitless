from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List
from db_session import get_db
from database import Appointment, User, Contact, SyncLog
from schemas import AppointmentOut
from datetime import datetime, timedelta, timezone
import uuid

router = APIRouter()


@router.get("/", response_model=List[AppointmentOut])
def list_appointments(db: Session = Depends(get_db)):
    return db.query(Appointment).all()


@router.get("/{appt_id}", response_model=AppointmentOut)
def get_appointment(appt_id: str, db: Session = Depends(get_db)):
    appt = db.query(Appointment).filter(Appointment.id == appt_id).first()
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found")
    return appt


@router.post("/remind-overdue")
def remind_overdue_meetings(
    grace_hours: int = Query(2, description="Hours after the meeting time before it counts as overdue"),
    db: Session = Depends(get_db),
):
    """
    Find meetings whose time has passed but the contact is still 'appointment_scheduled'
    (nobody marked Won/Lost/No-Show yet), and email the assigned rep to close them out.
    Manual trigger — run whenever you want to nudge reps about pending meetings.
    """
    from services.email import email_service
    import os

    now    = datetime.utcnow()
    cutoff = now - timedelta(hours=grace_hours)

    # Overdue = scheduled in the past (beyond grace), still open, contact not closed
    overdue = (
        db.query(Appointment)
        .filter(
            Appointment.status == "scheduled",
            Appointment.scheduled_at != None,
            Appointment.scheduled_at < cutoff,
        )
        .all()
    )

    reminded = 0
    skipped  = 0
    details  = []
    crm_url  = os.getenv("CRM_URL", "https://web-production-5bd62.up.railway.app")

    for appt in overdue:
        contact = db.query(Contact).filter(Contact.id == appt.contact_id).first()
        if not contact:
            skipped += 1
            continue

        # Only remind if the contact is still sitting at appointment_scheduled
        if contact.status != "appointment_scheduled":
            skipped += 1
            continue

        rep = db.query(User).filter(User.id == appt.assigned_to_id).first() if appt.assigned_to_id else None
        if not rep or not rep.email:
            skipped += 1
            continue

        # Format the meeting time in Eastern
        when = "recently"
        if appt.scheduled_at:
            try:
                from zoneinfo import ZoneInfo
                aware = appt.scheduled_at.replace(tzinfo=timezone.utc)
                local = aware.astimezone(ZoneInfo("America/New_York"))
                when = local.strftime("%B %d, %Y at %I:%M %p ET")
            except Exception:
                when = str(appt.scheduled_at)

        contact_name = f"{contact.first_name or ''} {contact.last_name or ''}".strip() or contact.email

        body = f"""Hi {rep.name},

Your meeting with {contact_name} was scheduled for {when} and it's still open in the CRM.

How did it go? Please update the contact so the pipeline stays accurate:

- If they signed up → mark Close Won
- If they passed → mark Close Lost
- If they didn't show → mark No Show (you can then send a follow-up to reschedule)

Open the contact here: {crm_url}/dashboard

Contact: {contact_name}
Email: {contact.email}

Thanks,
Limitless Leadership CRM"""

        try:
            email_service.send(
                to_email    = rep.email,
                to_name     = rep.name,
                subject     = f"Action needed — how did your meeting with {contact_name} go?",
                body        = body,
                sender_name = "Limitless Leadership CRM",
            )
            db.add(SyncLog(
                id=str(uuid.uuid4()), contact_id=contact.id, platform="crm",
                action="overdue_reminder_sent", tag="post_meeting", status="success",
            ))
            reminded += 1
            details.append(f"{contact_name} → {rep.name}")
        except Exception as e:
            print(f"[Overdue reminder] error for {contact.email}: {e}")
            skipped += 1

    db.commit()

    return {
        "status":   "done",
        "overdue_found": len(overdue),
        "reminded": reminded,
        "skipped":  skipped,
        "details":  details,
        "message":  f"{reminded} reminder(s) sent to reps for overdue meetings.",
    }


@router.post("/{contact_id}/no-show")
def mark_no_show(contact_id: str, db: Session = Depends(get_db)):
    """
    Mark a contact's meeting as No Show.
    Sets the appointment status to 'no_show' and moves the contact back so a
    follow-up can be generated manually with the existing Follow Up button.
    """
    contact = db.query(Contact).filter(Contact.id == contact_id).first()
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")

    # Most recent scheduled appointment for this contact
    appt = (
        db.query(Appointment)
        .filter(Appointment.contact_id == contact_id)
        .order_by(Appointment.scheduled_at.desc())
        .first()
    )
    if appt:
        appt.status = "no_show"

    # Move contact back to outreach_sent so the Follow Up button appears
    contact.status = "outreach_sent"

    db.add(SyncLog(
        id=str(uuid.uuid4()), contact_id=contact.id, platform="crm",
        action="marked_no_show", tag="no_show", status="success",
    ))
    db.commit()

    return {
        "status":     "no_show",
        "contact_id": contact_id,
        "message":    "Marked as no-show. You can now generate a follow-up to reschedule.",
    }
