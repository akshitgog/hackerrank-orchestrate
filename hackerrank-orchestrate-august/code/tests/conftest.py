"""Shared pytest fixtures and June-style helper builder functions for offline testing."""
import pytest
from src.classifiers.schema_models import SensorObservation, MediaExtraction
from src.routing_engine.decision_tree import route_message


def obs(
    intent="transactional_update",
    priority="medium",
    risk="none",
    sensitive=False,
    actionable=True,
    evidence_ids=None,
    **kw
):
    """June-style helper builder for SensorObservation fixtures."""
    if evidence_ids is None:
        evidence_ids = ["none"]
    base = dict(
        content_intent=intent,
        secondary_intents=[],
        priority_label=priority,
        risk_label=risk,
        contains_sensitive_request=sensitive,
        is_actionable=actionable,
        best_evidence_ids=evidence_ids,
        confidence="high",
        flag_for_review=False,
    )
    base.update(kw)
    return SensorObservation(**base)


def media(media_type="image", text="Sample OCR text", status="success", **kw):
    """Helper builder for MediaExtraction fixtures."""
    base = dict(
        media_type=media_type,
        transcribed_text=text,
        media_status=status,
    )
    base.update(kw)
    return MediaExtraction(**base)


def decide_obs(observation: SensorObservation, is_dnd=False, is_opted_out=False):
    """Helper runner to route a SensorObservation through the 7-Gate decision tree."""
    user_profile = {
        "dnd_active": "1" if is_dnd else "0",
        "allows_promotions": "0" if is_opted_out else "1",
    }
    message = {"message_id": "test_msg_001", "text": "Sample text", "type": "text"}
    return route_message(
        sensor_obs=observation.model_dump(),
        user_profile=user_profile,
        group_membership=None,
        business_relationship={"opted_out": "1" if is_opted_out else "0"},
        message=message,
        config=None,
    )
