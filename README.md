# Message Notification Router

This project looks at the context of an incoming WhatsApp message (the text, images, voice notes, the sender's history, and your DND status) and decides whether that message should **notify** you immediately, be saved for a **digest**, or be silently **muted**. It then fills in a structured record explaining exactly why that decision was made.

I built it for the **HackerRank Orchestrate** hackathon (August 2026), a 24-hour event to design and ship an AI agent.

---

## What it produces

For every message, the agent emits a fixed 6-column row: `message_id`, `action`, `message_type`, `reason`, `confidence`, and `evidence_message_ids`. Allowed values for every field live in one place (`schema_models.py`) so the prompt, the validator, and the output can never drift apart.

---

## Architecture

Two LLM calls drive a chain-of-thought perception loop per message. All context is pre-fetched in pure Python; the model never sees engagement scores or makes the final routing call.

```
messages.csv + 10 context CSVs + media/
        |
        v
Deterministic loading            context/load_dataset.py, user_profiles.py
  . user profile, DND, group membership, business relationship
  . per-source engagement score (opened / dismissed — pure math)
  . sender interaction rates (open, dismiss, reply)
        |
        v
Media extraction                 classifiers/media_extractor.py
  . image -> VLM observation -> LLM image router (2 calls, cached)
  . voice -> Deepgram STT -> normalization (cached)
        |
        v
Chain-of-thought perception      classifiers/llm_client.py
  . Call 1 (msg_observer):       boolean signal extraction from message text
  . Call 2 (msg_router):         intent classification from signals (not raw text)
  . both cached by SHA-256 of prompt content
        |
        v
Pydantic typed seam              classifiers/schema_models.py
  . SensorObservation: validates every LLM field against Literal enums
  . invalid output -> fallback to regex heuristic (never crashes)
        |
        v
Deterministic decision tree      routing_engine/decision_tree.py
  . 8 gates in strict priority order (see below)
  . engagement score applied here, not in the LLM prompt
        |
        v
Confidence calibration           routing_engine/confidence_calibrator.py
        |
        v
output.csv   (6 columns, deterministic row order)
```

A single failing message never crashes a batch: `safe_fallback.py` degrades it to a conservative fallback row (`digest` / `unknown` / confidence 0.50) so `output.csv` always has exactly one row per input.

---

## Key design decisions

### User profiling as the central design choice

The problem statement says: *"A sale poster may be useful for one user and unwanted noise for another."* Most systems answer "is this message important?" — ours answers **"is this message important TO THIS USER?"** by building a per-source engagement profile from dataset columns that most systems ignore.

**Three engagement tiers from three different tables.** The system computes `opened / (opened + dismissed)` at three granularities, then picks the most specific one available:

| Tier | Source table | Columns used | What it captures |
|---|---|---|---|
| Global | `users.csv` | `messages_opened_30d`, `notifications_dismissed_30d` | Is this user generally engaged? |
| Business | `user_business_history.csv` | `messages_opened_30d`, `messages_dismissed_30d` | Does this user care about *this brand*? |
| Group | `group_members.csv` | `messages_read_30d`, `notifications_dismissed_30d` | Does this user engage with *this group*? |

Selection priority: business > group > global. A message from Zepto to a user who opened 8/9 messages from Zepto gets a different routing decision than the same message to a user who dismissed 7/9 — without the LLM ever knowing the difference.

**Personalization can only demote, never upgrade.** Gate 3.7 (low engagement demotion) sits *below* the safety gates in the decision tree. If `source_engagement < 0.25` and priority isn't critical/high, the message demotes to `digest`. But a genuine scam is still muted at Gate 1 regardless of engagement, and an emergency still notifies at Gate 3. This is a structural guarantee in the gate ordering, not a prompt instruction the model might ignore.

**Engagement stays out of the LLM prompt.** The engagement score feeds the deterministic decision tree only. The LLM prompt never sees it — keeping the SHA-256 cache hash stable across re-runs. Repeat runs with no code changes complete in under 2 seconds at zero cost. Most systems would ask the LLM "does this user care about this sender?" — expensive, non-deterministic, and uncacheable.

See [`doc/ARCHITECTURE_PLANNING.md` §5.7](doc/ARCHITECTURE_PLANNING.md) for the full engagement computation and [`doc/DATASET_ANALYSIS.md` §3](doc/DATASET_ANALYSIS.md) for which dataset columns map to which personalization signals.

---

### Supporting design decisions

**Safety gate in code, not in the prompt.** Prompt instructions can be argued away by adversarial message content; post-model rules cannot. Gate 1 unconditionally mutes phishing regardless of what the LLM says about priority or actionability.

**Two-stage chain-of-thought.** A single prompt that both observes AND classifies forces the model to resolve ambiguous messages into one bucket. Splitting into observer (what signals exist?) and router (what do they mean?) means you can trace errors to exactly one stage and fix it with a prompt edit.

**Protecting operational alerts.** The LLM flagged work messages ("missed water supply", "server deadline") as high-risk threats because they contained urgency language. One sentence in `msg_router.yaml` ("Never assign high risk to operational messages without credential signals") fixed both false positives permanently.

---

## The 8-Gate Decision Tree

| Gate | What it does |
|---|---|
| **Gate 1** — Scam / Phishing | Mutes anything with credential requests, account threats, prompt injection, or high risk — splits into `scam` (phishing) vs `spam` (suspicious but no credentials). |
| **Gate 2** — Promo opt-out | Mutes promotional messages when the user has `allows_promotions=0` in their business relationship. |
| **Gate 3** — Emergency override | Forces `notify`/`urgent` for critical-priority + low-risk messages, even during DND or muted groups. |
| **Gate 3.5** — Sender fatigue | Mutes low-value intents (forwards, greetings, promos) when the sender's dismiss rate is ≥50% or they have zero opens. |
| **Gate 3.7** — Low engagement | Demotes to `digest` when `source_engagement < 0.25` and priority isn't critical/high — the personalization gate. |
| **Gate 4** — Actionable high-priority | Notifies when priority is `high` AND the message is actionable or sender is admin. |
| **Gate 5** — DND / muted group | Digests non-urgent messages during quiet hours; mutes low-value chatter in user-muted groups. |
| **Gate 6** — Opted-in promos | Routes promotional content to `digest`/`promotion` when the user still allows promotions. |
| **Gate 7** — Default fallback | Everything that didn't trigger an earlier gate falls to `digest` with an intent-mapped type. |

Safety gates (1–3) fire first and cannot be overridden by personalization. Engagement (3.7) only ever demotes to digest, never upgrades a muted threat. This is a structural guarantee in the gate ordering.

---

## Project structure

```
.
├── README.md
├── problem_statement.md
├── dataset/                  11 CSV files + media/images/ + media/audio/
├── doc/                      design write-ups (architecture, safety, testing, edge cases)
└── code/
    ├── main.py               batch runner: messages.csv -> output.csv
    ├── config/
    │   ├── config.yaml       model selection, thresholds, engagement config
    │   └── settings.py       Pydantic v2 fail-fast boot validation
    ├── env/                  .env (secrets, never committed)
    ├── prompts/              5 YAML templates (editable without code changes)
    │   ├── msg_observer.yaml     signal extraction (Call 1)
    │   ├── msg_router.yaml       intent classification (Call 2)
    │   ├── vlm_observer.yaml     VLM image observation
    │   ├── img_router.yaml       image classification
    │   └── stt_config.yaml       STT normalization rules
    ├── src/
    │   ├── context/          dataset loading, user profiles, engagement scores
    │   ├── classifiers/      LLM/VLM/STT adapters, cache, schema validation
    │   ├── routing_engine/   decision tree, confidence calibrator, safe fallback
    │   └── output_validator/ 110-row completeness + enum + evidence checks
    ├── tests/                15 offline tests (no API key needed)
    └── evaluation/           scoring tools + ground-truth comparison
```

---

## Model selection

All model names live in `code/config/config.yaml` using LiteLLM's prefix format:

```yaml
models:
  llm_model: "bedrock/amazon.nova-micro-v1:0"    # Text classification
  vlm_model: "bedrock/amazon.nova-lite-v1:0"     # Image analysis
  stt_model: "deepgram/nova-3"                   # Voice note transcription
```

| Provider | Prefix | Required env var |
|---|---|---|
| AWS Bedrock | `bedrock/` | `AWS_ACCESS_KEY_ID` + `AWS_SECRET_ACCESS_KEY` |
| Google Gemini | `gemini/` | `GEMINI_API_KEY` |
| OpenAI | `openai/` | `OPENAI_API_KEY` |
| Anthropic | `anthropic/` | `ANTHROPIC_API_KEY` |
| Fireworks AI | `fireworks_ai/` | `FIREWORKS_API_KEY` |
| Deepgram (STT) | `deepgram/` | `DEEPGRAM_API_KEY` |

Override at runtime without touching the config:
```bash
export ORCHESTRATE_LLM_MODEL="gemini/gemini-2.5-flash"
python code/main.py
```

If model names are absent from `config.yaml`, the system auto-selects based on whichever API key it finds.

---

## Setup & Running

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp code/env/.env.example code/env/.env   # add your API keys

# Run the full pipeline
python code/main.py

# Run offline tests (no API key needed, <1s)
cd code && python -m pytest tests/ -q
```

---

## Testing

15 tests across 4 tiers, all offline:

- **Schema boundaries:** Pydantic rejects invalid LLM output enum values
- **Regression fixtures:** 9 critical edge cases (emergency override, scam suppression, DND)
- **Randomized invariant fuzzing:** 500 permutations proving the tree never emits invalid actions or out-of-bounds confidence
- **Dataset acceptance:** CSV integrity and 110-row completeness

---

## Software engineering principles applied

### Architecture patterns

| Pattern | Where it shows up |
|---|---|
| **Hexagonal architecture (Ports & Adapters)** | Core routing logic has zero knowledge of external services. LLM providers (Bedrock, Gemini, OpenAI) sit behind an adapter port (`llm_client.py` → LiteLLM). Dataset files enter through a loading port (`load_dataset.py`). Output exits through a validation port (`output_validator/`). The core domain (`decision_tree.py`) is testable with no network, no API keys, no filesystem. |
| **Chain of Responsibility** | The 8-gate decision tree is a literal chain — each gate either handles the message and returns a decision, or passes control to the next gate. Adding Gate 3.7 required zero changes to existing gates. |
| **Strategy pattern** | Media extraction selects strategy by `media_type`: VLM pipeline for images, STT pipeline for voice, no-op for text-only. Each strategy is interchangeable behind the same interface. |
| **Pipeline pattern (async)** | Each message flows through context→media→observer→router→decision→calibration stages via `asyncio.gather` with semaphore-bounded concurrency. Stages are composable and independently testable. |
| **Cache-aside pattern** | SHA-256 of prompt content → check local cache → hit returns instantly, miss calls API and stores. Content-addressed, so identical prompts across different messages share cache entries. |

### SOLID & engineering principles

| Principle | Where it shows up |
|---|---|
| **Separation of concerns** | LLM only extracts signals; pure Python decides routing. Neither layer knows the other's internals — they communicate through a typed Pydantic contract (`SensorObservation`). |
| **Single source of truth** | All allowed enum values live in `schema_models.py`. The prompt, the validator, and the CSV writer all derive from one definition — they cannot drift. |
| **Fail-safe defaults** | Any unhandled exception produces a conservative `digest`/`unknown`/0.50 row via `safe_fallback.py`. The system never drops a row, never crashes a batch, and never emits an undeserved `notify`. |
| **Deterministic reproducibility** | SHA-256 content-addressed cache on every LLM call. Same input → same hash → same cached response. Zero cost on re-runs, bit-for-bit identical output. |
| **Open/closed principle** | New gates are added by inserting a function at a priority level — existing gates don't change. Gate 3.7 (engagement) was added without modifying Gates 1–6. |
| **Dependency inversion** | The decision tree depends on abstract label enums, not on which LLM produced them. Swapping the model (Bedrock → Gemini → OpenAI) changes one config line, not the routing logic. |
| **Defensive input handling** | Message text is untrusted user data. The prompt wraps it in XML tags and instructs the model to classify adversarial override attempts as `prompt_injection`. Code enforces the mute — the model only flags. |
| **Configuration over code** | Thresholds (`low_engagement_threshold`, confidence per gate, model names) live in `config.yaml`. Tuning doesn't require a code change or a re-deploy. Pydantic validates the config at boot. |
| **Spec-first testing** | Tests are derived from `problem_statement.md` invariants, not from implementation. 500 randomized permutations prove the tree never violates spec contracts regardless of input combination. |

---

## Lessons learned

- **Let the model observe; let code decide.** Auditability and safety guarantees come almost for free when the LLM only extracts signals and deterministic gates make the final call.
- **Keep volatile data out of the LLM prompt.** Engagement scores belong in the decision tree, not the prompt. This preserves cache stability and keeps costs near zero on repeat runs.
- **Be explicit about what you constrain.** The single most impactful fix was one sentence in the router prompt. Explicit constraints beat hoping the model figures it out.
- **Personalize with math, not prompts.** An engagement ratio in 5 lines of Python is deterministic, testable, and free. Asking an LLM the same question is expensive and unreliable.
