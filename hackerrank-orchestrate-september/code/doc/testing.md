# Testing & Verification Strategy — Buy or Wait?

## 1. Overview

The **Buy or Wait?** system employs a multi-tiered testing and verification framework:
1. **Unit Test Suite**: Rapid, localized tests validating individual mathematical, recurrence, schema parsing, and guardrail functions.
2. **Integration Test Suite**: End-to-end simulation pipelines testing interactions across profiles, events, and candidate generation without external LLM dependencies.
3. **Public Sample Regression Suite**: Benchmarks generated predictions against `dataset/sample_requests.csv` via `code/evaluation/main.py`.
4. **Final Batch Verification**: 250-row full dataset sanity checks enforcing 100% contract compliance and fallback isolation.

---

## 2. Test Suites

All tests are located in `code/tests/`:

| Test Module | Coverage & Responsibilities |
|---|---|
| `test_finance.py` | 90-day cash flow ledger simulation, opening snapshot boundaries, recurrence detection (calendar month, anchor preservation, weekly/biweekly), variable essential reserves lookback, FX currency conversions, same-day settlement ordering, and headroom calculation. |
| `test_decision.py` | Earliest safe date search, preference gating (`payment_methods_user_will_consider`, `max_installment_months`), partial payment two-payment schedule generation, installment schedule expansion, spending change recovery (bounded search, relief calculation, `reduce_to` floor), lexicographical candidate ranking, and guardrail enforcement. |
| `test_evidence.py` | Gated LLM invocation, schema validation of evidence facts, target event ID handling, negative constraints against duplicate events, date rescheduling and status updates, and image amount extraction logic. |
| `test_config_gateway.py` | `config.yaml` schema validation, `.env` loading and environment variable override semantics, LiteLLM gateway backoff and retry behavior, JSON extraction across conversational fences, and Bedrock model configuration. |
| `test_evaluation.py` | Evaluator metrics: native-currency MAE, USD-normalized MAE, classification precision/recall/F1, semantic schedule matching, and structural error detection. |
| `test_integration.py` | Full multi-component pipeline run with synthetic dataset verifying deterministic `amount_safe_to_pay` and decision output. |

---

## 3. Running the Tests

### 3.1 Run via Pytest
Execute from the repository root:

```bash
python -m pytest code/tests/ -v
```

All 27 test cases run locally in under 2 seconds without requiring external network access or live API calls.

### 3.2 Run via Unittest
Alternatively, run using Python's built-in `unittest` runner:

```bash
python -m unittest discover -s code/tests -v
```

---

## 4. Public Sample Regression Testing

The 25 public samples in `dataset/sample_requests.csv` are used as a regression benchmark to detect unintended behavioral regressions during development.

### Step 1: Generate Predictions for Public Samples
```bash
python code/main.py \
  --config code/config.yaml \
  --requests dataset/sample_requests.csv \
  --output artifacts/sample_predictions.csv \
  --debug
```

### Step 2: Evaluate Against Benchmark
```bash
python code/evaluation/main.py \
  --expected dataset/sample_requests.csv \
  --predictions artifacts/sample_predictions.csv \
  --profiles dataset/financial_profiles.csv \
  --rates dataset/exchange_rates.csv \
  --details artifacts/evaluation_details.csv \
  --report artifacts/evaluation_report.md
```

### Evaluation Targets:
- **Structural Integrity**: **0 structural errors** (strict 8-column header, no nulls, valid plans, valid spending changes).
- **Categorical Accuracy**: High accuracy across `affordability_status` and `recommended_payment_method` (baseline > 75%).
- **Plan Exactness**: Exact schedule and date adherence.

---

## 5. Full Dataset Production Run Verification

Before preparing the submission, the 250 evaluation requests in `dataset/requests.csv` must be processed:

```bash
python code/main.py \
  --config code/config.yaml \
  --requests dataset/requests.csv \
  --output output.csv \
  --final-run
```

### Mandatory Verification Checklist:
- [x] `output.csv` exists at repository root.
- [x] Contains exactly 251 lines (header + 250 rows).
- [x] Header matches exactly:
  ```text
  request_id,amount_safe_to_pay,affordability_status,recommended_payment_method,payment_plan,earliest_date_for_full_payment,spending_changes_needed,decision_explanation
  ```
- [x] Every row satisfies $0 \le \text{amount\_safe\_to\_pay} \le \text{requested\_amount}$.
- [x] `code/evaluation/usage_report.md` exists and contains token and cost accounting for the run.
- [x] No secrets, API keys, or temporary files are present in the output.
