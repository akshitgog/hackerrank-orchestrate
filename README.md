# Message Notification Router

> **HackerRank Orchestrate Hackathon · August 2026**

Most notification systems ask *"is this message important?"* — this one asks **"is this message important to *this* user?"**

It reads an incoming WhatsApp message (text, images, voice notes), cross-references the sender's history and the user's engagement patterns, then routes to one of three actions: **notify**, **digest**, or **mute** — with a structured explanation of exactly why.

**TL;DR**
- 2 LLM calls per message (observer → router); all other logic is pure Python
- Per-user engagement scores built from 11 CSVs; the LLM never sees them
- 9-gate deterministic decision tree; safety gates cannot be overridden
- SHA-256 content cache — repeat runs complete in <2s at zero cost

---

## Output

Each message produces exactly one row in `output.csv`:

| Column | Example |
|---|---|
| `message_id` | `msg_042` |
| `action` | `digest` |
| `message_type` | `promotion` |
| `reason` | `low engagement with sender` |
| `confidence` | `0.72` |
| `evidence_message_ids` | `msg_011, msg_019` |

All allowed values are defined once in `schema_models.py` — the prompt, validator, and CSV writer share the same source and cannot drift.

---

## Architecture

Two LLM calls drive a chain-of-thought perception loop per message. All context is pre-fetched in pure Python; the model never sees engagement scores or makes the final routing call.

```text
┌───────────────────────────────────────────────────────────────────────────┐
│  INPUT  ·  messages.csv + 10 context CSVs + media/                        │
└────────────────────────────────────┬──────────────────────────────────────┘
                                     │
                                     ▼
┌───────────────────────────────────────────────────────────────────────────┐
│  DETERMINISTIC LOADING  ·  load_dataset.py  —  profile, DND, engagement   │
└────────────────────────────────────┬──────────────────────────────────────┘
                                     │
                                     ▼
┌───────────────────────────────────────────────────────────────────────────┐
│  MEDIA EXTRACTION  ·  media_extractor.py  —  image→VLM  ·  voice→STT      │
└────────────────────────────────────┬──────────────────────────────────────┘
                                     │
                                     ▼
┌───────────────────────────────────────────────────────────────────────────┐
│  LLM PERCEPTION  ·  llm_client.py  —  observer→router, SHA-256 cached     │
└────────────────────────────────────┬──────────────────────────────────────┘
                                     │
                                     ▼
┌───────────────────────────────────────────────────────────────────────────┐
│  PYDANTIC SEAM  ·  schema_models.py  —  enum checks, regex fallback       │
└────────────────────────────────────┬──────────────────────────────────────┘
                                     │
                                     ▼
┌───────────────────────────────────────────────────────────────────────────┐
│  DECISION TREE  ·  decision_tree.py  —  9 gates, engagement applied       │
└────────────────────────────────────┬──────────────────────────────────────┘
                                     │
                                     ▼
┌───────────────────────────────────────────────────────────────────────────┐
│  CONFIDENCE CALIBRATION  ·  confidence_calibrator.py                      │
└────────────────────────────────────┬──────────────────────────────────────┘
                                     │
                                     ▼
┌───────────────────────────────────────────────────────────────────────────┐
│  OUTPUT  ·  output.csv  —  6 columns, deterministic row order             │
└───────────────────────────────────────────────────────────────────────────┘
```

| Stage | What happens |
|---|---|
| **Input** | 11 CSV files + media folder loaded as the raw dataset |
| **Deterministic Loading** | Builds user profile, DND status, group membership, business relationship, and per-source engagement scores — pure Python, no LLM |
| **Media Extraction** | Images routed through VLM observation + LLM image classifier (2 calls); voice notes transcribed via Deepgram STT — both cached |
| **LLM Perception** | Call 1 (`msg_observer`) extracts boolean signals from message text; Call 2 (`msg_router`) classifies intent from those signals, not raw text |
| **Pydantic Seam** | `SensorObservation` validates every LLM field against `Literal` enums; invalid output silently falls back to regex heuristic |
| **Decision Tree** | 9 gates in strict priority order apply engagement scores and route to `notify`, `digest`, or `mute` — LLM never touches this |
| **Confidence Calibration** | Adjusts raw confidence based on gate fired, signal strength, and engagement tier |
| **Output** | One deterministic row per message: `message_id`, `action`, `message_type`, `reason`, `confidence`, `evidence_message_ids` |

