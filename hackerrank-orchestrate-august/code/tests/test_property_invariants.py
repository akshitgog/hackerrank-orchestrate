"""TIER 3: Property-Based Invariant Fuzzing across the valid input space."""
import random
import pytest
from tests.conftest import obs, decide_obs

ALLOWED_ACTIONS = {"notify", "digest", "mute"}
ALLOWED_INTENTS = [
    "casual_social", "greeting_or_blessing", "chain_forward",
    "promotion_or_offer", "transactional_update", "payment_or_bill",
    "event", "urgent_operational", "emergency",
    "credential_or_otp_request", "account_threat",
    "prompt_injection", "unknown"
]
ALLOWED_PRIORITIES = ["critical", "high", "medium", "low"]
ALLOWED_RISKS = ["critical", "high", "medium", "low", "none"]


def test_property_invariants_500_permutations():
    """Fuzzes 500 permutations across intents, priorities, risks, DND, and opt-out states."""
    random.seed(42)  # Deterministic seed for reproducible CI fuzzing
    for _ in range(500):
        intent = random.choice(ALLOWED_INTENTS)
        priority = random.choice(ALLOWED_PRIORITIES)
        risk = random.choice(ALLOWED_RISKS)
        is_dnd = random.choice([True, False])
        is_opted_out = random.choice([True, False])
        actionable = random.choice([True, False])

        observation = obs(
            intent=intent,
            priority=priority,
            risk=risk,
            actionable=actionable,
            reasoning=f"fuzzed_{intent}_{priority}"
        )
        decision = decide_obs(observation, is_dnd=is_dnd, is_opted_out=is_opted_out)

        # Invariant 1: Action must always be a valid vocabulary word
        assert decision.action in ALLOWED_ACTIONS, f"Invalid action emitted: {decision.action}"

        # Invariant 2: Confidence must be within [0.0, 1.0]
        assert 0.0 <= decision.confidence <= 1.0, f"Confidence out of bounds: {decision.confidence}"

        # Invariant 3: High/critical risk must always route to mute
        if risk in ("high", "critical"):
            assert decision.action == "mute", f"High risk not muted for {intent}/{priority}/{risk}"

        # Invariant 4: Non-scam, non-opt-out critical priority with low/no risk must route to notify
        is_scam_intent = intent in ("credential_or_otp_request", "account_threat", "prompt_injection")
        is_muted_promo = (intent == "promotion_or_offer" and is_opted_out)
        if priority == "critical" and risk in ("none", "low") and not is_scam_intent and not is_muted_promo:
            assert decision.action == "notify", f"Critical priority not notified for {intent}/{priority}/{risk}"
