from fastapi import APIRouter, Depends, BackgroundTasks, Query, HTTPException
from sqlalchemy.orm import Session
from db_session import get_db, SessionLocal

router = APIRouter()

DEFAULT_TITLES = [
    "VP Operations", "General Manager", "Director of Operations",
    "Chief Executive Officer", "President", "Director of Sales",
    "Regional Manager", "Owner", "Managing Director",
]


# ── Apollo ───────────────────────────────────────────────────────────────────────

@router.post("/apollo/search")
def search_apollo(
    region:           str  = Query(..., description="e.g. California, Texas, Florida"),
    industry:         str  = Query("automotive"),
    limit:            int  = Query(25, ge=1, le=100),
    enrich:           bool = Query(True, description="Enrich contacts to get emails (uses credits)"),
    background_tasks: BackgroundTasks = None,
    db: Session = Depends(get_db)
):
    background_tasks.add_task(
        _run_prospecting,
        titles=DEFAULT_TITLES, region=region,
        industry=industry, limit=limit, enrich=enrich
    )
    return {
        "status":  "search_started",
        "region":  region,
        "limit":   limit,
        "enrich":  enrich,
        "message": "Check /contacts/?source=apollo for results in a few seconds"
    }


@router.post("/apollo/search/sync")
def search_apollo_sync(
    region:   str  = Query(..., description="e.g. California"),
    industry: str  = Query("automotive"),
    limit:    int  = Query(10, ge=1, le=25),
    enrich:   bool = Query(True, description="Enrich to get emails (uses credits)"),
    db: Session = Depends(get_db)
):
    from agents.prospector import prospector_agent
    result = prospector_agent.search_and_import(
        titles=DEFAULT_TITLES, region=region,
        industry=industry, limit=limit, enrich=enrich, db=db
    )
    return result


@router.post("/apollo/enrich/{contact_id}")
def enrich_contact(contact_id: str, db: Session = Depends(get_db)):
    from services.apollo import apollo_service
    from database import Contact, SyncLog
    import uuid

    contact = db.query(Contact).filter(Contact.id == contact_id).first()
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")

    FREE_PROVIDERS = {"gmail.com","yahoo.com","hotmail.com","outlook.com","aol.com","icloud.com","live.com","msn.com","protonmail.com","me.com"}
    domain = contact.email.split("@")[1].lower() if contact.email and "@" in contact.email else None
    if domain in FREE_PROVIDERS:
        domain = None  # personal email — don't tell Apollo it's their company

    enriched = apollo_service.enrich_person(
        email      = contact.email,
        first_name = contact.first_name,
        last_name  = contact.last_name,
        domain     = domain,
    )

    if not enriched:
        return {"status": "not_found", "message": "Apollo has no data for this contact"}

    updated_fields = []
    for field in ["title", "company", "industry", "region", "linkedin_url", "apollo_id"]:
        if not getattr(contact, field, None) and enriched.get(field):
            setattr(contact, field, enriched[field])
            updated_fields.append(field)

    db.add(SyncLog(
        id=str(uuid.uuid4()), contact_id=contact.id, platform="apollo",
        action="enriched_contact", tag=",".join(updated_fields) or "no_new_data",
        status="success",
    ))
    db.commit()

    # If only apollo_id came back, Apollo matched but has no professional data
    if updated_fields in ([], ["apollo_id"]):
        return {
            "status":         "matched_no_data",
            "updated_fields": updated_fields,
            "message":        "Apollo found this person but has no title/company data. Try filling Title manually.",
            "apollo_data":    enriched,
        }

    return {"status": "enriched", "updated_fields": updated_fields, "apollo_data": enriched}


