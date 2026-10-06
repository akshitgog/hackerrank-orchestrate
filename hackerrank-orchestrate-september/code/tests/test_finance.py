from __future__ import annotations

import sys
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from finance.recurrence import _latest_pattern, detect_series, next_date
from finance.simulator import ForecastError, build_baseline_occurrences, calculate_capacity, convert_amount
from models.domain import FinancialEvent, Profile, Request


def request(amount: str = "500") -> Request:
    return Request("r1", "u1", date(2026, 1, 10), "purchase", Decimal(amount), date(2026, 2, 1), True, "")


def profile() -> Profile:
    return Profile("u1", "USD", Decimal("1000"), Decimal("200"), frozenset({"rent"}))


def event(**overrides) -> FinancialEvent:
    values = dict(
        event_id="e1", user_id="u1", event_type="expense", description="one debit",
        category="rent", direction="debit", amount=Decimal("100"), currency="USD",
        event_date=date(2026, 1, 11), settlement_date=date(2026, 1, 11), status="scheduled",
        linked_event_id=None, flexibility="fixed", minimum_allowed_amount=None,
    )
    values.update(overrides)
    return FinancialEvent(**values)


class RecurrenceTests(unittest.TestCase):
    def test_monthly_and_end_of_month_patterns(self):
        self.assertEqual(_latest_pattern([date(2025, 11, 30), date(2025, 12, 31), date(2026, 1, 31)])[0], "monthly")
        self.assertEqual(next_date(date(2026, 1, 31), "monthly", 31), date(2026, 2, 28))

    def test_weekly_requires_four_gaps(self):
        dates = [date(2026, 1, 1), date(2026, 1, 8), date(2026, 1, 15), date(2026, 1, 22), date(2026, 1, 29)]
        self.assertEqual(_latest_pattern(dates)[0], "weekly")
        self.assertIsNone(_latest_pattern(dates[:-1])[0])

    def test_biweekly_requires_three_gaps(self):
        dates = [date(2026, 1, 1), date(2026, 1, 15), date(2026, 1, 29), date(2026, 2, 12)]
        self.assertEqual(_latest_pattern(dates)[0], "biweekly")

    def test_missed_occurrence_makes_series_stale(self):
        rows = [
            event(
                event_id=f"e{index}",
                status="settled",
                event_date=when,
                settlement_date=when,
            )
            for index, when in enumerate((date(2025, 9, 1), date(2025, 10, 1), date(2025, 11, 1)))
        ]
        self.assertEqual(detect_series(rows, date(2026, 1, 10)), {})


class SimulatorTests(unittest.TestCase):
    def test_safe_amount_uses_worst_baseline_balance(self):
        result = calculate_capacity(
            request(), profile(), [event()], {}, horizon_days=90, lookback_days=90,
            bucket_days=30, evidence_status="not_needed"
        )
        self.assertTrue(result.valid)
        self.assertEqual(result.amount_safe_to_pay, Decimal("500"))
        self.assertEqual(result.minimum_baseline_balance, Decimal("900"))

    def test_safe_amount_is_capped_by_headroom(self):
        result = calculate_capacity(
            request("900"), profile(), [event(amount=Decimal("350"))], {}, horizon_days=90,
            lookback_days=90, bucket_days=30, evidence_status="not_needed"
        )
        self.assertEqual(result.amount_safe_to_pay, Decimal("450"))

    def test_pending_credit_is_not_counted(self):
        result = calculate_capacity(
            request("900"), profile(), [event(direction="credit", status="pending", amount=Decimal("500"))], {},
            horizon_days=90, lookback_days=90, bucket_days=30, evidence_status="not_needed"
        )
        self.assertEqual(result.amount_safe_to_pay, Decimal("800"))

    def test_overdue_pending_debit_is_reserved_once_on_request_date(self):
        pending = event(
            status="pending", amount=Decimal("125"),
            event_date=date(2026, 1, 8), settlement_date=date(2026, 1, 9),
        )
        occurrences = build_baseline_occurrences(
            request(), profile(), [pending], {}, horizon_days=90,
            lookback_days=90, bucket_days=30,
        )
        self.assertEqual(len(occurrences), 1)
        self.assertEqual(occurrences[0].date, date(2026, 1, 10))
        self.assertEqual(occurrences[0].signed_amount, Decimal("-125"))

    def test_equal_same_day_transactions_are_not_accidentally_deduplicated(self):
        first = event(event_id="e1")
        second = event(event_id="e2")
        occurrences = build_baseline_occurrences(
            request(), profile(), [first, second], {}, horizon_days=90,
            lookback_days=90, bucket_days=30,
        )
        self.assertEqual([item.event_id for item in occurrences], ["e1", "e2"])

    def test_settled_history_is_not_replayed(self):
        historical = event(
            status="settled",
            category="shopping",
            event_date=date(2026, 1, 9),
            settlement_date=date(2026, 1, 9),
        )
        result = calculate_capacity(
            request("900"), profile(), [historical], {}, horizon_days=90, lookback_days=90,
            bucket_days=30, evidence_status="not_needed"
        )
        self.assertEqual(result.minimum_baseline_balance, Decimal("1000"))

    def test_fx_requires_exact_date_and_direction(self):
        rates = {(date(2026, 1, 11), "EUR", "USD"): Decimal("1.1")}
        self.assertEqual(convert_amount(Decimal("10"), "EUR", "USD", date(2026, 1, 11), rates), Decimal("11.0"))
        with self.assertRaises(ForecastError):
            convert_amount(Decimal("10"), "EUR", "USD", date(2026, 1, 12), rates)

    def test_confirmed_next_salary_continues_without_duplicate(self):
        history = event(
            event_id="salary_old", event_type="income", description="payroll credit",
            category="salary", direction="credit", amount=Decimal("300"),
            status="settled", event_date=date(2025, 12, 15), settlement_date=date(2025, 12, 15),
        )
        scheduled = event(
            event_id="salary_next", event_type="income", description="next confirmed salary",
            category="salary", direction="credit", amount=Decimal("325"),
            status="scheduled", event_date=date(2026, 1, 15), settlement_date=date(2026, 1, 15),
        )
        occurrences = build_baseline_occurrences(
            request(), profile(), [history, scheduled], {}, horizon_days=90,
            lookback_days=90, bucket_days=30,
        )
        salary_dates = [item.date for item in occurrences if item.category == "salary"]
        self.assertEqual(salary_dates, [date(2026, 1, 15), date(2026, 2, 15), date(2026, 3, 15)])
        self.assertTrue(all(item.signed_amount == Decimal("325") for item in occurrences if item.category == "salary"))


if __name__ == "__main__":
    unittest.main()
