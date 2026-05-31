from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from db_session import get_db
from database import Contact, Outreach, SyncLog, User
from schemas import OutreachOut
from agents.classifier import classifier_agent
from agents.copywriter  import copywriter_agent
from services.email     import email_service
import uuid, os
from datetime import datetime

router = APIRouter()

CALENDLY_BASE = os.getenv("CALENDLY_BASE_URL", "https://calendly.com/your-link")


def _build_calendly_link(contact_id: str) -> str:
    return f"{CALENDLY_BASE}?utm_content={contact_id}"


@router.get("/", response_model=List[OutreachOut])
def list_outreach(
    contact_id: Optional[str] = None,
    status:     Optional[str] = None,
    db: Session = Depends(get_db)
):
    q = db.query(Outreach)
    if contact_id: q = q.filter(Outreach.contact_id == contact_id)
    if status:     q = q.filter(Outreach.status == status)
    return q.all()


@router.post("/generate/{contact_id}")
def generate_outreach(contact_id: str, db: Session = Depends(get_db)):
    """
    1. Classify the contact (hot/warm/cold)
    2. Write personalized email with Claude
    3. Save as draft
    """
    contact = db.query(Contact).filter(Contact.id == contact_id).first()
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    if contact.status == "outreach_sent":
        raise HTTPException(status_code=409, detail="Contact already received outreach")

    # Step 1 — Classify
    score_result = classifier_agent.classify(contact, db)

    # Step 2 — Generate email
    calendly_link = _build_calendly_link(contact_id)
    email_result  = copywriter_agent.write_email(contact, calendly_link, db)

    # Step 3 — Save as draft
    outreach = Outreach(
        id            = str(uuid.uuid4()),
        contact_id    = contact_id,
        channel       = "email",
        subject       = email_result.get("subject"),
        body          = email_result.get("body"),
        status        = "draft",
        calendly_link = calendly_link,
    )
    db.add(outreach)
    db.commit()
    db.refresh(outreach)

    return {
        "outreach_id":   outreach.id,
        "score":         score_result,
        "subject":       outreach.subject,
        "body":          outreach.body,
        "calendly_link": outreach.calendly_link,
        "status":        outreach.status,
    }


@router.post("/{outreach_id}/send")
def send_outreach(
    outreach_id:  str,
    sender_name:  str = Query(None, description="Sales rep name to replace [Your Name]"),
    db: Session = Depends(get_db)
):
    """
    Send a draft email via SendGrid.
    Marks contact as outreach_sent and logs the sync.
    """
    outreach = db.query(Outreach).filter(Outreach.id == outreach_id).first()
    if not outreach:
        raise HTTPException(status_code=404, detail="Outreach not found")
    if outreach.status not in ["draft", "pending_approval"]:
        raise HTTPException(status_code=409, detail=f"Cannot send — status is '{outreach.status}'")

    contact = db.query(Contact).filter(Contact.id == outreach.contact_id).first()
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")

    # Get sender name — from query param or first user in DB
    if not sender_name:
        user = db.query(User).first()
        sender_name = user.name if user else EMAIL_FROM_NAME

    # Send via SendGrid
    result = email_service.send(
        to_email    = contact.email,
        to_name     = f"{contact.first_name or ''} {contact.last_name or ''}".strip(),
        subject     = outreach.subject,
        body        = outreach.body,
        sender_name = sender_name,
    )

    if not result.get("success"):
        raise HTTPException(
            status_code = 502,
            detail      = f"SendGrid error: {result.get('error')}"
        )

    # Update outreach status
    outreach.status  = "sent"
    outreach.sent_at = datetime.utcnow()

    # Update contact status
    contact.status = "outreach_sent"

    # Log the sync
    db.add(SyncLog(
        id         = str(uuid.uuid4()),
        contact_id = contact.id,
        platform   = "sendgrid",
        action     = "email_sent",
        tag        = "outreach",
        status     = "success",
    ))
    db.commit()

    return {
        "status":     "sent",
        "outreach_id": outreach_id,
        "to":          contact.email,
        "subject":     outreach.subject,
        "message_id":  result.get("message_id"),
    }


@router.post("/batch/generate-and-send")
def batch_generate_and_send(
    score_filter: str = Query("hot", description="hot | warm | cold | all"),
    sender_name:  str = Query(None,  description="Sales rep name"),
    limit:        int = Query(10,    ge=1, le=100),
    db: Session = Depends(get_db)
):
    """
    Batch operation:
    1. Find pending contacts by score
    2. Generate + send outreach for each one
    Great for launching a campaign from Kajabi contacts.
    """
    q = db.query(Contact).filter(Contact.status == "pending")
    if score_filter != "all":
        q = q.filter(Contact.score == score_filter)
    contacts = q.limit(limit).all()

    if not contacts:
        return {"message": "No pending contacts found for this filter", "sent": 0}

    results = []
    for contact in contacts:
        try:
            # Generate
            calendly_link = _build_calendly_link(contact.id)
            classifier_agent.classify(contact, db)
            email_result  = copywriter_agent.write_email(contact, calendly_link, db)

            outreach = Outreach(
                id            = str(uuid.uuid4()),
                contact_id    = contact.id,
                channel       = "email",
                subject       = email_result.get("subject"),
                body          = email_result.get("body"),
                status        = "draft",
                calendly_link = calendly_link,
            )
            db.add(outreach)
            db.commit()

            # Send
            send_result = email_service.send(
                to_email    = contact.email,
                to_name     = f"{contact.first_name or ''} {contact.last_name or ''}".strip(),
                subject     = outreach.subject,
                body        = outreach.body,
                sender_name = sender_name,
            )

            if send_result.get("success"):
                outreach.status  = "sent"
                outreach.sent_at = datetime.utcnow()
                contact.status   = "outreach_sent"
                db.commit()
                results.append({"email": contact.email, "status": "sent"})
            else:
                results.append({"email": contact.email, "status": "failed",
                                 "error": send_result.get("error")})

        except Exception as e:
            results.append({"email": contact.email, "status": "error", "error": str(e)})

    sent   = sum(1 for r in results if r["status"] == "sent")
    failed = len(results) - sent

    return {
        "total":   len(contacts),
        "sent":    sent,
        "failed":  failed,
        "results": results,
    }


@router.post("/followup/{contact_id}")
def generate_followup(contact_id: str, db: Session = Depends(get_db)):
    """Generate a follow-up email for a contact that hasn't responded"""
    from agents.followup import followup_agent

    contact = db.query(Contact).filter(Contact.id == contact_id).first()
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")

    original = (
        db.query(Outreach)
        .filter(Outreach.contact_id == contact_id, Outreach.status == "sent")
        .order_by(Outreach.sent_at.desc())
        .first()
    )
    if not original:
        raise HTTPException(status_code=404, detail="No sent outreach found")

    days_since = (datetime.utcnow() - original.sent_at).days if original.sent_at else 0
    result     = followup_agent.write_followup(contact, original, days_since, db)

    followup = Outreach(
        id            = str(uuid.uuid4()),
        contact_id    = contact_id,
        channel       = "email",
        subject       = result.get("subject"),
        body          = result.get("body"),
        status        = "draft",
        calendly_link = original.calendly_link,
    )
    db.add(followup)
    db.commit()

    return {
        "outreach_id": followup.id,
        "subject":     followup.subject,
        "body":        followup.body,
        "days_since":  days_since,
        "status":      "draft"
    }


# needed for sender name fallback
EMAIL_FROM_NAME = os.getenv("EMAIL_FROM_NAME", "Your Company")
