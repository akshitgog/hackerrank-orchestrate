from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evidence.resolver import resolve_evidence
from models.domain import FinancialEvent, ImageLink, Message, Request


class FakeGateway:
    def __init__(self, payload):
        self.payload = payload

    def complete_json(self, messages, *, vision, **kwargs):
        self.vision = vision
        return self.payload


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.request = Request("r1", "u1", date(2026, 1, 10), "purchase", Decimal("50"), date(2026, 1, 20), False, "")
        self.event = FinancialEvent(
            "e1", "u1", "expense", "linked bill", "utilities", "debit", None, "USD",
            date(2026, 1, 9), date(2026, 1, 12), "pending", None, "fixed", None,
        )

    def test_model_fact_fills_blank_linked_amount(self):
        payload = {"facts": [{
            "source_id": "image_01", "action": "fill_event_amount",
            "target_event_id": "e1", "amount": "12.34", "currency": "USD",
        }]}
        with tempfile.TemporaryDirectory() as directory:
            image_dir = Path(directory)
            (image_dir / "image_01.png").write_bytes(b"not-a-real-image")
            result = resolve_evidence(
                self.request, [self.event], [], [ImageLink("image_01", "u1", "r1", "e1")],
                image_dir, FakeGateway(payload), "mark_invalid",
            )
        self.assertTrue(result.valid)
        self.assertEqual(result.events[0].amount, Decimal("12.34"))

    def test_unknown_event_target_is_rejected(self):
        message = Message("m1", "u1", "r1", None, "2026-01-09T00:00:00Z", "bank", "data")
        gateway = FakeGateway({"facts": [{
            "source_id": "m1", "action": "cancel_event", "target_event_id": "missing"
        }]})
        result = resolve_evidence(
            self.request, [self.event.updated(amount=Decimal("10"))], [message], [], Path("."),
            gateway, "mark_invalid",
        )
        self.assertFalse(result.valid)
        self.assertIn("unknown event", result.warnings[0])


if __name__ == "__main__":
    unittest.main()
