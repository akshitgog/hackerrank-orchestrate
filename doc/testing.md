# AI Deletion Audit Agent: Testing & Verification Strategy

## 1. Testing Philosophy
Testing is divided into three isolated tiers:
1. **Isolated Sub-Agent Unit Tests:** Verifying that individual sub-agents behave deterministically without relying on other agents.
2. **Guardrail & Retry Verification:** Verifying that malformed outputs trigger self-correction up to 3 retries and fallback gracefully.
3. **End-to-End Benchmark Evaluation:** Measuring whole-pipeline accuracy against `dataset/sample_output.csv` (32 cases) across all 5 evaluation dimensions.

---

## 2. Unit Testing Suite (`code/tests/`)

### Test 1: Logging Agent (`test_logging_agent.py`)
* **Test Case A (Current Email Match):**
  - Input: `amina.elmasri@gmail.com`
  - Expected: Resolves `user_01`, finds current phone and email hash.
* **Test Case B (Historical Email Backtracking):**
  - Input: `mateo.rios@outlook.com` (from `sample_deletion_requests.csv` case_02)
  - Expected: Backtracks through `user_audit_log.csv` to resolve `user_02`, recovering old email, old phone, and old email hashes.
* **Test Case C (Timestamp Cutoff Enforcement):**
  - Input: User with audit events before and after `audit_at`.
  - Expected: Events strictly $> \text{audit\_at}$ are discarded.

### Test 2: Audit Agent (`test_audit_agent.py`)
* **Test Case A (Residual Record in Database Replica):**
  - Input: `case_05` identity profile.
  - Expected: Flags `REPORT_REMAINING_RECORD` on `account_005` with `evidence_id = evidence_54`.
* **Test Case B (Active Sync Job):**
  - Input: `case_15` identity profile.
  - Expected: Flags `REPORT_ACTIVE_DATA_FLOW` on `data_flow_9846`.
* **Test Case C (Unblocked Restore Risk):**
  - Input: `case_14` identity profile.
  - Expected: Flags `REPORT_RESTORE_RISK` on `backup_3870`.
* **Test Case D (Policy Tombstone Check):**
  - Input: `case_31` vs `case_32`.
  - Expected: `case_31` (tombstone with redacted PII) is compliant; `case_32` (tombstone with exposed PII) flags `REPORT_EXPOSED_PII`.

### Test 3: Lazy Multimodal Cache (`test_multimodal_cache.py`)
* **Test Case A (Cache Miss & Extraction):**
  - Requests `evidence_18.pdf` when cache is empty.
  - Expected: Reads text stream via `pypdf`, writes structured JSON to cache, returns extracted data.
* **Test Case B (Cache Hit):**
  - Requests `evidence_18.pdf` a second time.
  - Expected: Loads from disk cache in $<1$ ms with 0 tokens spent.

### Test 4: Step-JSON Agent (`test_step_json_agent.py`)
* **Test Case A (Sorting & Numbering):**
  - Passes intentionally shuffled list of findings, remediations, and verifications.
  - Expected: Outputs array sorted strictly by Phase $\rightarrow$ Operation Priority $\rightarrow$ System ID $\rightarrow$ Resource ID, with sequential step numbers $1..N$.
* **Test Case B (Evidence ID Rule):**
  - Expected: Findings have non-empty `evidence_id`; remediations and future verifications have `evidence_id = ""`.

---

## 3. Evaluation Benchmark Suite (`code/evaluation/main.py`)

The evaluation script runs the entire pipeline against `dataset/sample_deletion_requests.csv` and grades predictions against `dataset/sample_output.csv`.

### Metric 1: Case-Level Deletion Status Accuracy
$$\text{Accuracy} = \frac{\sum_{i=1}^{32} \mathbb{I}(\hat{y}_i == y_i)}{32}$$

### Metric 2: Step-Level Precision, Recall, and F1
* Matching criteria: exact match on `(phase, system_id, resource_id, operation, state)`.
* Precision: $\frac{|\text{Matches}|}{|\text{Predicted Steps}|}$
* Recall: $\frac{|\text{Matches}|}{|\text{Ground Truth Steps}|}$
* F1 Score: $2 \times \frac{\text{Precision} \times \text{Recall}}{\text{Precision} + \text{Recall}}$

### Metric 3: Sequence & Array-Order Accuracy
* Confirms that array order matches ground truth. Evaluates whether the sorting engine broke ties correctly.

### Metric 4: Evidence Citation Accuracy
* Confirms that cited `file_id`, `activity_id`, or `audit_id` matches the canonical ground truth evidence.

---

## 4. Empirical Threshold Search & Comparison Ledger

The evaluation framework automatically runs the grid sweep across $\tau \in [0.50, 0.70, 0.80, 0.85, 0.90, 0.95]$ and writes the ledger to `code/evaluation/threshold_comparison.json`:

```json
{
  "threshold_sweep_results": [
    {"threshold": 0.50, "accuracy": 0.937, "precision": 0.912, "recall": 1.000, "f1": 0.954},
    {"threshold": 0.70, "accuracy": 0.968, "precision": 0.968, "recall": 1.000, "f1": 0.984},
    {"threshold": 0.80, "accuracy": 1.000, "precision": 1.000, "recall": 1.000, "f1": 1.000},
    {"threshold": 0.85, "accuracy": 0.968, "precision": 1.000, "recall": 0.968, "f1": 0.984},
    {"threshold": 0.90, "accuracy": 0.937, "precision": 1.000, "recall": 0.937, "f1": 0.967},
    {"threshold": 0.95, "accuracy": 0.875, "precision": 1.000, "recall": 0.875, "f1": 0.933}
  ],
  "optimal_threshold": 0.80
}
```
Every run is logged persistently to `code/evaluation/evaluation_history.jsonl` with timestamp, git commit, and execution time.
