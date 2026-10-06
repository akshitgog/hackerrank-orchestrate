from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from collections import defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


AMOUNT_COLUMNS = {"request_id", "user_id", "requested_amount", "amount_safe_to_pay"}
STRUCTURED_FIELDS = (
    "affordability_status", "recommended_payment_method", "payment_plan",
    "earliest_date_for_full_payment", "spending_changes_needed",
)
FINAL_COLUMNS = [
    "request_id", "amount_safe_to_pay", "affordability_status",
    "recommended_payment_method", "payment_plan", "earliest_date_for_full_payment",
    "spending_changes_needed", "decision_explanation",
]


def parse_decimal(value: str | None) -> Decimal | None:
    if value is None or value.strip() == "":
        return None
    try:
        result = Decimal(value)
    except InvalidOperation:
        return None
    return result if result.is_finite() else None


def decimal_text(value: Decimal | None) -> str:
    if value is None:
        return ""
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def read_csv(path: Path, required: set[str]) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or ())
        missing = required - set(fields)
        if missing:
            raise ValueError(f"{path} missing columns: {sorted(missing)}")
        return fields, list(reader)


def build_usd_rates(rates_path: Path) -> dict[str, Decimal]:
    _, rows = read_csv(rates_path, {"rate_date", "from_currency", "to_currency", "rate"})
    edges: dict[tuple[str, str], Decimal] = {}
    for row in rows:
        rate = parse_decimal(row["rate"])
        if rate is not None:
            edges.setdefault((row["from_currency"], row["to_currency"]), rate)
    result = {"USD": Decimal("1")}
    currencies = {currency for pair in edges for currency in pair}
    for currency in currencies:
        if currency == "USD":
            continue
        if (currency, "USD") in edges:
            result[currency] = edges[(currency, "USD")]
        elif ("USD", currency) in edges:
            result[currency] = Decimal("1") / edges[("USD", currency)]
    changed = True
    while changed:
        changed = False
        for (source, target), rate in edges.items():
            if source not in result and target in result:
                result[source] = rate * result[target]
                changed = True
            if target not in result and source in result:
                result[target] = result[source] / rate
                changed = True
    return result


def parse_plan(value: str) -> tuple[tuple[date, Decimal], ...] | None:
    if value == "none":
        return ()
    parsed = []
    try:
        for item in value.split("|"):
            when, amount = item.split(":", 1)
            parsed.append((date.fromisoformat(when), Decimal(amount)))
    except (ValueError, InvalidOperation):
        return None
    if any(not amount.is_finite() for _, amount in parsed):
        return None
    return tuple(sorted(parsed))


def parse_changes(value: str) -> frozenset[tuple[str, ...]] | None:
    if value == "none":
        return frozenset()
    result = set()
    for item in value.split("|"):
        parts = tuple(item.split(":"))
        if len(parts) == 2 and parts[0] == "stop":
            result.add(parts)
        elif len(parts) == 3 and parts[0] == "reduce_to" and parse_decimal(parts[2]) is not None:
            result.add((parts[0], parts[1], decimal_text(parse_decimal(parts[2]))))
        else:
            return None
    return frozenset(result)


def classification_metrics(expected: list[str], predicted: list[str | None]) -> dict[str, Any]:
    labels = sorted(set(expected) | {item for item in predicted if item is not None})
    confusion = {label: {other: 0 for other in labels + ["<missing>"]} for label in labels}
    for truth, guess in zip(expected, predicted):
        confusion[truth][guess or "<missing>"] += 1
    per_class = {}
    for label in labels:
        tp = sum(1 for truth, guess in zip(expected, predicted) if truth == label and guess == label)
        fp = sum(1 for truth, guess in zip(expected, predicted) if truth != label and guess == label)
        fn = sum(1 for truth, guess in zip(expected, predicted) if truth == label and guess != label)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        per_class[label] = {
            "precision": precision, "recall": recall,
            "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
            "support": sum(value == label for value in expected),
        }
    return {
        "accuracy": sum(truth == guess for truth, guess in zip(expected, predicted)) / len(expected) if expected else 0.0,
        "confusion_matrix": confusion, "per_class": per_class,
    }


def structural_errors(fields: list[str], rows: list[dict[str, str]], require_final: bool) -> list[str]:
    errors = []
    if require_final and fields != FINAL_COLUMNS:
        errors.append("prediction columns are not exactly the required eight columns in order")
    ids = [row.get("request_id", "") for row in rows]
    if len(ids) != len(set(ids)):
        errors.append("duplicate prediction request_id")
    for row in rows:
        rid = row.get("request_id", "<missing>")
        amount = parse_decimal(row.get("amount_safe_to_pay"))
        if amount is None:
            errors.append(f"{rid}: invalid amount_safe_to_pay")
        if "payment_plan" in row and parse_plan(row["payment_plan"]) is None:
            errors.append(f"{rid}: invalid payment_plan")
        if "spending_changes_needed" in row:
            changes = parse_changes(row["spending_changes_needed"])
            if changes is None or len(changes) > 3:
                errors.append(f"{rid}: invalid spending_changes_needed")
    return errors


