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

CALENDLY_BASE   = os.getenv("CALENDLY_BASE_URL", "https://calendly.com/your-link")
EMAIL_FROM_NAME = os.getenv("EMAIL_FROM_NAME", "Limitless Leadership")


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

    score_result = classifier_agent.classify(contact, db)

    calendly_link = _build_calendly_link(contact_id)
    email_result  = copywriter_agent.write_email(contact, calendly_link, db)

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
    sender_name:  str = Query(None, description="Sender name override (defaults to company brand)"),
    db: Session = Depends(get_db)
):
    """
    Send a draft email via Brevo.
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

    # Sender name always defaults to the company brand, not a user's name
    if not sender_name:
        sender_name = EMAIL_FROM_NAME

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
            detail      = f"Email error: {result.get('error')}"
        )

    outreach.status  = "sent"
    outreach.sent_at = datetime.utcnow()
    contact.status   = "outreach_sent"

    db.add(SyncLog(
        id         = str(uuid.uuid4()),
        contact_id = contact.id,
        platform   = "brevo",
        action     = "email_sent",
        tag        = "outreach",
        status     = "success",
    ))
    db.commit()

    if contact.kajabi_id:
        try:
            from services.kajabi import kajabi_service
            kajabi_service.tag_contact_by_name(contact.kajabi_id, "crm-contacted")
            db.add(SyncLog(
                id=str(uuid.uuid4()), contact_id=contact.id,
                platform="kajabi", action="add_tag",
                tag="crm-contacted", status="success",
            ))
            db.commit()
        except Exception as e:
            print(f"[Kajabi tag] crm-contacted error: {e}")

    return {
        "status":      "sent",
        "outreach_id": outreach_id,
        "to":          contact.email,
        "subject":     outreach.subject,
        "message_id":  result.get("message_id"),
    }


@router.post("/batch/generate-and-send")
def batch_generate_and_send(
    score_filter: str = Query("hot", description="hot | warm | cold | all"),
    sender_name:  str = Query(None,  description="Sender name (defaults to company brand)"),
    limit:        int = Query(10,    ge=1, le=100),
    db: Session = Depends(get_db)
):
    """
    Batch: find pending contacts by score, generate + send outreach for each.
    """
    if not sender_name:
        sender_name = EMAIL_FROM_NAME

    q = db.query(Contact).filter(Contact.status == "pending")
    if score_filter != "all":
        q = q.filter(Contact.score == score_filter)
    contacts = q.limit(limit).all()

    if not contacts:
        return {"message": "No pending contacts found for this filter", "sent": 0}

    results = []
    for contact in contacts:
        try:
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


@router.post("/followup/batch/generate")
def batch_generate_followups(
    days_since_min: int = Query(5, description="Only contacts whose last email was sent at least this many days ago"),
    limit:          int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db)
):
    """
    Generate follow-up DRAFTS (not sent) for contacts contacted but not scheduled,
    whose last email was >= days_since_min days ago. Admin reviews then sends.
    """
    from agents.followup import followup_agent
    from datetime import timedelta

    cutoff = datetime.utcnow() - timedelta(days=days_since_min)

    candidates = (
        db.query(Contact)
        .filter(Contact.status == "outreach_sent")
        .limit(limit * 3)
        .all()
    )

    created = 0
    skipped = 0
    details = []

    for contact in candidates:
        if created >= limit:
            break

        last_sent = (
            db.query(Outreach)
            .filter(Outreach.contact_id == contact.id, Outreach.status == "sent")
            .order_by(Outreach.sent_at.desc())
            .first()
        )
        if not last_sent or not last_sent.sent_at or last_sent.sent_at > cutoff:
            skipped += 1
            continue

        existing_draft = (
            db.query(Outreach)
            .filter(Outreach.contact_id == contact.id, Outreach.status == "draft")
            .first()
        )
        if existing_draft:
            skipped += 1
            continue

        followup_count = (
            db.query(Outreach)
            .filter(Outreach.contact_id == contact.id, Outreach.status == "sent")
            .count()
        )
        if followup_count >= 3:
            skipped += 1
            continue

        days_since = (datetime.utcnow() - last_sent.sent_at).days
        try:
            result = followup_agent.write_followup(contact, last_sent, days_since, db)
            draft = Outreach(
                id            = str(uuid.uuid4()),
                contact_id    = contact.id,
                channel       = "email",
                subject       = result.get("subject"),
                body          = result.get("body"),
                status        = "draft",
                calendly_link = last_sent.calendly_link,
            )
            db.add(draft)
            db.commit()
            created += 1
            details.append(f"{contact.first_name} {contact.last_name} (day {days_since})")
        except Exception as e:
            print(f"[Followup batch] Error for {contact.email}: {e}")
            skipped += 1

    return {
        "status":         "done",
        "drafts_created": created,
        "skipped":        skipped,
        "details":        details,
        "message":        f"{created} follow-up drafts created. Review and send them in the Outreach tab.",
    }


@router.delete("/{outreach_id}", status_code=204)
def delete_outreach(outreach_id: str, db: Session = Depends(get_db)):
    """Delete an outreach record (draft or sent)."""
    outreach = db.query(Outreach).filter(Outreach.id == outreach_id).first()
    if not outreach:
        raise HTTPException(status_code=404, detail="Outreach not found")
    db.delete(outreach)
    db.commit()


@router.patch("/{outreach_id}")
def update_outreach(
    outreach_id: str,
    data: dict,
    db: Session = Depends(get_db)
):
    """Update outreach body or subject — used when sales rep edits before sending"""
    outreach = db.query(Outreach).filter(Outreach.id == outreach_id).first()
    if not outreach:
        raise HTTPException(status_code=404, detail="Outreach not found")
    if outreach.status not in ["draft", "pending_approval"]:
        raise HTTPException(status_code=409, detail="Cannot edit — already sent")

    if "body" in data:
        outreach.body = data["body"]
    if "subject" in data:
        outreach.subject = data["subject"]

    db.commit()
    return {"status": "updated", "outreach_id": outreach_id}
