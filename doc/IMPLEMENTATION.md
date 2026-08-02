# IMPLEMENTATION.md — Codebase Architecture & Hackathon Execution Roadmap

This document defines the production implementation roadmap for the HackerRank Orchestrate Message Notification Router, adhering to the Principal Engineering standards in [`june_edition_learning.md`](file:///C:/Users/Galactus/OneDrive/Desktop/orches/doc/june_edition_learning.md) and incorporating the winning Rank 3 architectural principles (Universal Safe-Default Row, Layer-by-Layer Verification, Deterministic Invariant Ownership).

---

## 1. Codebase Architecture (4-Layer Clean Hierarchy)

Our repository is organized into four modular layers, separating **probabilistic sensors** from **deterministic domain invariants**:

```text
dataset/                        # The 11 CSV dataset files + media/
doc/                            # Challenge documentation & architecture specs
code/
├── config/                     # Declarative configuration & Pydantic v2 validation
│   ├── config.yaml             # Externalized model names, thresholds, paths (12-Factor App)
│   └── settings.py             # Pydantic v2 Fail-Fast boot validation
├── env/                        # Secrets & environment variable templates
│   ├── .env                    # Secrets file (API keys, never committed)
│   └── .env.example            # Template for required environment variables
├── prompts/                    # Top-level YAML prompt templates (editable without code changes)
│   ├── llm_labeler.yaml        # LLM semantic classification system & user prompt
│   ├── vlm_screener.yaml       # VLM image OCR & content analysis prompt
│   └── stt_config.yaml         # STT transcription normalization & Hindi-English rules
├── src/                        # APPLICATION SOURCE CODE (Hexagonal / Ports-and-Adapters)
│   ├── __init__.py
│   ├── context/                # LAYER 1: WHATSAPP DATASET & CONTEXT STORE (Pure Python)
│   │   ├── __init__.py
│   │   ├── load_dataset.py     # DatasetContext: indexes all 11 CSV files with typed primary keys
│   │   ├── message_history.py  # On-demand lookup of sender/business/group historical messages
│   │   └── user_profiles.py    # DND quiet hours, engagement rates, group membership, business opt-out
│   ├── classifiers/            # LAYER 2: PROBABILISTIC CLASSIFIERS & EXTRACTORS (LLM/VLM/STT)
│   │   ├── __init__.py
│   │   ├── schema_models.py    # Pydantic v2 typed seam: SensorObservation, MediaExtraction
│   │   ├── response_cache.py   # SHA-256 deterministic API response cache (zero duplicate billing)
│   │   ├── llm_client.py       # LiteLLM async adapter with retry, backoff, and semaphore
│   │   ├── media_extractor.py  # Pillow image preprocessing + VLM/STT extraction with fallback
│   │   └── prompt_loader.py    # Single clean loader for top-level code/prompts/ YAML files
│   ├── routing_engine/         # LAYER 3: DETERMINISTIC ROUTER (Pure Python, zero network)
│   │   ├── __init__.py
│   │   ├── decision_tree.py    # 7-Gate Decision Tree with edge case annotations
│   │   ├── confidence_calibrator.py # Deterministic confidence from config thresholds
│   │   └── safe_fallback.py    # Universal Safe-Default Row & regex heuristic classifier
│   └── output_validator/       # LAYER 4: OUTPUT CONTRACT ENFORCEMENT
│       ├── __init__.py
├── tests/                      # PRACTICAL OFFLINE TEST SUITE (pytest fixtures & regression lock)
│   ├── __init__.py
│   ├── conftest.py             # Shared Pytest fixtures and mock helpers
│   ├── test_schema_models.py   # Verifies Parse-Don't-Validate typed seams
│   ├── test_decision_tree.py   # Practical 5-line sample row regression fixtures (like June edition)
│   └── test_properties.py      # Hypothesis property-based fuzzing for schema invariants
└── main.py                     # CLI entry point; asyncio event loop & batch pipeline orchestration
```

---

## 2. Universal Safe-Default Row Contract (`src/router/fallback.py`)

To guarantee zero dropped rows and 100% adherence to the 110-row Completeness Invariant, whenever any layer fails unrecoverably for a row, `fallback.py` emits the **Universal Safe-Default Row**:

```json
{
  "action": "digest",
  "message_type": "unknown",
  "reason": "Automated pipeline fallback due to unrecoverable sensor error",
  "confidence": 0.50,
  "evidence_message_ids": "none"
}
```

---

## 3. Implementation Roadmap (Phased Hackathon Execution)

```
[ Phase 1: Data & Context Layer ] ──► [ Phase 2: Sensor & Media Layer ]
                                                 │
[ Phase 4: QA & Regression Lock ] ◄── [ Phase 3: Deterministic Router ]
```

### Phase 1: Data & Context Layer (`src/data/` & `src/config/`)
- [ ] Implement `settings.py` with Pydantic v2 `model_validate()` for YAML/ENV configuration (`12-Factor App`).
- [ ] Add **Fail-Fast boot validation** to abort immediately if dataset files or API keys are missing.
- [ ] Implement `loader.py` to index `users.csv`, `groups.csv`, `group_members.csv`, `business_accounts.csv`, `user_business_history.csv`, `message_history.csv`, and `message_events.csv`.
- [ ] Implement `history.py` to query top 3-5 candidate historical messages for a given sender/group/business on demand.
- [ ] Implement `profiles.py` to calculate `user_open_rate`, `user_reply_rate`, `user_dismissal_rate`, and check `in_dnd_window`.

### Phase 2: Sensor & Media Layer (`src/sensor/`)
- [ ] Implement `media.py` using `asyncio` to transcribe `.mp3` voice notes and OCR `.jpg` image circulars/posters. Add graceful exception handling (`media_status = "extraction_failed"`).
- [ ] Implement `schema.py` defining Pydantic v2 models for LLM JSON output (`content_intent`, `priority_label`, `risk_label`, `best_evidence_ids`, etc.).
- [ ] Implement `prompt.py` with XML tags (`<user_message>`, `<candidate_history>`) and prompt-injection defense instructions.
- [ ] Implement `llm.py` with an `asyncio.Semaphore` rate-limiter and 3-attempt exponential backoff.

### Phase 3: Deterministic Router Layer (`src/router/`)
- [ ] Implement `policy.py` containing our **Deterministic Rule-Based Decision Tree**:
  1. Gate 1: Scam / Phishing Gate (`contains_sensitive_request=true` in unsafe flow OR `risk_label in [high, critical]`) $\rightarrow$ `mute` / `scam`.
  2. Gate 2: Promotional Consent Gate (`allows_promotions=0` + `promotion_or_offer`) $\rightarrow$ `mute` / `promotion`.
  3. Gate 3: Emergency Override Gate (`priority_label=critical`, safe) $\rightarrow$ `notify` / `urgent` (overrides DND & mutes).
  4. Gate 4: Actionable Operational Rule (`priority_label=high` + actionable/admin) $\rightarrow$ `notify`.
  5. Gate 5: DND & Muted Group Rule $\rightarrow$ `digest` (or `mute` for greetings/forwards).
  6. Gate 6: Opted-in Promotions $\rightarrow$ `digest` / `promotion`.
- [ ] Implement `calibration.py` assigning deterministic confidence (`0.95`, `0.90`, `0.85`, `0.70`, minus `0.15` for media extraction failure).
- [ ] Implement `fallback.py` to emit the Universal Safe-Default Row or run offline classification when API calls fail.

### Phase 4: Quality Assurance & Evaluation (`src/validator/` & `test/`)
- [ ] Implement `check_output.py` to enforce the **110-Row Completeness Invariant**, exact 6-column order, CSV quoting, and evidence ID existence in `message_history.csv`.
- [ ] Build offline unit test suite (`pytest`) mocking LLM responses to test domain invariant boundaries without network calls.
- [ ] Build property-based test suite (`test_properties.py`) using `Hypothesis` (`@given(st.sampled_from(...))`) to prove out-of-vocabulary labels never occur.
- [ ] Verify execution from terminal (`python code/main.py`) produces valid `dataset/output.csv`.

---

## 4. Concurrency & Deterministic Output Ordering (Asyncio Architecture)

To process 110 messages rapidly without rate limits or row shuffling:
1. **Input Indexing:** Each row in `messages.csv` is assigned its original zero-based positional index (`row_index = 0..109`).
2. **Concurrent Execution:** Messages are processed in parallel via `asyncio.gather(..., return_exceptions=True)` regulated by an `asyncio.Semaphore(10)`.
3. **Exception Recovery:** If any row raises an unhandled exception during async processing, `fallback.py` emits the Universal Safe-Default Row so no row is dropped.
4. **Deterministic Sorting:** Upon completion of all 110 async tasks, results are sorted by `row_index` before writing `output.csv`.

---

## 5. Verification Checklist Before Final Submission

- [x] All 13 Edge Cases mapped to deterministic rules in `EDGE_CASES.md`.
- [x] Threat analysis & API failure fallbacks documented in `THREAT_ANALYSIS.md`.
- [x] Universal Safe-Default Row contract codified in `IMPLEMENTATION.md`.
- [x] Prompts externalized to top-level `prompts/` YAML files (editable without code changes).
- [ ] Zero hardcoded magic strings or numeric weights in Python logic.
- [ ] 100% of sample rows pass offline Decision Tree scorecard (`test/test_formula_offline.py`).
- [ ] End-to-end run generates `output.csv` with exactly 110 rows and zero schema violations.
