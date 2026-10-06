from __future__ import annotations

import csv
import importlib.util
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path


EVALUATOR_PATH = Path(__file__).resolve().parents[1] / "evaluation" / "main.py"
SPEC = importlib.util.spec_from_file_location("amount_evaluator", EVALUATOR_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


class EvaluationTests(unittest.TestCase):
    def test_missing_prediction_remains_in_denominator(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            expected = root / "expected.csv"
            predictions = root / "predictions.csv"
            profiles = root / "profiles.csv"
            write_csv(expected, ["request_id", "user_id", "requested_amount", "amount_safe_to_pay"], [
                {"request_id": "r1", "user_id": "u1", "requested_amount": "100", "amount_safe_to_pay": "50"},
                {"request_id": "r2", "user_id": "u1", "requested_amount": "200", "amount_safe_to_pay": "80"},
            ])
            write_csv(predictions, ["request_id", "amount_safe_to_pay", "valid"], [
                {"request_id": "r1", "amount_safe_to_pay": "49.995", "valid": "true"},
            ])
            write_csv(profiles, ["user_id", "home_currency"], [{"user_id": "u1", "home_currency": "USD"}])
            details, summary = MODULE.evaluate(expected, predictions, profiles, tolerance=Decimal("0.01"))
        self.assertEqual(summary["n"], 2)
        self.assertEqual(summary["valid"], 1)
        self.assertEqual(summary["exact"], 1)
        self.assertEqual(details[0]["normalized_absolute_error"], "0.00005")


if __name__ == "__main__":
    unittest.main()