A single failing message never crashes a batch — `safe_fallback.py` writes a conservative `digest / unknown / 0.50` row so `output.csv` always has exactly one row per input.

---

## Key design decisions

### Personalization as the core insight

The problem statement says: *"A sale poster may be useful for one user and unwanted noise for another."*

This system computes a per-source engagement score — `opened / (opened + dismissed)` — at three granularities, then picks the most specific one available:

| Tier | Source | What it captures |
|---|---|---|
| Business | `user_business_history.csv` | Does this user care about *this brand*? |
| Group | `group_members.csv` | Does this user engage with *this group*? |
| Global | `users.csv` | Is this user generally engaged? |

A Zepto message to a user who opened 8 of 9 Zepto messages routes differently than the same message to one who dismissed 7 of 9 — without the LLM ever knowing the score.

**Personalization can only demote, never upgrade.** Gate 3.7 sits below all safety gates. A scam is still muted at Gate 1 regardless of engagement. An emergency still notifies at Gate 3. This is a structural guarantee in the gate ordering, not a prompt instruction.

**Engagement stays out of the LLM prompt** — keeping the SHA-256 cache hash stable across re-runs. Repeat runs with no code changes complete in under 2 seconds at zero cost.

---

### Other decisions that mattered

**Safety in code, not prompts.** Prompt instructions can be argued away by adversarial message content; post-model rules cannot. Gate 1 unconditionally mutes phishing regardless of what the LLM returns.

**Two-stage chain-of-thought.** Splitting into observer (what signals exist?) and router (what do they mean?) means errors are traceable to one stage and fixable with one prompt edit.

**One sentence fixed two false positives.** The LLM flagged work messages ("missed water supply", "server deadline") as high-risk because they contained urgency language. Adding *"Never assign high risk to operational messages without credential signals"* to `msg_router.yaml` fixed both permanently.

---

## The 9-Gate Decision Tree

Safety gates (1–3) fire first and cannot be overridden by personalization. Engagement (3.7) only ever demotes — it never upgrades a muted threat.

| Gate | Trigger | Action |
|---|---|---|
| **1** — Scam / Phishing | Credential requests, account threats, prompt injection | `mute` → `scam` or `spam` |
| **2** — Promo opt-out | `allows_promotions=0` in business relationship | `mute` |
| **3** — Emergency override | Critical priority + low risk | `notify` / `urgent`, DND ignored |
| **3.5** — Sender fatigue | Dismiss rate ≥50% or zero opens, low-value intent | `mute` |
| **3.7** — Low engagement | `source_engagement < 0.25`, non-critical priority | `digest` |
| **4** — Actionable high-priority | Priority `high` + actionable message or admin sender | `notify` |
| **5** — DND / muted group | Quiet hours or user-muted group | `digest` or `mute` |
| **6** — Opted-in promos | User allows promotions | `digest` / `promotion` |
| **7** — Default fallback | Everything else | `digest` with intent-mapped type |

---

## Project structure

```
.
├── README.md
├── problem_statement.md
├── dataset/                  CSV files + media/images/ + media/audio/
├── doc/                      design write-ups
└── code/
    ├── main.py
    ├── config/
    ├── env/                  .env (secrets, never committed)
    ├── prompts/               YAML templates (editable without code changes)
    ├── src/
    │   ├── context/
    │   ├── classifiers/
    │   ├── routing_engine/
    │   └── output_validator/
    ├── tests/
    └── evaluation/
```

### File guide

