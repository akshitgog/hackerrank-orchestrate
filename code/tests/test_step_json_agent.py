"""Unit tests for Phase 3 Step-JSON Agent and Guardrails."""

import unittest
from code.src.audit_agent.models import AuditFinding, AuditVerificationProof, AuditResult
from code.src.step_json_agent.builder import StepJsonBuilder
from code.guardrails.jev_schema_guardrail import StepJsonGuardrail


class TestStepJsonAgent(unittest.TestCase):
    """Verifies canonical step construction, ordering, numbering, and guardrails."""

    def test_not_applicable_produces_empty_list(self) -> None:
        """NOT_APPLICABLE cases must always return empty steps array."""
        result = AuditResult(
            case_id="case_999",
            user_id="user_999",
            is_complete=False,
            deletion_status="NOT_APPLICABLE",
            findings=(),
            verifications=(),
        )
        steps = StepJsonBuilder.build_steps(result)
        self.assertEqual(steps, [])
        violations = StepJsonGuardrail.validate(steps, "NOT_APPLICABLE")
        self.assertEqual(violations, [])

    def test_complete_case_has_only_evidence_verifications(self) -> None:
        """COMPLETE cases must only contain evidence-backed verification steps."""
        proofs = (
            AuditVerificationProof(
                system_id="account_service",
                resource_id="account_541",
                operation="VERIFY_RECORD_ABSENT",
                state="ABSENT",
                evidence_id="evidence_51",
            ),
            AuditVerificationProof(
                system_id="identity_service",
                resource_id="tombstone_440",
                operation="VERIFY_RECORD_REDACTED",
                state="REDACTED",
                evidence_id="evidence_51",
            ),
            AuditVerificationProof(
                system_id="security_service",
                resource_id="audit_record_6909",
                operation="VERIFY_RECORD_PRESENT",
                state="PRESENT",
                evidence_id="evidence_51",
            ),
        )
        result = AuditResult(
            case_id="case_31",
            user_id="user_541",
            is_complete=True,
            deletion_status="COMPLETE",
            findings=(),
            verifications=proofs,
        )

        steps = StepJsonBuilder.build_steps(result)
        self.assertEqual(len(steps), 3)

        # Check consecutive numbering
        self.assertEqual([s["step_no"] for s in steps], [1, 2, 3])

        # All steps must be VERIFICATION with non-empty evidence_id
        for s in steps:
            self.assertEqual(s["phase"], "VERIFICATION")
            self.assertTrue(s["evidence_id"])

        # Check canonical verification ordering: ABSENT (10) < PRESENT (20) < REDACTED (30)
        self.assertEqual(steps[0]["operation"], "VERIFY_RECORD_ABSENT")
        self.assertEqual(steps[1]["operation"], "VERIFY_RECORD_PRESENT")
        self.assertEqual(steps[2]["operation"], "VERIFY_RECORD_REDACTED")

        violations = StepJsonGuardrail.validate(steps, "COMPLETE")
        self.assertEqual(violations, [])

    def test_incomplete_case_ordering_and_evidence_blanking(self) -> None:
        """INCOMPLETE case must sequence FINDING -> REMEDIATION -> VERIFICATION and blank evidence."""
        findings = (
            AuditFinding(
                system_id="integration_service",
                resource_id="data_flow_9846",
                operation="REPORT_ACTIVE_DATA_FLOW",
                state="ACTIVE",
                evidence_id="evidence_01",
                data_category="CONNECTOR_DATA_FLOW",
            ),
            AuditFinding(
                system_id="search_service",
                resource_id="search_101",
                operation="REPORT_REMAINING_RECORD",
                state="PRESENT",
                evidence_id="evidence_92",
                data_category="SEARCH_INDEX",
            ),
            AuditFinding(
                system_id="support_platform",
                resource_id="support_555",
                operation="REPORT_EXPOSED_PII",
                state="PRESENT",
                evidence_id="evidence_92",
                data_category="CUSTOMER_SUPPORT",
            ),
        )
        result = AuditResult(
            case_id="case_test",
            user_id="user_99",
            is_complete=False,
            deletion_status="INCOMPLETE",
            findings=findings,
            verifications=(),
        )

        steps = StepJsonBuilder.build_steps(result, security_audit_id="audit_record_99")
        self.assertTrue(len(steps) > 3)

        # 1. Check strict 1..N renumbering
        step_nos = [s["step_no"] for s in steps]
        self.assertEqual(step_nos, list(range(1, len(steps) + 1)))

        # 2. Check phase segregation
        phases = [s["phase"] for s in steps]
        finding_indices = [i for i, p in enumerate(phases) if p == "FINDING"]
        remediation_indices = [i for i, p in enumerate(phases) if p == "REMEDIATION"]
        verification_indices = [i for i, p in enumerate(phases) if p == "VERIFICATION"]

        self.assertLess(max(finding_indices), min(remediation_indices))
        self.assertLess(max(remediation_indices), min(verification_indices))

        # 3. Check remediation dependency ordering: flow disabled before record deletion/redaction
        rem_ops = [s["operation"] for s in steps if s["phase"] == "REMEDIATION"]
        self.assertEqual(rem_ops[0], "DISABLE_DATA_FLOW")
        self.assertIn("DELETE_RECORD", rem_ops)
        self.assertIn("REDACT_RECORD", rem_ops)

        # 4. Check evidence_id rules: findings have it, remediation and incomplete verification do not
        for s in steps:
            if s["phase"] == "FINDING":
                self.assertTrue(s["evidence_id"])
            else:
                self.assertEqual(s["evidence_id"], "")

        # 5. Guardrail validation
        violations = StepJsonGuardrail.validate(steps, "INCOMPLETE")
        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
