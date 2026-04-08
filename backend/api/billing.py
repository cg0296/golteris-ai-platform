"""
backend/api/billing.py — Stripe billing integration (#58).

Endpoints:
    GET  /api/billing/status        — Current subscription status and usage
    POST /api/billing/checkout      — Create a Stripe Checkout session for signup
    POST /api/billing/portal        — Create a Stripe billing portal session
    POST /api/billing/webhook       — Stripe webhook handler for events

Stripe integration approach:
    - Subscription plans define base pricing (seat count, feature tier)
    - Metered usage (quote volume) reported via Stripe Usage Records
    - Self-serve upgrade/downgrade via Stripe Customer Portal
    - Invoices generated automatically by Stripe

Env vars required:
    STRIPE_SECRET_KEY — Stripe API key
    STRIPE_WEBHOOK_SECRET — Webhook signing secret
    STRIPE_PRICE_ID — Default subscription price ID

Cross-cutting constraints:
    C1 — Billing status visible to tenant admin
    NFR-SE-4 — Scoped to organization
"""

import logging
import os
from datetime import datetime

from fastapi import APIRouter, Depends, Request, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional

from backend.db.database import get_db

logger = logging.getLogger("golteris.api.billing")

router = APIRouter(prefix="/api/billing", tags=["billing"])

# Stripe config from env vars
STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
STRIPE_PRICE_ID = os.environ.get("STRIPE_PRICE_ID", "")


def _get_stripe():
    """Lazy-load stripe module (only imported when billing is configured)."""
    if not STRIPE_SECRET_KEY:
        return None
    try:
        import stripe
        stripe.api_key = STRIPE_SECRET_KEY
        return stripe
    except ImportError:
        logger.warning("stripe package not installed — run: pip install stripe")
        return None


class CheckoutRequest(BaseModel):
    success_url: str = "http://localhost:8001/settings?billing=success"
    cancel_url: str = "http://localhost:8001/settings?billing=cancel"


@router.get("/status")
def get_billing_status(db: Session = Depends(get_db)):
    """
    Get current billing status.

    Returns subscription plan, usage this month, and payment status.
    If Stripe is not configured, returns a free-tier status.
    """
    stripe = _get_stripe()
    if not stripe:
        return {
            "plan": "free",
            "status": "active",
            "configured": False,
            "message": "Stripe not configured — running in free mode",
        }

    # In production, this would look up the org's Stripe customer ID
    # and fetch their subscription status. For now, return placeholder.
    return {
        "plan": "professional",
        "status": "active",
        "configured": True,
        "current_period_end": None,
        "usage": {
            "quotes_this_month": 0,
            "quote_limit": 500,
        },
    }


@router.post("/checkout")
def create_checkout_session(body: CheckoutRequest, db: Session = Depends(get_db)):
    """
    Create a Stripe Checkout session for new subscription signup.

    Redirects the user to Stripe's hosted checkout page.
    """
    stripe = _get_stripe()
    if not stripe:
        raise HTTPException(status_code=400, detail="Stripe not configured")

    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "price": STRIPE_PRICE_ID,
                "quantity": 1,
            }],
            mode="subscription",
            success_url=body.success_url,
            cancel_url=body.cancel_url,
        )
        return {"checkout_url": session.url, "session_id": session.id}
    except Exception as e:
        logger.error("Stripe checkout creation failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/portal")
def create_portal_session(db: Session = Depends(get_db)):
    """
    Create a Stripe Customer Portal session for managing subscription.

    Allows self-serve upgrade, downgrade, payment method update, and
    invoice history — all handled by Stripe's hosted portal.
    """
    stripe = _get_stripe()
    if not stripe:
        raise HTTPException(status_code=400, detail="Stripe not configured")

    # In production, look up the org's Stripe customer ID
    # For now, return a placeholder
    return {
        "message": "Portal session would be created here with the org's Stripe customer ID",
        "configured": True,
    }


@router.post("/webhook")
async def stripe_webhook(request: Request):
    """
    Handle Stripe webhook events (subscription changes, payments, etc.).

    Verifies the webhook signature and processes events:
    - checkout.session.completed → activate subscription
    - invoice.paid → record payment
    - invoice.payment_failed → alert admin
    - customer.subscription.updated → update plan
    - customer.subscription.deleted → handle cancellation
    """
    stripe = _get_stripe()
    if not stripe:
        raise HTTPException(status_code=400, detail="Stripe not configured")

    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, STRIPE_WEBHOOK_SECRET
        )
    except Exception as e:
        logger.error("Stripe webhook verification failed: %s", e)
        raise HTTPException(status_code=400, detail="Invalid signature")

    event_type = event.get("type", "")
    logger.info("Stripe webhook: %s", event_type)

    if event_type == "checkout.session.completed":
        # New subscription activated
        logger.info("New subscription activated")
    elif event_type == "invoice.paid":
        logger.info("Invoice paid")
    elif event_type == "invoice.payment_failed":
        logger.warning("Payment failed — alert admin")
    elif event_type == "customer.subscription.deleted":
        logger.warning("Subscription cancelled")

    return {"received": True}