| Path | Purpose |
|---|---|
| `README.md` | Project overview |
| `problem_statement.md` | Original hackathon problem statement |
| `dataset/` | 11 CSV files + `media/images/` + `media/audio/` |
| `doc/` | Design write-ups — architecture, safety, testing, edge cases |
| `code/main.py` | Batch runner: `messages.csv` → `output.csv` |
| `code/config/config.yaml` | Model selection, thresholds, engagement config |
| `code/config/settings.py` | Pydantic v2 fail-fast boot validation |
| `code/env/` | `.env` (secrets, never committed) |
| `code/prompts/msg_observer.yaml` | Signal extraction (Call 1) |
| `code/prompts/msg_router.yaml` | Intent classification (Call 2) |
| `code/prompts/vlm_observer.yaml` | VLM image observation |
| `code/prompts/img_router.yaml` | Image classification |
| `code/prompts/stt_config.yaml` | STT normalization rules |
| `code/src/context/` | Dataset loading, user profiles, engagement scores |
| `code/src/classifiers/` | LLM/VLM/STT adapters, cache, schema validation |
| `code/src/routing_engine/` | Decision tree, confidence calibrator, safe fallback |
| `code/src/output_validator/` | 110-row completeness + enum + evidence checks |
| `code/tests/` | 15 offline tests (no API key needed) |
| `code/evaluation/` | Scoring tools + ground-truth comparison |

---

## Setup & running

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp code/env/.env.example code/env/.env   # add your API keys

python code/main.py                      # full pipeline
cd code && python -m pytest tests/ -q   # offline tests, no API key needed
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

Override at runtime: `export ORCHESTRATE_LLM_MODEL="gemini/gemini-2.5-flash"`

If model names are absent from `config.yaml`, the system auto-selects based on whichever API key it finds.

<details>
<summary>All supported providers</summary>

| Provider | Prefix | Required env var |
|---|---|---|
| AWS Bedrock | `bedrock/` | `AWS_ACCESS_KEY_ID` + `AWS_SECRET_ACCESS_KEY` |
| Google Gemini | `gemini/` | `GEMINI_API_KEY` |
| OpenAI | `openai/` | `OPENAI_API_KEY` |
| Anthropic | `anthropic/` | `ANTHROPIC_API_KEY` |
| Fireworks AI | `fireworks_ai/` | `FIREWORKS_API_KEY` |
| Deepgram (STT) | `deepgram/` | `DEEPGRAM_API_KEY` |

</details>

---

## Testing

15 tests across 4 tiers, all offline — no API key needed:

- **Schema boundaries** — Pydantic rejects invalid LLM output enum values
- **Regression fixtures** — 9 critical edge cases (emergency override, scam suppression, DND)
- **Randomized invariant fuzzing** — 500 permutations proving the tree never emits invalid actions or out-of-bounds confidence
- **Dataset acceptance** — CSV integrity and 110-row completeness

---

## Software engineering principles

<details>
<summary>Architecture patterns</summary>

**Hexagonal architecture (Ports & Adapters)** — Core routing logic has zero knowledge of external services. LLM providers sit behind `llm_client.py` → LiteLLM. Dataset files enter through `load_dataset.py`. Output exits through `output_validator/`. The core domain (`decision_tree.py`) is testable with no network, no API keys, no filesystem.

**Strategy pattern** — Media extraction selects strategy by `media_type`: VLM pipeline for images, STT for voice, no-op for text. Each strategy is interchangeable behind the same interface.

**Pipeline pattern (async)** — Each message flows through context → media → observer → router → decision → calibration via `asyncio.gather` with semaphore-bounded concurrency. Stages are composable and independently testable.

**Dependency inversion** — The decision tree depends on abstract label enums, not on which LLM produced them. Swapping models changes one config line, not the routing logic.

**Defensive input handling** — Message text is untrusted. The prompt wraps it in XML tags and classifies adversarial override attempts as `prompt_injection`. Code enforces the mute — the model only flags.

</details>

---

## Lessons learned

**Let the model observe; let code decide.** Auditability and safety guarantees come almost for free when the LLM only extracts signals and deterministic gates make the final call.

**Keep volatile data out of the LLM prompt.** Engagement scores belong in the decision tree, not the prompt. This preserves cache stability and keeps costs near zero on repeat runs.

**Be explicit about what you constrain.** The single most impactful fix was one sentence in the router prompt. Explicit constraints beat hoping the model figures it out.

**Personalize with math, not prompts.** An engagement ratio in 5 lines of Python is deterministic, testable, and free. Asking an LLM the same question is expensive and unreliable.
