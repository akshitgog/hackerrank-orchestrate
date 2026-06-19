# HackerRank Orchestrate: Implementation Plan

This document outlines the final, frozen architecture based on the "One place to change = everything adapts" principle.

---

## 1. Directory Structure

```text
.
├── AGENTS.md                         # Rules and logs configuration
├── problem_statement.md              # Requirements and constraints
├── README.md                         # Project documentation
├── log.txt                           # Shared session/architecture log
├── planning/
│   └── master_schema.json            # Exact JSON contract for all inputs/outputs
├── dataset/
│   ├── sample_claims.csv             # 20 labeled claims (Development)
│   ├── claims.csv                    # 45 unlabeled claims (Production Input)
│   ├── user_history.csv              # Risk signals per user
│   ├── evidence_requirements.csv     # VLM constraints per object
│   ├── synthetic_claims.csv          # Golden edge-case testing set
│   └── images/                       # Local disk storage for all images
├── config/
│   ├── providers.yaml                # ONLY place provider + model is defined
│   └── dataset.yaml                  # ONLY place dataset paths are defined
├── .env.example                      # Template for API keys
└── src/
    ├── main.py                       # Orchestrator entry point
    ├── core/
    │   └── config.py                 # ONLY file that reads secrets and config variables (including base image path)
    ├── llm/
    │   ├── client.py                 # Abstract router. Knows about providers, routes requests.
    │   └── providers/
    │       ├── bedrock.py            # Boto3 logic
    │       ├── anthropic.py          # Anthropic SDK logic
    │       ├── openai.py             # OpenAI SDK logic
    │       └── mock.py               # Returns fixture JSON ($0 cost)
    ├── pipeline/
    │   ├── extractor.py              # LLM logic to parse user_claim -> {component, issue}
    │   ├── assessor.py               # VLM logic. Injects prompt, handles image paths.
    │   └── validator.py              # Validates VLM JSON schema and enums
    ├── tools/
    │   └── decision_engine.py        # Python logic to aggregate multi-image outputs
    ├── models/
    │   ├── evidence.py               # Pydantic schemas for VLM output
    │   └── decision.py               # Pydantic schemas for Final output
    └── prompts/
        └── vlm_system_prompt.txt     # Finalized agnostic VLM instruction
```

---

## 2. The 4-Layer Architecture

### Layer 1 — VLM Prompt
The prompt in `src/prompts/vlm_system_prompt.txt` is **object-agnostic** but **reviewer-aware**.
It contains rules for quality, authenticity, severity, and confidence. It does *not* contain specific knowledge about cars, laptops, or packaging.

### Layer 2 — Pipeline Extractor & Assessor
`extractor.py` reads the `user_claim` and uses a cheap LLM to extract `{object}`, `{component}`, and `{issue}`.
It dynamically fetches the `{evidence_requirements}`.
`assessor.py` injects these 4 variables into the VLM prompt and passes the local image path to the client.

### Layer 3 — Provider Abstraction
`src/llm/client.py` is the only file that knows providers exist.
It reads `config/providers.yaml`. If the config says `provider: mock`, it routes to `mock.py` which returns static JSON. If `provider: anthropic`, it routes to `anthropic.py`.
**Switching providers requires changing one line in `providers.yaml` and zero code changes.**

### Layer 4 — Secrets and Environment Management
`src/core/config.py` is the singular truth for environment variables and paths.
It reads `.env` for API keys (e.g., `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`).
It reads `config/dataset.yaml` to locate the `dataset/` directory and image base paths.
No hardcoded paths or keys exist in the pipeline code. If a user clones this repo, they only need to update `.env` and `dataset.yaml` to run it.

---

## 3. Data Flow (Multi-Image Bifurcation)

1. **Extraction:** `extractor.py` -> returns `component`, `issue`.
2. **Assessment (VLM Loop):** `assessor.py` loops over `image_paths`. If a claim has 3 images, `assessor.py` calls the VLM 3 times. It produces an array of 3 JSON `vlm_output` objects.
3. **Decision Bifurcation:** The `decision_engine.py` receives the array of 3 outputs. It resolves conflicts (e.g., if img1 contradicts, but img2 supports, the engine logic determines the final `claim_status`). It picks the "best" image to extract `issue_type` and `severity`. It merges visual risk flags from all images with history flags from `user_history.csv`.
4. **Final Output:** The aggregated result is validated by `validator.py` and written as a single row to `output.csv`.

---

## 4. Testing Strategy

The testing stack isolates different layers of the system. The key principle is to not use one dataset for all three purposes:

### 1. Logic Regression Dataset
- **Purpose**: Test the Risk Engine, Decision Engine, and Output Generator without VLM API costs.
- **Input**: Hand-written JSON combining mock `user_history` and `vlm_outputs`. No images.
- **Target**: 30-50 hand-written cases.
- **Expected**: Exact JSON output (e.g., `claim_status`, `risk_flags`).

### 2. Synthetic Claim Dataset
- **Purpose**: Test full pipeline behavior on complex edge cases (e.g., multiple conflicting images, annotated images, zoomed images, wrong components).
- **Input**: Generated claims, user history, expected VLM outputs, and (optionally) generated matching images.
- **Target**: 20-30 edge claims.
- **Expected**: Final CSV rows matching edge-case behavior.

### 3. Organizer Dataset
- **Purpose**: Measure actual competition performance.
- **Input**: The provided `dataset/sample_claims.csv` and provided test images.
- **Target**: Real competition data.
- **Expected**: Output matches provided expected CSV.
