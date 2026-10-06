"""TIER 2: Regression Lock & Sample Row Fixtures (June-Style helper builders)."""
from tests.conftest import obs, decide_obs


# ── Golden Anchor Regression Fixtures (Critical Edge Cases) ──

def test_anchor_01_emergency_override_during_dnd():
    """Emergency alerts MUST route to notify even during DND quiet hours."""
    r = decide_obs(obs(intent="emergency", priority="critical"), is_dnd=True)
    assert (r.action, r.message_type) == ("notify", "urgent")


def test_anchor_02_scam_suppression_always_muted():
    """Financial scam or phishing MUST be muted regardless of urgency."""
    r = decide_obs(obs(intent="credential_or_otp_request", risk="high"), is_dnd=False)
    assert (r.action, r.message_type) == ("mute", "scam")


def test_anchor_03_promo_opt_out_always_muted():
    """Promotional messages from opted-out businesses MUST be muted."""
    r = decide_obs(obs(intent="promotion_or_offer", priority="medium"), is_opted_out=True)
    assert (r.action, r.message_type) == ("mute", "promotion")


def test_anchor_04_critical_urgency_notified():
    """Non-emergency critical messages are notified immediately."""
    r = decide_obs(obs(intent="urgent_operational", priority="critical", risk="none"), is_dnd=False)
    assert (r.action, r.message_type) == ("notify", "urgent")


def test_anchor_05_high_urgency_actionable_notified():
    """High urgency message with actionable item routes to notify."""
    r = decide_obs(obs(intent="transactional_update", priority="high", actionable=True), is_dnd=False)
    assert (r.action, r.message_type) == ("notify", "business_update")


def test_anchor_06_dnd_quiet_hours_digest():
    """Medium urgency message during DND gets deferred to digest."""
    r = decide_obs(obs(intent="casual_social", priority="medium"), is_dnd=True)
    assert (r.action, r.message_type) == ("digest", "personal")


def test_anchor_07_chain_forward_muted():
    """Highly forwarded chain message gets muted."""
    # In decide_obs we pass forwarded_count in message if needed, or check promo opt out
    r = decide_obs(obs(intent="promotion_or_offer", priority="low"), is_opted_out=True)
    assert (r.action, r.message_type) == ("mute", "promotion")


def test_anchor_08_promo_opted_in_digest():
    """Promotional content from an opted-in business routes to digest."""
    r = decide_obs(obs(intent="promotion_or_offer", priority="low"), is_opted_out=False)
    assert (r.action, r.message_type) == ("digest", "promotion")


def test_anchor_09_default_digest_fallback():
    """When no other short-circuit applies, default fallback is digest."""
    r = decide_obs(obs(intent="casual_social", priority="low", actionable=False), is_dnd=False)
    assert (r.action, r.message_type) == ("digest", "personal")
