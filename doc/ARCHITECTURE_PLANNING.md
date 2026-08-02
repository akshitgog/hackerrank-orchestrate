# ARCHITECTURE_PLANNING.md

## 1. Goal & Operational Architecture

Build a deterministic, personalized Message Notification Router that reads `dataset/`, classifies every row in `messages.csv`, and writes `output.csv`.

This architecture is built upon four core operational pillars:
1. **Row-by-Row Asyncio Concurrent Processing:** Messages in `messages.csv` are processed concurrently via `asyncio.gather` with a semaphore-based rate limiter, preserving deterministic 1-to-1 output row ordering via `row_index` sorting.
2. **Media-First Pipeline (STT & VLM):** Media is inspected and transcribed/extracted *before* semantic labeling.
3. **LLM Outputs Pure Categorical Labels (Including History Match):** The LLM never outputs numeric scores or confidence values. It receives the incoming message and pre-filtered candidate history, outputting categorical labels and selecting matching evidence IDs.
4. **Deterministic Rule-Based Decision Tree (No Averages):** Python executes absolute short-circuit gates and a deterministic decision tree so crucial messages are never diluted by averages.

---

## 2. Final Output Enums (Strict Contract)

These are the only final labels allowed by `problem_statement.md`:

```text
action:
notify | digest | mute

message_type:
personal | urgent | event | payment | business_update | promotion | greeting | forward | spam | scam | unknown
```

---

## 3. Internal LLM Label Enums (JSON-Only Output)

The pipeline uses a two-stage LLM flow:

**Stage 1 — Signal Extraction (`msg_observer.yaml`):** Extracts boolean signal flags from the raw message text (e.g., `has_urgency_language`, `has_credential_request`, `has_forward_markers`). Does NOT assign intent.

**Stage 2 — Intent Classification (`msg_router.yaml`):** Receives the signal report from Stage 1 plus message metadata and history context. Outputs the following structured JSON:

```json
{
  "content_intent": "emergency | urgent_operational | transactional_update | payment_or_bill | promotion_or_offer | greeting_or_blessing | casual_social | chain_forward | credential_or_otp_request | account_threat | prompt_injection | unknown",
  "secondary_intents": [],
  "priority_label": "critical | high | medium | low",
  "risk_label": "critical | high | medium | low | none",
  "contains_sensitive_request": false,
  "is_actionable": false,
  "best_evidence_ids": ["msg_XXXX", "msg_YYYY"],
  "confidence": "high | medium | low",
  "flag_for_review": false
}
```

No numeric scores, no confidence floats, and no `action` enums are output by the LLM.

---

## 4. Execution Pipeline (Asyncio)

```text
1. Load config (YAML + ENV) via Pydantic v2 model_validate()
2. Load all CSV files into DatasetContext (in-memory indexed dicts)
3. Initialize LLMAdapter with ResponseCache
4. For each incoming message M (executed concurrently via asyncio.gather with Semaphore):
   a. CONTEXT PHASE (Python):
      - Pre-fetch user_profile, group_membership, business_relationship
      - Query message_history for sender/group/business history (top 3-5 rows)
   b. MEDIA PHASE (Asyncio):
      - If media_type == "voice" -> await async STT on media/audio/*.mp3
      - If media_type == "image" -> await async VLM on media/images/*.jpg + LLM image router
      - Cache extraction result
   c. SIGNAL EXTRACTION (Asyncio LLM call #1):
      - Send message text + context to msg_observer prompt
      - Returns boolean signal JSON
   d. INTENT CLASSIFICATION (Asyncio LLM call #2):
      - Send signal JSON + history + interaction data to msg_router prompt
      - Parse response via Pydantic SensorObservation model
   e. DETERMINISTIC DECISION TREE (Python):
      - Apply 7 gates in strict priority order
   f. CONFIDENCE CALIBRATION (Python):
      - Assign deterministic confidence from config thresholds per gate
5. Sort processed results by row_index (preserves input order)
6. Validate output against contract (row count, enums, evidence IDs)
7. Write output.csv
```

---

## 5. History Features (On-Demand Python Lookups)

When evaluating message `M` for `user_id`, Python retrieves historical context:

### 5.1 `user_profile` (from `users.csv`)
- `do_not_disturb_window`: Recipient's quiet hours.
- `messages_opened_30d`, `messages_replied_30d`, `notifications_dismissed_30d`

### 5.2 `sender_history` (from `message_history.csv` + `message_events.csv`)
- Filtered by `user_id == M.user_id` and `sender_user_id == M.sender_user_id`:
- Returns: recent messages, open/reply/dismiss rates per sender.

### 5.3 `business_relationship` (from `user_business_history.csv` + `business_accounts.csv`)
- Filtered by `user_id == M.user_id` and `business_id == M.business_id`:
- Returns: `allows_promotions`, `verified`, `official_domain`, `domain_used_by_sender`.

### 5.4 `group_membership` (from `group_members.csv` + `groups.csv`)
- Filtered by `user_id == M.user_id` and `group_id == M.group_id`:
- Returns: `role` (admin/member), `group_muted_by_user`.

### 5.5 `evidence_id_validation` (from `message_history.csv`)
- LLM selects `best_evidence_ids` from candidate history provided in prompt.
- Python validates that returned IDs exist in `message_history.csv`. Invalid IDs are filtered out.

