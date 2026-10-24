"""Step-JSON Agent: canonical serializer and dependency planner.

Transforms findings and verifications into strictly ordered, renumbered,
and schema-validated steps_json payloads matching the challenge contract.
"""

import json
from typing import Any, Sequence
from code.src.audit_agent.models import AuditFinding, AuditVerificationProof, AuditResult


# Canonical orderings defined by challenge specification and sample distributions
FINDING_ORDER = {
    "REPORT_REMAINING_RECORD": 10,
    "REPORT_EXPOSED_PII": 20,
    "REPORT_ACTIVE_DATA_FLOW": 30,
    "REPORT_RESTORE_RISK": 40,
}

# Remediation dependency rule: disable flows and block restores before modifying records
REMEDIATION_ORDER = {
    "DISABLE_DATA_FLOW": 10,
    "BLOCK_RESTORE": 20,
    "DELETE_RECORD": 30,
    "REDACT_RECORD": 40,
    "ANONYMIZE_RECORD": 50,
}

VERIFICATION_ORDER = {
    "VERIFY_RECORD_ABSENT": 10,
    "VERIFY_RECORD_PRESENT": 20,
    "VERIFY_RECORD_REDACTED": 30,
    "VERIFY_RECORD_ANONYMIZED": 40,
    "VERIFY_DATA_FLOW_DISABLED": 50,
    "VERIFY_RESTORE_BLOCKED": 60,
}


