from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional
from db_session import get_db
from database import Campaign, CampaignRecipient, Contact
from services.email import email_service
from datetime import datetime
import uuid

router = APIRouter()

DAILY_LIMIT = 270  # stay under Brevo's 300/day free tier


# ── Helper: build the filtered contact query ──────────────────────────────────
def _filter_contacts(db, region, source, score, status):
    q = db.query(Contact).filter(Contact.email != None)

    if region and region != "all":
        q = q.filter(Contact.region.ilike(f"%{region}%"))
    if source and source != "all":
        q = q.filter(Contact.source == source)
    if score and score != "all":
        q = q.filter(Contact.score == score)
    if status and status != "all":
        if status == "contacted":
            q = q.filter(Contact.status.in_(
                ["outreach_sent", "appointment_scheduled", "closed_won", "closed_lost"]
            ))
        else:
            q = q.filter(Contact.status == status)

    return q.all()


# ── Preview how many contacts a filter matches ────────────────────────────────
@router.get("/preview-count")
def preview_count(
    region: Optional[str] = "all",
    source: Optional[str] = "all",
    score:  Optional[str] = "all",
    status: Optional[str] = "all",
    db: Session = Depends(get_db),
):
    contacts = _filter_contacts(db, region, source, score, status)
    return {"count": len(contacts)}


# ── Generate the campaign email with Claude ───────────────────────────────────
@router.post("/generate")
def generate_campaign_email(data: dict, db: Session = Depends(get_db)):
    """Given a prompt, Claude writes the invitation. Returns subject + body (not saved yet)."""
    prompt = (data.get("prompt") or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="Prompt is required")

    from agents.campaign_writer import campaign_writer_agent
    result = campaign_writer_agent.write_campaign(prompt, db)

    return {
        "subject": result.get("subject"),
        "body":    result.get("body"),
    }


# ── Create the campaign (saves draft + recipient list) ────────────────────────
@router.post("/create")
def create_campaign(data: dict, db: Session = Depends(get_db)):
    """
    Create a campaign with the approved email + filters.
    Builds the recipient list from the filters. Nothing is sent yet.
    """
    name    = (data.get("name") or "").strip()
    subject = (data.get("subject") or "").strip()
    body    = (data.get("body") or "").strip()
    if not name or not subject or not body:
        raise HTTPException(status_code=400, detail="Name, subject and body are required")

    region = data.get("region", "all")
    source = data.get("source", "all")
    score  = data.get("score",  "all")
    status = data.get("status", "all")

    contacts = _filter_contacts(db, region, source, score, status)
    if not contacts:
        raise HTTPException(status_code=400, detail="No contacts match these filters")

    campaign = Campaign(
        id            = str(uuid.uuid4()),
        name          = name,
        prompt        = data.get("prompt", ""),
        subject       = subject,
        body          = body,
        filter_region = region,
        filter_source = source,
        filter_score  = score,
        filter_status = status,
        total_recipients = str(len(contacts)),
        sent_count    = "0",
        status        = "draft",
        daily_limit   = str(DAILY_LIMIT),
    )
    db.add(campaign)

    for c in contacts:
        db.add(CampaignRecipient(
            id          = str(uuid.uuid4()),
            campaign_id = campaign.id,
            contact_id  = c.id,
            email       = c.email,
            name        = f"{c.first_name or ''} {c.last_name or ''}".strip(),
            status      = "pending",
        ))

    db.commit()

    return {
        "campaign_id":     campaign.id,
        "name":            campaign.name,
        "total_recipients": len(contacts),
        "daily_limit":     DAILY_LIMIT,
        "message":         f"Campaign created with {len(contacts)} recipients. Send when ready.",
    }


