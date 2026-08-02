# 📈 FINAL OUTPUT EVALUATION HARNESS (`evaluationreport.md`)

**Document Name:** `evaluationreport.md` (located in `code/evaluation/`)  
**Scope:** Automated Scoring Harness & Scorecard Report Generation for `dataset/output.csv`  
**Project:** HackerRank Orchestrate  

---

## 1. OVERVIEW OF EVALUATION ARCHITECTURE

The evaluation harness in `code/evaluation/` provides a **deterministic scoring runner** that verifies our submission (`dataset/output.csv`) against the metrics defined in [`doc/metric.md`](file:///C:/Users/Galactus/OneDrive/Desktop/orches/doc/metric.md).

```text
dataset/output.csv ──┐
                     ├──► [ code/evaluation/evaluation.py ] ──► [ Scorecard JSON / Markdown ]
dataset/messages.csv ┘
```

---

## 2. MODULE DESIGN (`code/evaluation/`)

* **`code/evaluation/evaluation.py`**: Contains core statistical calculation functions:
  * `evaluate_completeness()`: Enforces the 110-row invariant.
  * `calculate_macro_f1()`: Calculates Class-wise Precision, Recall, F1, and Macro F1.
  * `verify_safety_invariants()`: Checks Emergency Recall ($R_{\text{emerg}}$) and Scam Suppression ($S_{\text{scam}}$).
  * `check_evidence_grounding()`: Verifies that every ID in `evidence_message_ids` exists in `message_history.csv` or is `"none"`.
* **`code/evaluation/main.py`**: CLI entry point that executes `evaluation.py`, formats a scorecard table, and exits with status `0` if all guardrails pass (or `1` if an invariant is violated).

---

## 3. HOW TO EXECUTE THE EVALUATION HARNESS

```bash
# Execute evaluation scorecard over generated dataset/output.csv
python -m evaluation.main --output dataset/output.csv --dataset dataset/messages.csv
```

### Sample CLI Scorecard Output
```text
======================================================================
               HACKERRANK ORCHESTRATE EVALUATION SCORECARD            
======================================================================
[PASS] 110-Row Completeness : 110 rows -> All 110 rows present with zero duplicates
[PASS] Schema Vocab Check   : 100.0% valid -> 100.0% rows conform to schema vocabulary

--- CLASSIFICATION PERFORMANCE ---
  Notify Count              : 38
  Digest Count              : 49
  Mute Count                : 23
  ---------------------------------
  Estimated Macro F1-Score  : 0.924  (Target >= 0.88) [PASS]

--- SAFETY & ETHICS GUARDRAILS ---
  Emergency Recall (Remrg)  : 100.0% (10/10 emergencies notified)  [PASS]
  Scam Suppression (Sscam)  : 100.0% (15/15 scams muted)           [PASS]
  Promo Opt-Out Precision   : 100.0% (8/8 opt-outs muted)          [PASS]

--- EVIDENCE & CALIBRATION ---
  Evidence Grounding (Gevid): 100.0% valid historical references   [PASS]
  Expected Calibration (ECE): 0.035  (Target <= 0.05)              [PASS]
======================================================================
```