class StepJsonBuilder:
    """Builds canonical, sorted, and consecutively numbered steps_json arrays."""

    @staticmethod
    def _finding_sort_key(step: dict[str, Any]) -> tuple[int, str, str]:
        op = step.get("operation", "")
        return (
            FINDING_ORDER.get(op, 99),
            step.get("system_id", ""),
            step.get("resource_id", ""),
        )

    @staticmethod
    def _remediation_sort_key(step: dict[str, Any]) -> tuple[int, str, str]:
        op = step.get("operation", "")
        return (
            REMEDIATION_ORDER.get(op, 99),
            step.get("system_id", ""),
            step.get("resource_id", ""),
        )

    @staticmethod
    def _verification_sort_key(step: dict[str, Any]) -> tuple[int, str, str]:
        op = step.get("operation", "")
        return (
            VERIFICATION_ORDER.get(op, 99),
            step.get("system_id", ""),
            step.get("resource_id", ""),
        )

    @classmethod
    def build_steps(
        cls,
        audit_result: AuditResult,
        security_audit_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Construct the full ordered step sequence for a given audit result.

        Args:
            audit_result: Audit findings and verifications from the AuditScanner.
            security_audit_id: Optional retained audit record ID to verify if applicable.

        Returns:
            List of step dictionaries numbered 1..N.
        """
        # 1. NOT_APPLICABLE cases have empty steps
        if audit_result.deletion_status == "NOT_APPLICABLE":
            return []

        # 2. COMPLETE cases: only evidence-backed verification steps
        if audit_result.deletion_status == "COMPLETE":
            raw_verifications = [
                {
                    "phase": "VERIFICATION",
                    "system_id": v.system_id,
                    "resource_id": v.resource_id,
                    "operation": v.operation,
                    "state": v.state,
                    "evidence_id": v.evidence_id,
                }
                for v in audit_result.verifications
            ]
            sorted_verifications = sorted(raw_verifications, key=cls._verification_sort_key)
            for idx, step in enumerate(sorted_verifications, start=1):
                step["step_no"] = idx
            return sorted_verifications

        # 3. INCOMPLETE cases: FINDING -> REMEDIATION -> VERIFICATION
        findings_list: list[dict[str, Any]] = []
        remediations_list: list[dict[str, Any]] = []
        verifications_list: list[dict[str, Any]] = []

        # A. Process Findings
        for f in audit_result.findings:
            findings_list.append(
                {
                    "phase": "FINDING",
                    "system_id": f.system_id,
                    "resource_id": f.resource_id,
                    "operation": f.operation,
                    "state": f.state,
                    "evidence_id": f.evidence_id,
                }
            )

        # Sort findings canonically
        sorted_findings = sorted(findings_list, key=cls._finding_sort_key)

        # B. Derive Remediation Steps from Findings
        for f in audit_result.findings:
            if f.operation == "REPORT_ACTIVE_DATA_FLOW":
                remediations_list.append(
                    {
                        "phase": "REMEDIATION",
                        "system_id": f.system_id,
                        "resource_id": f.resource_id,
                        "operation": "DISABLE_DATA_FLOW",
                        "state": "DISABLED",
                        "evidence_id": "",
                    }
                )
                verifications_list.append(
                    {
                        "phase": "VERIFICATION",
                        "system_id": f.system_id,
                        "resource_id": f.resource_id,
                        "operation": "VERIFY_DATA_FLOW_DISABLED",
                        "state": "DISABLED",
                        "evidence_id": "",
                    }
                )
            elif f.operation == "REPORT_RESTORE_RISK":
                remediations_list.append(
                    {
                        "phase": "REMEDIATION",
                        "system_id": f.system_id,
                        "resource_id": f.resource_id,
                        "operation": "BLOCK_RESTORE",
                        "state": "BLOCKED",
                        "evidence_id": "",
                    }
                )
                verifications_list.append(
                    {
                        "phase": "VERIFICATION",
                        "system_id": f.system_id,
                        "resource_id": f.resource_id,
                        "operation": "VERIFY_RESTORE_BLOCKED",
                        "state": "BLOCKED",
                        "evidence_id": "",
                    }
                )
            elif f.operation == "REPORT_REMAINING_RECORD":
                remediations_list.append(
                    {
                        "phase": "REMEDIATION",
                        "system_id": f.system_id,
                        "resource_id": f.resource_id,
                        "operation": "DELETE_RECORD",
                        "state": "ABSENT",
                        "evidence_id": "",
                    }
                )
                verifications_list.append(
                    {
                        "phase": "VERIFICATION",
                        "system_id": f.system_id,
                        "resource_id": f.resource_id,
                        "operation": "VERIFY_RECORD_ABSENT",
                        "state": "ABSENT",
                        "evidence_id": "",
                    }
                )
            elif f.operation == "REPORT_EXPOSED_PII":
                # Determine treatment: Anonymize vs Redact based on system / category
                if "analytics" in f.system_id or f.data_category == "ANALYTICS_RECORD":
                    remediations_list.append(
                        {
                            "phase": "REMEDIATION",
                            "system_id": f.system_id,
                            "resource_id": f.resource_id,
                            "operation": "ANONYMIZE_RECORD",
                            "state": "ANONYMIZED",
                            "evidence_id": "",
                        }
                    )
                    verifications_list.append(
                        {
                            "phase": "VERIFICATION",
                            "system_id": f.system_id,
                            "resource_id": f.resource_id,
                            "operation": "VERIFY_RECORD_ANONYMIZED",
                            "state": "ANONYMIZED",
                            "evidence_id": "",
                        }
                    )
                else:
                    remediations_list.append(
                        {
                            "phase": "REMEDIATION",
                            "system_id": f.system_id,
                            "resource_id": f.resource_id,
                            "operation": "REDACT_RECORD",
                            "state": "REDACTED",
                            "evidence_id": "",
                        }
                    )
                    verifications_list.append(
                        {
                            "phase": "VERIFICATION",
                            "system_id": f.system_id,
                            "resource_id": f.resource_id,
                            "operation": "VERIFY_RECORD_REDACTED",
                            "state": "REDACTED",
                            "evidence_id": "",
                        }
                    )

        # C. Add Baseline Verifications (e.g. Account absent, Security record present)
        user_num = audit_result.user_id.replace("user_", "")
        primary_account = f"account_{user_num}"
        # Ensure primary account verification is included
        if not any(v["system_id"] == "account_service" and v["operation"] == "VERIFY_RECORD_ABSENT" for v in verifications_list):
            verifications_list.append(
                {
                    "phase": "VERIFICATION",
                    "system_id": "account_service",
                    "resource_id": primary_account,
                    "operation": "VERIFY_RECORD_ABSENT",
                    "state": "ABSENT",
                    "evidence_id": "",
                }
            )

        if security_audit_id:
            verifications_list.append(
                {
                    "phase": "VERIFICATION",
                    "system_id": "security_service",
                    "resource_id": security_audit_id,
                    "operation": "VERIFY_RECORD_PRESENT",
                    "state": "PRESENT",
                    "evidence_id": "",
                }
            )

        # Sort each phase canonically
        sorted_remediations = sorted(remediations_list, key=cls._remediation_sort_key)
        sorted_verifications = sorted(verifications_list, key=cls._verification_sort_key)

        # Combine all phases in exact strict order: FINDING -> REMEDIATION -> VERIFICATION
        all_steps = sorted_findings + sorted_remediations + sorted_verifications

        # Renumber sequentially 1..N
        for idx, step in enumerate(all_steps, start=1):
            step["step_no"] = idx

        return all_steps

    @classmethod
    def to_json_str(cls, steps: list[dict[str, Any]]) -> str:
        """Serialize steps list to standard JSON string."""
        return json.dumps(steps, separators=(",", ":"))
