"""
policy.py — Deterministic Rule-Based Decision Tree.

PURE PYTHON. Zero network calls. Zero LLM imports. Importable and testable in isolation.
Implements 7 gates in strict priority order per ARCHITECTURE_PLANNING.md.
"""

from dataclasses import dataclass
from typing import Optional, Dict, Any


@dataclass
class RoutingDecision:
    """Holds the final routing output for a single message."""
    action: str           # notify | digest | mute
    message_type: str     # personal, urgent, event, payment, business_update, promotion, greeting, forward, spam, scam, unknown
    reason: str           # Human-readable 1-2 sentence explanation
    confidence: float     # 0.0-1.0, set later by calibration.py
    evidence_message_ids: str  # Semicolon-separated IDs or "none"


# Maps content_intent -> output message_type
_INTENT_TO_MSG_TYPE = {
    "casual_social": "personal",
    "greeting_or_blessing": "greeting",
    "chain_forward": "forward",
    "promotion_or_offer": "promotion",
    "transactional_update": "business_update",
    "payment_or_bill": "payment",
    "event": "event",
    "urgent_operational": "urgent",
    "emergency": "urgent",
    "credential_or_otp_request": "scam",
    "account_threat": "scam",
    "prompt_injection": "scam",
    "unknown": "unknown",
}