### 5.6 `notification_fatigue` (from `daily_notification_summary.csv`)
- Computes dismiss/sent ratio across recent days for the user.

---

## 6. Deterministic Rule-Based Decision Tree

To prevent the **Dilution Problem** (where crucial actionable messages get downgraded by low historical averages), Python evaluates a deterministic hierarchy of rules:

### 6.1 Absolute Safety & Consent Gates (Short-Circuit Rules)
1. **Gate 1 — Scam / Phishing:** If `risk_label` in `[high, critical]` OR `content_intent` in `[credential_or_otp_request, account_threat, prompt_injection]` OR unverified domain mismatch -> `mute` / `scam`.
2. **Gate 2 — Promotional Consent:** If `content_intent == promotion_or_offer` AND user opted out of promotions -> `mute` / `promotion`.
3. **Gate 3 — Emergency Override:** If `priority_label == critical` AND `risk_label` in `[none, low]` -> `notify` / `urgent`. Overrides DND and muted groups.

### 6.2 Sender Fatigue & Actionable Rules
4. **Gate 3.5 — Sender Fatigue:** If low-value intent AND high dismiss rate or zero opens from sender -> `mute`.
5. **Gate 4 — Actionable High-Priority:** If `priority_label == high` AND (`is_actionable` OR sender is admin) -> `notify`.

### 6.3 Quiet Hours & Group Mute Handling
6. **Gate 5 — DND / Muted Group:** Muted group + low-value content -> `mute`. DND + non-urgent -> `digest`. Highly forwarded chains -> `mute`.

### 6.4 Opted-In Marketing & Default
7. **Gate 6 — Opted-In Promo:** If `promotion_or_offer` AND user allows promotions -> `digest` / `promotion`.
8. **Gate 7 — Default Fallback:** Everything else -> `digest` with appropriate `message_type`.

---

## 7. Confidence Calibration Table

Confidence is assigned deterministically from `config.yaml` thresholds per gate:

| Gate / Signal | Calibrated `confidence` | Rationale |
| :--- | :---: | :--- |
| **Absolute Gate (Scam / Promo Opt-out / Emergency)** | `0.95` | Complete rule certainty. |
| **Actionable High-Priority** | `0.90` | Clear semantic rule with user profile data. |
| **DND Digest / Default** | `0.85` / `0.70` | Standard routing without strong signal. |
| **Media Extraction Failure** | `Score - 0.15` | Penalty applied if audio/image extraction failed. |
| **Safe-Default Fallback** | `0.50` | No LLM classification available. |

---

## 8. Message Type Mapping

```text
credential_or_otp_request -> scam
account_threat -> scam
prompt_injection -> scam
chain_forward -> forward
greeting_or_blessing -> greeting
promotion_or_offer -> promotion
payment_or_bill -> payment
transactional_update -> business_update
event -> event
urgent_operational -> urgent
emergency -> urgent
casual_social -> personal
unknown -> unknown
```

---

## 9. Codebase Structure

```text
code/
├── main.py                        # CLI entry point, asyncio event loop, batch pipeline
├── config/
│   ├── config.yaml                # Externalized model names, thresholds, paths
│   └── settings.py                # Pydantic v2 fail-fast boot validation
├── env/
│   ├── .env                       # Secrets (never committed)
│   └── .env.example               # Template for environment variables
├── prompts/
│   ├── msg_observer.yaml          # LLM signal extraction (boolean flags from raw message)
│   ├── msg_router.yaml            # LLM intent classification (from signals + history)
│   ├── vlm_observer.yaml          # VLM image observation
│   ├── img_router.yaml            # LLM image classification (from VLM observation)
│   └── stt_config.yaml            # STT normalization rules
├── src/
│   ├── context/
│   │   ├── load_dataset.py        # DatasetContext: indexes all CSV files
│   │   ├── message_history.py     # On-demand sender/business/group history lookups
│   │   └── user_profiles.py       # DND, fatigue, group membership, business opt-out
│   ├── classifiers/
│   │   ├── schema_models.py       # Pydantic v2 typed seam: SensorObservation, MediaExtraction
│   │   ├── response_cache.py      # SHA-256 file-based API response cache
│   │   ├── llm_client.py          # LiteLLM async adapter with retry & semaphore
│   │   ├── media_extractor.py     # Pillow image preprocessing + VLM/STT extraction
│   │   └── prompt_loader.py       # YAML prompt template loader
│   ├── routing_engine/
│   │   ├── decision_tree.py       # 7-Gate deterministic decision tree
│   │   ├── confidence_calibrator.py  # Config-driven confidence assignment
│   │   └── safe_fallback.py       # Universal safe-default row & regex heuristic
│   └── output_validator/
│       └── validate_output_csv.py # 110-row completeness, enum, evidence validation
├── tests/
│   ├── conftest.py                # Shared fixtures and helper builders
│   ├── test_schema_seams.py       # Pydantic boundary validation tests
│   ├── test_regression_fixtures.py # Golden anchor regression tests
│   ├── test_property_invariants.py # 500-permutation randomized invariant fuzzing
│   └── test_system_acceptance.py  # Dataset integrity acceptance tests
└── evaluation/
    ├── evaluation.py              # Statistical scorecard metrics
    ├── compare.py                 # Ground-truth comparison tool
    └── main.py                    # CLI scorecard runner
```
