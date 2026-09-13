# System Architecture — Buy or Wait?

## 1. Architectural Philosophy

The **Buy or Wait?** system is designed around a strict separation of concerns:
- **LLMs / VLMs** are used exclusively at the boundary for **unstructured evidence understanding** (extracting financial facts from user messages and documents/receipts/images).
- **Deterministic Python** owns **100% of financial arithmetic**, multi-period cash flow simulation, capacity calculation, candidate generation, spending recovery, preference enforcement, problem-statement ranking, and guardrails.

```text
               UNSTRUCTURED WORLD (Probabilistic)
               Messages (CSV) & Images (PNG)
                               │
                               ▼
               ┌───────────────────────────────┐
               │    Evidence Resolution Layer  │
               │   LiteLLM Gateway (VLM/LLM)   │
               │  - Structured extraction      │
               │  - Negative constraints       │
               │  - Bounded retries / backoff  │
               └───────────────┬───────────────┘
                               │ Validated Facts (dataclasses)
                               ▼
   ═════════════════════════════════════════════════════════════
               STRUCTURED WORLD (100% Deterministic Python)
                               │
               ┌───────────────▼───────────────┐
               │   Canonical Financial State   │
               │  - Current available balance  │
               │  - Historical recurrence      │
               │  - Settlement date FX rates   │
               │  - Pending debit reserves     │
               └───────────────┬───────────────┘
                               │
               ┌───────────────▼───────────────┐
               │    90-Day Simulation Engine   │
               │  - Chronological daily ledger │
               │  - Variable essential reserve │
               │  - Invariant: B(t) >= MinBal  │
               └───────────────┬───────────────┘
                               │
               ┌───────────────▼───────────────┐
               │   Baseline Capacity Engine    │
               │  - amount_safe_to_pay (FROZEN)│
               │  - earliest_date_for_full_pay │
               └───────────────┬───────────────┘
                               │
               ┌───────────────▼───────────────┐
               │    Candidate Strategy Engine  │
               │  - full_payment               │
               │  - partial_payment            │
               │  - installments (exact match) │
               │  - wait                       │
               └───────────────┬───────────────┘
                               │
               ┌───────────────▼───────────────┐
               │   Spending Recovery Engine    │
               │  - Bounded search (<=3 changes│
               │  - Flexible non-protected deb │
               │  - Exact reduce_to calculation│
               └───────────────┬───────────────┘
                               │
               ┌───────────────▼───────────────┐
               │    Decision & Ranking Engine  │
               │  - Lexicographical ranking    │
               │  - Preference gating          │
               │  - Label assignment           │
               └───────────────┬───────────────┘
                               │
               ┌───────────────▼───────────────┐
               │    Output Guardrail Layer     │
               │  - Schema validation          │
               │  - Invariant verification     │
               │  - Isolated fallback handler  │
               └───────────────┬───────────────┘
                               │
                               ▼
                          output.csv
```

---

## 2. Core Subsystems and Components

### 2.1 Data Ingestion & Models (`code/data/` and `code/models/`)
- **`code/data/loader.py`**:
  - Ingests all participant datasets: `requests.csv`, `financial_profiles.csv`, `financial_events.csv`, `request_payment_options.csv`, `exchange_rates.csv`, `messages.csv`, and `images.csv`.
  - Parses all monetary values into Python `Decimal` objects (avoiding floating-point inaccuracies).
  - Validates dates as `YYYY-MM-DD` and structures events by `user_id` and `request_id`.
  - Builds exact historical currency conversion tables indexed by `(rate_date, from_currency, to_currency)`.
- **`code/models/domain.py`**:
  - Implements strongly-typed dataclasses for every domain entity: `Request`, `Profile`, `FinancialEvent`, `PaymentOption`, `Message`, `ImageRecord`, `Occurrence`, `Candidate`, `SpendingChange`, `FinalDecision`, `CapacityResult`, and `RunSummary`.

