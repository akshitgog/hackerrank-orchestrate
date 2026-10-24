"""Unit tests for the Logging Agent (Identity Tracker) and IdentityGuardrail."""

import unittest
from pathlib import Path
import pandas as pd

from code.src.logging_agent.tracker import IdentityTracker
from code.guardrails.identity_guardrail import IdentityGuardrail


class TestLoggingAgent(unittest.TestCase):
    """Test suite for IdentityTracker and IdentityGuardrail."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.tracker = IdentityTracker()
        cls.guardrail = IdentityGuardrail(cls.tracker.audit_log_df)

    def test_current_email_resolution(self) -> None:
        """Case 01: Test matching against user_identities.csv directly."""
        email = "amina.elmasri@gmail.com"
        audit_at = "2026-09-03T12:00:00Z"
        profile = self.tracker.get_identity_profile(email, audit_at)

        self.assertIsNotNone(profile)
        self.assertEqual(profile.user_id, "user_01")
        self.assertEqual(profile.matched_via, "current_email")
        self.assertIn("amina.elmasri@gmail.com", profile.all_emails)

        # Validate with guardrail
        valid, errors = self.guardrail.validate(profile)
        self.assertTrue(valid, f"Guardrail failed: {errors}")

    def test_historical_email_backtracking(self) -> None:
        """Case 10: Test matching against user_audit_log.csv historical old_value."""
        email = "nadia.ionescu@yahoo.com"
        audit_at = "2026-09-03T12:00:00Z"
        profile = self.tracker.get_identity_profile(email, audit_at)

        self.assertIsNotNone(profile)
        self.assertEqual(profile.user_id, "user_10")
        self.assertEqual(profile.matched_via, "audit_log_historical")
        # Historical email requested
        self.assertIn("nadia.ionescu@yahoo.com", profile.all_emails)
        # Current email in snapshot
        self.assertIn("nadia.petrescu@yahoo.com", profile.all_emails)

        # Validate with guardrail
        valid, errors = self.guardrail.validate(profile)
        self.assertTrue(valid, f"Guardrail failed: {errors}")

    def test_case_insensitivity(self) -> None:
        """Verify emails with uppercase and spaces resolve identically."""
        email_upper = "  AMINA.ELMASRI@GMAIL.COM  "
        audit_at = "2026-09-03T12:00:00Z"
        profile = self.tracker.get_identity_profile(email_upper, audit_at)

        self.assertIsNotNone(profile)
        self.assertEqual(profile.user_id, "user_01")

    def test_strict_audit_at_cutoff(self) -> None:
        """Verify changes occurring after audit_at are strictly excluded."""
        # user_485 has phone audit on 2024-12-14
        email = "claire.moreau@orange.fr"
        # Cutoff BEFORE any audit events
        early_cutoff = "2024-01-01T00:00:00Z"
        profile_early = self.tracker.get_identity_profile(email, early_cutoff)

        if profile_early:
            # Audit log records after early_cutoff must not be added to all_phones
            valid, errors = self.guardrail.validate(profile_early)
            self.assertTrue(valid, f"Guardrail failed on early cutoff: {errors}")

    def test_guardrail_rejections(self) -> None:
        """Verify that IdentityGuardrail rejects invalid profiles."""
        valid, errors = self.guardrail.validate(None)
        self.assertFalse(valid)
        self.assertIn("None", errors[0])

    def test_all_sample_requests_resolution(self) -> None:
        """Benchmark: 100% of the 32 sample requests must resolve to a valid user_id."""
        sample_df = pd.read_csv("dataset/sample_deletion_requests.csv")
        unresolved = []

        for _, row in sample_df.iterrows():
            profile = self.tracker.get_identity_profile(row["email"], row["audit_at"])
            if not profile:
                unresolved.append(row["case_id"])
            else:
                valid, errors = self.guardrail.validate(profile)
                self.assertTrue(valid, f"Guardrail failed for {row['case_id']}: {errors}")

        self.assertEqual(len(unresolved), 0, f"Unresolved sample cases: {unresolved}")

    def test_all_eval_requests_resolution(self) -> None:
        """Benchmark: 100% of the 518 evaluation requests must resolve to a valid user_id."""
        eval_df = pd.read_csv("dataset/deletion_requests.csv")
        unresolved = []

        for _, row in eval_df.iterrows():
            profile = self.tracker.get_identity_profile(row["email"], row["audit_at"])
            if not profile:
                unresolved.append(row["case_id"])

        self.assertEqual(len(unresolved), 0, f"Unresolved evaluation cases: {unresolved}")


if __name__ == "__main__":
    unittest.main()
