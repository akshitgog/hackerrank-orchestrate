# AI Deletion Audit Agent: Testing and Verification Strategy

## 1. Testing goals

Tests protect four outcomes:

1. **Identity correctness** — current and historical identifiers resolve without post-cutoff leakage.
2. **Evidence correctness** — findings and proofs are tied to admissible, resource-local evidence.
3. **Plan correctness** — policy treatment, operation ordering, and step numbering match the output contract.
4. **Pipeline correctness** — sample and whole-dataset runs produce parseable, complete output.

Tests are divided into focused unit tests, guardrail tests, sample evaluation, and whole-run validation. Run the smallest relevant layer first.

## 2. Fast verification commands

From the repository root:

```powershell
# Production unit and guardrail tests
python -m pytest code/tests -q

# Syntax check for production modules
python -m py_compile code/main.py code/src/audit_agent/scanner.py code/src/audit_agent/attribution.py code/src/logging_agent/tracker.py code/src/step_json_agent/builder.py

# Generate one deterministic sample prediction file
python code/main.py --sample --no-llm --threshold 0.65 --output sample_predictions.csv

# Score that exact saved run without rerunning the pipeline
python code/evaluation/main.py --pred sample_predictions.csv --threshold 0.65 --no-llm

# Run every configured threshold and package the best whole-dataset result
python code/evaluation/run_threshold_grid.py --clear-cache --run-whole

# Whole-dataset execution
python code/main.py --whole
```

The sample evaluator writes history entries. Run it deliberately when that side effect is wanted.

## 3. Unit test coverage

### 3.1 Identity tracker

File: `code/tests/test_logging_agent.py`

Coverage includes:

- current email resolution;
- historical email backtracking;
- case and whitespace normalization;
- strict `event_time <= audit_at` filtering;
- identity guardrail rejection of missing or invalid profiles;
- resolution of all sample and whole-dataset request rows.

Important boundary: a historical value occurring after `audit_at` must not be searchable for that audit.

### 3.2 Normalization

File: `code/tests/test_normalizer.py`

Coverage includes composed/decomposed Unicode, accent stripping, and generation of accented/unaccented name variants. These tests protect evidence matching for international names.

### 3.3 Audit scanner

File: `code/tests/test_audit_agent.py`

Coverage includes:

- lazy PDF cache miss and hit;
- residual account records in SQL replicas;
- active connector flow detection;
- restore-risk detection;
- clean-case verification output;
- audit guardrail validation.

When changing the scanner, add a fixture for the specific evidence shape being fixed: JSON key/value logs, line timestamps, inner snapshot timestamps, tombstones, backup catalogs, or connector configurations.

### 3.4 Step JSON

File: `code/tests/test_step_json_agent.py`

Coverage includes:

- empty `NOT_APPLICABLE` output;
- complete cases containing only evidence-backed verifications;
- incomplete cases ordered by phase;
- remediation dependency order;
- blank evidence IDs for proposed remediations and future verifications;
- consecutive step numbering and schema guardrail validation.

## 4. Sample evaluation

`code/evaluation/main.py --pred` compares a saved pipeline result with:

- requests: `dataset/sample_deletion_requests.csv`;
- truth: `dataset/sample_output.csv`.

It reports:

### Status accuracy

```text
correct deletion statuses / total cases
```

### Step precision, recall, and F1

Step matching uses `(phase, system_id, resource_id)` as the pairing key, then compares operation and state fields. Evidence grounding is measured separately because an otherwise correct step can cite the wrong file.

```text
precision = matched_steps / predicted_steps
recall    = matched_steps / gold_steps
F1        = 2 * precision * recall / (precision + recall)
```

### Field accuracy

The evaluator compares `phase`, `system_id`, `resource_id`, `operation`, and `state` for matched steps.

### Sequence accuracy

The evaluator checks consecutive `step_no` values and nondecreasing phase order. Exact canonical array order should also be checked when investigating a benchmark mismatch.

### Evidence grounding

Findings and complete-case verifications require non-empty evidence IDs. Incomplete-case remediation and future verification steps require empty evidence IDs.

## 5. Threshold experiments

The evaluator supports one saved prediction file or a direct legacy pipeline run:

```powershell
python code/main.py --sample --no-llm --threshold 0.65 --output sample_predictions.csv
python code/evaluation/main.py --pred sample_predictions.csv --threshold 0.65 --no-llm
```

For threshold selection, use the production sweep:

```powershell
python code/evaluation/run_threshold_grid.py --clear-cache --run-whole
```

The sweep runs the real pipeline once for each value in
`thresholds.grid_search_candidates`, saves every prediction under
`evaluation/threshold_runs/`, evaluates each saved file, writes all measured rows to
`evaluation/evaluation_report.md`, and records machine-readable results in
`evaluation/threshold_grid_history.jsonl`. The selected sample prediction is copied to
root `sample_predictions.csv`.

Threshold ranking is status accuracy, then step F1, then full-case exact matches including
evidence IDs, then evidence grounding. The configured `0.65` is kept only when it ties for
the best measured result; otherwise the report names the measured winner.

## 6. Whole-dataset validation

After `python code/main.py --whole` or the threshold-grid `--run-whole` packaging step,
validate:

1. `output.csv` exists at the workspace root.
2. It has exactly the expected columns.
3. It has one row per `dataset/deletion_requests.csv` row.
4. Rows are sorted by `case_id`.
5. Every `steps_json` value parses as a JSON array.
6. `NOT_APPLICABLE` rows contain `[]`.
7. Every step has required fields and consecutive numbering.
8. Every operation/state/phase combination is allowed by `problem_statement.md`.

A lightweight validation can be run with:

```powershell
python -c "import json,pandas as pd; o=pd.read_csv('output.csv'); print(len(o), o.columns.tolist()); [json.loads(x) for x in o.steps_json]; print('JSON OK')"
```

## 7. Regression workflow for scanner changes

When changing parsing, ownership, timestamps, or policy:

1. Run the affected unit test file.
2. Run `python -m pytest code/tests -q`.
3. Run the deterministic sample evaluator.
4. Compare status, step F1, field accuracy, sequence accuracy, and evidence grounding with the prior recorded run.
5. Inspect mismatched cases by resource and evidence, not by adding a case-specific branch.

## 8. Failure diagnosis

| Symptom | First check |
|---|---|
| Identity unresolved | Normalized current email, historical email rows, and `audit_at` cutoff. |
| False residual finding | Evidence capture time, inner observation time, and whether the record is resource-local. |
| Missing active-flow finding | `system_activity.csv`, log trace correlation, and `enabled`/`CHECK_DATA_FLOW` markers. |
| Wrong tombstone action | `ACCOUNT_TOMBSTONE` rule and presence of direct PII fields. |
| Wrong step order | `StepJsonBuilder` priority maps and duplicate resource keys. |
| Empty complete-case proof | Admissible manifest evidence and inferred verification fallback. |
| Cache inconsistency | `file_id`, source path, capture time, and cached extraction schema. |

## 9. Known repository test boundary

The `cache/` directory contains exploratory and historical diagnostic scripts. They are useful during investigation but are not the production test suite and may depend on local helper state. Use `code/tests` for the maintained regression suite; report unrelated exploratory-test collection failures separately.
