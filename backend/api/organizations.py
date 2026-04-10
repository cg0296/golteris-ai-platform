"""
backend/api/organizations.py — Organization (tenant) management API (#55).

Endpoints:
    GET    /api/organizations          — List all organizations
    POST   /api/organizations          — Create a new organization
    GET    /api/organizations/:id      — Get organization details
    PATCH  /api/organizations/:id      — Update organization settings

Used by the admin to create and manage tenants. In v1 single-tenant mode,
there is one organization. In v2, multiple organizations exist.

Cross-cutting constraints:
    NFR-SE-4 — org_id on every row, managed here
"""

import logging
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional

from backend.db.database import get_db
from backend.db.models import Organization, User

logger = logging.getLogger("golteris.api.organizations")

router = APIRouter(prefix="/api/organizations", tags=["organizations"])


class CreateOrgRequest(BaseModel):
    name: str
    slug: Optional[str] = None


class UpdateOrgRequest(BaseModel):
    name: Optional[str] = None
    settings: Optional[dict] = None
    active: Optional[bool] = None


@router.get("")
def list_organizations(db: Session = Depends(get_db)):
    """List all organizations."""
    orgs = db.query(Organization).order_by(Organization.created_at.desc()).all()
    return {
        "organizations": [_serialize_org(o, db) for o in orgs],
        "total": len(orgs),
    }


@router.post("")
def create_organization(body: CreateOrgRequest, db: Session = Depends(get_db)):
    """
    Create a new tenant organization.

    Auto-generates a slug from the name if not provided.
    """
    slug = body.slug or re.sub(r"[^a-z0-9]+", "-", body.name.lower()).strip("-")

    existing = db.query(Organization).filter(Organization.slug == slug).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Organization with slug '{slug}' already exists")

    org = Organization(name=body.name, slug=slug)
    db.add(org)
    db.commit()
    db.refresh(org)

    logger.info("Created organization '%s' (slug: %s)", body.name, slug)
    return _serialize_org(org, db)


@router.get("/profile")
def get_org_profile_endpoint(db: Session = Depends(get_db)):
    """
    Get the active org's company profile for frontend branding (#174).

    Returns company_name, sign_off, ref_prefix, tagline.
    Used by Sidebar, LoginPage, and anywhere the company name appears.
    """
    from backend.services.org_profile import get_org_profile
    return get_org_profile(db)


@router.get("/{org_id}")
def get_organization(org_id: int, db: Session = Depends(get_db)):
    """Get details of a specific organization."""
    org = db.query(Organization).filter(Organization.id == org_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    return _serialize_org(org, db)


@router.patch("/{org_id}")
def update_organization(org_id: int, body: UpdateOrgRequest, db: Session = Depends(get_db)):
    """Update an organization's name, settings, or active status."""
    org = db.query(Organization).filter(Organization.id == org_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    if body.name is not None:
        org.name = body.name
    if body.settings is not None:
        org.settings = body.settings
    if body.active is not None:
        org.active = body.active

    db.commit()
    db.refresh(org)
    return _serialize_org(org, db)


def _serialize_org(org: Organization, db: Session) -> dict:
    user_count = db.query(User).filter(User.org_id == org.id).count()
    return {
        "id": org.id,
        "name": org.name,
        "slug": org.slug,
        "settings": org.settings,
        "active": org.active,
        "user_count": user_count,
        "created_at": org.created_at.isoformat() if org.created_at else None,
    }
