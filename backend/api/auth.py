"""
backend/api/auth.py — Authentication API endpoints (#54).

Endpoints:
    POST /api/auth/login    — Login with email + password, returns JWT
    POST /api/auth/register — Create a new user (owner only)
    GET  /api/auth/me        — Get current user info from token
    POST /api/auth/logout    — Client-side only (clears token)
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.auth import (
    create_access_token,
    get_current_user,
    hash_password,
    require_role,
    verify_password,
)
from backend.db.database import get_db
from backend.db.models import User

logger = logging.getLogger("golteris.api.auth")

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: str
    password: str


class RegisterRequest(BaseModel):
    email: str
    password: str
    name: str
    role: str = "operator"


@router.post("/login")
def login(body: LoginRequest, db: Session = Depends(get_db)):
    """
    Authenticate with email + password. Returns a JWT access token.
    """
    user = db.query(User).filter(User.email == body.email).first()
    if not user or not verify_password(body.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if not user.active:
        raise HTTPException(status_code=401, detail="Account is disabled")

    token = create_access_token(user.id, user.email, user.role)

    return {
        "token": token,
        "user": {
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "role": user.role,
        },
    }


@router.post("/register")
def register(
    body: RegisterRequest,
    db: Session = Depends(get_db),
):
    """
    Create a new user. For initial setup, allows creation without auth.
    After first user exists, requires owner role.
    """
    # Check if any users exist — first user can register freely
    user_count = db.query(User).count()

    if user_count > 0:
        # Subsequent users need an authenticated owner
        # For now, allow registration if password matches a setup key
        pass  # TODO: enforce owner auth for subsequent registrations

    # Check for duplicate email
    existing = db.query(User).filter(User.email == body.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    user = User(
        email=body.email,
        hashed_password=hash_password(body.password),
        name=body.name,
        role=body.role if user_count == 0 else "operator",  # First user is owner
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_access_token(user.id, user.email, user.role)

    return {
        "token": token,
        "user": {
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "role": user.role,
        },
    }


@router.get("/me")
def get_me(user: User = Depends(get_current_user)):
    """Get the current authenticated user's info."""
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "role": user.role,
    }
