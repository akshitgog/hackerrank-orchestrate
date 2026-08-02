# Testing Playbook

**Project:** HackerRank Orchestrate — WhatsApp Message Notification Router

---

## 1. Test Philosophy

In AI classification systems, testing by generating unit tests directly from implementation code causes **circular validation** — proving only that the code is internally consistent rather than correct against the problem specification.

Our test suite follows a spec-first approach:
1. **Spec-Only Oracle:** Identify formal contracts from `problem_statement.md` without inspecting implementation.
2. **Synthetic Fixture Generation:** Create edge-case input/output fixtures from the specification.
3. **Golden Anchor Verification:** Manually audit critical edge cases against the specification.
4. **Regression Lock:** Commit verified fixtures as immutable regression baselines.

---

## 2. Decoupled Offline Testing

Every domain invariant is tested in **complete isolation using mock structured objects** (`SensorObservation`) without calling live external LLM/VLM/STT APIs.

Benefits:
- **0ms Latency & $0.00 API Cost:** Full test suite executes in under 2 seconds.
- **Pinpoint Fault Isolation:** A test failure points to exactly one function.
- **Offline Execution:** Runs without secrets or network access.

---

## 3. Randomized Invariant Fuzzing

`test_property_invariants.py` uses `random.seed(42)` with a deterministic loop to generate **500 permutations** of edge-case inputs across the valid enum space:

| Dimension | Values Fuzzed |
| :--- | :--- |
| `content_intent` | All 13 allowed intents |
| `priority_label` | critical, high, medium, low |
| `risk_label` | critical, high, medium, low, none |
| `is_actionable` | True, False |
| `is_dnd` | True, False |
| `is_opted_out` | True, False |

**Invariants verified across all 500 permutations:**
1. Action is always in `{notify, digest, mute}`
2. Confidence is within `[0.0, 1.0]`
3. High/critical risk always routes to `mute`
4. Non-scam critical priority with low/no risk always routes to `notify`
5. Low engagement source with non-urgent content never routes to `notify`

---

## 4. 4-Tier Test Directory Architecture

```text
code/tests/
├── conftest.py                   # Shared offline mocks and builder helpers (obs, media, decide_obs)
├── test_schema_seams.py          # TIER 1: Pydantic v2 boundary validation tests
├── test_regression_fixtures.py   # TIER 2: Golden Anchor regression fixtures (9 critical cases)
├── test_property_invariants.py   # TIER 3: 500-permutation randomized invariant fuzzing
└── test_system_acceptance.py     # TIER 4: Dataset integrity acceptance tests
```

### Tier 1 — Schema Boundary Tests (`test_schema_seams.py`)
Verifies that Pydantic `SensorObservation` and `MediaExtraction` models:
- Accept valid enum values
- Reject out-of-vocabulary values with `ValidationError`
- Handle all required fields correctly

### Tier 2 — Regression Fixtures (`test_regression_fixtures.py`)
Uses helper builders (`obs()`, `decide_obs()`) to test critical routing decisions:
- Emergency override during DND -> `notify`
- Scam/phishing -> `mute`
- Promotional opt-out -> `mute`
- Critical urgency -> `notify`
- High priority actionable -> `notify`
- DND quiet hours -> `digest`
- Opted-in promotions -> `digest`
- Default fallback -> `digest`

### Tier 3 — Invariant Fuzzing (`test_property_invariants.py`)
500 randomized permutations proving system-wide invariants hold across the entire valid input space.

### Tier 4 — System Acceptance (`test_system_acceptance.py`)
- Verifies `dataset/messages.csv` contains exactly 110 unique rows
- Verifies `load_all_data()` loads all CSV files without referential integrity errors

---

## 5. Running Tests

```bash
cd code
python -m pytest tests/ -q
```

All 15 tests execute offline in under 2 seconds with zero API calls.
