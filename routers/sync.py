from fastapi import APIRouter, Depends, BackgroundTasks, Query
from sqlalchemy.orm import Session
from db_session import get_db

router = APIRouter()

DEFAULT_TITLES = [
    "VP Operations", "General Manager", "Director of Operations",
    "Chief Executive Officer", "President", "Director of Sales",
    "Regional Manager", "Owner", "Managing Director",
]


@router.post("/apollo/search")
def search_apollo(
    region:           str  = Query(..., description="e.g. California, Texas, Florida"),
    industry:         str  = Query("automotive"),
    limit:            int  = Query(25, ge=1, le=100),
    enrich:           bool = Query(True, description="Enrich contacts to get emails (uses credits)"),
    background_tasks: BackgroundTasks = None,
    db: Session = Depends(get_db)
):
    """
    Trigger the Prospector Agent:
    1. Search Apollo for automotive executives (FREE)
    2. Claude filters the best candidates
    3. Enrich approved contacts for emails (1 credit each)
    4. Save to CRM database
    Runs in background — check /contacts/ for results.
    """
    background_tasks.add_task(
        _run_prospecting,
        titles=DEFAULT_TITLES, region=region,
        industry=industry, limit=limit, enrich=enrich, db=db
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
    """
    Same as above but waits for results.
    Use limit ≤ 10 to avoid timeout.
    Tip: set enrich=false first to preview contacts before spending credits.
    """
    from agents.prospector import prospector_agent
    result = prospector_agent.search_and_import(
        titles=DEFAULT_TITLES, region=region,
        industry=industry, limit=limit, enrich=enrich, db=db
    )
    return result


@router.post("/kajabi/import")
def import_from_kajabi(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """Import all contacts from Kajabi (coming soon)"""
    background_tasks.add_task(_run_kajabi_import, db)
    return {"status": "import_started", "message": "Kajabi service not yet connected"}


def _run_prospecting(titles, region, industry, limit, enrich, db):
    from agents.prospector import prospector_agent
    try:
        result = prospector_agent.search_and_import(
            titles=titles, region=region, industry=industry, limit=limit, enrich=enrich, db=db
        )
        print(f"[Prospector] Completed: {result}")
    except Exception as e:
        print(f"[Prospector] Error: {e}")


def _run_kajabi_import(db):
    print("[Kajabi] Service not yet connected")


@router.post("/apollo/enrich/{contact_id}")
def enrich_contact(contact_id: str, db: Session = Depends(get_db)):
    """
    Enrich a single contact already in the CRM using Apollo.
    FREE — works on all plans.
    Useful for Kajabi contacts that are missing title, company, or industry.
    """
    from services.apollo import apollo_service
    from database import Contact, SyncLog
    import uuid

    contact = db.query(Contact).filter(Contact.id == contact_id).first()
    if not contact:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Contact not found")

    # Extract domain from email
    domain = contact.email.split("@")[1] if contact.email and "@" in contact.email else None

    enriched = apollo_service.enrich_person(
        email      = contact.email,
        first_name = contact.first_name,
        last_name  = contact.last_name,
        domain     = domain,
    )

    if not enriched:
        return {"status": "not_found", "message": "Apollo has no data for this contact"}

    # Update contact with enriched data — only fill empty fields
    updated_fields = []
    for field in ["title", "company", "industry", "region", "linkedin_url", "apollo_id"]:
        if not getattr(contact, field) and enriched.get(field):
            setattr(contact, field, enriched[field])
            updated_fields.append(field)

    db.add(SyncLog(
        id         = str(uuid.uuid4()),
        contact_id = contact.id,
        platform   = "apollo",
        action     = "enriched_contact",
        tag        = ",".join(updated_fields) or "no_new_data",
        status     = "success",
    ))
    db.commit()

    return {
        "status":         "enriched",
        "updated_fields": updated_fields,
        "apollo_data":    enriched,
    }


@router.post("/apollo/enrich/bulk")
def enrich_bulk(
    limit: int = Query(10, ge=1, le=10),
    db: Session = Depends(get_db)
):
    """
    Bulk enrich up to 10 pending contacts at once.
    FREE — great for enriching Kajabi imports right after they come in.
    """
    from services.apollo import apollo_service
    from database import Contact, SyncLog
    import uuid

    # Get contacts missing title or company
    contacts = (
        db.query(Contact)
        .filter(Contact.source.in_(["kajabi", "clickfunnels", "manual"]))
        .filter(Contact.title == None)
        .limit(limit)
        .all()
    )

    if not contacts:
        return {"status": "nothing_to_enrich", "message": "All contacts already have title data"}

    # Prepare batch for Apollo
    batch = []
    for c in contacts:
        domain = c.email.split("@")[1] if c.email and "@" in c.email else None
        batch.append({
            "first_name": c.first_name,
            "last_name":  c.last_name,
            "email":      c.email,
            "domain":     domain,
            "_contact_id": c.id,  # internal reference
        })

    results = apollo_service.bulk_enrich(batch)

    enriched_count = 0
    for i, enriched in enumerate(results):
        if not enriched or i >= len(contacts):
            continue
        contact = contacts[i]
        for field in ["title", "company", "industry", "region", "apollo_id"]:
            if not getattr(contact, field) and enriched.get(field):
                setattr(contact, field, enriched[field])
        db.add(SyncLog(
            id         = str(uuid.uuid4()),
            contact_id = contact.id,
            platform   = "apollo",
            action     = "bulk_enriched",
            tag        = "bulk",
            status     = "success",
        ))
        enriched_count += 1

    db.commit()

    return {
        "status":   "done",
        "contacts": len(contacts),
        "enriched": enriched_count,
    }
