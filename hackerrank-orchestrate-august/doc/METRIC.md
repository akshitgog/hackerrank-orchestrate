# 📊 EVALUATION METRICS & STATISTICAL SCORECARD (`metric.md`)

**Document Name:** `metric.md`  
**Scope:** Mathematical Formulas & Evaluation Metrics for WhatsApp Message Notification Router  
**Project:** HackerRank Orchestrate  

---

## 1. OFFICIAL EVALUATION METRIC HIERARCHY

To evaluate our submission (`dataset/output.csv`) for the HackerRank Orchestrate challenge, we apply a **multi-objective evaluation scorecard** combining classification accuracy, safety recall invariants, confidence calibration, and historical evidence grounding.

```text
       [ OVERALL HACKATHON EVALUATION SCORE ]
                         │
         ┌───────────────┼───────────────┐
         ▼               ▼               ▼
  (70% Weight)     (20% Weight)    (10% Weight)
  Macro F1-Score   Safety Recall   Evidence Grounding
  & Accuracy       Invariants      & Calibration
```

---

## 2. PRIMARY CLASSIFICATION METRIC: MACRO F1-SCORE (70%)

Because message actions (`notify`, `digest`, `mute`) can be class-imbalanced, standard accuracy is misleading. We calculate **Macro F1-Score** across all three classes $C = \{\text{notify}, \text{digest}, \text{mute}\}$:

$$\text{Precision}_c = \frac{\text{TP}_c}{\text{TP}_c + \text{FP}_c}, \quad \text{Recall}_c = \frac{\text{TP}_c}{\text{TP}_c + \text{FN}_c}$$

$$\text{F1}_c = 2 \cdot \frac{\text{Precision}_c \cdot \text{Recall}_c}{\text{Precision}_c + \text{Recall}_c}$$

$$\text{Macro F1} = \frac{1}{|C|} \sum_{c \in C} \text{F1}_c$$

* **Target Benchmark:** $\text{Macro F1} \ge 0.88$ across test evaluations.

---

## 3. SAFETY & ETHICS INVARIANT METRICS (20%)

In a production WhatsApp notification system, certain misclassifications cause real-world harm. We define three **hard-constraint guardrail metrics**:

| Metric | Formula | Requirement | Failure Impact |
| :--- | :--- | :--- | :--- |
| **Emergency Recall ($R_{\text{emerg}}$)** | $\frac{\text{TP}_{\text{emergency}}}{\text{Total True Emergencies}}$ | **100% (1.00)** | A missed medical/safety emergency during DND quiet hours could endanger life. |
| **Scam Suppression Rate ($S_{\text{scam}}$)** | $\frac{\text{Muted True Scams}}{\text{Total True Scams}}$ | **100% (1.00)** | Silently allowing financial phishing messages to ping the user violates security guarantees. |
| **Promo Opt-Out Precision ($P_{\text{promo}}$)** | $\frac{\text{Muted Opt-Out Promos}}{\text{Total Opt-Out Promos}}$ | **100% (1.00)** | Sending promotional notifications from opted-out businesses violates user trust. |

---

## 4. CONFIDENCE CALIBRATION & EVIDENCE GROUNDING (10%)

### 1. Expected Calibration Error (ECE)
Evaluates whether the output `confidence` score in `output.csv` reflects empirical accuracy. Binned into $M=10$ confidence buckets:

$$\text{ECE} = \sum_{m=1}^{M} \frac{|B_m|}{N} \left| \text{acc}(B_m) - \text{conf}(B_m) \right|$$

* **Target:** $\text{ECE} \le 0.05$ (well-calibrated probabilities).

### 2. Evidence Grounding Ratio ($G_{\text{evid}}$)
Measures the proportion of output predictions that correctly cite historical supporting `evidence_message_ids` when relevant history exists:

$$G_{\text{evid}} = \frac{\text{Rows with Valid Evidence IDs}}{\text{Total Rows Requiring Historical Context}}$$

* **Target:** No hallucinated evidence IDs (0% hallucination rate); `none` used cleanly when no history applies.