def evaluate(
    expected_path: Path,
    predictions_path: Path,
    profiles_path: Path,
    rates_path: Path | None = None,
    *,
    tolerance: Decimal,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    expected_fields, expected = read_csv(expected_path, AMOUNT_COLUMNS)
    prediction_fields, predictions = read_csv(predictions_path, {"request_id", "amount_safe_to_pay"})
    _, profiles = read_csv(profiles_path, {"user_id", "home_currency"})
    profile_currency = {row["user_id"]: row["home_currency"] for row in profiles}
    usd_rates = build_usd_rates(rates_path) if rates_path else {}
    prediction_map = {row["request_id"]: row for row in predictions}
    expected_ids = [row["request_id"] for row in expected]
    details = []
    numeric_errors = []
    normalized_errors = []
    usd_errors = []
    exact = 0
    valid = 0
    per_currency: dict[str, list[Decimal]] = defaultdict(list)
    for truth in expected:
        rid = truth["request_id"]
        prediction = prediction_map.get(rid)
        expected_amount = parse_decimal(truth["amount_safe_to_pay"])
        predicted_amount = parse_decimal(prediction.get("amount_safe_to_pay")) if prediction else None
        declared_valid = prediction is not None and prediction.get("valid", "true").lower() != "false"
        error = abs(predicted_amount - expected_amount) if declared_valid and predicted_amount is not None and expected_amount is not None else None
        requested = parse_decimal(truth["requested_amount"])
        normalized = error / requested if error is not None and requested not in {None, Decimal("0")} else None
        currency = profile_currency[truth["user_id"]]
        usd = error * usd_rates[currency] if error is not None and currency in usd_rates else None
        is_exact = error is not None and error <= tolerance
        if error is not None:
            valid += 1
            exact += int(is_exact)
            numeric_errors.append(error)
            per_currency[currency].append(error)
        if normalized is not None:
            normalized_errors.append(normalized)
        if usd is not None:
            usd_errors.append(usd)
        detail = {
            "request_id": rid, "home_currency": currency,
            "requested_amount": decimal_text(requested),
            "expected_amount_safe_to_pay": decimal_text(expected_amount),
            "predicted_amount_safe_to_pay": decimal_text(predicted_amount),
            "valid_prediction": str(error is not None).lower(),
            "exact_match": str(is_exact).lower() if error is not None else "",
            "absolute_error": decimal_text(error), "absolute_error_usd": decimal_text(usd),
            "normalized_absolute_error": decimal_text(normalized),
        }
        for field in STRUCTURED_FIELDS:
            if field in expected_fields:
                if field == "payment_plan":
                    match = prediction is not None and parse_plan(truth[field]) == parse_plan(prediction.get(field, ""))
                elif field == "spending_changes_needed":
                    match = prediction is not None and parse_changes(truth[field]) == parse_changes(prediction.get(field, ""))
                else:
                    match = prediction is not None and truth[field] == prediction.get(field, "")
                detail[f"{field}_match"] = str(match).lower()
        details.append(detail)

    summary: dict[str, Any] = {
        "n": len(expected), "valid": valid, "exact": exact,
        "mae": sum(numeric_errors, Decimal("0")) / len(numeric_errors) if numeric_errors else None,
        "median_absolute_error": statistics.median(numeric_errors) if numeric_errors else None,
        "max_absolute_error": max(numeric_errors) if numeric_errors else None,
        "mean_normalized_ae": sum(normalized_errors, Decimal("0")) / len(normalized_errors) if normalized_errors else None,
        "usd_mae": sum(usd_errors, Decimal("0")) / len(usd_errors) if usd_errors else None,
        "usd_median_ae": statistics.median(usd_errors) if usd_errors else None,
        "usd_max_ae": max(usd_errors) if usd_errors else None,
        "currencies": {currency: {"n": len(values), "mae": sum(values, Decimal("0")) / len(values)} for currency, values in per_currency.items()},
        "missing_or_invalid": [row["request_id"] for row in details if row["valid_prediction"] != "true"],
        "unexpected_prediction_ids": sorted(set(prediction_map) - set(expected_ids)),
        "duplicate_prediction_ids": [rid for rid in set(row["request_id"] for row in predictions) if sum(item["request_id"] == rid for item in predictions) > 1],
        "structural_errors": structural_errors(prediction_fields, predictions, all(field in expected_fields for field in FINAL_COLUMNS)),
    }
    for field in ("affordability_status", "recommended_payment_method"):
        if field in expected_fields:
            summary[field] = classification_metrics(
                [row[field] for row in expected],
                [prediction_map.get(row["request_id"], {}).get(field) for row in expected],
            )
    for field in ("payment_plan", "spending_changes_needed"):
        if field in expected_fields:
            summary[field] = {"exact": sum(row.get(f"{field}_match") == "true" for row in details), "n": len(expected)}
    if "earliest_date_for_full_payment" in expected_fields:
        day_errors = []
        empty_mismatch = 0
        for truth in expected:
            predicted = prediction_map.get(truth["request_id"], {}).get("earliest_date_for_full_payment", "")
            actual = truth["earliest_date_for_full_payment"]
            if bool(predicted) != bool(actual):
                empty_mismatch += 1
            elif predicted and actual:
                try:
                    day_errors.append(abs((date.fromisoformat(predicted) - date.fromisoformat(actual)).days))
                except ValueError:
                    empty_mismatch += 1
        summary["earliest_date_for_full_payment"] = {
            "exact": sum(row.get("earliest_date_for_full_payment_match") == "true" for row in details),
            "n": len(expected), "mean_absolute_day_error": sum(day_errors) / len(day_errors) if day_errors else None,
            "empty_nonempty_mismatch": empty_mismatch,
        }
    if "spending_changes_needed" in expected_fields:
        tp = fp = fn = 0
        for truth in expected:
            expected_set = parse_changes(truth["spending_changes_needed"]) or frozenset()
            predicted_set = parse_changes(prediction_map.get(truth["request_id"], {}).get("spending_changes_needed", "")) or frozenset()
            tp += len(expected_set & predicted_set); fp += len(predicted_set - expected_set); fn += len(expected_set - predicted_set)
        precision = tp / (tp + fp) if tp + fp else 1.0
        recall = tp / (tp + fn) if tp + fn else 1.0
        summary["spending_changes_needed"].update({
            "precision": precision, "recall": recall,
            "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
        })
    return details, summary


def write_details(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader(); writer.writerows(rows)


def write_report(path: Path, summary: dict[str, Any], tolerance: Decimal) -> None:
    lines = [
        "# Public sample evaluation", "", f"Tolerance: `{tolerance}`", "",
        f"- amount_safe_to_pay exact: {summary['exact']}/{summary['n']}",
        f"- native-currency MAE: {decimal_text(summary['mae'])}",
        f"- median absolute error: {decimal_text(summary['median_absolute_error'])}",
        f"- max absolute error: {decimal_text(summary['max_absolute_error'])}",
        f"- mean normalized error: {decimal_text(summary['mean_normalized_ae'])}",
        f"- USD-normalized MAE: {decimal_text(summary['usd_mae'])}",
    ]
    for field in ("affordability_status", "recommended_payment_method"):
        if field in summary:
            lines.append(f"- {field} accuracy: {summary[field]['accuracy']:.4f}")
    for field in ("payment_plan", "earliest_date_for_full_payment", "spending_changes_needed"):
        if field in summary:
            lines.append(f"- {field} exact: {summary[field]['exact']}/{summary[field]['n']}")
    lines.extend(["", "## Structural validation", ""])
    lines.extend(f"- {item}" for item in summary["structural_errors"])
    if not summary["structural_errors"]:
        lines.append("No structural validation failures.")
    lines.extend(["", "## Classification details", "", "```json", json.dumps({key: summary[key] for key in ("affordability_status", "recommended_payment_method") if key in summary}, indent=2), "```", ""])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate full public-sample predictions")
    parser.add_argument("--expected", required=True); parser.add_argument("--predictions", required=True)
    parser.add_argument("--profiles", required=True); parser.add_argument("--rates")
    parser.add_argument("--details", required=True); parser.add_argument("--report", required=True)
    parser.add_argument("--tolerance", default="0.01")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    details, summary = evaluate(
        Path(args.expected), Path(args.predictions), Path(args.profiles),
        Path(args.rates) if args.rates else None, tolerance=Decimal(args.tolerance),
    )
    write_details(Path(args.details), details); write_report(Path(args.report), summary, Decimal(args.tolerance))
    print(f"amount_safe_to_pay exact: {summary['exact']}/{summary['n']}")
    for field in ("affordability_status", "recommended_payment_method"):
        if field in summary:
            print(f"{field} accuracy: {summary[field]['accuracy']:.4f}")
    for field in ("payment_plan", "earliest_date_for_full_payment", "spending_changes_needed"):
        if field in summary:
            print(f"{field} exact: {summary[field]['exact']}/{summary[field]['n']}")
    print(f"Structural failures: {len(summary['structural_errors'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
