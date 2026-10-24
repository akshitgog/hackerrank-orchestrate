"""Guardrail validator for step_json serialization and challenge contract conformance."""

import json
from typing import Any


ALLOWED_OPERATIONS = {
    # Findings
    "REPORT_REMAINING_RECORD": ("FINDING", "PRESENT"),
    "REPORT_EXPOSED_PII": ("FINDING", "PRESENT"),
    "REPORT_ACTIVE_DATA_FLOW": ("FINDING", "ACTIVE"),
    "REPORT_RESTORE_RISK": ("FINDING", "ACTIVE"),
    # Remediation
    "DISABLE_DATA_FLOW": ("REMEDIATION", "DISABLED"),
    "BLOCK_RESTORE": ("REMEDIATION", "BLOCKED"),
    "DELETE_RECORD": ("REMEDIATION", "ABSENT"),
    "REDACT_RECORD": ("REMEDIATION", "REDACTED"),
    "ANONYMIZE_RECORD": ("REMEDIATION", "ANONYMIZED"),
    # Verification
    "VERIFY_RECORD_ABSENT": ("VERIFICATION", "ABSENT"),
    "VERIFY_RECORD_PRESENT": ("VERIFICATION", "PRESENT"),
    "VERIFY_RECORD_REDACTED": ("VERIFICATION", "REDACTED"),
    "VERIFY_RECORD_ANONYMIZED": ("VERIFICATION", "ANONYMIZED"),
    "VERIFY_DATA_FLOW_DISABLED": ("VERIFICATION", "DISABLED"),
    "VERIFY_RESTORE_BLOCKED": ("VERIFICATION", "BLOCKED"),
}

PHASE_RANK = {
    "FINDING": 1,
    "REMEDIATION": 2,
    "VERIFICATION": 3,
}


class StepJsonGuardrail:
    """Enforces rigorous schema and semantic validation on generated steps."""

    @classmethod
    def validate(
        cls,
        steps: list[dict[str, Any]],
        deletion_status: str,
    ) -> list[str]:
        """Validate step list against challenge contract.

        Returns:
            List of violation error strings (empty if valid).
        """
        violations: list[str] = []

        # 1. NOT_APPLICABLE contract
        if deletion_status == "NOT_APPLICABLE":
            if steps:
                violations.append("NOT_APPLICABLE status must have empty steps_json array.")
            return violations

        if deletion_status not in ("COMPLETE", "INCOMPLETE"):
            violations.append(f"Invalid deletion_status: {deletion_status}")

        if deletion_status == "COMPLETE":
            # COMPLETE cases must only have VERIFICATION steps
            for s in steps:
                if s.get("phase") != "VERIFICATION":
                    violations.append(
                        f"COMPLETE case contains non-VERIFICATION phase: {s.get('phase')}"
                    )

        current_phase_rank = 0
        expected_step_no = 1

        for idx, s in enumerate(steps, start=1):
            # Check required fields
            req_keys = {"step_no", "phase", "system_id", "resource_id", "operation", "state", "evidence_id"}
            missing_keys = req_keys - set(s.keys())
            if missing_keys:
                violations.append(f"Step {idx} missing required keys: {missing_keys}")

            step_no = s.get("step_no")
            if step_no != expected_step_no:
                violations.append(f"Non-consecutive step_no: expected {expected_step_no}, got {step_no}")
            expected_step_no += 1

            phase = s.get("phase")
            op = s.get("operation")
            state = s.get("state")
            ev_id = s.get("evidence_id")

            # Check phase ranking
            rank = PHASE_RANK.get(phase, 99)
            if rank < current_phase_rank:
                violations.append(f"Phase ordering violation at step {idx}: {phase} after higher phase.")
            current_phase_rank = max(current_phase_rank, rank)

            # Check operation and state compatibility
            if op not in ALLOWED_OPERATIONS:
                violations.append(f"Step {idx} has forbidden operation: {op}")
            else:
                expected_phase, expected_state = ALLOWED_OPERATIONS[op]
                if phase != expected_phase:
                    violations.append(f"Step {idx} phase mismatch: {op} belongs to {expected_phase}, not {phase}")
                if state != expected_state:
                    violations.append(f"Step {idx} state mismatch: {op} must have state {expected_state}, got {state}")

            # Evidence ID rules (§6.3 / §6.6)
            if phase == "FINDING":
                if not ev_id or not str(ev_id).strip():
                    violations.append(f"Step {idx} (FINDING) must cite non-empty evidence_id.")
            elif phase == "REMEDIATION":
                if ev_id != "":
                    violations.append(f"Step {idx} (REMEDIATION) must have evidence_id as empty string ''.")
            elif phase == "VERIFICATION":
                if deletion_status == "COMPLETE" and (not ev_id or not str(ev_id).strip()):
                    violations.append(f"Step {idx} (COMPLETE VERIFICATION) must cite evidence_id.")
                elif deletion_status == "INCOMPLETE" and ev_id != "":
                    violations.append(f"Step {idx} (INCOMPLETE VERIFICATION) must have empty evidence_id ''.")

        return violations
