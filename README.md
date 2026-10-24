# HackerRank Orchestrate - October 2026

## Ghost Data Still Exists: AI Deletion-Audit Multi-Agent System

This repository contains the production implementation of the **Ghost Data Still Exists** deletion-audit agent for the HackerRank Orchestrate challenge. 

A deletion workflow may claim **Complete** while personal data remains in databases, read/reporting replicas, logs, support attachments, exports, search indexes, analytics profiles, or backups. Active synchronization and restore processes can also recreate data that was deleted from its original source. This system independently audits all participant-visible evidence at each case's `audit_at` cutoff, establishes true resource states, and generates fully grounded, policy-compliant remediation plans.

---

## 1. System Architecture

The solution uses a modular, decoupled multi-agent architecture:

```
                                  [ Incoming Request ]
                                           │
                                           ▼
                       ┌───────────────────────────────────────┐
                       │   Stage 1: Intent Classifier (Triage) │
                       │  • Multilingual (6 languages)         │
                       │  • Local DeBERTa NLI Intent Triage    │
                       │  • Non-deletion guard (SAR/Export)    │
                       └───────────────────┬───────────────────┘
                                           │ (Authorized Deletion)
                                           ▼
                       ┌───────────────────────────────────────┐
                       │   Stage 2: Logging Agent (Identity)   │
                       │  • NFC Canonical Normalization        │
                       │  • Accent Stripping & Alias Expansion │
                       │  • Temporal Identity Profile (<=Cutoff)│
                       └───────────────────┬───────────────────┘
                                           │
                                           ▼
                       ┌───────────────────────────────────────┐
                       │   Stage 3: Audit Agent (Deep Evidence)│
                       │  • In-Memory SQLite Unicode Engine    │
                       │  • 28 JSON Snapshot/Bundle Scanners   │
                       │  • System Activity & Log Analyzers    │
                       │  • Canonical Multimodal Perceptual    │
                       │    Decoupling (11 PNGs + 4 PDFs)      │
                       │  • Temporal Cutoff (>= requested_at)  │
                       └───────────────────┬───────────────────┘
                                           │
                                           ▼
                       ┌───────────────────────────────────────┐
                       │   Stage 4: Step-JSON Agent (Planner)  │
                       │  • Dependency-First Remediation Graph │
                       │  • Flow/Restore Disable -> Record Del │
                       │  • Downstream -> Upstream Order       │
                       │  • RFC 8259 English Schema Serializer │
                       └───────────────────┬───────────────────┘
                                           │
                                           ▼
                       ┌───────────────────────────────────────┐
                       │   Stage 5: Deterministic Guardrails   │
                       │  • Intent Guardrail                   │
                       │  • Identity Grounding Guardrail       │
                       │  • Temporal Boundary Guardrail        │
                       │  • Step-JSON Schema & Sequence Check  │
                       └───────────────────┬───────────────────┘
                                           │
                                           ▼
                                    [ output.csv ]
```

### Core Agents

1. **Intent Classifier (`code/src/orchestrator/classifier.py`)**:
   - Evaluates incoming request texts in English, Portuguese, Korean, Spanish, Japanese, and French.
   - Detects non-deletion actions (Subject Access Requests, data export, marketing opt-outs) and routes them directly to `NOT_APPLICABLE` with `steps_json = []`.
   - Uses zero-shot NLI (`local/mDeBERTa-v3-base-xnli` on local GPU with robust fallback) at calibrated confidence threshold `0.50`–`0.65`.

2. **Logging Agent (`code/src/logging_agent/`)**:
   - `normalizer.py`: Enforces NFC canonical composition and accent stripping (`Sofía Fernández` $\rightarrow$ `sofia fernandez`), resolving cross-system diacritical encoding discrepancies.
   - `tracker.py`: Reconstructs complete identity profiles (`user_id`, historical emails, email hashes, phones, address variants) up to `audit_at` from `user_identities.csv` and `user_audit_log.csv`.

