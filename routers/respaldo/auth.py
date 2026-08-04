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

_FAILED = defaultdict(list)      # key (ip|email) -> [timestamps of failures]
_MAX_FAILS   = 5                 # allowed failures
_LOCK_WINDOW = 15 * 60           # within 15 minutes → lock
_LOCK_TIME   = 15 * 60           # lock duration (seconds)


def _login_key(ip: str, email: str) -> str:
    return f"{ip}|{(email or '').lower()}"


def _is_locked(key: str) -> int:
    """Return seconds remaining if locked, else 0."""
    now = _now()
    fails = [t for t in _FAILED[key] if now - t < _LOCK_WINDOW]
    _FAILED[key] = fails
    if len(fails) >= _MAX_FAILS:
        # locked until the oldest relevant failure ages out
        unlock_at = fails[0] + _LOCK_TIME
        remaining = int(unlock_at - now)
        return max(remaining, 0)
    return 0


def _record_fail(key: str):
    _FAILED[key].append(_now())


def _clear_fails(key: str):
    _FAILED.pop(key, None)


# ── Schemas ────────────────────────────────────────────────────────────────────
class LoginRequest(BaseModel):
    email:    EmailStr
    password: str

class RegisterRequest(BaseModel):
    name:     str
    email:    EmailStr
    password: str
    role:     str = "sales_rep"  # admin | sales_rep

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
    Login with email and password.
    Returns a JWT token valid for 24 hours.
    Protected against brute-force: after 5 failed attempts from the same
    IP+email within 15 minutes, further attempts are locked for 15 minutes.
    """
    # Resolve client IP (respect Railway's proxy header)
    client_ip = request.client.host if request.client else "unknown"
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        client_ip = fwd.split(",")[0].strip()

    key = _login_key(client_ip, data.email)

    # Check lock
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

    # Success — clear any failed attempts for this key
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
    """
    existing = db.query(User).filter(User.email == data.email).first()
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")

    if data.role not in ["admin", "sales_rep"]:
        raise HTTPException(status_code=400, detail="Role must be admin or sales_rep")

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
    Create the first admin account.
    Only works if no users exist in the system.
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
        role            = "admin",
        is_active       = "true",
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_token(user.id, user.role)

    return {
        "message":      "Admin account created successfully",
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
    """Get the current user's profile"""
    return current_user


@router.patch("/me/password")
def change_password(
    data:         ChangePasswordRequest,
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_user)
):
    """Change your own password"""
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
    user.is_active = "false"
    db.commit()
    return {"status": "deactivated"}
