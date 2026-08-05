from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr
from typing import Optional
from db_session import get_db
from database import User
from auth import hash_password, verify_password, create_token, get_current_user, require_admin
import uuid

router = APIRouter()

# ── Brute-force protection: track failed login attempts per IP + email ──
from collections import defaultdict
from time import time as _now

_FAILED = defaultdict(list)
_MAX_FAILS   = 5
_LOCK_WINDOW = 15 * 60
_LOCK_TIME   = 15 * 60


def _login_key(ip: str, email: str) -> str:
    return f"{ip}|{(email or '').lower()}"


def _is_locked(key: str) -> int:
    now = _now()
    fails = [t for t in _FAILED[key] if now - t < _LOCK_WINDOW]
    _FAILED[key] = fails
    if len(fails) >= _MAX_FAILS:
        unlock_at = fails[0] + _LOCK_TIME
        remaining = int(unlock_at - now)
        return max(remaining, 0)
    return 0


def _record_fail(key: str):
    _FAILED[key].append(_now())


def _clear_fails(key: str):
    _FAILED.pop(key, None)


# ── Roles ──────────────────────────────────────────────────────────────────────
# super_admin → the single owner account; everything auto-assigns to them.
# admin       → regular users who operate the CRM.
VALID_ROLES = ["super_admin", "admin"]


# ── Schemas ────────────────────────────────────────────────────────────────────
class LoginRequest(BaseModel):
    email:    EmailStr
    password: str

class RegisterRequest(BaseModel):
    name:     str
    email:    EmailStr
    password: str
    role:     str = "admin"

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password:     str

class UserOut(BaseModel):
    id:         str
    name:       str
    email:      str
    role:       str
    is_active:  str
    class Config:
        from_attributes = True


# ── Login ──────────────────────────────────────────────────────────────────────
@router.post("/login")
def login(data: LoginRequest, request: Request, db: Session = Depends(get_db)):
    """
    Login with email and password. JWT valid 24h.
    Brute-force protected: 5 failed attempts per IP+email in 15 min → 15 min lock.
    """
    client_ip = request.client.host if request.client else "unknown"
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        client_ip = fwd.split(",")[0].strip()

    key = _login_key(client_ip, data.email)

    locked_for = _is_locked(key)
    if locked_for > 0:
        minutes = (locked_for // 60) + 1
        raise HTTPException(
            status_code = status.HTTP_429_TOO_MANY_REQUESTS,
            detail      = f"Too many failed attempts. Try again in {minutes} minute(s)."
        )

    user = db.query(User).filter(User.email == data.email).first()

    if not user or not verify_password(data.password, user.hashed_password):
        _record_fail(key)
        raise HTTPException(
            status_code = status.HTTP_401_UNAUTHORIZED,
            detail      = "Invalid email or password"
        )

    if user.is_active == "false":
        raise HTTPException(status_code=403, detail="Account is inactive")

    _clear_fails(key)

    token = create_token(user.id, user.role)

    return {
        "access_token": token,
        "token_type":   "bearer",
        "user": {
            "id":   user.id,
            "name": user.name,
            "role": user.role,
            "email": user.email,
        }
    }


# ── Register (admin only) ──────────────────────────────────────────────────────
@router.post("/register", response_model=UserOut)
def register(
    data: RegisterRequest,
    db:   Session = Depends(get_db),
    _:    User    = Depends(require_admin)
):
    """
    Create a new user. Only admins can do this.
    Roles: super_admin (only ONE allowed) | admin.
    """
    existing = db.query(User).filter(User.email == data.email).first()
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")

    if data.role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail="Role must be super_admin or admin")

    # Only ONE super_admin may exist
    if data.role == "super_admin":
        existing_super = db.query(User).filter(User.role == "super_admin").first()
        if existing_super:
            raise HTTPException(
                status_code=409,
                detail="A super admin already exists. Only one is allowed."
            )

    user = User(
        id              = str(uuid.uuid4()),
        name            = data.name,
        email           = data.email,
        hashed_password = hash_password(data.password),
        role            = data.role,
        is_active       = "true",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


# ── Setup first admin (only if no users exist) ────────────────────────────────
@router.post("/setup")
def setup_admin(data: RegisterRequest, db: Session = Depends(get_db)):
    """
    Create the first account. Only works if no users exist.
    The first account is created as super_admin (the owner).
    """
    count = db.query(User).count()
    if count > 0:
        raise HTTPException(
            status_code = 403,
            detail      = "Setup already completed. Use /auth/register to add users."
        )

    user = User(
        id              = str(uuid.uuid4()),
        name            = data.name,
        email           = data.email,
        hashed_password = hash_password(data.password),
        role            = "super_admin",
        is_active       = "true",
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_token(user.id, user.role)

    return {
        "message":      "Super admin account created successfully",
        "access_token": token,
        "token_type":   "bearer",
        "user": {
            "id":    user.id,
            "name":  user.name,
            "role":  user.role,
            "email": user.email,
        }
    }


# ── Profile ────────────────────────────────────────────────────────────────────
@router.get("/me", response_model=UserOut)
def get_profile(current_user: User = Depends(get_current_user)):
    return current_user


@router.patch("/me/password")
def change_password(
    data:         ChangePasswordRequest,
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_user)
):
    if not verify_password(data.current_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect")

    current_user.hashed_password = hash_password(data.new_password)
    db.commit()
    return {"status": "password updated"}


# ── User management (admin only) ───────────────────────────────────────────────
@router.get("/users", response_model=list[UserOut])
def list_users(
    db: Session = Depends(get_db),
    _:  User    = Depends(require_admin)
):
    return db.query(User).all()


@router.patch("/users/{user_id}/deactivate")
def deactivate_user(
    user_id: str,
    db:      Session = Depends(get_db),
    _:       User    = Depends(require_admin)
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    # Protect the super_admin from being deactivated
    if user.role == "super_admin":
        raise HTTPException(status_code=403, detail="Cannot deactivate the super admin")
    user.is_active = "false"
    db.commit()
    return {"status": "deactivated"}


@router.delete("/users/{user_id}", status_code=204)
def delete_user(
    user_id:      str,
    db:           Session = Depends(get_db),
    current_user: User    = Depends(require_admin)
):
    """
    Permanently delete a user.
    Protections:
      - Cannot delete the super_admin (the owner account)
      - Cannot delete yourself
      - Any appointments assigned to them are reassigned to the super_admin
        (or left unassigned if no super_admin exists)
    """
    from database import Appointment

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if user.role == "super_admin":
        raise HTTPException(status_code=403, detail="Cannot delete the super admin")

    if user.id == current_user.id:
        raise HTTPException(status_code=403, detail="You cannot delete your own account")

    # Reassign this user's appointments to the super_admin (fallback: unassigned)
    super_admin = db.query(User).filter(User.role == "super_admin").first()
    reassign_to = super_admin.id if super_admin else None
    db.query(Appointment).filter(
        Appointment.assigned_to_id == user_id
    ).update({Appointment.assigned_to_id: reassign_to})

    db.delete(user)
    db.commit()
