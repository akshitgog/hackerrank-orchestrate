from __future__ import annotations

import sys
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from models.domain import Dataset, FinancialEvent, Profile, Request
from pipeline.orchestrator import run_amount_safe_stage


class IntegrationTests(unittest.TestCase):
    def test_pipeline_produces_one_deterministic_result_without_evidence(self):
        request = Request("r1", "u1", date(2026, 1, 1), "purchase", Decimal("700"), date(2026, 2, 1), False, "")
        profile = Profile("u1", "USD", Decimal("1000"), Decimal("200"), frozenset({"rent"}))
        debit = FinancialEvent(
            "e1", "u1", "expense", "rent due", "rent", "debit", Decimal("250"), "USD",
            date(2026, 1, 2), date(2026, 1, 2), "scheduled", None, "fixed", None,
        )
        dataset = Dataset((request,), {"u1": profile}, {"u1": (debit,)}, {}, {}, {})
        config = {
            "runtime": {"forecast_horizon_days": 90, "variable_essential_lookback_days": 90, "variable_essential_bucket_days": 30},
            "evidence": {"enabled": False, "failure_policy": "mark_invalid"},
        }
        results = run_amount_safe_stage(dataset, config, image_dir=Path("."), artifacts_dir=Path("artifacts"))
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].amount_safe_to_pay, Decimal("550"))


if __name__ == "__main__":
    unittest.main()
