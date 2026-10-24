"""Guardrail for the Audit Agent (Verification Scanner)."""

from typing import Optional
import pandas as pd

from code.src.audit_agent.models import AuditResult


class AuditGuardrail:
    """Enforces evidence grounding, schema conformance, and decision consistency."""

    VALID_FINDING_OPERATIONS = {
        "REPORT_REMAINING_RECORD",
        "REPORT_EXPOSED_PII",
        "REPORT_ACTIVE_DATA_FLOW",
        "REPORT_RESTORE_RISK",
    }

    VALID_VERIFICATION_OPERATIONS = {
        "VERIFY_RECORD_ABSENT",
        "VERIFY_RECORD_PRESENT",
        "VERIFY_RECORD_REDACTED",
        "VERIFY_RECORD_ANONYMIZED",
        "VERIFY_DATA_FLOW_DISABLED",
        "VERIFY_RESTORE_BLOCKED",
    }

    def __init__(
        self,
        evidence_manifest_path: str = "dataset/evidence_files.csv",
    ) -> None:
        self.evidence_manifest_path = evidence_manifest_path
        self._known_evidence_ids: set[str] = set()
        self._load_known_ids()

    def _load_known_ids(self) -> None:
        """Load known evidence IDs from manifest."""
        try:
            df = pd.read_csv(self.evidence_manifest_path)
            self._known_evidence_ids = set(df["file_id"].dropna().astype(str))
        except Exception:
            self._known_evidence_ids = set()

    def validate(self, result: Optional[AuditResult]) -> tuple[bool, list[str]]:
        """Validate an AuditResult against system invariants."""
        errors: list[str] = []

        if result is None:
            return False, ["Audit result is None."]

        # 1. State Consistency
        if result.deletion_status == "COMPLETE":
            if result.findings:
                errors.append(f"Case {result.case_id} is marked COMPLETE but contains findings.")
            if not result.verifications:
                errors.append(f"Case {result.case_id} is marked COMPLETE but has no verification proofs.")
        elif result.deletion_status == "INCOMPLETE":
            if not result.findings:
                errors.append(f"Case {result.case_id} is marked INCOMPLETE but has 0 findings.")

        # 2. Finding Operation & Evidence Validation
        for f in result.findings:
            if f.operation not in self.VALID_FINDING_OPERATIONS:
                errors.append(f"Invalid finding operation '{f.operation}' in case {result.case_id}.")
            if not f.evidence_id:
                errors.append(f"Finding for {f.resource_id} has empty evidence_id.")
            elif self._known_evidence_ids and f.evidence_id not in self._known_evidence_ids:
                # Also allow activity_id or audit_id
                if not (f.evidence_id.startswith("activity_") or f.evidence_id.startswith("audit_")):
                    errors.append(f"Unrecognized evidence_id '{f.evidence_id}' in finding {f.resource_id}.")

        # 3. Verification Operation Validation
        for v in result.verifications:
            if v.operation not in self.VALID_VERIFICATION_OPERATIONS:
                errors.append(f"Invalid verification operation '{v.operation}' in case {result.case_id}.")
            if not v.evidence_id:
                errors.append(f"Verification proof for {v.resource_id} in COMPLETE case has empty evidence_id.")

        return len(errors) == 0, errors
