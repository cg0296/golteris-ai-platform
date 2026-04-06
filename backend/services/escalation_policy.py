"""
backend/services/escalation_policy.py — Confidence scoring and HITL escalation policy.

This service decides whether an RFQ needs human review based on per-field
confidence scores from the extraction agent. It replaces the hardcoded 0.90
threshold in extraction.py and validation.py with a configurable policy
that can vary per workflow.

How it works:
    1. Load the escalation policy for the workflow (from workflows.config JSONB)
    2. Evaluate each field's confidence score against the policy thresholds
    3. If any required field is below threshold, flag for HITL review
    4. Create a human-readable review card explaining what's uncertain and why

The policy is stored in the workflow's config JSONB under the key
"escalation_policy". Example:
    {
        "escalation_policy": {
            "default_threshold": 0.90,
            "field_thresholds": {
                "destination": 0.85,
                "commodity": 0.80
            }
        }
    }

If no policy is configured, the default (0.90 for all fields) is used.
This matches the existing behavior before this issue was implemented.

Called by:
    - backend/agents/extraction.py — to determine initial RFQ state
    - backend/agents/validation.py — to decide which fields need follow-up

Cross-cutting constraints:
    C3 — Escalation reasons use plain English ("destination is unclear")
    FR-AG-2 — Every extracted field has a confidence score (0.0-1.0)
    FR-AG-3 — Low-confidence fields flag the RFQ into Needs Review
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy.orm import Session

from backend.db.models import AuditEvent, RFQ, Workflow

logger = logging.getLogger("golteris.services.escalation_policy")

# Default threshold when no policy is configured — matches FR-AG-2
DEFAULT_THRESHOLD = 0.90

# Required fields that trigger escalation when below threshold.
# These are the fields a broker MUST have to send a quote to carriers.
REQUIRED_FIELDS = ["origin", "destination", "equipment_type", "truck_count", "commodity"]

# Human-readable labels for each field — used in review cards (C3)
FIELD_LABELS = {
    "origin": "pickup location",
    "destination": "delivery location",
    "equipment_type": "truck type",
    "truck_count": "number of trucks",
    "commodity": "what's being shipped",
    "weight_lbs": "load weight",
}


@dataclass
class EscalationPolicy:
    """
    Configuration for when to escalate an RFQ for human review.

    Attributes:
        default_threshold: The confidence threshold for all fields (0.0-1.0).
            Fields with confidence below this trigger escalation.
        field_thresholds: Per-field overrides. If a field has an entry here,
            its threshold is used instead of default_threshold. Useful for
            relaxing thresholds on commonly ambiguous fields (e.g., destination
            in markets where city names repeat across states).
    """
    default_threshold: float = DEFAULT_THRESHOLD
    field_thresholds: dict[str, float] = field(default_factory=dict)

    def get_threshold(self, field_name: str) -> float:
        """Get the effective threshold for a specific field."""
        return self.field_thresholds.get(field_name, self.default_threshold)


@dataclass
class EscalationResult:
    """
    The outcome of evaluating an RFQ against the escalation policy.

    Attributes:
        needs_review: True if any field failed its threshold.
        missing_fields: Fields that are null (not extracted at all).
        low_confidence_fields: Fields below threshold with their scores.
        reasons: Human-readable list of why escalation was triggered (C3).
    """
    needs_review: bool = False
    missing_fields: list[tuple[str, str]] = field(default_factory=list)  # (field_name, label)
    low_confidence_fields: list[tuple[str, str, float, float]] = field(default_factory=list)  # (field_name, label, score, threshold)
    reasons: list[str] = field(default_factory=list)


def get_policy_for_workflow(db: Session, workflow_id: Optional[int] = None) -> EscalationPolicy:
    """
    Load the escalation policy from a workflow's config.

    If no workflow_id is provided or the workflow has no policy configured,
    returns the default policy (0.90 for all fields).

    Args:
        db: SQLAlchemy session.
        workflow_id: The workflow to load policy for (optional).

    Returns:
        EscalationPolicy with the configured or default thresholds.
    """
    if workflow_id is None:
        return EscalationPolicy()

    workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
    if not workflow:
        return EscalationPolicy()

    config = workflow.config or {}
    policy_config = config.get("escalation_policy", {})

    return EscalationPolicy(
        default_threshold=policy_config.get("default_threshold", DEFAULT_THRESHOLD),
        field_thresholds=policy_config.get("field_thresholds", {}),
    )


def evaluate_rfq(
    rfq: RFQ,
    policy: Optional[EscalationPolicy] = None,
) -> EscalationResult:
    """
    Evaluate an RFQ's confidence scores against the escalation policy.

    Checks each required field for:
    1. Missing values (null) — always triggers escalation
    2. Low confidence — below the policy threshold for that field

    Args:
        rfq: The RFQ to evaluate.
        policy: The escalation policy to apply. If None, uses the default.

    Returns:
        EscalationResult with the decision and human-readable reasons.
    """
    if policy is None:
        policy = EscalationPolicy()

    confidence = rfq.confidence_scores or {}
    result = EscalationResult()

    for field_name in REQUIRED_FIELDS:
        label = FIELD_LABELS.get(field_name, field_name)
        value = getattr(rfq, field_name, None)
        threshold = policy.get_threshold(field_name)

        if value is None:
            # Field is missing entirely
            result.missing_fields.append((field_name, label))
            result.reasons.append(f"{label.capitalize()} is missing")
            result.needs_review = True
        else:
            score = confidence.get(field_name, 1.0)
            if score < threshold:
                # Field exists but confidence is too low
                result.low_confidence_fields.append((field_name, label, score, threshold))
                # C3: plain English reason, not "confidence 0.45 < threshold 0.90"
                result.reasons.append(
                    f"{label.capitalize()} is unclear — \"{value}\" "
                    f"(confidence {score:.0%}, needs {threshold:.0%})"
                )
                result.needs_review = True

    return result


def create_review_card(
    db: Session,
    rfq_id: int,
    escalation: EscalationResult,
) -> Optional[AuditEvent]:
    """
    Create a human-readable review card for an escalated RFQ.

    The review card appears in the RFQ detail timeline and the Needs Review
    queue. It explains in plain English what's uncertain and why the RFQ
    was flagged for human review (C3, FR-AG-3).

    Args:
        db: SQLAlchemy session.
        rfq_id: The RFQ that was escalated.
        escalation: The escalation result with reasons.

    Returns:
        The created AuditEvent, or None if no escalation was needed.
    """
    if not escalation.needs_review:
        return None

    # Build human-readable description (C3)
    if len(escalation.reasons) == 1:
        description = f"Flagged for review — {escalation.reasons[0].lower()}"
    else:
        reason_list = "; ".join(r.lower() for r in escalation.reasons)
        description = f"Flagged for review — {reason_list}"

    event = AuditEvent(
        rfq_id=rfq_id,
        event_type="escalated_for_review",
        actor="escalation_policy",
        description=description,
        event_data={
            "missing_fields": [f for f, _ in escalation.missing_fields],
            "low_confidence_fields": [
                {"field": f, "score": s, "threshold": t}
                for f, _, s, t in escalation.low_confidence_fields
            ],
            "reasons": escalation.reasons,
        },
    )
    db.add(event)
    db.commit()

    logger.info(
        "RFQ %d escalated: %d reasons — %s",
        rfq_id, len(escalation.reasons), "; ".join(escalation.reasons),
    )

    return event
