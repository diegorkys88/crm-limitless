from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime


# ── Contact ────────────────────────────────────────────────────────────────────

class ContactCreate(BaseModel):
    """What we receive when creating a contact"""
    first_name:       Optional[str] = None
    last_name:        Optional[str] = None
    email:            EmailStr
    phone:            Optional[str] = None
    company:          Optional[str] = None
    title:            Optional[str] = None
    industry:         Optional[str] = None
    region:           Optional[str] = None
    source:           Optional[str] = "manual"  # kajabi|clickfunnels|apollo|google|manual
    kajabi_id:        Optional[str] = None
    clickfunnels_id:  Optional[str] = None
    apollo_id:        Optional[str] = None

class ContactUpdate(BaseModel):
    """Fields that can be updated"""
    first_name:  Optional[str] = None
    last_name:   Optional[str] = None
    phone:       Optional[str] = None
    company:     Optional[str] = None
    title:       Optional[str] = None
    industry:    Optional[str] = None
    region:      Optional[str] = None
    score:       Optional[str] = None   # hot|warm|cold
    status:      Optional[str] = None

class ContactOut(BaseModel):
    """What we return to the frontend"""
    id:               str
    first_name:       Optional[str]
    last_name:        Optional[str]
    email:            str
    phone:            Optional[str]
    company:          Optional[str]
    title:            Optional[str]
    industry:         Optional[str]
    region:           Optional[str]
    source:           Optional[str]
    score:            Optional[str]
    status:           Optional[str]
    kajabi_id:        Optional[str]
    clickfunnels_id:  Optional[str]
    apollo_id:        Optional[str]
    created_at:       Optional[datetime]

    class Config:
        from_attributes = True


# ── Outreach ───────────────────────────────────────────────────────────────────

class OutreachCreate(BaseModel):
    contact_id:    str
    channel:       str = "email"
    subject:       Optional[str] = None
    body:          Optional[str] = None
    calendly_link: Optional[str] = None

class OutreachOut(BaseModel):
    id:            str
    contact_id:    str
    channel:       str
    subject:       Optional[str]
    body:          Optional[str]
    status:        str
    calendly_link: Optional[str]
    sent_at:       Optional[datetime]
    opened_at:     Optional[datetime]
    clicked_at:    Optional[datetime]

    class Config:
        from_attributes = True


# ── Appointment ────────────────────────────────────────────────────────────────

class AppointmentOut(BaseModel):
    id:                str
    contact_id:        str
    assigned_to_id:    Optional[str]
    calendly_event_id: Optional[str]
    scheduled_at:      Optional[datetime]
    status:            str
    ai_summary:        Optional[str]
    created_at:        Optional[datetime]

    class Config:
        from_attributes = True


# ── User ───────────────────────────────────────────────────────────────────────

class UserCreate(BaseModel):
    name:        str
    email:       EmailStr
    role:        str = "sales_rep"
    calendar_id: Optional[str] = None

class UserOut(BaseModel):
    id:          str
    name:        str
    email:       str
    role:        str
    calendar_id: Optional[str]
    created_at:  Optional[datetime]

    class Config:
        from_attributes = True


# ── Webhooks ───────────────────────────────────────────────────────────────────

class CalendlyWebhookPayload(BaseModel):
    """Payload received from Calendly when someone books"""
    event:   str           # invitee.created | invitee.canceled
    payload: dict


class ClickFunnelsWebhookPayload(BaseModel):
    """Payload received from ClickFunnels when a form is submitted"""
    event_type: str
    data:       dict
