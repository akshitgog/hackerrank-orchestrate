"""
calibration.py — Deterministic confidence assignment.

Reads thresholds from config.confidence (Pydantic ConfidenceConfig).
PURE PYTHON. Zero network calls. Zero LLM-generated numeric scores.
"""

from typing import Any
from .decision_tree import RoutingDecision


def calibrate_confidence(decision: RoutingDecision, gate_name: str, media_ok: bool, config: Any) -> float:
    """
    Assign a deterministic confidence score based on which gate fired.

    Args:
        decision: The RoutingDecision from policy.py.
        gate_name: One of "gate_scam", "gate_promo_optout", "gate_emergency",
                   "gate_actionable", "gate_dnd_digest", "default".
        media_ok: Whether media extraction succeeded (False applies penalty).
        config: AppConfig with config.confidence.* thresholds.

    Returns:
        Float confidence in [0.0, 1.0].
    """
    # Read base confidence from config
    conf = config.confidence
    gate_map = {
        "gate_scam": conf.gate_scam,
        "gate_promo_optout": conf.gate_promo_optout,
        "gate_emergency": conf.gate_emergency,
        "gate_actionable": conf.gate_actionable,
        "gate_dnd_digest": conf.gate_dnd_digest,
        "default": conf.default,
    }
    base_conf = gate_map.get(gate_name, conf.default)

    # Apply media extraction failure penalty
    if not media_ok:
        base_conf -= conf.media_failure_penalty

    # Clamp to [0.0, 1.0]
    return max(0.0, min(1.0, round(base_conf, 2)))