@router.post("/apollo/enrich/bulk")
def enrich_bulk(limit: int = Query(10, ge=1, le=10), db: Session = Depends(get_db)):
    from services.apollo import apollo_service
    from database import Contact, SyncLog
    import uuid

    contacts = (
        db.query(Contact)
        .filter(Contact.source.in_(["kajabi", "clickfunnels", "manual"]))
        .filter(Contact.title == None)
        .limit(limit)
        .all()
    )

    if not contacts:
        return {"status": "nothing_to_enrich", "message": "All contacts already have title data"}

    FREE_PROVIDERS_BULK = {"gmail.com","yahoo.com","hotmail.com","outlook.com","aol.com","icloud.com","live.com","msn.com","protonmail.com","me.com"}
    batch = []
    for c in contacts:
        domain = c.email.split("@")[1].lower() if c.email and "@" in c.email else None
        if domain in FREE_PROVIDERS_BULK:
            domain = None
        batch.append({
            "first_name": c.first_name, "last_name": c.last_name,
            "email": c.email, "domain": domain,
        })

    results = apollo_service.bulk_enrich(batch)

    enriched_count = 0
    for i, enriched in enumerate(results):
        if not enriched or i >= len(contacts):
            continue
        contact = contacts[i]
        for field in ["title", "company", "industry", "region", "apollo_id"]:
            if not getattr(contact, field, None) and enriched.get(field):
                setattr(contact, field, enriched[field])
        db.add(SyncLog(
            id=str(uuid.uuid4()), contact_id=contact.id, platform="apollo",
            action="bulk_enriched", tag="bulk", status="success",
        ))
        enriched_count += 1

    db.commit()
    return {"status": "done", "contacts": len(contacts), "enriched": enriched_count}


# ── Kajabi ───────────────────────────────────────────────────────────────────────

@router.post("/kajabi/import")
def import_from_kajabi(
    background_tasks: BackgroundTasks,
    limit: int = Query(None, description="Max contacts to import. Leave empty for all."),
):
    """
    Import contacts from Kajabi into the CRM.
    Runs in background. Deduplicates by email automatically.
    """
    background_tasks.add_task(_run_kajabi_import, limit)
    return {
        "status":  "import_started",
        "message": "Kajabi import running in background — check /contacts/?source=kajabi for results"
    }


@router.post("/kajabi/import/sync")
def import_from_kajabi_sync(
    limit: int = Query(20, ge=1, le=100, description="Max contacts for this test run"),
    db: Session = Depends(get_db)
):
    """
    Same as above but waits for the result — use for testing with small limits.
    """
    from services.kajabi import kajabi_service
    from database import Contact, SyncLog
    import uuid

    try:
        kajabi_contacts, meta = kajabi_service.list_contacts(page=1, page_size=limit)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Kajabi error: {str(e)}")

    imported = 0
    skipped  = 0

    for kc in kajabi_contacts:
        email = kc.get("email")
        if not email:
            skipped += 1
            continue

        existing = db.query(Contact).filter(Contact.email == email).first()
        if existing:
            # Update kajabi_id if missing
            if not existing.kajabi_id:
                existing.kajabi_id = kc.get("kajabi_id")
            skipped += 1
            continue

        contact = Contact(
            id          = str(uuid.uuid4()),
            first_name  = kc.get("first_name"),
            last_name   = kc.get("last_name"),
            email       = email,
            phone       = kc.get("phone"),
            source      = "kajabi",
            kajabi_id   = kc.get("kajabi_id"),
            status      = "pending",
        )
        db.add(contact)
        db.add(SyncLog(
            id=str(uuid.uuid4()), contact_id=contact.id, platform="kajabi",
            action="contact_imported", tag="initial_import", status="success",
        ))
        imported += 1

    db.commit()

    return {
        "found":    len(kajabi_contacts),
        "imported": imported,
        "skipped":  skipped,
        "meta":     meta,
    }


@router.post("/kajabi/tag/{contact_id}")
def tag_kajabi_contact(
    contact_id: str,
    tag_name:   str = Query(..., description="e.g. crm-contacted, crm-scheduled"),
    db: Session = Depends(get_db)
):
    """
    Add a tag to a contact in Kajabi.
    The tag must already exist in Kajabi (Settings > Tags) — the API can't create new tags.
    """
    from services.kajabi import kajabi_service
    from database import Contact, SyncLog
    import uuid

    contact = db.query(Contact).filter(Contact.id == contact_id).first()
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    if not contact.kajabi_id:
        raise HTTPException(status_code=400, detail="Contact has no kajabi_id — not synced from Kajabi")

    success = kajabi_service.tag_contact_by_name(contact.kajabi_id, tag_name)

    db.add(SyncLog(
        id=str(uuid.uuid4()), contact_id=contact.id, platform="kajabi",
        action="add_tag", tag=tag_name,
        status="success" if success else "failed",
    ))
    db.commit()

    if not success:
        raise HTTPException(status_code=502, detail=f"Could not add tag '{tag_name}' — does it exist in Kajabi?")

    return {"status": "tagged", "contact_id": contact_id, "tag": tag_name}


# ── Background tasks ───────────────────────────────────────────────────────────

