from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from db_session import get_db
from database import Appointment, User
from schemas import AppointmentOut, UserCreate, UserOut
import uuid

# ── Appointments ───────────────────────────────────────────────────────────────
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