def route_message(
    sensor_obs: Optional[Dict[str, Any]],
    user_profile: Dict[str, Any],
    group_membership: Optional[Dict[str, Any]],
    business_relationship: Optional[Dict[str, Any]],
    message: Dict[str, Any],
    config: Any,
) -> RoutingDecision:
    """
    Deterministic decision tree for routing a single message.

    Args:
        sensor_obs: Dict from SensorObservation.model_dump(), or None if LLM failed.
        user_profile: User profile dict with dnd_active, allows_promotions, etc.
        group_membership: Group membership dict with is_admin, is_muted, or None.
        business_relationship: Business relationship dict, or None.
        message: Raw message dict from messages.csv.
        config: AppConfig instance.

    Returns:
        RoutingDecision with action, message_type, reason, confidence=0.0 (set by calibration).
    """
    # If sensor failed entirely, use heuristic fallback
    if sensor_obs is None:
        from .safe_fallback import heuristic_classify
        return heuristic_classify(message, user_profile, group_membership, business_relationship, config)

    # Extract semantic labels from LLM observation
    content_intent = sensor_obs.get("content_intent", "unknown")
    priority_label = sensor_obs.get("priority_label", "low")
    risk_label = sensor_obs.get("risk_label", "none")
    is_actionable = sensor_obs.get("is_actionable", False)
    contains_sensitive = sensor_obs.get("contains_sensitive_request", False)

    # Extract context from pre-fetched profiles
    allows_promotions = str(user_profile.get("allows_promotions", "1")) == "1"
    dnd_active = str(user_profile.get("dnd_active", "0")) == "1"

    is_group_admin = False
    is_sender_admin = False
    group_muted = False
    if group_membership:
        is_group_admin = str(group_membership.get("is_admin", "0")) == "1"
        is_sender_admin = str(group_membership.get("is_sender_admin", "0")) == "1"
        group_muted = str(group_membership.get("is_muted", "0")) == "1"

    forwarded_count = int(message.get("forwarded_count", 0) or 0)

    # ─────────────────────────────────────────────────────────────
    # Gate 1: Scam / Phishing / Prompt Injection
    # Edge Cases: EC-01 (OTP phishing), EC-02 (domain impersonation), EC-13 (prompt injection)
    # ─────────────────────────────────────────────────────────────
    if risk_label in ("high", "critical"):
        return RoutingDecision("mute", "scam", "High risk content detected by semantic analysis.", 0.0, "none")
    if content_intent in ("credential_or_otp_request", "account_threat", "prompt_injection"):
        return RoutingDecision("mute", "scam", "Credential phishing, account threat, or prompt injection detected.", 0.0, "none")
    if contains_sensitive and not _is_verified_business(message, business_relationship):
        return RoutingDecision("mute", "scam", "Sensitive credential request from unverified source.", 0.0, "none")
        
    if business_relationship:
        official_domain = business_relationship.get("official_domain", "").strip()
        used_domain = business_relationship.get("domain_used_by_sender", "").strip()
        verified = str(business_relationship.get("verified", "0")) == "1"
        if official_domain and used_domain and official_domain.lower() != used_domain.lower() and not verified:
            return RoutingDecision("mute", "scam", "Unverified sender using a suspicious mismatched domain.", 0.0, "none")

    # ─────────────────────────────────────────────────────────────
    # Gate 2: Promotional Consent (User opted out)
    # Edge Cases: EC-04 (user opted out of marketing)
    # ─────────────────────────────────────────────────────────────
    if content_intent == "promotion_or_offer" and not allows_promotions:
        return RoutingDecision("mute", "promotion", "User has opted out of promotional messages from this business.", 0.0, "none")

    # ─────────────────────────────────────────────────────────────
    # Gate 3: Emergency Override (overrides DND & mutes)
    # Edge Cases: EC-10 (urgent message during DND)
    # ─────────────────────────────────────────────────────────────
    if priority_label == "critical" and risk_label in ("none", "low"):
        return RoutingDecision("notify", "urgent", "Critical priority message overrides all quiet settings.", 0.0, "none")

    # ─────────────────────────────────────────────────────────────
    # Gate 3.5: Sender Fatigue (Mute Spammers)
    # ─────────────────────────────────────────────────────────────
    sender_dismiss_rate = float(user_profile.get("sender_dismiss_rate", 0.0))
    sender_open_rate = float(user_profile.get("sender_open_rate", 1.0))
    sender_sent_count = int(user_profile.get("sender_sent_count", 0))

    if content_intent in ("chain_forward", "greeting_or_blessing", "promotion_or_offer"):
        if sender_dismiss_rate >= 0.5 or (sender_sent_count >= 2 and sender_open_rate == 0.0):
            msg_type = _INTENT_TO_MSG_TYPE.get(content_intent, "unknown")
            return RoutingDecision("mute", msg_type, "Sender has a pattern of ignored low-value messages.", 0.0, "none")

    # ─────────────────────────────────────────────────────────────
    # Gate 4: Actionable Operational / High Priority
    # Edge Cases: EC-06 (admin urgent update), EC-07 (actionable work message)
    # ─────────────────────────────────────────────────────────────
    if priority_label == "high" and (is_actionable or is_sender_admin):
        msg_type = _INTENT_TO_MSG_TYPE.get(content_intent, "urgent")
        return RoutingDecision("notify", msg_type, "High priority actionable message from trusted source.", 0.0, "none")

    # Time-sensitive updates from group admins -> notify
    if is_sender_admin and content_intent in ("urgent_operational", "emergency"):
        msg_type = _INTENT_TO_MSG_TYPE.get(content_intent, "event")
        return RoutingDecision("notify", msg_type, "Time-sensitive update from group admin.", 0.0, "none")

    # High-value business interactions -> notify
    if content_intent in ("transactional_update", "event", "payment_or_bill") and _is_verified_business(message, business_relationship):
        msg_type = _INTENT_TO_MSG_TYPE.get(content_intent, "business_update")
        return RoutingDecision("notify", msg_type, "Verified business update, event, or bill.", 0.0, "none")

    # Direct personal messages requesting action -> notify
    if content_intent == "casual_social" and priority_label == "high":
        return RoutingDecision("notify", "personal", "Direct high-priority personal message.", 0.0, "none")

    # ─────────────────────────────────────────────────────────────
    # Gate 5: DND & Muted Group Suppression
    # Edge Cases: EC-05 (user in DND), EC-08 (muted group greetings)
    # ─────────────────────────────────────────────────────────────
    # Muted group + low-value content -> mute
    if group_membership and group_muted and not is_group_admin:
        if content_intent in ("greeting_or_blessing", "chain_forward"):
            msg_type = "greeting" if content_intent == "greeting_or_blessing" else "forward"
            return RoutingDecision("mute", msg_type, "Low-value content in a user-muted group.", 0.0, "none")
        # Chain forwards with high forwarded_count -> mute even in unmuted groups
    if content_intent == "chain_forward" and forwarded_count > 3:
        return RoutingDecision("mute", "forward", "Highly forwarded chain message with no original content.", 0.0, "none")

    # Greetings & blessings with forwarding pattern -> mute
    if content_intent == "greeting_or_blessing" and forwarded_count > 0:
        return RoutingDecision("mute", "greeting", "Forwarded greeting/blessing message.", 0.0, "none")

    # DND active + non-urgent -> digest
    if dnd_active and priority_label not in ("high", "critical"):
        msg_type = _INTENT_TO_MSG_TYPE.get(content_intent, "personal")
        return RoutingDecision("digest", msg_type, "Message received during user's Do Not Disturb window.", 0.0, "none")

    # ─────────────────────────────────────────────────────────────
    # Gate 6: Promotional (Opted-in) -> Digest
    # Edge Cases: EC-04 (user opted in to promos)
    # ─────────────────────────────────────────────────────────────
    if content_intent == "promotion_or_offer" and allows_promotions:
        return RoutingDecision("digest", "promotion", "Promotional content from a business the user has opted into.", 0.0, "none")

    # ─────────────────────────────────────────────────────────────
    # Gate 7: Default -> Digest with appropriate message_type
    # ─────────────────────────────────────────────────────────────
    msg_type = _INTENT_TO_MSG_TYPE.get(content_intent, "personal")
    reason = "Standard message routed to digest for later review."

    # Events without urgency -> digest
    if content_intent == "event":
        reason = "Non-urgent event information for later review."
    # Casual greetings (not forwarded) -> digest (not mute, since they might be genuine)
    elif content_intent == "greeting_or_blessing":
        reason = "Casual greeting from a known contact."

    return RoutingDecision("digest", msg_type, reason, 0.0, "none")


def _is_verified_business(message: dict, business_rel: Optional[Dict[str, Any]]) -> bool:
    """Check if the sender is a verified business account."""
    if not message.get("business_id"):
        return False
    if business_rel and str(business_rel.get("verified", "0")) == "1":
        return True
    return False