def _run_prospecting(titles, region, industry, limit, enrich):
    from agents.prospector import prospector_agent
    db = SessionLocal()
    try:
        result = prospector_agent.search_and_import(
            titles=titles, region=region, industry=industry, limit=limit, enrich=enrich, db=db
        )
        print(f"[Prospector] Completed: {result}")
    except Exception as e:
        print(f"[Prospector] Error: {e}")
    finally:
        db.close()


def _run_kajabi_import(limit):
    from services.kajabi import kajabi_service
    from database import Contact, SyncLog
    import uuid

    db = SessionLocal()
    try:
        if limit:
            kajabi_contacts, _ = kajabi_service.list_contacts(page=1, page_size=limit)
        else:
            kajabi_contacts = kajabi_service.list_all_contacts()

        imported = 0
        skipped  = 0

        for kc in kajabi_contacts:
            email = kc.get("email")
            if not email:
                skipped += 1
                continue
            existing = db.query(Contact).filter(Contact.email == email).first()
            if existing:
                if not existing.kajabi_id:
                    existing.kajabi_id = kc.get("kajabi_id")
                skipped += 1
                continue

            contact = Contact(
                id=str(uuid.uuid4()), first_name=kc.get("first_name"),
                last_name=kc.get("last_name"), email=email, phone=kc.get("phone"),
                source="kajabi", kajabi_id=kc.get("kajabi_id"), status="pending",
            )
            db.add(contact)
            db.add(SyncLog(
                id=str(uuid.uuid4()), contact_id=contact.id, platform="kajabi",
                action="contact_imported", tag="bulk_import", status="success",
            ))
            imported += 1

        db.commit()
        print(f"[Kajabi] Import done — found:{len(kajabi_contacts)} imported:{imported} skipped:{skipped}")
    except Exception as e:
        print(f"[Kajabi] Import error: {e}")
    finally:
        db.close()


@router.get("/kajabi/test")
def test_kajabi_connection():
    """
    Diagnostic endpoint — verifies OAuth2 token works and shows account info.
    Use this before running imports to confirm everything is connected.
    """
    from services.kajabi import kajabi_service
    try:
        me = kajabi_service.get_me()
        site_id = kajabi_service.get_site_id()
        tags = kajabi_service.list_tags()
        return {
            "status":     "connected",
            "account":    me.get("attributes", {}),
            "site_id":    site_id,
            "tags_found": [t["name"] for t in tags],
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Kajabi connection failed: {str(e)}")


# ── Calendly ───────────────────────────────────────────────────────────────────

@router.post("/calendly/webhook/register")
def register_calendly_webhook(
    webhook_url: str = Query(
        None,
        description="Leave empty to use CRM_URL from environment"
    )
):
    """
    Register the CRM webhook URL in Calendly.
    Call this once to connect Calendly to the CRM.
    After this, every booking will automatically create an appointment in the CRM.
    """
    from services.calendly import calendly_service
    import os

    crm_url = os.getenv("CRM_URL", "https://web-production-5bd62.up.railway.app")

    target_url = webhook_url or f"{crm_url}/webhooks/calendly"

    try:
        user = calendly_service.get_user()
        if not user:
            raise HTTPException(status_code=502, detail="Could not get Calendly user info")

        org = user.get("current_organization")
        result = calendly_service.register_webhook(target_url, org)

        return {
            "status":      "registered",
            "webhook_url": target_url,
            "calendly_id": result.get("resource", {}).get("uri", ""),
            "events":      ["invitee.created", "invitee.canceled"],
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Calendly error: {str(e)}")


@router.get("/calendly/webhook/list")
def list_calendly_webhooks():
    """List all webhooks registered in Calendly"""
    from services.calendly import calendly_service
    try:
        webhooks = calendly_service.list_webhooks()
        return {
            "count": len(webhooks),
            "webhooks": [
                {
                    "uri":    w.get("uri"),
                    "url":    w.get("callback_url"),
                    "events": w.get("events"),
                    "state":  w.get("state"),
                }
                for w in webhooks
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Calendly error: {str(e)}")


@router.delete("/calendly/webhook/{webhook_uuid}")
def delete_calendly_webhook(webhook_uuid: str):
    """Delete a Calendly webhook by UUID"""
    from services.calendly import calendly_service
    try:
        success = calendly_service.delete_webhook(webhook_uuid)
        if success:
            return {"status": "deleted", "uuid": webhook_uuid}
        raise HTTPException(status_code=502, detail="Could not delete webhook")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Calendly error: {str(e)}")
