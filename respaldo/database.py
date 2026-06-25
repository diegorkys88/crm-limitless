from sqlalchemy import (
    create_engine, Column, String, Text, DateTime, ForeignKey
)
from sqlalchemy.dialects.sqlite import TEXT
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.sql import func
import uuid

Base = declarative_base()

def gen_uuid():
    return str(uuid.uuid4())


class Contact(Base):
    __tablename__ = "contacts"

    id                = Column(String(36), primary_key=True, default=gen_uuid)
    first_name        = Column(String(100))
    last_name         = Column(String(100))
    email             = Column(String(255), unique=True, nullable=False, index=True)
    phone             = Column(String(50))
    company           = Column(String(255))
    title             = Column(String(255))   # e.g. VP Operations
    industry          = Column(String(100))   # e.g. Automotive
    region            = Column(String(100))   # e.g. California
    # Where this contact came from
    source            = Column(String(50))    # kajabi | clickfunnels | apollo | google
    # AI classification
    score             = Column(String(20))    # hot | warm | cold
    # Current status in the pipeline
    status            = Column(String(50), default="pending")
    # pending → outreach_sent → appointment_scheduled → closed_won | closed_lost
    # IDs in external platforms (for sync)
    kajabi_id         = Column(String(100))
    clickfunnels_id   = Column(String(100))
    apollo_id         = Column(String(100))

    created_at        = Column(DateTime, server_default=func.now())
    updated_at        = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # Relationships
    outreaches        = relationship("Outreach",    back_populates="contact", cascade="all, delete")
    appointments      = relationship("Appointment", back_populates="contact", cascade="all, delete")
    agent_logs        = relationship("AgentLog",    back_populates="contact", cascade="all, delete")
    sync_logs         = relationship("SyncLog",     back_populates="contact", cascade="all, delete")


class Outreach(Base):
    __tablename__ = "outreach"

    id              = Column(String(36), primary_key=True, default=gen_uuid)
    contact_id      = Column(String(36), ForeignKey("contacts.id"), nullable=False, index=True)
    channel         = Column(String(20), default="email")  # email | sms
    subject         = Column(String(500))
    body            = Column(Text)                         # full message written by Claude
    status          = Column(String(30), default="draft")
    # draft → pending_approval → sent → opened → clicked | bounced
    calendly_link   = Column(String(500))                  # unique link per contact
    sent_at         = Column(DateTime)
    opened_at       = Column(DateTime)
    clicked_at      = Column(DateTime)

    contact         = relationship("Contact", back_populates="outreaches")


class User(Base):
    """Sales reps and admins who use the CRM"""
    __tablename__ = "users"

    id              = Column(String(36), primary_key=True, default=gen_uuid)
    name            = Column(String(255), nullable=False)
    email           = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    role            = Column(String(30), default="sales_rep")  # admin | sales_rep
    calendar_id     = Column(String(255))
    is_active       = Column(String(5), default="true")

    created_at      = Column(DateTime, server_default=func.now())

    appointments    = relationship("Appointment", back_populates="assigned_to")


class Appointment(Base):
    __tablename__ = "appointments"

    id                = Column(String(36), primary_key=True, default=gen_uuid)
    contact_id        = Column(String(36), ForeignKey("contacts.id"), nullable=False, index=True)
    assigned_to_id    = Column(String(36), ForeignKey("users.id"), nullable=True)
    calendly_event_id = Column(String(255))  # ID from Calendly webhook
    scheduled_at      = Column(DateTime)
    status            = Column(String(30), default="scheduled")
    # scheduled → completed | cancelled | no_show
    ai_summary        = Column(Text)  # Claude's briefing for the sales rep

    created_at        = Column(DateTime, server_default=func.now())

    contact           = relationship("Contact", back_populates="appointments")
    assigned_to       = relationship("User",    back_populates="appointments")


class AgentLog(Base):
    """Records every action taken by any AI agent"""
    __tablename__ = "agent_log"

    id          = Column(String(36), primary_key=True, default=gen_uuid)
    contact_id  = Column(String(36), ForeignKey("contacts.id"), nullable=True, index=True)
    agent_name  = Column(String(50))
    # prospector | classifier | copywriter | follow_up | scheduler
    action      = Column(String(100))
    # e.g. "scored_contact", "generated_email", "sent_followup"
    input       = Column(Text)   # what was sent to Claude
    output      = Column(Text)   # what Claude returned
    created_at  = Column(DateTime, server_default=func.now())

    contact     = relationship("Contact", back_populates="agent_logs")


class SyncLog(Base):
    """Records every sync action with external platforms"""
    __tablename__ = "sync_log"

    id          = Column(String(36), primary_key=True, default=gen_uuid)
    contact_id  = Column(String(36), ForeignKey("contacts.id"), nullable=True, index=True)
    platform    = Column(String(50))   # kajabi | clickfunnels | calendly | apollo
    action      = Column(String(100))  # import_contact | add_tag | remove_tag | webhook_received
    tag         = Column(String(100))  # crm-contacted | crm-scheduled | crm-closed
    status      = Column(String(30))   # success | failed
    synced_at   = Column(DateTime, server_default=func.now())

    contact     = relationship("Contact", back_populates="sync_logs")


# ── Create all tables ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    engine = create_engine("sqlite:///crm.db", echo=True)
    Base.metadata.create_all(engine)
    print("\n✅ All tables created successfully.")
