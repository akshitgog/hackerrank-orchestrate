# Buy or Wait? — AI Financial Decision Agent
### HackerRank Orchestrate (September 2026) Starter Solution

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://img.shields.io/badge/tests-27%20passed-success.svg)]()
[![Evaluator](https://img.shields.io/badge/structural%20errors-0-brightgreen.svg)]()

An enterprise-grade, deterministic AI financial agent built for the **HackerRank Orchestrate** hackathon challenge: **Buy or Wait?**.

For every purchase or payment request, the agent decides whether the user should **pay in full now**, **pay partially**, **use an installment plan**, **wait until a safe date**, or **not proceed**. Decisions are strictly personalized by reconstructing the user's forward financial position from structured profiles, dated foreign exchange rates, seller payment options, recurring cash flows, and unstructured evidence (messages and images).

---

## Table of Contents
1. [Core Design Philosophy](#1-core-design-philosophy)
2. [System Architecture](#2-system-architecture)
3. [Subfolder Breakdown & Module Architecture](#3-subfolder-breakdown--module-architecture)
4. [Deterministic Core vs. LLM Boundary](#4-deterministic-core-vs-llm-boundary)
5. [Strict Guardrails & Business Invariants](#5-strict-guardrails--business-invariants)
6. [Setup and Execution Guide](#6-setup-and-execution-guide)
   - [Prerequisites](#61-prerequisites)
   - [Environment Configuration](#62-environment-configuration)
   - [Running the Production Pipeline](#63-running-the-production-pipeline)
   - [Running the Local Evaluator](#64-running-the-local-evaluator)
   - [Running the Test Suite](#65-running-the-test-suite)
7. [Output Contract & Schema](#7-output-contract--schema)
8. [Token Usage & Observability](#8-token-usage--observability)
9. [Documentation Links](#9-documentation-links)
10. [Zero Hardcoding & Evaluability Guarantee](#10-zero-hardcoding--evaluability-guarantee)

---

## 1. Core Design Philosophy

```text
    PROBABILISTIC WORLD (AI / VLM)         DETERMINISTIC WORLD (Python)
    Extract structured facts from        100% of arithmetic, 90-day simulation,
    untrusted messages & image bills   ──► capacity checks, ranking, candidate
    (LiteLLM Gateway + Nova Pro)          generation, spending recovery, guardrails
```

- **Zero LLM Math**: Large Language Models are never permitted to perform financial arithmetic, simulate cash balances, evaluate affordability, or select final categorical labels.
- **Probabilistic Boundary**: Models are invoked exclusively to interpret unstructured natural language messages and receipt/bill images with missing amounts.
- **Deterministic Financial Engine**: Built purely in Python using arbitrary-precision `Decimal` arithmetic, calendar-aware date mechanics, and strict constraint validation.
- **Fail-Safe Isolation**: Individual request or API exceptions are caught and resolved into contract-compliant conservative fallback rows, ensuring the full 250-request batch run never crashes.

---

## 2. System Architecture

```text
                                  DATASET
                     (requests, profiles, events, FX,
                        payment options, messages, images)
                                     │
                                     ▼
                        ┌─────────────────────────┐
                        │   Data Ingestion Layer  │  (data/loader.py)
                        │  - Decimal amount parse │
                        │  - Exact dated FX index │
                        └────────────┬────────────┘
                                     │
                                     ▼
                        ┌─────────────────────────┐
                        │   Evidence Resolution   │  (evidence/resolver.py)
                        │  - Multimodal gateway   │  (evidence/gateway.py)
                        │  - Missing amount OCR   │
                        │  - Negative constraints │
                        └────────────┬────────────┘
                                     │ Validated Facts
                                     ▼
                        ┌─────────────────────────┐
                        │ Financial Recurrence &  │  (finance/recurrence.py)
                        │ 90-Day Ledger Simulator │  (finance/simulator.py)
                        │  - Anchor preservation │
                        │  - Essential reserves   │
                        │  - Same-day ordering    │
                        └────────────┬────────────┘
                                     │
                 ┌───────────────────┴───────────────────┐
                 ▼                                       ▼
    ┌─────────────────────────┐             ┌─────────────────────────┐
    │   amount_safe_to_pay    │             │ earliest_date_for_full  │
    │   (PERMANENTLY FROZEN)  │             │      payment date       │
    └────────────┬────────────┘             └────────────┬────────────┘
                 │                                       │
                 └───────────────────┬───────────────────┘
                                     │
                                     ▼
                        ┌─────────────────────────┐
                        │    Candidate Engine     │  (decision/engine.py)
                        │  - full_payment         │
                        │  - partial_payment      │
                        │  - installments (exact) │
                        │  - wait                 │
                        └────────────┬────────────┘
                                     │
                                     ▼
                        ┌─────────────────────────┐
                        │ Spending Recovery (<=3) │  (decision/engine.py)
                        │  - Only flexible debits │
                        │  - Solved reduce floors │
                        └────────────┬────────────┘
                                     │
                                     ▼
                        ┌─────────────────────────┐
                        │  Lexicographical Ranker │  (decision/engine.py)
                        │  & Final Decision Maker │
                        └────────────┬────────────┘
                                     │
                                     ▼
                        ┌─────────────────────────┐
                        │ Strict Output Guardrail │  (validation/guardrails.py)
                        │  - Invariant validation │
                        │  - Fallback safety      │
                        └────────────┬────────────┘
                                     │
                                     ▼
                                 output.csv
```

---

## 3. Subfolder Breakdown & Module Architecture

The `code/` directory is organized into focused, single-responsibility packages. This modular layout strictly separates probabilistic evidence reasoning from deterministic financial math:

```text
code/
├── artifacts/          # Local benchmark predictions, evaluation reports, and run summaries
├── data/               # Configuration management and strict dataset ingestion
├── decision/           # Deterministic candidate generation, spending recovery, and ranking engine
├── doc/                # Deep-dive architecture, guardrails, testing, and evaluator specifications
├── evaluation/         # Standalone local evaluator harness and mandatory usage_report.md
├── evidence/           # Multi-modal LLM gateway (LiteLLM) and fact validation resolver
├── finance/            # Calendar-aware recurrence detection and 90-day ledger simulation
├── models/             # Strongly typed Pydantic domain entities and schema definitions
├── observability/      # LLM token telemetry, cost accounting, and usage report generator
├── pipeline/           # End-to-end request orchestrator and error-isolation lifecycle
├── tests/              # 27 comprehensive unit and integration verification tests
├── validation/         # Business invariant checks, schema enforcement, and fallback rows
├── .env.example        # Environment variable template for AWS Bedrock credentials
├── config.yaml         # Central runtime, model, horizon, and path configuration
├── main.py             # CLI entry point for full-dataset runs and evaluation passes
├── README.md           # Engineering documentation and execution guide
└── requirements.txt    # Python package dependencies
```

### Module Responsibilities:

- **`code/data/`**: Ingestion & configuration layer.
  - `config.py`: Resolves runtime configuration (`config.yaml`), repository paths, and loads credentials safely from `.env`.
  - `loader.py`: Ingests all raw dataset CSVs, strictly parses currency strings to arbitrary-precision `Decimal`, builds date-keyed exchange-rate maps, and links payment options to requests.
- **`code/decision/`**: Strategic reasoning & ranking engine.
  - `engine.py`: Evaluates candidate options across all 5 payment methods (`full_payment`, `partial_payment`, `installments`, `wait`, `not_recommended`). Searches up to 3 legal spending changes on flexible recurring debits to rescue near-affordable plans, and applies the official lexicographical ranking order.
- **`code/doc/`**: System specifications & engineering references.
  - `architecture.md`: In-depth 10-stage execution pipeline diagram, data flow specifications, and allowed evidence actions.
  - `guardrails.md`: Formal definitions of the 8 business invariants, monetary bounds, and conservative fallback mechanics.
  - `testing.md`: Complete testing matrix covering all 27 unit and integration tests with deterministic mocks.
  - `evaluator.md`: Local evaluation benchmark specification, error codes, and macro-averaged metrics.
- **`code/evaluation/`**: Verification benchmark & cost accounting.
  - `main.py`: Local evaluation CLI comparing model predictions against ground truth (`sample_requests.csv`) across safe-amount accuracy, macro-F1 classification, payment plan exactness, and spending change validity.
  - `usage_report.md`: Mandatory submission artifact summarizing model providers, calls, token counts, averages, and estimated cost across the final full evaluation run.
- **`code/evidence/`**: Probabilistic multimodal boundary.
  - `gateway.py`: Robust LiteLLM interface to AWS Bedrock (Claude / Nova Pro) featuring exponential backoff, markdown JSON fence stripping, brace-counting extraction, and per-call token telemetry.
  - `resolver.py`: Parses unstructured evidence from messages and bill images, validates target event references, and translates extractions into validated financial actions (`confirm`, `amend`, `cancel`, `add`).
- **`code/finance/`**: Core financial calculations & balance simulation.
  - `recurrence.py`: Detects weekly, biweekly, and monthly recurring transactions, preserving anchor days with a 10-day monthly tolerance window.
  - `simulator.py`: Performs 90-day daily cash-flow simulations, immediately reserves pending debits, calculates 30-day bucketed variable essential reserves, models confirmed salary continuations, and determines immutable safe headroom.
- **`code/models/`**: Domain models & schemas.
  - `domain.py`: Pydantic data classes representing users, financial events, exchange rates, payment options, evidence payloads, candidate schedules, and final decisions.
- **`code/observability/`**: Telemetry & usage tracking.
  - `usage.py`: Real-time token accounting, calculating total and per-request token usage, and automatically writing formatted markdown usage reports.
- **`code/pipeline/`**: Execution orchestration & fault tolerance.
  - `orchestrator.py`: Drives each request through the full lifecycle (loading, evidence resolution, simulation, candidate evaluation, ranking, and validation) with per-request error isolation to prevent batch failures.
- **`code/tests/`**: Automated verification test suite.
  - Contains 27 passing tests across `test_decision.py`, `test_finance.py`, `test_evidence.py`, `test_config_gateway.py`, `test_evaluation.py`, and `test_integration.py`.
- **`code/validation/`**: Guardrails & schema enforcement.
  - `guardrails.py`: Asserts schema compliance, monetary bounds ($0 \le \text{amount\_safe\_to\_pay} \le \text{requested\_amount}$), forward solvency across all plan dates, and provides compliant conservative fallback rows.
- **`code/artifacts/`**: Benchmark artifacts & predictions.
  - Stores local sample evaluation details (`evaluation_details.csv`), benchmark reports (`evaluation_report.md`), output CSVs, and execution summaries.

---

## 4. Deterministic Core vs. LLM Boundary

| Stage | Mechanism | Model Used? | Deterministic? |
|---|---|:---:|:---:|
| **Data Ingestion** | Exact parsing of CSVs into `Decimal` & ISO dates | No | Yes |
| **Evidence Extraction** | Extracts amounts from images, dates/status from messages | **Amazon Nova Pro** via LiteLLM | Gated (LLM) |
| **Fact Validation** | Enforces allowed actions (`confirm`, `amend`, `cancel`, `add`) | No | Yes |
| **Recurrence Detection** | Calendar month, anchor day, weekly/biweekly detection | No | Yes |
| **Variable Reserves** | Historical 90-day debit analysis in 30-day buckets | No | Yes |
| **90-Day Simulation** | Daily cash-flow trajectory and balance projection | No | Yes |
| **Safe Amount** | Headroom calculation: $\min_t B(t) - \text{MinBal}$ | No | Yes |
| **Candidate Generation** | Preference-gated strategy expansion | No | Yes |
| **Spending Recovery** | Bounded $\le 3$ search over flexible, non-protected debits | No | Yes |
| **Lexicographical Rank** | Problem-statement priority ordering | No | Yes |
| **Output Guardrails** | Invariant assertion and schema compliance | No | Yes |

---

## 5. Strict Guardrails & Business Invariants

The pipeline enforces strict invariant checks (`code/validation/guardrails.py`) prior to emitting predictions:

1. **Monetary Bounds**:
   $$0 \le \text{amount\_safe\_to\_pay} \le \text{requested\_amount}$$
2. **Safe Amount Immutability**:
   `amount_safe_to_pay` is calculated once during baseline capacity estimation and permanently frozen. It is never modified by downstream candidate selection or spending recovery.
3. **90-Day Solvency Invariant**:
   $$\forall t \in [0, 90], \quad B(t) \ge \text{minimum\_balance\_to\_keep}$$
   The balance must remain at or above the user's preferred minimum balance after every projected baseline expense and candidate payment.
4. **Conservative Cash Flow**:
   - Pending debits are reserved immediately on `max(request_date, settlement_date)`.
   - Pending credits, tax refunds, bonuses, commissions, and investment gains are excluded until confirmed settled.
5. **Installment Plan Exactness**:
   Custom installment plans are strictly forbidden. Any recommended installment plan must **exactly match** a seller payment option in `request_payment_options.csv` in count, amounts, dates, and total payable.
6. **Partial Payment Two-Payment Contract**:
   Recommended only if permitted by the request and user profile. Must contain **exactly two payments**: `amount_safe_to_pay` on `request_date`, followed by the exact remaining balance on `earliest_date_for_full_payment`.
7. **Spending Change Limitations**:
   - At most 3 changes ($\le 3$).
   - May only target recurring debit events.
   - Categories in `profile.expense_categories_to_protect` cannot be touched.
   - Reduction amounts must satisfy $\text{minimum\_allowed\_amount} \le \text{new\_amount} < \text{original\_amount}$.
8. **Fault-Tolerant Fallback**:
   If an unhandled exception or data resolution failure occurs, the pipeline isolates the failure and emits the contract-compliant conservative fallback row (`amount_safe_to_pay = 0`, `affordability_status = not_affordable`, `recommended_payment_method = not_recommended`, `payment_plan = none`).

---

## 6. Setup and Execution Guide

### 6.1 Prerequisites
- Python 3.11 or higher.
- AWS credentials with Amazon Bedrock access (or other LiteLLM-supported provider).

### 6.2 Environment Configuration
Install required dependencies:
```bash
python -m pip install -r code/requirements.txt
```

Create `code/.env` (or set environment variables in your terminal):
```dotenv
AWS_ACCESS_KEY_ID=your_access_key
AWS_SECRET_ACCESS_KEY=your_secret_key
AWS_REGION_NAME=us-east-1
```
*Note: Credentials in `code/.env` are automatically loaded and kept out of version control.*

### 6.3 Running the Production Pipeline
To evaluate the full 250 evaluation requests in `dataset/requests.csv` and generate `output.csv`:

```bash
python code/main.py --requests dataset/requests.csv --output output.csv --final-run
```

- **Output File**: Written to `output.csv` at the repository root.
- **Model Usage Report**: Written to `code/evaluation/usage_report.md`.
- **Debug Traces** (Optional): Add `--debug` to emit comprehensive per-request audit logs to `artifacts/debug/output/`.

### 6.4 Running the Local Evaluator
To evaluate predictions against the 25 public samples in `dataset/sample_requests.csv`:

```bash
# Step 1: Generate predictions for public samples
python code/main.py --requests dataset/sample_requests.csv --output artifacts/sample_predictions.csv --debug

# Step 2: Run the local evaluator
python code/evaluation/main.py \
  --expected dataset/sample_requests.csv \
  --predictions artifacts/sample_predictions.csv \
  --profiles dataset/financial_profiles.csv \
  --rates dataset/exchange_rates.csv \
  --details artifacts/evaluation_details.csv \
  --report artifacts/evaluation_report.md
```

### 6.5 Running the Test Suite
Run the full 27-test verification suite locally via `pytest`:
```bash
python -m pytest code/tests/ -v
```
Or via Python's built-in `unittest` runner:
```bash
python -m unittest discover -s code/tests -v
```

---

## 7. Output Contract & Schema

The final `output.csv` conforms strictly to the problem statement schema:

| Column | Type | Allowed Values / Format | Description |
|---|---|---|---|
| `request_id` | String | `request_01`, `request_02`, ... | Matches request identifier |
| `amount_safe_to_pay` | Decimal | `0` to `requested_amount` | Safe amount on `request_date` before spending changes |
| `affordability_status` | Enum | `affordable_now`, `affordable_with_plan`, `affordable_later`, `not_affordable` | Overall affordability assessment |
| `recommended_payment_method` | Enum | `full_payment`, `partial_payment`, `installments`, `wait`, `not_recommended` | Best payment strategy according to ranking |
| `payment_plan` | String | `YYYY-MM-DD:amount\|...` or `none` | Chronological schedule of candidate payments |
| `earliest_date_for_full_payment` | Date | `YYYY-MM-DD` or empty string | First projected date safe for 100% full payment |
| `spending_changes_needed` | String | `stop:<id>\|reduce_to:<id>:<amount>` or `none` | Up to 3 legal spending adjustments |
| `decision_explanation` | String | Concise natural language string | Grounded summary of financial rationale |

---

## 8. Token Usage & Observability

All model interactions are routed through `code/evidence/gateway.py`. Every request's token consumption, model identifier, latency, and estimated cost are tracked and summarized into:

```text
code/evaluation/usage_report.md
```

This single file reports:
- Total and average model calls per request.
- Total input and output tokens consumed.
- Per-request average token consumption.
- Estimated total and per-request expenditure.

---

## 9. Documentation Links

Deep-dive technical specifications and subsystem documentation:
- [System Architecture Specification](doc/architecture.md): Full pipeline, data flows, and subsystem interactions.
- [Guardrails & Invariant Validation](doc/guardrails.md): Complete list of business invariants, safety constraints, and fallback isolation.
- [Testing & Verification Strategy](doc/testing.md): Test suites, unit test coverage, and regression benchmarking.
- [Local Evaluator Specification](doc/evaluator.md): Benchmark metrics, confusion matrices, and structural validation checks.

---

## 10. Zero Hardcoding & Evaluability Guarantee

- **No Hardcoded Labels**: The codebase contains zero hardcoded `request_id`, `user_id`, `event_id`, or sample target amounts.
- **Pure Generalization**: All calculations are derived directly from the supplied CSV datasets via normalized mathematical models.
- **Strict Determinism**: Zero stochasticity in financial calculations; all monetary operations utilize Python's `Decimal` type.
- **Terminal Runnable**: The repository contains all required scripts and configurations to run out of the box.