### 2.2 Evidence Resolution Layer (`code/evidence/`)
- **`code/evidence/gateway.py`**:
  - Centralized provider-agnostic interface wrapping LiteLLM.
  - Features exponential backoff (`time.sleep(2 ** attempt)`) to smoothly absorb API rate limits.
  - Multi-tiered JSON extraction: strips markdown formatting (` ```json `), and utilizes brace-matching token counters to reliably extract valid JSON payloads even when conversational padding is emitted.
  - Logs per-call trace entries to `artifacts/usage.jsonl` (model, attempt, latency, input tokens, output tokens, total tokens).
- **`code/evidence/resolver.py`**:
  - **Gated Execution**: If a request has no relevant messages or linked images with missing amounts, LLM calls are skipped entirely.
  - **Multimodal Extraction**: When financial events have blank amounts, routes the corresponding receipt/invoice image (`dataset/media/images/<image_id>.png`) to the vision model to extract exact monetary amounts (`fill_event_amount`).
  - **Negative Prompt Constraints**: Strictly instructs the model that provided events are already confirmed transactions and prohibits re-emitting them, preventing token explosion.
  - **Complete Action Schema (`ALLOWED_ACTIONS`)**:
    1. `ignore`: Skip irrelevant or non-actionable evidence.
    2. `fill_event_amount`: Extract missing amounts from bill/invoice images.
    3. `amend_event_amount`: Update transaction values based on confirmed notices.
    4. `amend_event_date`: Reschedule dates. Rescheduled future events automatically transition to `scheduled`.
    5. `cancel_event`: Cancel active subscriptions or scheduled payments.
    6. `set_series_amount`: Adjust recurring series amounts effective from a specified date.
    7. `terminate_series`: End a recurring commitment (e.g., job resignation, lease end).
    8. `add_one_time_event`: Emit confirmed one-time cash flows (e.g., arrears, one-time bonus).
    9. `add_recurring_event`: Introduce a newly confirmed recurring series.
    10. `classify_internal_transfer`: Neutralize self-account transfers to prevent double counting.
    11. `classify_non_cash`: Exclude equity or paper valuation changes from cash flow.
    12. `exclude_unconfirmed_credit`: Zero out unconfirmed speculative credits (lottery, pending bonus).

### 2.3 Financial Simulation & Recurrence (`code/finance/`)
- **`code/finance/recurrence.py`**:
  - Calendar-aware recurrence detection across historical settled events.
  - In historical detection (`_is_next_month`), allows an anchor day shift of up to 10 days between consecutive calendar months to account for payroll date adjustments around weekends and bank holidays.
  - In forward recurrence expansion (`next_date`), advances by exact calendar month and clamps to the month-end (`calendar.monthrange(year, month)[1]`).
  - Detects weekly and biweekly intervals across flexible and fixed debits.
- **`code/finance/simulator.py`**:
  - **Authoritative Opening Snapshot**: `financial_profiles.csv` `current_available_balance` serves as the authoritative starting balance on `request_date`. Historical settled events with `settlement_date <= request_date` are never replayed as cash flow.
  - **Conservative Cash Treatment**:
    - Pending debits are reserved on `max(request_date, settlement_date)`.
    - Pending credits (bonuses, refunds, prize winnings, unrealized investments) are strictly excluded until confirmed.
    - Confirmed recurring salary is projected forward onto settlement dates.
  - **Variable Essential Reserve Policy**: Evaluates settled debit history over the prior 90 days in three 30-day buckets. Calculates conservative reserves for essential categories (groceries, utilities, transport) and distributes them across future 30-day windows.
  - **Deterministic Same-Day Ordering**:
    1. Confirmed incoming credits settling on day $t$.
    2. Protected fixed debits on day $t$.
    3. Flexible baseline debits on day $t$.
    4. Candidate purchase payment on day $t$.
  - **Baseline Capacity & Amount Safe**:
    $$\text{Headroom} = \min_{t \in [0, 90]} B(t) - \text{minimum\_balance\_to\_keep}$$
    $$\text{amount\_safe\_to\_pay} = \min(\text{requested\_amount}, \max(0, \text{Headroom}))$$
    Once calculated, `amount_safe_to_pay` is **permanently frozen**.
  - **Earliest Full Safe Date**: Scans each day $d$ in $[0, 90]$ to find the earliest date where paying 100% of `requested_amount` preserves $B(t) \ge \text{minimum\_balance\_to\_keep}$ for all remaining days.

### 2.4 Candidate Generation & Decision Engine (`code/decision/`)
- **`code/decision/engine.py`**:
  - **Preference Gating**: Enforces `payment_methods_user_will_consider` and `max_installment_months`. Closed payment methods are never generated.
  - **Strategy Generators**:
    - `full_payment`: Exactly 1 payment on `request_date` equal to `requested_amount`.
    - `partial_payment`: Requires `allows_partial_payment == true`, $0 < \text{amount\_safe\_to\_pay} < \text{requested\_amount}$, and $\text{earliest\_date\_for\_full\_payment} \le \text{desired\_completion\_date}$. Creates exactly two payments: `amount_safe_to_pay` on `request_date`, and the remainder on `earliest_date_for_full_payment`.
    - `installments`: Evaluates all provided options in `request_payment_options.csv`. Never invents custom plans.
    - `wait`: 1 payment of `requested_amount` on `earliest_date_for_full_payment` (requires full payment acceptance and completion on or before deadline).
  - **90-Day Counterfactual Overlay**: Every candidate plan is overlaid onto the baseline cash flow stream and simulated day-by-day.
  - **Spending Change Recovery**:
    - Triggered only if no zero-change candidate is safe.
    - Bounded search evaluating at most 3 spending changes.
    - Targets only flexible, non-protected debit events in categories the user permits (`expense_categories_user_is_willing_to_stop` and `expense_categories_user_is_willing_to_reduce`).
    - Solves `reduce_to` floors mathematically without guessing, enforcing `minimum_allowed_amount`.
  - **Lexicographical Ranking**:
    1. Complete full request by `desired_completion_date`.
    2. Require no spending changes.
    3. Minimize total amount paid.
    4. Start payment earlier.
    5. Use fewer payments.
    6. Tie-breaker: lowest `payment_option_id`.

### 2.5 Validation & Guardrails (`code/validation/`)
- **`code/validation/guardrails.py`**:
  - Inspects every proposed decision against problem statement rules before emission.
  - Re-verifies monetary bounds, chronological ordering, schedule exactness, and category protection.
  - Provides a terminal conservative fallback row (`amount_safe_to_pay = 0`, `affordability_status = not_affordable`, `recommended_payment_method = not_recommended`, `payment_plan = none`, `earliest_date_for_full_payment = ""`, `spending_changes_needed = none`) if operational or data exceptions occur.

### 2.6 Observability & Accounting (`code/observability/`)
- **`code/observability/usage.py`**:
  - Collects all LLM invocation records from `gateway.records`.
  - Aggregates input tokens, output tokens, total tokens, and calls by provider and call type.
  - Outputs the mandatory `evaluation/usage_report.md` summarizing model providers, model names, call counts, input/output tokens, per-request token averages, and estimated expenditure.
