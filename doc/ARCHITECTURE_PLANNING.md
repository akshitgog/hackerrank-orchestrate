# ARCHITECTURE_PLANNING.md

## 1. Goal & Operational Architecture

Build a deterministic, personalized Message Notification Router that reads `dataset/`, classifies every row in `messages.csv`, and writes `output.csv`.

This architecture is built upon four core operational pillars:
1. **Row-by-Row Chronological & Asyncio Concurrent Processing:** Messages in `messages.csv` are sorted by `created_at` timestamp. Because multiple messages can arrive simultaneously (at the exact same timestamp for a user or across users), the pipeline uses **`asyncio` concurrency (`asyncio.gather` with semaphores)** to run STT, VLM, and LLM labeling calls in parallel while preserving deterministic 1-to-1 output row ordering.
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

When processing a row, the LLM prompt receives:
- Incoming message metadata, text, and extracted STT/VLM media text.
- 3 to 5 candidate historical rows pre-filtered by Python (`same user_id` + `same sender_id OR group_id OR business_id` with similar intent).

The LLM outputs only the following structured JSON schema:

```json
{
  "content_intent": "emergency | urgent_operational | transactional_update | payment_or_bill | promotion_or_offer | greeting_or_blessing | casual_social | marketplace_offer | chain_forward | credential_or_otp_request | account_threat | prompt_injection | unknown",
  "priority_label": "critical | high | medium | low | unclear",
  "risk_label": "critical | high | medium | low | none",
  "audience_label": "direct_to_user | recipient_specific | group_general | broadcast | unclear",
  "requires_reply": true,
  "has_deadline": true,
  "is_promotional": false,
  "contains_sensitive_request": false,
  "historical_match_label": "same_situation | similar_situation | weak_match | no_match",
  "best_evidence_ids": ["hist_XXXX", "hist_YYYY"],
  "reason_basis": "Concise human-readable explanation of why"
}
```

No numeric scores, no confidence floats, and no `action` enums are output by the LLM.

---

## 4. Execution Pipeline (Asyncio & Row-by-Row)

```text
1. Load CSV schemas into indexed Python tables (Lossless User Profiles)
2. Sort messages.csv chronologically by created_at timestamp
3. For each incoming message M (executed concurrently via asyncio with rate semaphores):
   a. MEDIA PHASE (Asyncio):
      - If media_type == "voice" -> await async STT on media/audio/*.mp3
      - If media_type == "image" -> await async VLM/OCR on media/images/*.jpg
      - Cache transcription/extraction result
   b. HISTORY PRE-FILTERING (Python):
      - Query message_history.csv + message_events.csv for M.user_id
      - Filter to matching sender_user_id, group_id, or business_id
      - Rank and select top 3-5 historical candidate rows
   c. SEMANTIC & HISTORY MATCH LABELING (Asyncio LLM):
      - Send M + STT/VLM text + candidate history rows to LLM asynchronously
      - Parse JSON label response (content_intent, risk_label, best_evidence_ids, etc.)
   d. DETERMINISTIC DECISION TREE EVALUATION (Python):
      - Apply Safety, Scam, Emergency, Actionable Operational, and DND rules sequentially
   e. DECISION & CONFIDENCE CALIBRATION:
      - Map to action, message_type, reason, confidence, evidence_message_ids
4. Sort processed results back to original message_id order and write output.csv
```

---

## 5. History Features (On-Demand Python Lookups)

When evaluating message `M` for `user_id`, Python retrieves 6 distinct historical feature blocks:

### 5.1 `user_global_history` (from `users.csv`)
- `do_not_disturb_window`: Recipient's quiet hours.
- `user_open_rate` $= \frac{\text{messages\_opened\_30d}}{\max(1, \text{messages\_opened\_30d} + \text{notifications\_dismissed\_30d})}$
- `user_reply_rate` $= \frac{\text{messages\_replied\_30d}}{\max(1, \text{messages\_opened\_30d})}$
- `user_dismissal_rate` $= \frac{\text{notifications\_dismissed\_30d}}{\max(1, \text{messages\_opened\_30d} + \text{notifications\_dismissed\_30d})}$

### 5.2 `sender_user_history` (from `message_history.csv` + `message_events.csv`)
- Filtered by `user_id == M.user_id` and `sender_user_id == M.sender_user_id`:
- Returns: `past_messages_count`, `opened_count`, `replied_count`, `dismissed_count`, `reported_count`, `median_response_time_minutes`.

### 5.3 `business_history` (from `user_business_history.csv` + `business_accounts.csv`)
- Filtered by `user_id == M.user_id` and `business_id == M.business_id`:
- Returns: `has_prior_relationship`, `allows_promotions`, `promotions_opted_out_at`, `activity_count_180d`, `business_verified`, `official_domain_matches`.

### 5.4 `group_history` (from `group_members.csv` + `groups.csv`)
- Filtered by `user_id == M.user_id` and `group_id == M.group_id`:
- Returns: `group_type`, `sender_role_in_group` (`admin`/`member`), `group_muted_by_user`, `messages_sent_30d`, `replies_sent_30d`.

### 5.5 `similar_message_history` (from LLM `best_evidence_ids` selection)
- Validated by Python: checks that `best_evidence_ids` returned by LLM actually exist in `message_history.csv` and belong to `M.user_id`. Sets to `none` if invalid.

