"""TIER 1: Boundary & Schema Seam Tests (Parse, Don't Validate)."""
import pytest
from pydantic import ValidationError
from src.classifiers.schema_models import SensorObservation, MediaExtraction


def test_valid_sensor_observation():
    obs = SensorObservation(
        content_intent="emergency",
        secondary_intents=[],
        priority_label="high",
        risk_label="none",
        contains_sensitive_request=False,
        is_actionable=True,
        best_evidence_ids=["none"],
        confidence="high",
        flag_for_review=False
    )
    assert obs.content_intent == "emergency"
    assert obs.priority_label == "high"


def test_invalid_urgency_raises_validation_error():
    with pytest.raises(ValidationError):
        SensorObservation(
            content_intent="emergency",
            priority_label="extreme_invalid",  # Out-of-vocabulary enum
            risk_label="none",
            contains_sensitive_request=False,
            is_actionable=True,
            best_evidence_ids=["none"],
            reasoning="Should raise ValidationError"
        )


def test_media_extraction_default_values():
    media = MediaExtraction(
        media_type="image",
        transcribed_text="OTP is 1234",
        media_status="success"
    )
    assert media.media_status == "success"
    assert "OTP" in media.transcribed_text
