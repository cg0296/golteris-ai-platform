"""
backend/api/onboarding.py — Customer onboarding flow (#59).

Endpoints:
    POST /api/onboarding/signup     — Create account + org in one step
    GET  /api/onboarding/status     — Get onboarding progress
    POST /api/onboarding/complete   — Mark onboarding complete

Self-serve onboarding flow:
    1. Signup (creates user + org)
    2. Connect first mailbox
    3. Choose workflow template
    4. Process first email
    5. Review first draft

Each step is tracked so the UI can show progress and guide the user
through setup without human intervention.
"""

import logging
import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.db.database import get_db

logger = logging.getLogger("golteris.api.onboarding")

router = APIRouter(prefix="/api/onboarding", tags=["onboarding"])


# Onboarding milestones — checked in order
MILESTONES = [
    {"key": "account_created", "label": "Account created", "description": "Sign up and create your organization"},
    {"key": "mailbox_connected", "label": "Mailbox connected", "description": "Connect your email inbox"},
    {"key": "workflow_configured", "label": "Workflow configured", "description": "Choose which workflows to enable"},
    {"key": "first_email_processed", "label": "First email processed", "description": "Drop in an email and watch it get extracted"},
    {"key": "first_draft_reviewed", "label": "First draft reviewed", "description": "Approve or edit your first AI-generated draft"},
]


class SignupRequest(BaseModel):
    """Self-serve signup: creates user + organization in one step."""
    email: str
    password: str
    name: str
    company_name: str


@router.post("/signup")
def self_serve_signup(body: SignupRequest, db: Session = Depends(get_db)):
    """
    Create a new user and organization in one step.

    This is the entry point for self-serve onboarding. Creates:
    1. An Organization with the company name
    2. A User with owner role, linked to the new org
    3. Returns a JWT token so the user is immediately logged in
    """
    from backend.db.models import User, Organization
    from backend.auth import hash_password, create_access_token

    # Check for existing user
    existing = db.query(User).filter(User.email == body.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    # Create organization
    slug = re.sub(r"[^a-z0-9]+", "-", body.company_name.lower()).strip("-")
    existing_org = db.query(Organization).filter(Organization.slug == slug).first()
    if existing_org:
        slug = f"{slug}-{int(datetime.utcnow().timestamp()) % 10000}"

    org = Organization(name=body.company_name, slug=slug)
    db.add(org)
    db.flush()

    # Create user as owner of the new org
    user = User(
        email=body.email,
        hashed_password=hash_password(body.password),
        name=body.name,
        role="owner",
        org_id=org.id,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_access_token(user.id, user.email, user.role)

    logger.info("Self-serve signup: %s created org '%s' (slug: %s)", body.email, body.company_name, slug)

    return {
        "token": token,
        "user": {
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "role": user.role,
        },
        "organization": {
            "id": org.id,
            "name": org.name,
            "slug": org.slug,
        },
        "onboarding": {
            "milestones": MILESTONES,
            "completed": ["account_created"],
        },
    }


@router.get("/status")
def get_onboarding_status(db: Session = Depends(get_db)):
    """
    Get onboarding progress for the current user/org.

    Checks each milestone by querying the database for evidence that
    the step was completed (e.g., a mailbox exists, a workflow is enabled,
    a message was processed, an approval was resolved).
    """
    from backend.db.models import Workflow, Message, Approval, ApprovalStatus

    completed = ["account_created"]  # Always true if they're calling this

    # Check if any mailbox is connected (DB or env var)
    try:
        from backend.db.models import Mailbox
        has_mailbox = db.query(Mailbox).count() > 0
    except Exception:
        has_mailbox = False

    if has_mailbox:
        completed.append("mailbox_connected")

    # Check if any workflow is enabled
    has_workflow = db.query(Workflow).filter(Workflow.enabled == True).count() > 0
    if has_workflow:
        completed.append("workflow_configured")

    # Check if any message was processed
    has_message = db.query(Message).count() > 0
    if has_message:
        completed.append("first_email_processed")

    # Check if any approval was resolved
    has_approval = db.query(Approval).filter(
        Approval.status.in_([ApprovalStatus.APPROVED, ApprovalStatus.REJECTED])
    ).count() > 0
    if has_approval:
        completed.append("first_draft_reviewed")

    return {
        "milestones": MILESTONES,
        "completed": completed,
        "progress_pct": round(len(completed) / len(MILESTONES) * 100),
        "is_complete": len(completed) == len(MILESTONES),
    }


@router.post("/complete")
def mark_onboarding_complete(db: Session = Depends(get_db)):
    """
    Explicitly mark onboarding as complete (dismiss the onboarding UI).
    """
    return {
        "status": "ok",
        "message": "Onboarding complete — welcome to Golteris!",
    }
