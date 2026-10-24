"""Guardrail for intent classification and decision boundary validation."""

from typing import Any
from code.src.orchestrator.models import IntentClassificationResult


class IntentGuardrail:
    """Enforces strict confidence bounds and non-deletion contract rules."""

    @classmethod
    def validate(
        cls,
        result: IntentClassificationResult,
        threshold: float,
    ) -> list[str]:
        """Validate intent classification result.

        Returns:
            List of violation error messages (empty if valid).
        """
        violations: list[str] = []

        # 1. Bounds check on confidence
        if not (0.0 <= result.confidence <= 1.0):
            violations.append(f"Confidence score out of bounds [0.0, 1.0]: {result.confidence}")

        # 2. Decision boundary consistency with threshold
        if result.is_deletion_authorized and result.confidence < threshold:
            violations.append(
                f"Deletion authorized with confidence ({result.confidence}) below threshold ({threshold})."
            )

        # 3. Category and rationale validity
        if not result.intent_category:
            violations.append("Intent category cannot be empty.")
        if not result.rationale:
            violations.append("Classification rationale cannot be empty.")

        return violations
