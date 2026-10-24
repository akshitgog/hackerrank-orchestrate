# Software Engineering Rules & Standards

## 1. Secrets & Credentials Management
1. **Never commit secrets:** API keys, tokens, credentials, or private configuration must never be hardcoded or committed to git.
2. **Environment Variables:** All secrets must be loaded exclusively via environment variables from `code/.env` (using `python-dotenv`).
3. **Template Repository File:** Maintain `code/.env.example` in version control with dummy placeholders to guide setup.

---

## 2. Configuration & Parameter Architecture
1. **Zero Hardcoded Constants:** Model names, threshold grids, timeouts, file paths, and retry limits must reside in `code/config/config.yaml`.
2. **Dynamic Overrides:** The configuration loader must allow overriding configuration parameters via environment variables or CLI flags without changing source code.

---

## 3. Code Quality & Modularity Standards
1. **Strict Type Hinting:** All functions and methods must use Python 3.10+ type annotations (`set[str]`, `list[dict]`, `Optional[str]`).
2. **Typed Data Models:** Data passed between sub-agents must use strongly-typed dataclasses or Pydantic models (e.g. `UserIdentityProfile`, `AuditFinding`, `RemediationStep`).
3. **Single Responsibility Principle:** Each sub-agent directory contains its own domain logic, isolated from other sub-agents.
4. **Idempotence & Pure Functions:** Database querying, JSON sorting, and identity matching must be pure, idempotent functions with zero side effects on the input dataset.

---

## 4. Guardrails & Error Resilience
1. **Guardrails for Every Sub-Agent:** Every sub-agent must have a paired validator in `code/guardrails/` that asserts input and output validity before returning data to the Orchestrator.
2. **Bounded Retry Loops:** The Orchestrator must support bounded retries ($N \le 3$) for guardrail failures, providing explicit feedback prompts on what failed.
3. **Fail-Safe Fallbacks:** If maximum retries are exceeded, the agent must fallback to safe deterministic behavior rather than crashing.

---

## 5. Caching & Performance
1. **Lazy On-Demand Caching:** Multimodal evidence (PDFs and PNGs) must only be processed when explicitly required by a case, and cached immediately to disk (`cache/multimodal_cache.json`).
2. **Memory Efficiency:** In-memory SQLite connections should be scoped or reused efficiently to avoid memory leaks over 518 sequential iterations.

---

## 6. Evaluation History & Audit Trail
1. **Evaluation Logging:** Every invocation of `code/evaluation/main.py` must append a structured JSON line to `code/evaluation/evaluation_history.jsonl` documenting:
   - Timestamp
   - Threshold used
   - Accuracy, Precision, Recall, F1
   - Total model calls and token consumption
2. **Documentation Integrity:** Preserve all existing comments and documentation unrelated to code changes.
