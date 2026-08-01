"""
fallback.py — Universal Safe-Default Row & offline heuristic classifier.

Used when ALL API calls fail or LLM returns None.
PURE PYTHON. Zero network calls.
"""

import re
from typing import Dict, Any, Optional
from .decision_tree import RoutingDecision


def get_safe_default_row(message_id: str, config: Any) -> RoutingDecision:
    """
    Universal Safe-Default Row.
    Guarantees zero dropped rows and 100% Completeness Invariant.
    Conservative: never an undeserved 'notify' or false 'scam'.
    """
    return RoutingDecision(
        action="digest",
        message_type="unknown",
        reason="Automated pipeline fallback due to unrecoverable sensor error.",
        confidence=config.confidence.fallback_default,
        evidence_message_ids="none",
    )


# Compiled regex patterns for heuristic classification (zero runtime compilation cost)
_SCAM_PATTERNS = re.compile(
    r"\b(otp|password|pin|verify\s+(your|now)|kyc|login\s*code|"
    r"account.*(block|suspend|expire)|click\s+here\s+to\s+(claim|verify))\b",
    re.IGNORECASE,
)
_GREETING_PATTERNS = re.compile(
    r"\b(good\s+morning|good\s+evening|good\s+night|happy\s+birthday|"
    r"blessings|stay\s+positive|keep\s+smiling)\b",
    re.IGNORECASE,
)
_PROMO_PATTERNS = re.compile(
    r"\b(sale|discount|offer|%\s*off|coupon|deal|cashback|"
    r"unsubscribe|reply\s+stop)\b",
    re.IGNORECASE,
)
_URGENT_PATTERNS = re.compile(
    r"\b(urgent|emergency|server\s+down|prod\s+review|escalation|"
    r"critical|asap|immediately|right\s+now)\b",
    re.IGNORECASE,
)


def heuristic_classify(
    message: Dict[str, Any],
    user_profile: Dict[str, Any],
    group_membership: Optional[Dict[str, Any]],
    business_relationship: Optional[Dict[str, Any]],
    config: Any,
) -> RoutingDecision:
    """
    Regex/keyword-based offline classifier.
    Used when ALL LLM/VLM/STT API calls fail.
    """
    text = str(message.get("message_text", "") or "").lower()
    forwarded_count = int(message.get("forwarded_count", 0) or 0)
    allows_promotions = str(user_profile.get("allows_promotions", "1")) == "1"

    # Rule 1: Scam / credential phishing keywords
    if _SCAM_PATTERNS.search(text):
        return RoutingDecision(
            "mute", "scam",
            "Heuristic fallback: credential/phishing keywords detected.",
            config.confidence.fallback_default, "none",
        )

    # Rule 2: Highly forwarded chain messages
    if forwarded_count > 3:
        return RoutingDecision(
            "mute", "forward",
            "Heuristic fallback: highly forwarded chain message.",
            config.confidence.fallback_default, "none",
        )

    # Rule 3: Greeting / blessing patterns
    if _GREETING_PATTERNS.search(text):
        if forwarded_count > 0:
            return RoutingDecision(
                "mute", "greeting",
                "Heuristic fallback: forwarded greeting/blessing.",
                config.confidence.fallback_default, "none",
            )
        return RoutingDecision(
            "digest", "greeting",
            "Heuristic fallback: casual greeting.",
            config.confidence.fallback_default, "none",
        )

    # Rule 4: Promotional keywords
    if _PROMO_PATTERNS.search(text):
        if allows_promotions:
            return RoutingDecision(
                "digest", "promotion",
                "Heuristic fallback: promotional content, user opted in.",
                config.confidence.fallback_default, "none",
            )
        return RoutingDecision(
            "mute", "promotion",
            "Heuristic fallback: promotional content, user opted out.",
            config.confidence.fallback_default, "none",
        )

    # Rule 5: Urgent keywords
    if _URGENT_PATTERNS.search(text):
        return RoutingDecision(
            "notify", "urgent",
            "Heuristic fallback: urgency keywords detected.",
            config.confidence.fallback_default, "none",
        )

    # Rule 6: Default safe fallback
    return get_safe_default_row(str(message.get("message_id", "")), config)
