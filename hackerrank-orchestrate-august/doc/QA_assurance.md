# Quality Assurance

**Project:** HackerRank Orchestrate — WhatsApp Message Notification Router

---

## 1. Quality Control Layers

Different classes of errors require different testing approaches:

| Layer | Owns | How It's Done |
| :--- | :--- | :--- |
| **Layer 1: Unit & Integration Testing** (`pytest` + offline mocks) | Code crashes, schema violations, deterministic routing logic bugs | `python -m pytest code/tests/ -q` — runs 15 tests offline in <2s |
| **Layer 2: Policy Backtesting** (Shadow-mode over sample rows) | Business rule regressions — a rule change that silently alters routing decisions | Run pipeline on `sample_messages.csv`, compare against known-good output via `evaluation/compare.py` |
| **Layer 3: Safety & Evaluation Scorecard** | Emergency recall, scam suppression, confidence calibration | Run `python -m evaluation.main` against output to verify safety invariants |
| **Layer 4: Manual Adversarial Review** | Prompt injection, VLM attacks, schema exploits | Manual review of edge cases documented in `doc/ADVERSARIAL.md` |

---

## 2. Automated Test Gate

Before submitting, the following must pass:

```text
[ Stage 1: Schema & Boundary Tests ]     -> test_schema_seams.py (3 tests)
[ Stage 2: Regression Fixtures ]          -> test_regression_fixtures.py (9 tests)
[ Stage 3: Randomized Invariant Fuzzing ] -> test_property_invariants.py (1 test, 500 permutations)
[ Stage 4: Dataset Acceptance ]           -> test_system_acceptance.py (2 tests)
```

All stages run offline with zero API calls via mock `SensorObservation` objects.

---

## 3. Policy Backtesting Workflow

When modifying thresholds in `config.yaml` or rules in `decision_tree.py`:

1. **Run pipeline** on `sample_messages.csv` (30 solved examples with ground truth)
2. **Compare output** using `python code/evaluation/compare.py`
3. **Check accuracy** — action accuracy and type accuracy against known labels
4. **Verify safety** — run evaluation scorecard to check emergency recall and scam suppression

---

## 4. Adversarial Defense Verification

The pipeline handles adversarial inputs through multiple layers:
* **Pydantic Typed Seam:** Rejects any LLM output with invalid enum values
* **Prompt Instructions:** Models instructed to treat message content as untrusted data
* **LLM Risk Constraint:** Router prompt forbids high/critical risk on operational messages without credential signals
* **Decision Tree Gate 1 (Split):** Deterministically mutes phishing intents as `scam`, non-phishing high-risk as `spam`
* **Engagement Personalization (Gate 3.7):** Low-engagement sources demoted to digest — never upgrades safety
* **Safe-Default Fallback:** Any unhandled exception emits a conservative `digest`/`unknown` row

---

## 5. Evaluation Scorecard

The evaluation module (`code/evaluation/`) provides:
- **110-Row Completeness Check:** Verifies 1-to-1 input/output mapping
- **Schema Vocabulary Check:** 100% of rows contain valid action and confidence values
- **Action Distribution:** Counts notify/digest/mute frequencies
- **Safety Guardrails:** Emergency recall rate and scam suppression rate
- **Macro F1 Estimate:** Balance metric across the 3 action classes

Run: `cd code && python -m evaluation.main --output ../dataset/output.csv --dataset ../dataset/messages.csv`
