# IMPLEMENTATION.md — Codebase Architecture

This document describes the implemented architecture of the HackerRank Orchestrate Message Notification Router.

---

## 1. Codebase Architecture (4-Layer Clean Hierarchy)

The repository is organized into four modular layers, separating **probabilistic sensors** from **deterministic domain invariants**:

```text
dataset/                        # The 11 CSV dataset files + media/
doc/                            # Architecture specs & analysis
code/
├── config/                     # Declarative configuration & Pydantic v2 validation
│   ├── config.yaml             # Externalized model names, thresholds, paths
│   └── settings.py             # Pydantic v2 fail-fast boot validation
├── env/                        # Secrets & environment variable templates
│   ├── .env                    # Secrets file (never committed)
│   └── .env.example            # Template for required environment variables
├── prompts/                    # YAML prompt templates (editable without code changes)
│   ├── msg_observer.yaml       # LLM signal extraction (boolean flags from raw message)
│   ├── msg_router.yaml         # LLM intent classification (from signals + history)
│   ├── vlm_observer.yaml       # VLM image observation
│   ├── img_router.yaml         # LLM image classification (from VLM observation)
│   └── stt_config.yaml         # STT normalization rules for Hindi-English code-switching
├── src/
│   ├── context/                # LAYER 1: DATASET & CONTEXT STORE (Pure Python)
│   │   ├── load_dataset.py     # DatasetContext: indexes all CSV files with typed primary keys
│   │   ├── message_history.py  # On-demand sender/business/group history lookups
│   │   └── user_profiles.py    # DND quiet hours, fatigue, group membership, engagement ratios
│   ├── classifiers/            # LAYER 2: PROBABILISTIC CLASSIFIERS & EXTRACTORS (LLM/VLM/STT)
│   │   ├── schema_models.py    # Pydantic v2 typed seam: SensorObservation, MediaExtraction
│   │   ├── response_cache.py   # SHA-256 deterministic API response cache
│   │   ├── llm_client.py       # LiteLLM async adapter with retry, semaphore, self-correction
│   │   ├── media_extractor.py  # Pillow image preprocessing + VLM/STT extraction with fallback
│   │   └── prompt_loader.py    # YAML prompt template loader and STT normalization
│   ├── routing_engine/         # LAYER 3: DETERMINISTIC ROUTER (Pure Python, zero network)
│   │   ├── decision_tree.py    # 8-Gate deterministic decision tree (with engagement personalization)
│   │   ├── confidence_calibrator.py  # Config-driven confidence assignment per gate
│   │   └── safe_fallback.py    # Universal safe-default row & regex heuristic classifier
│   └── output_validator/       # LAYER 4: OUTPUT CONTRACT ENFORCEMENT
│       └── validate_output_csv.py  # 110-row completeness, enum vocabulary, evidence validation
├── tests/                      # Offline test suite (pytest)
│   ├── conftest.py             # Shared fixtures and helper builders
│   ├── test_schema_seams.py    # Pydantic boundary validation
│   ├── test_regression_fixtures.py  # Golden anchor regression tests
│   ├── test_property_invariants.py  # 500-permutation randomized invariant fuzzing
│   └── test_system_acceptance.py    # Dataset integrity acceptance tests
├── evaluation/                 # Post-run evaluation tools
│   ├── evaluation.py           # Statistical scorecard metrics
│   ├── compare.py              # Ground-truth comparison tool
│   └── main.py                 # CLI scorecard runner
└── main.py                     # CLI entry point; asyncio event loop & batch pipeline
```

---

## 2. Universal Safe-Default Row Contract

To guarantee zero dropped rows and 100% adherence to the 110-row Completeness Invariant, whenever any layer fails unrecoverably for a row, `safe_fallback.py` emits:

```json
{
  "action": "digest",
  "message_type": "unknown",
  "reason": "Automated pipeline fallback due to unrecoverable sensor error.",
  "confidence": 0.50,
  "evidence_message_ids": "none"
}
```

