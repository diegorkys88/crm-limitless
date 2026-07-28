from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr
from db_session import get_db, SessionLocal
from database import Contact, SyncLog
import uuid

router = APIRouter()

# ── Simple in-memory rate limiter (per IP) ──
# Resets when the app restarts — fine for basic abuse protection.
from collections import defaultdict
from time import time as _now

_RATE_STORE = defaultdict(list)          # ip -> [timestamps]
_RATE_MAX   = 5                          # max signups
_RATE_WINDOW = 60                        # per 60 seconds

# Known disposable / throwaway email domains to reject
_DISPOSABLE = {
    "tempmail.com","temp-mail.org","guerrillamail.com","mailinator.com",
    "10minutemail.com","throwawaymail.com","yopmail.com","trashmail.com",
    "sharklasers.com","getnada.com","maildrop.cc","fakeinbox.com",
    "dispostable.com","tempmailo.com","emailondeck.com",
}


def _rate_limited(ip: str) -> bool:
    now = _now()
    hits = [t for t in _RATE_STORE[ip] if now - t < _RATE_WINDOW]
    _RATE_STORE[ip] = hits
    if len(hits) >= _RATE_MAX:
        return True
    _RATE_STORE[ip].append(now)
    return False


class EventSignup(BaseModel):
    name:    str
    email:   EmailStr
    website: str = ""   # honeypot — real users never fill this (hidden field)


@router.get("/event", include_in_schema=False)
def event_form():
    """Serve the public event capture form (no auth)."""
    return FileResponse("static/event.html")


@router.post("/public/event-signup")
def event_signup(
    data:             EventSignup,
    request:          Request,
    background_tasks: BackgroundTasks,
    db:               Session = Depends(get_db),
):
    """
    Public endpoint — creates a contact from the event QR form.
    No authentication (it's a public stand form).
    Protections: honeypot, per-IP rate limit, disposable-domain block.
    Deduplicates by email. Fires Apollo enrichment in the background.
    """
    # ── Guard 1: honeypot — bots fill hidden fields, humans don't ──
    if data.website.strip():
        # Silently accept so the bot thinks it worked, but do nothing
        return {"status": "created"}

    # ── Guard 2: rate limit per IP ──
    client_ip = request.client.host if request.client else "unknown"
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        client_ip = fwd.split(",")[0].strip()
    if _rate_limited(client_ip):
        raise HTTPException(status_code=429, detail="Too many signups. Please wait a moment and try again.")

    email = data.email.strip().lower()
    name  = data.name.strip()

    # ── Guard 3: reject disposable email domains ──
    domain = email.split("@")[1] if "@" in email else ""
    if domain in _DISPOSABLE:
        raise HTTPException(status_code=422, detail="Please use a permanent email address.")

    # Basic sanity on name length
    if len(name) < 2 or len(name) > 120:
        raise HTTPException(status_code=422, detail="Please enter a valid name.")

    # Split name into first / last
    parts      = name.split(" ", 1)
    first_name = parts[0] if parts else name
    last_name  = parts[1] if len(parts) > 1 else None

    # Dedupe by email
    existing = db.query(Contact).filter(Contact.email == email).first()
    if existing:
        # Already known — log the touch but don't duplicate
        db.add(SyncLog(
            id=str(uuid.uuid4()), contact_id=existing.id, platform="event",
            action="event_signup_duplicate", tag="event", status="success",
        ))
        db.commit()
        # Still returns OK so the visitor sees the friendly confirmation
        return {"status": "already_registered", "contact_id": existing.id}

    contact = Contact(
        id         = str(uuid.uuid4()),
        first_name = first_name,
        last_name  = last_name,
        email      = email,
        source     = "event",
        status     = "pending",
        subscribed = "true",   # they opted in at the booth
    )
    db.add(contact)
    db.add(SyncLog(
        id=str(uuid.uuid4()), contact_id=contact.id, platform="event",
        action="event_signup", tag="event", status="success",
    ))
    db.commit()

    # Enrich with Apollo + classify in the background (don't block the visitor)
    background_tasks.add_task(_enrich_and_classify, contact.id)

    return {"status": "created", "contact_id": contact.id}


def _enrich_and_classify(contact_id: str):
    """Background: try Apollo enrich, then classify with Claude."""
    db = SessionLocal()
    try:
        contact = db.query(Contact).filter(Contact.id == contact_id).first()
        if not contact:
            return

        # ── Apollo enrich (best-effort) ──
        try:
            from services.apollo import apollo_service
            FREE = {"gmail.com","yahoo.com","hotmail.com","outlook.com","aol.com",
                    "icloud.com","live.com","msn.com","protonmail.com","me.com"}
            domain = contact.email.split("@")[1].lower() if "@" in contact.email else None
            if domain in FREE:
                domain = None

            enriched = apollo_service.enrich_person(
                email      = contact.email,
                first_name = contact.first_name,
                last_name  = contact.last_name,
                domain     = domain,
            )
            if enriched:
                for field in ["title", "company", "industry", "region", "apollo_id"]:
                    if not getattr(contact, field, None) and enriched.get(field):
                        setattr(contact, field, enriched[field])
                db.commit()
        except Exception as e:
            print(f"[Event enrich] {contact_id}: {e}")

        # ── Classify with Claude ──
        try:
            from agents.classifier import classifier_agent
            db.refresh(contact)
            classifier_agent.classify(contact, db)
        except Exception as e:
            print(f"[Event classify] {contact_id}: {e}")

    finally:
        db.close()
