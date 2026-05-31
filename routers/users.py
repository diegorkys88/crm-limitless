from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from db_session import get_db
from database import User
from schemas import UserCreate, UserOut
import uuid

router = APIRouter()

@router.get("/", response_model=List[UserOut])
def list_users(db: Session = Depends(get_db)):
    return db.query(User).all()

@router.post("/", response_model=UserOut, status_code=201)
def create_user(data: UserCreate, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.email == data.email).first()
    if existing:
        raise HTTPException(status_code=409, detail="User already exists")
    user = User(id=str(uuid.uuid4()), **data.model_dump())
    db.add(user)
    db.commit()
    db.refresh(user)
    return user
