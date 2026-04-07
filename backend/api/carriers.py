"""
backend/api/carriers.py — FastAPI router for carrier management (#32).

Endpoints:
    GET  /api/carriers              — List all active carriers
    GET  /api/carriers/match/{rfq_id} — Carriers matching an RFQ's equipment/lane
    POST /api/rfqs/{rfq_id}/distribute — Distribute RFQ to selected carriers

Cross-cutting constraints:
    C2 — Distribution creates a pending approval; sends only after approval
"""

import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.db.models import Carrier, RFQ
from backend.services.carrier_distribution import (
    distribute_to_carriers,
    get_matching_carriers,
    list_carriers,
)

logger = logging.getLogger("golteris.api.carriers")

router = APIRouter(tags=["carriers"])


@router.get("/api/carriers")
def get_carriers(db: Session = Depends(get_db)):
    """List all active carriers for the carrier selection UI."""
    carriers = list_carriers(db, active_only=True)
    return {
        "carriers": [_serialize_carrier(c) for c in carriers],
        "total": len(carriers),
    }


@router.get("/api/carriers/match/{rfq_id}")
def get_matching(rfq_id: int, db: Session = Depends(get_db)):
    """
    Return carriers matching an RFQ's equipment type and lane.

    Used by the carrier selection modal to pre-check matching carriers.
    """
    rfq = db.query(RFQ).filter(RFQ.id == rfq_id).first()
    if not rfq:
        raise HTTPException(status_code=404, detail=f"RFQ {rfq_id} not found")

    carriers = get_matching_carriers(db, rfq)
    return {
        "carriers": [_serialize_carrier(c) for c in carriers],
        "total": len(carriers),
        "rfq_id": rfq_id,
    }


class DistributeRequest(BaseModel):
    """Request body for carrier RFQ distribution."""
    carrier_ids: List[int]


@router.post("/api/rfqs/{rfq_id}/distribute")
def distribute_rfq(
    rfq_id: int,
    body: DistributeRequest,
    db: Session = Depends(get_db),
):
    """
    Distribute an RFQ to selected carriers.

    Creates a batch approval (C2 gate) and per-carrier send tracking.
    The broker must approve before any emails are sent.
    """
    try:
        result = distribute_to_carriers(db, rfq_id, body.carrier_ids)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return result


def _serialize_carrier(carrier: Carrier) -> dict:
    """Convert a Carrier to a JSON dict for the selection UI."""
    return {
        "id": carrier.id,
        "name": carrier.name,
        "email": carrier.email,
        "contact_name": carrier.contact_name,
        "phone": carrier.phone,
        "equipment_types": carrier.equipment_types or [],
        "lanes": carrier.lanes or [],
        "preferred": carrier.preferred,
    }
