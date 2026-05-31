from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from db_session import get_db
from database import Contact, User
from schemas import ContactCreate, ContactUpdate, ContactOut
from auth import get_current_user
import uuid

router = APIRouter()


@router.get("/", response_model=List[ContactOut])
def list_contacts(
    source: Optional[str] = Query(None),
    score:  Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    skip:   int = Query(0),
    limit:  int = Query(50),
    db:     Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    List contacts.
    - Admin: sees all contacts
    - Sales rep: sees only contacts assigned to their appointments
    """
    q = db.query(Contact)

    # Sales reps only see contacts they have appointments with
    if current_user.role == "sales_rep":
        from database import Appointment
        assigned_contact_ids = [
            a.contact_id for a in
            db.query(Appointment).filter(Appointment.assigned_to_id == current_user.id).all()
        ]
        # Also show pending contacts not yet assigned (for outreach)
        q = q.filter(
            (Contact.id.in_(assigned_contact_ids)) |
            (Contact.status == "pending")
        )

    if source: q = q.filter(Contact.source == source)
    if score:  q = q.filter(Contact.score  == score)
    if status: q = q.filter(Contact.status == status)
    return q.offset(skip).limit(limit).all()


@router.get("/{contact_id}", response_model=ContactOut)
def get_contact(contact_id: str, db: Session = Depends(get_db)):
    """Get a single contact by ID"""
    contact = db.query(Contact).filter(Contact.id == contact_id).first()
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    return contact


@router.post("/", response_model=ContactOut, status_code=201)
def create_contact(data: ContactCreate, db: Session = Depends(get_db)):
    """Create a new contact manually"""
    # Check for duplicate email
    existing = db.query(Contact).filter(Contact.email == data.email).first()
    if existing:
        raise HTTPException(status_code=409, detail="Contact with this email already exists")

    contact = Contact(id=str(uuid.uuid4()), **data.model_dump())
    db.add(contact)
    db.commit()
    db.refresh(contact)
    return contact


@router.patch("/{contact_id}", response_model=ContactOut)
def update_contact(contact_id: str, data: ContactUpdate, db: Session = Depends(get_db)):
    """Update contact fields"""
    contact = db.query(Contact).filter(Contact.id == contact_id).first()
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")

    for field, value in data.model_dump(exclude_none=True).items():
        setattr(contact, field, value)

    db.commit()
    db.refresh(contact)
    return contact


@router.delete("/{contact_id}", status_code=204)
def delete_contact(contact_id: str, db: Session = Depends(get_db)):
    """Delete a contact"""
    contact = db.query(Contact).filter(Contact.id == contact_id).first()
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    db.delete(contact)
    db.commit()
