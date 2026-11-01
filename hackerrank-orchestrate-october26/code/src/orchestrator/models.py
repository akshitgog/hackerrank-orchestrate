"""Data models for Orchestrator and Request Classification."""

from dataclasses import dataclass


@dataclass(frozen=True)
class IntentClassificationResult:
    """Immutable classification result for a customer request."""

    case_id: str
    request_text: str
    is_deletion_authorized: bool
    confidence: float
    intent_category: str  # e.g., DELETION, DATA_EXPORT, ACCESS, MARKETING_OPT_OUT, CORRECTION
    rationale: str
