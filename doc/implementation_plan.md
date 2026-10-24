# AI Deletion Audit Agent: Phased Implementation Plan

## Overview
This implementation plan outlines the sequential phases to build, verify, and evaluate the multi-agent system without jumping ahead. Each phase has concrete deliverables and acceptance criteria.

---

## Phase 0: Project Scaffolding & Configuration Setup
* **Goal:** Establish code structure, dependency definitions, configuration schemas, and environment secrets management.
* **Deliverables:**
  1. `code/config/config.yaml`: Central configuration for model endpoints, empirical threshold settings, dataset paths, and cache paths.
  2. `code/.env`: Local secrets file (API keys, credentials) with an uncommitted `.env.example` template.
  3. `code/requirements.txt`: Python package requirements (`pyyaml`, `pydantic`, `pandas`, `pypdf`, `python-dotenv`).
* **Acceptance Criteria:**
  - Configuration loads dynamically without hardcoded constants.
  - Secrets are read exclusively from environment variables.

---

## Phase 1: Logging Agent (Identity Tracker)
* **Goal:** Build and test historical identity reconstruction up to `audit_at`.
* **Deliverables:**
  1. `code/src/logging_agent/tracker.py`:
     - Case-insensitive email normalization.
     - Lookups in `dataset/user_identities.csv`.
     - Historical backtracking in `dataset/user_audit_log.csv`.
     - Strict cutoff: `event_time <= audit_at`.
  2. `code/guardrails/identity_guardrail.py`:
     - Asserts `user_id` presence, no post-cutoff timestamps, non-empty search terms.
  3. `code/tests/test_logging_agent.py`:
     - Unit test verifying resolution of historical email `mateo.rios@outlook.com` (user_02).
* **Acceptance Criteria:**
  - 100% of the 32 sample cases and 518 evaluation cases resolve to a valid `user_id`.

---

## Phase 2: Audit Agent & Lazy Multimodal Cache
* **Goal:** Build the verification scanner and on-demand evidence cache.
* **Deliverables:**
  1. `code/src/audit_agent/scanner.py`:
     - SQLite in-memory executor for 24 `.sql` snapshots.
     - Fast log and JSON parser for user identifiers.
     - `system_activity.csv` scanner for `CHECK_DATA_FLOW` and `CHECK_RESTORE_ACCESS`.
     - Policy engine mapping resources to `dataset/deletion_rules.csv`.
  2. `code/src/audit_agent/multimodal_cache.py`:
     - **Lazy on-demand caching:** Checks cache by `file_id`; extracts on miss, stores to disk, reuses on hit.
     - Direct text stream extraction for the 4 PDFs.
  3. `code/guardrails/audit_guardrail.py`:
     - Confirms all cited evidence IDs exist in manifests.
  4. `code/tests/test_audit_agent.py`:
     - Unit test for residual account finding (`case_05`), active flow (`case_15`), restore risk (`case_14`).
* **Acceptance Criteria:**
  - Accurately discovers remaining data, unredacted PII in tombstones, and active pipelines.

---

## Phase 3: Step-JSON Agent & JEV Formatter
* **Goal:** Implement the RFC 8259 JSON serializer with strict sorting and step renumbering.
* **Deliverables:**
  1. `code/src/step_json_agent/builder.py`:
     - Handles `COMPLETE` (verification only with evidence) vs `INCOMPLETE` (findings, remediations, verifications).
     - Phase ordering: `FINDING` $\rightarrow$ `REMEDIATION` $\rightarrow$ `VERIFICATION`.
     - Canonical operation priority sorting table.
     - Tie-breaking: `system_id` ascending, `resource_id` ascending.
     - Continuous 1..N renumbering.
  2. `code/guardrails/jev_schema_guardrail.py`:
     - Validates JSON parseability, continuous step numbers, valid operation enums, and empty strings for future remediations.
  3. `code/tests/test_step_json_agent.py`:
     - Shuffled step sorting test.
* **Acceptance Criteria:**
  - Exactly replicates ground truth array ordering for all 32 sample outputs.

---

## Phase 4: Orchestrator Agent & Retry Controller
* **Goal:** Wire the master orchestrator with TypeSafe AI Jev and retry loops.
* **Deliverables:**
  1. `code/src/orchestrator/controller.py`:
     - Iterates cases sequentially.
     - Integrates TypeSafe AI Jev for intent classification.
     - Calls Logging Agent $\rightarrow$ Audit Agent $\rightarrow$ Step-JSON Agent.
     - Intercepts guardrail errors and invokes retry loops (max 3 attempts).
  2. `code/main.py`:
     - CLI entry point running the full pipeline and writing root `output.csv`.
* **Acceptance Criteria:**
  - Runs cleanly from terminal; handles non-deletion requests as `NOT_APPLICABLE` with `[]`.

---

## Phase 5: Evaluation Framework & Threshold Tuning
* **Goal:** Build the benchmark evaluator and execute the empirical threshold grid search.
* **Deliverables:**
  1. `code/evaluation/main.py`:
     - Evaluates predictions against `dataset/sample_output.csv`.
     - Computes Case Status Accuracy, Step Precision/Recall/F1, Field Accuracy, and Sequence Accuracy.
  2. `code/evaluation/evaluation_logger.py`:
     - Logs each evaluation run (timestamp, threshold, metrics, token counts) to `code/evaluation/evaluation_history.jsonl`.
  3. Grid search over $[0.50, 0.70, 0.80, 0.85, 0.90, 0.95]$ with documented comparison ledger.
* **Acceptance Criteria:**
  - Achieves optimal balanced F1 on the 32 sample benchmark cases.

---

## Phase 6: Full Dataset Inference & Packaging
* **Goal:** Generate root `output.csv` (518 cases) and prepare submission reports.
* **Deliverables:**
  1. Final root `output.csv` (exactly 518 data rows sorted by `case_id`).
  2. `code/evaluation/evaluation_report.md` (metrics, 3 custom cases, failures & fixes).
  3. `code/evaluation/usage_report.md` (model breakdown, token counts, total & per-case cost).
* **Acceptance Criteria:**
  - Passes validation scripts; adheres to submission package requirements.
