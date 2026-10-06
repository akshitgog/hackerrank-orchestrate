# Buy or Wait? — Local Regression Evaluator

## 1. Purpose

`code/evaluation/main.py` is the deterministic local regression evaluator for the **Buy or Wait?** system. It evaluates predictions against public ground truth (`dataset/sample_requests.csv`) and enforces structural and financial validation rules.

The evaluator is decoupled from prediction generation. It does not estimate hidden HackerRank leaderboard scores, compute arbitrary weighted composite scores, or evaluate open-ended `decision_explanation` text. Instead, it provides reproducible, multi-metric diagnostics.

---

## 2. CLI Execution & Inputs

Run directly from the command line:

```bash
python code/evaluation/main.py \
  --expected dataset/sample_requests.csv \
  --predictions artifacts/sample_predictions.csv \
  --profiles dataset/financial_profiles.csv \
  --rates dataset/exchange_rates.csv \
  --details artifacts/evaluation_details.csv \
  --report artifacts/evaluation_report.md \
  --tolerance 0.01
```

### CLI Parameters:
- `--expected`: Path to the ground-truth benchmark CSV (`dataset/sample_requests.csv`).
- `--predictions`: Path to the model predictions CSV (e.g., `artifacts/sample_predictions.csv` or `output.csv`).
- `--profiles`: Path to user financial profiles (`dataset/financial_profiles.csv`).
- `--rates`: (Optional) Path to fixed conversion rates (`dataset/exchange_rates.csv`) used to compute USD-normalized errors.
- `--details`: Output CSV destination for granular, per-request diagnostic rows.
- `--report`: Output Markdown destination for summary metrics, classification reports, and structural validation logs.
- `--tolerance`: Tolerance threshold for monetary exact matching (default: `0.01`).

---

## 3. Pre-Evaluation Structural Validation

The evaluator parses the prediction file and checks structural integrity via `structural_errors()`:

1. **Column Order & Schema**: When evaluating the final 8-column schema, requires the exact eight columns in order:
   ```text
   request_id,amount_safe_to_pay,affordability_status,recommended_payment_method,payment_plan,earliest_date_for_full_payment,spending_changes_needed,decision_explanation
   ```
2. **Row Uniqueness**: Reports any duplicate prediction `request_id` entries.
3. **Monetary Parsing**: Ensures `amount_safe_to_pay` parses into a valid finite `Decimal`.
4. **Schedule Parsing**:
   - `payment_plan`: Parses `YYYY-MM-DD:amount` entries separated by `|`, or `none`. `parse_plan()` normalizes entries into a sorted tuple of `(date, Decimal)` pairs.
   - `spending_changes_needed`: Parses `stop:<event_id>` or `reduce_to:<event_id>:<amount>` actions separated by `|`, or `none`. Flags plans with invalid syntax or exceeding 3 actions.

---

## 4. Evaluated Metrics

### 4.1 `amount_safe_to_pay`
All monetary calculations use `Decimal` arithmetic:
- **Exact Match Count**: Count where `abs(predicted - expected) <= tolerance`.
- **Native Currency MAE / Median / Max**: Reported per native currency (INR, ZAR, IDR, USD, EUR).
- **Normalized Absolute Error**:
  $$\text{Normalized AE} = \frac{|\text{predicted\_amount\_safe\_to\_pay} - \text{expected\_amount\_safe\_to\_pay}|}{\text{requested\_amount}}$$
- **USD-Normalized MAE**: Converts native absolute errors into USD using constant exchange rates derived from `dataset/exchange_rates.csv`.

### 4.2 Categorical & Decision Alignment
- **`affordability_status`**: Overall accuracy, multi-class confusion matrix, and per-class precision, recall, F1, and support.
- **`recommended_payment_method`**: Overall accuracy, multi-class confusion matrix, and per-class precision, recall, F1, and support.
- **`payment_plan`**: Semantic exact-match rate comparing sorted `(date, Decimal)` tuples.
- **`earliest_date_for_full_payment`**: Exact date match rate, Mean Absolute Day Error (days difference when both dates are present), and empty/non-empty mismatch count.
- **`spending_changes_needed`**: Semantic exact match rate across parsed action sets, plus action-level precision, recall, and F1.

---

## 5. Generated Artifacts

1. **`evaluation_details.csv`**: Granular breakdown for each evaluated request:
   - `request_id`, `home_currency`, `requested_amount`
   - `expected_amount_safe_to_pay`, `predicted_amount_safe_to_pay`
   - `absolute_error`, `absolute_error_usd`, `normalized_absolute_error`
   - Per-target match flags (`affordability_status_match`, `recommended_payment_method_match`, `payment_plan_match`, `earliest_date_for_full_payment_match`, `spending_changes_needed_match`).

2. **`evaluation_report.md`**: Human-readable summary table containing:
   - Safe amount accuracy and error statistics.
   - Categorical accuracy and classification confusion matrices with per-class precision/recall/F1.
   - Structural validation status confirming 0 structural defects.
