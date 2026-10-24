"""Unit tests for Phase 4 Intent Classifier and Intent Guardrail."""

import unittest
from code.src.orchestrator.classifier import IntentClassifier
from code.guardrails.intent_guardrail import IntentGuardrail


class TestIntentClassifier(unittest.TestCase):
    """Verifies intent classification across multilingual requests and non-deletion patterns."""

    def setUp(self) -> None:
        self.classifier = IntentClassifier(threshold=0.80)

    def test_english_deletion_request(self) -> None:
        """Standard English deletion requests must be authorized."""
        text = "Please delete my account and erase all associated personal data."
        res = self.classifier.classify("case_01", text)
        self.assertTrue(res.is_deletion_authorized)
        self.assertEqual(res.intent_category, "ACCOUNT_DELETION")
        self.assertGreaterEqual(res.confidence, 0.80)
        violations = IntentGuardrail.validate(res, threshold=0.80)
        self.assertEqual(violations, [])

    def test_multilingual_deletion_requests(self) -> None:
        """Spanish, French, Portuguese deletion requests must be recognized."""
        samples = [
            ("case_es", "Deseo eliminar mi cuenta y borrar todos mis datos personales."),
            ("case_fr", "Je demande la suppression définitive de mon compte et l'effacement de mes données."),
            ("case_pt", "Solicito a exclusão permanente da conta associada a este e-mail."),
        ]
        for cid, text in samples:
            res = self.classifier.classify(cid, text)
            self.assertTrue(res.is_deletion_authorized, f"Failed for text: {text}")
            self.assertEqual(res.intent_category, "ACCOUNT_DELETION")
            violations = IntentGuardrail.validate(res, threshold=0.80)
            self.assertEqual(violations, [])

    def test_data_export_non_deletion(self) -> None:
        """Data export request must be classified as non-deletion (NOT_APPLICABLE)."""
        text = "I'd like to download my account information in a portable format. Please keep the account as it is."
        res = self.classifier.classify("case_535", text)
        self.assertFalse(res.is_deletion_authorized)
        self.assertEqual(res.intent_category, "DATA_EXPORT")
        violations = IntentGuardrail.validate(res, threshold=0.80)
        self.assertEqual(violations, [])

    def test_marketing_opt_out_non_deletion(self) -> None:
        """Marketing opt-out request must not authorize deletion."""
        text = "Please remove me from marketing lists only. I still want receipts and service messages for this account."
        res = self.classifier.classify("case_538", text)
        self.assertFalse(res.is_deletion_authorized)
        self.assertEqual(res.intent_category, "MARKETING_OPT_OUT")
        violations = IntentGuardrail.validate(res, threshold=0.80)
        self.assertEqual(violations, [])

    def test_correction_non_deletion(self) -> None:
        """Correction/rectification requests must not authorize deletion."""
        text = "The mobile number on my profile is out of date. Please replace it with the new one and leave the account active."
        res = self.classifier.classify("case_533", text)
        self.assertFalse(res.is_deletion_authorized)
        self.assertEqual(res.intent_category, "RECTIFICATION_CORRECTION")
        violations = IntentGuardrail.validate(res, threshold=0.80)
        self.assertEqual(violations, [])

    def test_access_request_non_deletion(self) -> None:
        """Information access requests must not authorize deletion."""
        text = "Could you send me a copy of the information held on my account? I still use it, so please don't delete or change anything."
        res = self.classifier.classify("case_542", text)
        self.assertFalse(res.is_deletion_authorized)
        self.assertEqual(res.intent_category, "ACCESS_REQUEST")
        violations = IntentGuardrail.validate(res, threshold=0.80)
        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
