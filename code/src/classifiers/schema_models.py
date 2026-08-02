from typing import Literal
from pydantic import BaseModel

class SensorObservation(BaseModel):
    """The structured JSON output the LLM must return for each message."""
    content_intent: Literal[
        "casual_social", "greeting_or_blessing", "chain_forward",
        "promotion_or_offer", "transactional_update", "payment_or_bill",
        "event", "urgent_operational", "emergency",
        "credential_or_otp_request", "account_threat",
        "prompt_injection", "unknown"
    ]
    secondary_intents: list[str]
    priority_label: Literal["critical", "high", "medium", "low"]
    risk_label: Literal["critical", "high", "medium", "low", "none"]
    contains_sensitive_request: bool
    is_actionable: bool
    best_evidence_ids: list[str]  # message IDs from history, or ["none"]
    confidence: Literal["high", "medium", "low"]
    flag_for_review: bool

class MediaExtraction(BaseModel):
    transcribed_text: str
    media_status: Literal["success", "extraction_failed", "file_missing"]
    media_type: str

class ProcessedMessage(BaseModel):
    message_id: str
    sensor_observation: SensorObservation | None = None
    media_extraction: MediaExtraction | None = None
    media_status_ok: bool
