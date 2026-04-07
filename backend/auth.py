"""
backend/auth.py — Authentication service (#54).

Handles password hashing, JWT token creation/validation, and the
FastAPI dependency for protecting routes.

Token flow:
    1. User POSTs email + password to /api/auth/login
    2. Server validates credentials, returns a JWT access token
    3. Frontend stores token in localStorage and sends it as
       Authorization: Bearer <token> on every request
    4. Protected routes use get_current_user() dependency to validate

Roles: owner (full access), operator (actions), viewer (read-only)
"""

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.db.models import User

# JWT configuration
SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "golteris-dev-secret-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 24

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Bearer token extractor
security = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    """Hash a password with bcrypt."""
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a password against its hash."""
    return pwd_context.verify(plain, hashed)


def create_access_token(user_id: int, email: str, role: str) -> str:
    """
    Create a JWT access token.

    The token contains the user's ID, email, and role. It expires
    after ACCESS_TOKEN_EXPIRE_HOURS (default 24h).
    """
    expire = datetime.now(timezone.utc) + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    payload = {
        "sub": str(user_id),
        "email": email,
        "role": role,
        "exp": expire,
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    """
    Decode and validate a JWT token.

    Returns the payload dict if valid, None if expired or invalid.
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Session = Depends(get_db),
) -> Optional[User]:
    """
    FastAPI dependency — extracts and validates the current user from JWT.

    Returns the User object if authenticated, None if no token provided.
    Raises 401 if token is invalid or expired.

    Usage:
        @app.get("/api/protected")
        def protected(user: User = Depends(get_current_user)):
            ...
    """
    if not credentials:
        return None

    payload = decode_token(credentials.credentials)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

    user_id = int(payload["sub"])
    user = db.query(User).filter(User.id == user_id, User.active == True).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )

    return user


def require_role(*roles: str):
    """
    FastAPI dependency factory — requires the user to have one of the specified roles.

    Usage:
        @app.post("/api/admin-only")
        def admin(user: User = Depends(require_role("owner"))):
            ...
    """
    def dependency(
        credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
        db: Session = Depends(get_db),
    ) -> User:
        user = get_current_user(credentials, db)
        if not user:
            raise HTTPException(status_code=401, detail="Authentication required")
        if user.role not in roles:
            raise HTTPException(status_code=403, detail=f"Requires role: {', '.join(roles)}")
        return user

    return dependency
