from __future__ import annotations

import sys
import tempfile
import unittest
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from decision.engine import (
    Payment, PaymentCandidate, SpendingChange, earliest_full_payment_date,
    evaluate_candidates, generate_candidates, rank_candidates, simulate,
)
from models.domain import FinancialEvent, Occurrence, PaymentOption, Profile, Request
from validation.guardrails import GuardrailError, validate_decision
from decision.engine import FinalDecision


def profile(methods=frozenset({"full_payment", "partial_payment", "installments"})):
    return Profile(
        "u1", "USD", Decimal("1000"), Decimal("200"), frozenset({"rent"}),
        frozenset({"dining"}), frozenset({"streaming"}), methods, 6,
    )


def request(amount="500", partial=True):
    return Request("r1", "u1", date(2026, 1, 1), "purchase", Decimal(amount), date(2026, 3, 31), partial, "")


def occurrence(event_id="e1", when=date(2026, 1, 5), amount="-100", protected=True, flexible=False, key=None):
    return Occurrence(f"{event_id}@{when}", event_id, when, Decimal(amount), "rent", "debit", protected, flexible, key)


def option(option_id="o1", count=3, amount="100", fee="0"):
    return PaymentOption(option_id, "r1", "installments", Decimal(amount), count, date(2026, 1, 2), 30, Decimal(fee), Decimal(amount) * count)


class DecisionTests(unittest.TestCase):
    def test_earliest_full_safe_date(self):
        rows = [occurrence(amount="-400"), Occurrence("salary@d", "salary", date(2026, 1, 10), Decimal("500"), "salary", "credit", True, False)]
        self.assertEqual(earliest_full_payment_date(request("700"), profile(), rows, 90), date(2026, 1, 10))

    def test_candidate_generation_respects_preferences_and_partial_contract(self):
        req = request()
        candidates = generate_candidates(req, profile(), [option()], Decimal("300"), date(2026, 1, 10), date(2026, 4, 1))
        methods = {item.method for item in candidates}
        self.assertEqual(methods, {"full_payment", "partial_payment", "installments", "wait"})
        partial = next(item for item in candidates if item.method == "partial_payment")
        self.assertEqual(partial.payments, (Payment(req.request_date, Decimal("300")), Payment(date(2026, 1, 10), Decimal("200"))))

    def test_installment_max_months_is_enforced(self):
        candidates = generate_candidates(request(), profile(), [option(count=7)], Decimal("0"), None, date(2026, 4, 1))
        installment = next(item for item in candidates if item.method == "installments")
        self.assertFalse(installment.eligible)
        self.assertEqual(installment.rejection_reason, "exceeds_max_installment_months")

    def test_simulator_applies_stop_and_reduce(self):
        rows = [occurrence("flex", amount="-100", protected=False, flexible=True, key="s")]
        stopped = simulate(rows, profile(), (), (SpendingChange("stop", "flex", Decimal("100"), series_key="s"),))
        reduced = simulate(rows, profile(), (), (SpendingChange("reduce_to", "flex", Decimal("100"), Decimal("25"), "s"),))
        self.assertEqual(stopped.minimum_balance, Decimal("1000"))
        self.assertEqual(reduced.minimum_balance, Decimal("975"))

    def test_rank_is_lexicographic(self):
        safe = simulate([], profile())
        base = PaymentCandidate("base", "installments", (Payment(date(2026, 1, 2), Decimal("100")),), Decimal("300"), date(2026, 1, 2), date(2026, 1, 2), "o2", simulation=safe)
        cases = [
            (replace(base, candidate_id="changes", spending_changes=(SpendingChange("stop", "e", Decimal("1")),)), base),
            (replace(base, candidate_id="costly", total_payable=Decimal("301")), base),
            (replace(base, candidate_id="late", start_date=date(2026, 1, 3)), base),
            (replace(base, candidate_id="many", payments=(Payment(date(2026, 1, 2), Decimal("50")), Payment(date(2026, 1, 3), Decimal("50")))), base),
            (replace(base, candidate_id="option3", payment_option_id="o3"), base),
        ]
        for worse, better in cases:
            with self.subTest(worse=worse.candidate_id):
                self.assertEqual(rank_candidates([worse, better])[0], better)

    def test_unsafe_candidates_do_not_rank(self):
        candidate = PaymentCandidate("full", "full_payment", (Payment(date(2026, 1, 1), Decimal("900")),), Decimal("900"), date(2026, 1, 1), date(2026, 1, 1))
        evaluated = evaluate_candidates([candidate], [], profile())
        self.assertEqual(rank_candidates(evaluated), [])

    def test_guardrail_rejects_inconsistent_full_payment(self):
        req = request()
        decision = FinalDecision("r1", Decimal("500"), "affordable_now", "full_payment", "2026-01-02:500", date(2026, 1, 1), "none", "x")
        with self.assertRaises(GuardrailError):
            validate_decision(decision, req, profile(), [], [], Decimal("500"))


if __name__ == "__main__":
    unittest.main()