3. **Audit Agent (`code/src/audit_agent/`)**:
   - `db.py`: Executes in-memory SQLite queries over 24 SQL database snapshots with custom `UNICODE_LOWER` and `STRIP_ACCENTS` scalar functions.
   - `scanner.py`: Performs deep parsing of 28 JSON evidence bundles/exports (search indexes, analytics profiles, support tickets, exports), system activity streams, and access logs.
   - `multimodal_cache.py`: Canonical multimodal perceptual decoupling. Uses Fireworks GLM-5 VLM and `pypdf` to objectively extract visual evidence (11 console screenshots, 4 PDF reports) into case-agnostic structured JSON (`cache/multimodal_cache.json`), eliminating cross-case prompt hallucination and ensuring zero cloud tokens during audits.
   - **Temporal Boundary Filter:** Enforces `captured_at >= requested_at` for residual findings to distinguish un-deleted data from pre-request historical snapshots.

4. **Step-JSON Agent (`code/src/step_json_agent/builder.py`)**:
   - Synthesizes findings and constructs dependency-ordered remediation plans (`FINDING` $\rightarrow$ `REMEDIATION` $\rightarrow$ `VERIFICATION`).
   - Ensures data flows and restores are disabled/blocked before dependent records are modified.
   - Handles `ACCOUNT_TOMBSTONE` preservation and anonymization per `deletion_rules.csv`.
   - Numbered 1..N consecutively with empty `evidence_id` for future actions and exact citations for findings/complete verifications.

5. **Guardrail Suite (`code/guardrails/`)**:
   - Four deterministic validators (`intent_guardrail.py`, `identity_guardrail.py`, `audit_guardrail.py`, `jev_schema_guardrail.py`) verifying schema, foreign key citations, and step consistency.

---

## 2. Setup & Installation

### Prerequisites
- Python 3.10+ (tested on Python 3.13)
- Windows PowerShell, macOS, or Linux terminal

### Environment Setup

```bash
# 1. Clone repository
git clone https://github.com/interviewstreet/hackerrank-orchestrate-october26.git
cd hackerrank-orchestrate-october26

# 2. Create and activate virtual environment
python -m venv .venv
# Windows (PowerShell):
.venv\Scripts\Activate.ps1
# macOS / Linux:
source .venv/bin/activate

# 3. Install dependencies
pip install -r code/requirements.txt

# 4. Optional: Configure environment variables
# Copy .env.example to code/.env if using custom LLM/VLM APIs
cp code/.env.example code/.env
```

---

## 3. Running the Pipeline

### Mode A: Full Production Run (518 Cases)
Executes the audit agent across the full evaluation dataset (`dataset/deletion_requests.csv`), validates all guardrails, generates the root submission `output.csv`, and records token telemetry to `evaluation/usage_report.md`:

```bash
python code/main.py --whole
```

### Mode B: Sample Evaluation Run (32 Cases)
Runs the audit pipeline on `dataset/sample_deletion_requests.csv` and validates against `dataset/sample_output.csv`:

```bash
python code/main.py --sample
```

### Mode C: Threshold Grid Search & Evaluation Benchmark
Runs automated parameter grid search across candidate thresholds `[0.50, 0.60, 0.65, 0.70, 0.80, 0.85, 0.90, 0.95]`, evaluates status, step F1, and sequence accuracy, tests 3 custom cases, and outputs `evaluation/evaluation_report.md`:

```bash
python code/evaluation/main.py
```

### Mode D: Unit Test Suite
Executes the complete test suite verifying normalizer, logging agent, audit scanner, step-json builder, and intent classifier:

```bash
python -m unittest discover -s code/tests -p "test_*.py"
```

---

## 4. Evaluation & Reports

Per challenge contract §6.8, all evaluation metrics and telemetry are persisted directly in Markdown:

1. **`evaluation/evaluation_report.md`** (also mirrored in `code/evaluation/evaluation_report.md`):
   - **Case-Level Deletion-Status Accuracy:** 100.0% (32/32 sample cases)
   - **Field-Level Accuracy:** 99.0%
   - **Sequence Accuracy:** 100.0% (`FINDING` $\rightarrow$ `REMEDIATION` $\rightarrow$ `VERIFICATION`)
   - **Evidence Grounding:** 100.0%
   - **Threshold Exploration History:** Complete grid search table across 8 candidate thresholds.
   - **Custom Evaluation Test Cases:** 3 distinct edge cases (§6.8) covering unicode name drift, unblocked backup restore, and non-deletion SAR access requests.
   - **Failure Analysis & Improvements:** Detailed retrospective of identified edge cases and algorithmic solutions.

2. **`evaluation/usage_report.md`** (also mirrored in `code/evaluation/usage_report.md`):
   - Executive summary of the 518-case full production run.
   - Model providers, model identifiers, call counts, prompt/completion tokens, and cost.
   - Efficiency analysis detailing zero-cost local inference and canonical multimodal caching.

---

## 5. Submission Artifacts

| Item | Description | Location / Status |
|---|---|---|
| **`output.csv`** | 518 evaluation predictions, sorted by `case_id`, valid RFC 8259 JSON steps | Root `output.csv` |
| **`code.zip`** | Clean archive containing `README.md`, `code/`, `evaluation/` | Root `code.zip` |
| **`chat_transcript`** | Complete agent interaction log following §5.2 format | Root `log.txt` |
| **AI Interview** | Live architectural and methodology explanation | See Section 6 below |

### Packaging `code.zip`

To package the submission archive strictly excluding `dataset/`, virtual environments, caches, and secrets:

**Windows (PowerShell):**
```powershell
# Remove caches
Get-ChildItem -Path code, evaluation -Recurse -Filter "__pycache__" | Remove-Item -Recurse -Force
if (Test-Path code/.env) { Copy-Item code/.env code/.env.bak; Remove-Item code/.env }

# Compress submission archive
Compress-Archive -Path README.md, code, evaluation -DestinationPath code.zip -Force

# Restore local .env
if (Test-Path code/.env.bak) { Move-Item code/.env.bak code/.env -Force }
```

**macOS / Linux:**
```bash
zip -r code.zip README.md code evaluation \
  -x "*/__pycache__/*" "*/.venv/*" "*/venv/*" "*/.git/*" "code/.env" "code.zip"
```

---

## 6. AI Interview: Technical Highlights

When presenting the architecture during the AI evaluation interview, highlight the following core engineering decisions:

1. **Perceptual Multimodal Decoupling:**
   - Instead of feeding user-specific prompts into a VLM during per-case auditing (which causes hallucination and cross-case cache pollution), visual perception is decoupled from policy auditing.
   - Screenshots and PDFs are converted once into objective, case-agnostic structural representations (`cache/multimodal_cache.json`). The deterministic audit engine then queries this structured data in sub-milliseconds with zero token usage.

2. **Temporal Cutoff Boundary (`captured_at >= requested_at`):**
   - A common pitfall is flagging pre-request database snapshots as deletion failures. The system strictly checks whether evidence was captured *after* the customer's deletion request was submitted.

3. **Unicode Normalization & Diacritic Stripping:**
   - Real-world enterprise systems store international names in inconsistent NFC/NFD compositions or unaccented ASCII representations (`Sofía Fernández` vs `Sofia Fernandez`). The Logging Agent generates normalized alias lookup sets, and the Audit SQLite engine injects custom `STRIP_ACCENTS` collations.

4. **Dependency-First Remediation Graph:**
   - In accordance with enterprise safety practices, data flows (synchronization jobs) and backup restore mechanisms must be disabled/blocked *before* downstream records are deleted or tombstoned. Modifying primary records while an active sync job is running leads to immediate data recreation.

5. **Deterministic Guardrails & Zero Hardcoding:**
   - Every single step, operation, system ID, and resource ID is dynamically resolved from `dataset/deletion_rules.csv`, `system_activity.csv`, and `evidence_files.csv`. Zero golden labels, case IDs, or hardcoded rules are used.
