import os
from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from db_session import get_db
from database import User
from dotenv import load_dotenv

load_dotenv()

# ── Config ─────────────────────────────────────────────────────────────────────
SECRET_KEY   = os.getenv("JWT_SECRET_KEY", "limitless-leadership-crm-secret-2026")
ALGORITHM    = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 24

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
bearer      = HTTPBearer()


# ── Password ───────────────────────────────────────────────────────────────────
def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


# ── JWT Token ──────────────────────────────────────────────────────────────────
def create_token(user_id: str, role: str) -> str:
    expire = datetime.utcnow() + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    payload = {
        "sub":  user_id,
        "role": role,
        "exp":  expire,
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(
            status_code = status.HTTP_401_UNAUTHORIZED,
            detail      = "Invalid or expired token",
            headers     = {"WWW-Authenticate": "Bearer"},
        )


# ── FastAPI Dependencies ───────────────────────────────────────────────────────
def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer),
    db: Session = Depends(get_db)
) -> User:
    """Inject the current logged-in user into any endpoint"""
    payload = decode_token(credentials.credentials)
    user    = db.query(User).filter(User.id == payload.get("sub")).first()
    if not user or user.is_active == "false":
        raise HTTPException(status_code=401, detail="User not found or inactive")
    return user

def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """Only admins can access this endpoint"""
    if current_user.role != "admin":
        raise HTTPException(
            status_code = status.HTTP_403_FORBIDDEN,
            detail      = "Admin access required"
        )
    return current_user

def get_current_user_optional(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(HTTPBearer(auto_error=False)),
    db: Session = Depends(get_db)
) -> Optional[User]:
    """Returns user if token present, None if not — for optional auth"""
    if not credentials:
        return None
    try:
        payload = decode_token(credentials.credentials)
        return db.query(User).filter(User.id == payload.get("sub")).first()
    except Exception:
        return None
