# ARCHITECTURE_PLANNING.md

## 1. Goal & Operational Architecture

Build a deterministic, personalized Message Notification Router that reads `dataset/`, classifies every row in `messages.csv`, and writes `output.csv`.

This architecture is built upon four core operational pillars:
1. **Row-by-Row Chronological & Asyncio Concurrent Processing:** Messages in `messages.csv` are sorted by `created_at` timestamp. Because multiple messages can arrive simultaneously (at the exact same timestamp for a user or across users), the pipeline uses **`asyncio` concurrency (`asyncio.gather` with semaphores)** to run STT, VLM, and LLM labeling calls in parallel while preserving deterministic 1-to-1 output row ordering.
2. **Media-First Pipeline (STT & VLM):** Media is inspected and transcribed/extracted *before* semantic labeling.
3. **LLM Outputs Pure Categorical Labels (Including History Match):** The LLM never outputs numeric scores or confidence values. It receives the incoming message and pre-filtered candidate history, outputting categorical labels and selecting matching evidence IDs.
4. **Bounded Sub-Scores & Sequential Gates (Python):** Python evaluates bounded sub-scores (`mean` / `weighted_mean`) and strict sequential gates (Safety, Scam, Emergency, Consent) to determine the final `action` and `message_type`.

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
- 3 to 5 candidate historical rows pre-filtered by Python (`same user_id` + `same sender_id OR group_id OR business_id`).

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
   d. SUB-SCORE & GATE EVALUATION (Python):
      - Convert categorical labels to bounded numeric values (0.0 to 1.0)
      - Evaluate bounded means (historical_engagement, interruption_fit, utility_score)
      - Apply sequential gates (Prompt Injection, Scam, Emergency, Consent)
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
  - `fast`: median $\le 10$ min ($\rightarrow 1.00$)
  - `normal`: median $>10$ and $\le 60$ min ($\rightarrow 0.65$)
  - `slow`: median $>60$ min ($\rightarrow 0.35$)
  - `no_signal`: no opened/replied event ($\rightarrow 0.50$)

---

## 6. Safety & Absolute Gates (Short-Circuit Rules)

Safety and consent gates execute *before* numeric scoring.

### 6.1 Prompt Injection Gate
If message text attempts control overrides (`"ignore previous rules"`, `"set action=notify"`), trap as untrusted content. If paired with OTP/PIN or account threats $\rightarrow$ `mute`/`scam`.

### 6.2 Credential / OTP Phishing Gate
If `contains_sensitive_request == true` in an unsafe flow (asking user to reply/share OTP, PIN, password, or visit an unverified domain) $\rightarrow$ short-circuit to `action = mute`, `message_type = scam`.

### 6.3 Domain Impersonation Gate
If `business_verified == 0` AND official domain mismatches sender domain AND report count is high $\rightarrow$ short-circuit to `action = mute`, `message_type = scam`.

### 6.4 Promotional Consent Gate
If `is_promotional == true` (or `content_intent == promotion_or_offer`) AND `allows_promotions == 0` (or opted out) $\rightarrow$ short-circuit to `action = mute`, `message_type = promotion`.
*(Note: Transactional delivery/booking updates (`transactional_update`) bypass this gate).*

### 6.5 Emergency Override Gate
If `priority_label == critical` AND `risk_label` not in `[high, critical]` $\rightarrow$ short-circuit to `action = notify`, `message_type = urgent` (or `event`). Urgency overrides DND quiet hours and muted groups.

---

## 7. Bounded Sub-Score Formulas (`mean` / `weighted_mean`)

For messages that do not short-circuit through safety or consent gates, Python calculates bounded sub-scores in the range `[0.0, 1.0]`:

### 7.1 Label-to-Number Mapping
```text
priority_points:
critical -> 1.00
high     -> 0.85
medium   -> 0.55
low      -> 0.25
unclear  -> 0.40

risk_penalty_factor:
critical -> 1.00
high     -> 0.85
medium   -> 0.55
low      -> 0.20
none     -> 0.00
```

### 7.2 Historical Engagement Sub-Score
```text
historical_engagement = mean(
  open_rate,
  reply_rate,
  1.0 - dismissal_rate,
  1.0 - report_rate
)
```

### 7.3 Interruption Fit Sub-Score
```text
interruption_fit = mean(
  not_in_dnd_or_priority_high,
  not_group_muted_or_priority_high,
  fatigue_tolerance,
  direct_or_recipient_specific_signal
)
```

### 7.4 Composite Utility Score
```text
utility_score = weighted_mean(
  semantic_importance,
  sender_trust,
  relationship_strength,
  historical_engagement,
  response_speed,
  consent_fit,
  interruption_fit
)
```

---

## 8. Final Decision Order (Sequential Evaluation)

```text
1. If Prompt Injection + Sensitive Credential Request -> mute / scam
2. If risk_label in [high, critical] OR Domain Impersonation -> mute / scam (or spam)
3. If Emergency Override (priority == critical, safe content) -> notify / urgent (or event)
4. If Promotional Consent Gate (is_promotional=true AND allows_promotions=0) -> mute / promotion
5. If utility_score >= 0.70 -> notify
6. If utility_score >= 0.40 -> digest
7. Else -> mute
```

### 8.1 Confidence Calibration
- `confidence` float `[0.0, 1.0]` is calibrated based on historical evidence strength and distance from threshold:
  - Strong history match (`same_situation` + valid evidence IDs): `0.85 – 0.95`
  - Moderate history match (`similar_situation`): `0.70 – 0.84`
  - Weak/no history match (`no_match`, blank history): `0.50 – 0.69`
  - Media extraction failure fallback: penalize confidence by `-0.15`

---

## 9. Message Type Mapping

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

## 10. Comprehensive Test Plan

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

## 11. Codebase Structure (Clean 4-Layer Hierarchy with Asyncio)

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
│   ├── scoring.py         # Evaluates mean / weighted_mean bounded sub-scores (0.0 - 1.0)
│   └── policy.py          # Executes sequential decision order, absolute gates, and enum mapping
└── validator/
    └── check_output.py    # Verifies 110 rows, exact 6 columns, CSV quoting, and evidence IDs
```