# ── Send / continue the campaign (batches of DAILY_LIMIT) ──────────────────────
@router.post("/{campaign_id}/send")
def send_campaign(campaign_id: str, db: Session = Depends(get_db)):
    """
    Send up to DAILY_LIMIT pending emails for this campaign.
    Run again the next day to continue with the remaining recipients.
    """
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    pending = (
        db.query(CampaignRecipient)
        .filter(CampaignRecipient.campaign_id == campaign_id,
                CampaignRecipient.status == "pending")
        .limit(DAILY_LIMIT)
        .all()
    )

    if not pending:
        campaign.status = "completed"
        db.commit()
        return {"status": "completed", "sent_now": 0, "message": "All recipients already sent."}

    campaign.status = "sending"
    db.commit()

    sent_now = 0
    failed   = 0

    for recipient in pending:
        # Personalize the {first_name} placeholder
        first_name = (recipient.name or "").split(" ")[0] or "there"
        personalized_body = campaign.body.replace("{first_name}", first_name)

        try:
            result = email_service.send(
                to_email    = recipient.email,
                to_name     = recipient.name or recipient.email,
                subject     = campaign.subject,
                body        = personalized_body,
                sender_name = "Limitless Leadership",
            )
            if result.get("success"):
                recipient.status  = "sent"
                recipient.sent_at = datetime.utcnow()
                sent_now += 1
            else:
                recipient.status = "failed"
                recipient.error  = str(result.get("error"))[:500]
                failed += 1
        except Exception as e:
            recipient.status = "failed"
            recipient.error  = str(e)[:500]
            failed += 1

        db.commit()

    # Update campaign totals
    total_sent = (
        db.query(CampaignRecipient)
        .filter(CampaignRecipient.campaign_id == campaign_id,
                CampaignRecipient.status == "sent")
        .count()
    )
    remaining = (
        db.query(CampaignRecipient)
        .filter(CampaignRecipient.campaign_id == campaign_id,
                CampaignRecipient.status == "pending")
        .count()
    )
    campaign.sent_count = str(total_sent)
    campaign.status     = "completed" if remaining == 0 else "partial"
    db.commit()

    return {
        "status":     campaign.status,
        "sent_now":   sent_now,
        "failed":     failed,
        "total_sent": total_sent,
        "remaining":  remaining,
        "message":    (f"Sent {sent_now} now. {remaining} remaining — come back tomorrow "
                       f"and click Continue to send the next batch." if remaining else
                       f"Campaign complete — {total_sent} emails sent."),
    }


# ── List campaigns ────────────────────────────────────────────────────────────
@router.get("/")
def list_campaigns(db: Session = Depends(get_db)):
    campaigns = db.query(Campaign).order_by(Campaign.created_at.desc()).all()
    return [{
        "id":               c.id,
        "name":             c.name,
        "subject":          c.subject,
        "status":           c.status,
        "total_recipients": int(c.total_recipients or 0),
        "sent_count":       int(c.sent_count or 0),
        "created_at":       c.created_at.isoformat() if c.created_at else None,
    } for c in campaigns]


# ── Campaign detail (with recipients) ─────────────────────────────────────────
@router.get("/{campaign_id}")
def get_campaign(campaign_id: str, db: Session = Depends(get_db)):
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    recipients = (
        db.query(CampaignRecipient)
        .filter(CampaignRecipient.campaign_id == campaign_id)
        .all()
    )

    return {
        "id":               campaign.id,
        "name":             campaign.name,
        "prompt":           campaign.prompt,
        "subject":          campaign.subject,
        "body":             campaign.body,
        "status":           campaign.status,
        "total_recipients": int(campaign.total_recipients or 0),
        "sent_count":       int(campaign.sent_count or 0),
        "filters": {
            "region": campaign.filter_region,
            "source": campaign.filter_source,
            "score":  campaign.filter_score,
            "status": campaign.filter_status,
        },
        "recipients": [{
            "name":    r.name,
            "email":   r.email,
            "status":  r.status,
            "sent_at": r.sent_at.isoformat() if r.sent_at else None,
        } for r in recipients],
    }


# ── Delete campaign ───────────────────────────────────────────────────────────
@router.delete("/{campaign_id}", status_code=204)
def delete_campaign(campaign_id: str, db: Session = Depends(get_db)):
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    db.query(CampaignRecipient).filter(CampaignRecipient.campaign_id == campaign_id).delete()
    db.delete(campaign)
    db.commit()