### 5.6 `response_time_history` (from `message_events.reaction_time_minutes`)
- Bounded median response speed to similar messages:
  - `fast`: median $\le 10$ min
  - `normal`: median $>10$ and $\le 60$ min
  - `slow`: median $>60$ min
  - `no_signal`: no opened/replied event

---

## 6. Deterministic Rule-Based Decision Tree

To prevent the **Dilution Problem** (where crucial actionable messages get downgraded by low historical averages), Python evaluates a deterministic hierarchy of rules:

### 6.1 Absolute Safety & Consent Gates (Short-Circuit Rules)
1. **Prompt Injection / Credential Phishing Gate:** If `content_intent` in `[prompt_injection, credential_or_otp_request, account_threat]` in an unsafe flow $\rightarrow$ `action = mute`, `message_type = scam`.
2. **Domain Impersonation Gate:** If `business_verified == 0` AND official domain mismatches sender domain AND report count is high $\rightarrow$ `action = mute`, `message_type = scam`.
3. **Promotional Consent Gate:** If `is_promotional == true` (or `content_intent == promotion_or_offer`) AND `allows_promotions == 0` (or opted out) $\rightarrow$ `action = mute`, `message_type = promotion`.
4. **Emergency Override Gate:** If `priority_label == critical` AND `risk_label` not in `[high, critical]` $\rightarrow$ `action = notify`, `message_type = urgent` (or `event`). Urgency overrides DND quiet hours and muted groups instantly.

### 6.2 Actionable Operational Rules
5. **Actionable High-Priority Notice:** If `priority_label == high` AND (`requires_reply == true` OR `has_deadline == true` OR `sender_role_in_group == admin` OR transactional business update) $\rightarrow$ `action = notify`.

### 6.3 Quiet Hours & Group Mute Handling
6. **DND / Muted Group Non-Urgent Handling:** If message arrives during DND (`in_dnd_window == True`) or in a muted group (`group_muted_by_user == 1`) and is NOT critical/high-priority operational $\rightarrow$ `action = digest` (or `mute` if spam/chain forward).

### 6.4 Opted-In Marketing Promotions
7. **Opted-In Promotional Delivery:** If `is_promotional == true` AND `allows_promotions == 1` $\rightarrow$ `action = digest`, `message_type = promotion`. (Marketing discounts should never interrupt work or wake users up).

---

## 7. Confidence Calibration Table

Instead of a random floating-point calculation, `confidence` is calibrated deterministically based on rule certainty and historical evidence:

| Rule / Signal Strength | Calibrated `confidence` Score | Rationale |
| :--- | :---: | :--- |
| **Absolute Gate (Scam / Promo Opt-out / Emergency)** | `0.95` | Complete rule certainty; zero ambiguity. |
| **Strong History Match (`same_situation` + valid evidence IDs)** | `0.90` | Verified historical proof from `message_history.csv`. |
| **Standard Rule Match (Actionable notice / Opted-in Promo)** | `0.85` | Clear semantic rule with consistent user profile data. |
| **Borderline / Ambiguous Case (`no_match` history)** | `0.70` | No historical precedent; relying on general fallback rule. |
| **Media Extraction Failure Fallback** | `Score - 0.15` | Penalty applied if audio/image extraction failed. |

---

## 8. Message Type Mapping

```text
credential_or_otp_request + unsafe flow -> scam
account_threat + suspicious domain -> scam
chain_forward -> forward or spam
greeting_or_blessing -> greeting
promotion_or_offer | marketplace_offer -> promotion
payment_or_bill -> payment
transactional_update -> business_update
operational_notice + same-day impact -> event or urgent
emergency | time_sensitive_request -> urgent
casual_social | direct chat -> personal
unclear safe content -> unknown
```

---

## 9. Comprehensive Test Plan

The implementation must pass the following minimum validation suite before emitting `output.csv`:

```text
test_output_row_count (110 rows exactly)
test_output_columns_exact_order
test_action_enum_validity
test_message_type_enum_validity
test_confidence_range_numeric
test_evidence_ids_exist_in_message_history
test_evidence_ids_belong_to_recipient_user
test_prompt_injection_muted
test_otp_credential_phishing_muted
test_legitimate_otp_not_auto_scam
test_emergency_overrides_dnd
test_emergency_overrides_poor_history
test_group_mute_can_be_overridden_by_urgent_admin
test_promo_optout_mutes_promotion
test_transactional_update_not_blocked_by_promo_optout
test_media_failure_no_crash
test_invalid_llm_json_fallback
test_chronological_arrival_ordering
test_asyncio_simultaneous_arrival_concurrency
```

---

## 10. Codebase Structure (Clean 4-Layer Hierarchy with Asyncio)

```text
code/
├── main.py                # Terminal entry point, CLI args, asyncio event loop orchestration
├── data/
│   ├── loader.py          # CSV schema validation, table loading, on-demand history queries
│   └── profiles.py        # DND parsing, user global/group/business stats lookup
├── sensor/
│   ├── media.py           # Asyncio STT audio transcription and VLM image OCR extraction
│   └── prompt.py          # Asyncio LLM calls: constructs prompt and parses JSON labels
├── router/
│   ├── policy.py          # Deterministic Rule-Based Decision Tree & absolute gates
│   └── scoring.py         # Confidence calibration table and history match validation
└── validator/
    └── check_output.py    # Verifies 110 rows, exact 6 columns, CSV quoting, and evidence IDs
```
