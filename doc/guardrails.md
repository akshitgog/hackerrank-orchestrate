# Guardrails & Invariant Validation — Buy or Wait?

## 1. Overview

In the **Buy or Wait?** system, guardrails form an independent defensive layer completely decoupled from candidate generation and decision logic. 

While the Decision Engine determines *what to choose*, the Guardrail Layer (`code/validation/guardrails.py`) enforces *what is legally and financially permissible*. Every candidate and final decision must pass all guardrails before being written to `output.csv`. Any violation raises `GuardrailError` and is caught by the operational fallback handler.

---

## 2. Invariants Enforced by Layer

### 2.1 Input Data Invariants
- **Schema Conformity**: Verified by `code/data/loader.py`. All amounts must parse into finite `Decimal` objects. Dates must follow ISO-8601 (`YYYY-MM-DD`).
- **Currency Completeness**: Foreign cash flows require exact matching rows in `dataset/exchange_rates.csv` corresponding to the event's `settlement_date` and direction (`event.currency -> profile.home_currency`). No live or synthetic rates are permitted.
- **Snapshot Integrity**: The user's opening balance is taken exclusively from `financial_profiles.csv` `current_available_balance`. Historical settled events on or before `request_date` are never replayed as cash flow.

### 2.2 LLM & Evidence Invariants
- **Non-Hallucination of Transactions**:
  - The model can only reference existing `event_id` strings or emit derived events backed by source evidence (e.g. arrears mentioned in message).
  - Negative prompt constraints prohibit the model from re-emitting existing events as new occurrences.
- **Strict Fact Actions**:
  - Only allowed actions are permitted: `confirm_event`, `amend_event_amount`, `amend_event_date`, `cancel_event`, `add_one_time_event`.
  - Future dates on rescheduled events automatically transition status from settled to `scheduled`.
  - Unknown target event IDs in message resolution are safely filtered without pipeline termination.

### 2.3 Financial Simulation & Capacity Invariants
- **Minimum Balance Invariant**:
  $$\forall t \in [0, 90], \quad B(t) \ge \text{minimum\_balance\_to\_keep}$$
  The balance cannot dip below the user's safety threshold after any scheduled debit, recurring expense, essential reserve, or candidate payment.
- **Credit Conservatism**:
  - Pending debits are reserved on `max(request_date, settlement_date)`.
  - Pending credits, lottery winnings, tax refunds, bonuses, and unrealized investment gains are strictly zeroed out until confirmed settled.
- **Amount Safe to Pay Invariant**:
  $$0 \le \text{amount\_safe\_to\_pay} \le \text{requested\_amount}$$
  Computed as $\min(\text{requested\_amount}, \max(0, \min_{t} B(t) - \text{minimum\_balance}))$.
- **Immutability (Freeze Rule)**:
  Once calculated in the baseline capacity engine, `amount_safe_to_pay` is permanently frozen. Downstream recommendation modules, candidate simulations, and spending changes are forbidden from modifying this value.

### 2.4 Candidate Strategy Invariants
Every payment strategy must conform to explicit problem-statement constraints:

#### Full Payment
- Requires the user profile to include `full_payment` in `payment_methods_user_will_consider`.
- Payment plan must consist of exactly 1 payment on `request_date` equal to `requested_amount`.

#### Partial Payment
- Allowed only if:
  1. `request.allows_partial_payment == True`
  2. Profile includes `partial_payment` in accepted payment methods.
  3. $0 < \text{amount\_safe\_to\_pay} < \text{requested\_amount}$.
  4. `earliest_date_for_full_payment` exists and is $\le \text{desired\_completion\_date}$.
- The plan must have **exactly two payments**:
  - Payment 1: `amount_safe_to_pay` on `request_date`.
  - Payment 2: `requested_amount - amount_safe_to_pay` on `earliest_date_for_full_payment`.
  - Sum of payments must equal `requested_amount`.

#### Installments
- Allowed only if `installments` is in `payment_methods_user_will_consider`.
- **Zero Hallucination Rule**: Custom installment schedules are strictly prohibited.
- Schedule dates, payment counts, periodic amounts, and total payable must **exactly match** a supplied option in `request_payment_options.csv`.
- Schedule duration must not exceed `profile.max_installment_months`.
- Final payment date must be $\le \text{desired\_completion\_date}$.

#### Wait
- Requires user to accept `full_payment`.
- Plan must consist of exactly 1 payment of `requested_amount` on `earliest_date_for_full_payment`.
- `earliest_date_for_full_payment` must be strictly $> \text{request\_date}$ and $\le \text{desired\_completion\_date}$.

#### Not Recommended
- Used when no candidate completes safely within deadlines and preferences.
- Plan must be `none`.
- `affordability_status` must be `not_affordable`.

### 2.5 Spending Change Recovery Invariants
- **Count Bound**: Maximum of 3 spending changes per request ($\le 3$).
- **Eligible Events Only**:
  - Must exist and belong to the request `user_id`.
  - Must be a `debit` event.
  - Category must **not** be in `profile.expense_categories_to_protect`.
- **Action Legality**:
  - `stop`: Permitted only if category is in `profile.expense_categories_user_is_willing_to_stop` AND event flexibility is `stoppable` or `reducible_or_stoppable`.
  - `reduce_to`: Permitted only if category is in `profile.expense_categories_user_is_willing_to_reduce` AND event flexibility is `reducible` or `reducible_or_stoppable`.
- **Reduction Value Bounds**:
  $$\text{minimum\_allowed\_amount} \le \text{new\_amount} < \text{original\_amount}$$
- **Disjoint Actions**: The same event cannot be both stopped and reduced.

### 2.6 Cross-Field Semantic Consistency
| Affordability Status | Allowed Methods | Earliest Date for Full Payment | Payment Plan |
|---|---|---|---|
| `affordable_now` | `full_payment` | Must equal `request_date` | 1 payment on `request_date` |
| `affordable_with_plan` | `full_payment`, `partial_payment`, `installments` | Safe full payment date or empty | 2 payments (partial) or option plan (installments) |
| `affordable_later` | `wait` | Date $> \text{request\_date}$ | 1 payment on earliest date |
| `not_affordable` | `not_recommended` | Date or empty | `none` |

---

## 3. Terminal Fault-Tolerant Fallback

If an unhandled exception or data resolution failure occurs for any request, the pipeline isolates the failure and emits the contract-compliant conservative fallback row:

```text
request_id                     = <request_id>
amount_safe_to_pay             = 0
affordability_status           = not_affordable
recommended_payment_method     = not_recommended
payment_plan                   = none
earliest_date_for_full_payment = 
spending_changes_needed        = none
decision_explanation           = Unable to verify financial safety because required data could not be resolved.
```

This ensures:
1. One malformed row never crashes a 250-request batch run.
2. The output CSV remains structurally complete with 100% valid rows.
3. Zero financial risk: default stance is not to recommend purchases when financial facts cannot be verified.
