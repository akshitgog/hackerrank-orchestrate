"""Unit tests for the Audit Agent (Verification Scanner) and AuditGuardrail."""

import unittest
from pathlib import Path

from code.src.logging_agent.tracker import IdentityTracker
from code.src.audit_agent.scanner import AuditScanner
from code.src.audit_agent.multimodal_cache import LazyMultimodalCache
from code.guardrails.audit_guardrail import AuditGuardrail


class TestAuditAgent(unittest.TestCase):
    """Test suite for AuditScanner, LazyMultimodalCache, and AuditGuardrail."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.tracker = IdentityTracker()
        cls.scanner = AuditScanner()
        cls.guardrail = AuditGuardrail()

    def test_multimodal_cache_lazy_loading(self) -> None:
        """Test on-demand cache extraction for digital PDF."""
        cache = LazyMultimodalCache()
        # Request evidence_18.pdf
        doc = cache.get_evidence("evidence_18")
        self.assertIsNotNone(doc)
        self.assertIn("Ingrid Dahl", doc["raw_text"])

        # Second lookup must hit memory/disk cache instantly
        doc2 = cache.get_evidence("evidence_18")
        self.assertEqual(doc["captured_at"], doc2["captured_at"])

    def test_residual_account_finding_case_05(self) -> None:
        """Case 05: Verify residual account_005 in failover replica is discovered."""
        email = "leila.haddad@yahoo.com"
        audit_at = "2026-09-03T12:00:00Z"
        profile = self.tracker.get_identity_profile(email, audit_at)
        self.assertIsNotNone(profile)

        result = self.scanner.audit_case("case_05", profile, audit_at)
        self.assertEqual(result.deletion_status, "INCOMPLETE")
        self.assertTrue(result.has_violations)

        # Check finding
        finding_ops = [f.operation for f in result.findings]
        self.assertIn("REPORT_REMAINING_RECORD", finding_ops)

        # Validate with guardrail
        valid, errors = self.guardrail.validate(result)
        self.assertTrue(valid, f"Guardrail failed: {errors}")

    def test_active_data_flow_finding_case_15(self) -> None:
        """Case 15: Verify enabled connector data_flow_9846 is discovered."""
        email = "lucia-torres@gmail.com"
        audit_at = "2026-09-15T12:00:00Z"
        profile = self.tracker.get_identity_profile(email, audit_at)
        self.assertIsNotNone(profile)

        result = self.scanner.audit_case("case_15", profile, audit_at)
        self.assertEqual(result.deletion_status, "INCOMPLETE")

        finding_ops = [f.operation for f in result.findings]
        self.assertIn("REPORT_ACTIVE_DATA_FLOW", finding_ops)

        valid, errors = self.guardrail.validate(result)
        self.assertTrue(valid, f"Guardrail failed: {errors}")

    def test_restore_risk_finding_case_14(self) -> None:
        """Case 14: Verify unblocked archive backup_3870 is discovered."""
        email = "y.tanaka32@gmail.com"
        audit_at = "2026-10-01T12:00:00Z"
        profile = self.tracker.get_identity_profile(email, audit_at)
        self.assertIsNotNone(profile)

        result = self.scanner.audit_case("case_14", profile, audit_at)
        self.assertEqual(result.deletion_status, "INCOMPLETE")

        finding_ops = [f.operation for f in result.findings]
        self.assertIn("REPORT_RESTORE_RISK", finding_ops)

        valid, errors = self.guardrail.validate(result)
        self.assertTrue(valid, f"Guardrail failed: {errors}")

    def test_clean_case_verification_case_01(self) -> None:
        """Case 01: Verify clean case results in COMPLETE with verification proof."""
        email = "amina.elmasri@gmail.com"
        audit_at = "2026-09-03T12:00:00Z"
        profile = self.tracker.get_identity_profile(email, audit_at)
        self.assertIsNotNone(profile)

        result = self.scanner.audit_case("case_01", profile, audit_at)
        self.assertEqual(result.deletion_status, "COMPLETE")
        self.assertEqual(len(result.findings), 0)
        self.assertGreater(len(result.verifications), 0)

        valid, errors = self.guardrail.validate(result)
        self.assertTrue(valid, f"Guardrail failed: {errors}")


if __name__ == "__main__":
    unittest.main()