When the LLM returns `None` but no hard crash occurs, the regex-based heuristic classifier (`heuristic_classify`) provides a more informed fallback using keyword patterns for scam, urgency, greeting, and promotion detection.

---

## 3. Two-Stage LLM Architecture (Chain-of-Thought)

The pipeline uses two sequential LLM calls per message to prevent classification collapse:

**Problem:** A single prompt that both observes AND classifies forces the model to resolve ambiguous messages into one bucket, silently discarding secondary signals. E.g., "Your account will be blocked — verify OTP now" fires BOTH `account_threat` AND `credential_request`.

**Solution:**
1. **Stage 1 — Signal Extraction (`msg_observer.yaml`):** Reports boolean flags (what signals are present). Multiple signals can be true simultaneously.
2. **Stage 2 — Intent Classification (`msg_router.yaml`):** Receives the signal report and resolves priority conflicts explicitly using documented priority rules. Constrained to never assign high/critical risk to operational messages without credential signals.

This chain-of-thought separation means:
- Debugging is precise: observer correct + router wrong → prompt tuning issue only
- Changing routing logic only requires editing `msg_router.yaml` — the observer remains stable
- The decision tree receives clean, separated intent/priority/risk labels to enforce deterministic rules

---

## 4. Concurrency & Deterministic Output Ordering

To process 110 messages concurrently without rate limit violations or row shuffling:

1. **Input Indexing:** Each message is assigned its zero-based positional index (`row_index`).
2. **Concurrent Execution:** Messages are processed via `asyncio.gather(*tasks)` regulated by `asyncio.Semaphore(max_concurrency)` from config.
3. **Exception Recovery:** If any row raises an unhandled exception, `safe_fallback.py` emits the safe-default row. No row is dropped.
4. **Deterministic Sorting:** Results are sorted by `row_index` before writing `output.csv`.

---

## 5. Per-Source Engagement Personalization

The system answers "is this message important TO THIS USER?" using pure Python engagement ratios:

| Signal | Source | Formula |
| :--- | :--- | :--- |
| `global_engagement` | `users.csv` | `messages_opened_30d / (opened + dismissed)` |
| `business_engagement` | `user_business_history.csv` | `messages_opened_30d / (opened + dismissed)` per user×business |
| `group_engagement` | `group_members.csv` | `messages_read_30d / (read + dismissed)` per user×group |
| `source_engagement` | Computed | Most relevant score: business > group > global |

Gate 3.7 uses `source_engagement`: if below `low_engagement_threshold` (default 0.25) and priority is not critical/high, the message is demoted to digest regardless of content type.

This uses dataset signals the problem statement provides without hardcoding to specific rows.

---

## 6. Configuration & Provider Flexibility

All model names, thresholds, and paths are externalized to `config.yaml` + environment variables:

- Model names use LiteLLM prefix format (e.g., `bedrock/amazon.nova-micro-v1:0`, `gemini/gemini-2.5-flash`)
- Provider auto-detection from available API keys in `.env`
- ENV overrides via `ORCHESTRATE_LLM_MODEL`, `ORCHESTRATE_VLM_MODEL`, `ORCHESTRATE_STT_MODEL`
- Confidence thresholds per gate are configurable without code changes
- Personalization threshold (`low_engagement_threshold`) configurable in `config.yaml`
- Concurrency, retries, and timeouts are configurable

---

## 7. Verification Checklist

- [x] Edge cases mapped to deterministic rules in decision tree
- [x] Universal safe-default row guarantees zero dropped rows
- [x] Prompts externalized to YAML files (editable without code changes)
- [x] All model names read from config (zero hardcoded model strings in source)
- [x] Per-source engagement personalization using dataset signals
- [x] LLM risk constraint prevents false-positive muting of work messages
- [x] 15 offline tests pass (`python -m pytest code/tests/ -q`)
- [x] Pipeline produces valid output with correct schema
- [x] Action accuracy 76.67%, Type accuracy 70% on 30-row sample
