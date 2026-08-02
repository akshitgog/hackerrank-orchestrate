# 🧪 PRODUCTION-GRADE TESTING PLAYBOOK (`testing.md`)

**Document Name:** `testing.md`  
**Scope:** Universal Test Case Creation Workflow, Decoupled Offline Mock Testing, Property-Based Fuzzing, June-Style Regression Fixtures, and System Acceptance Unit Testing  
**Project:** HackerRank Orchestrate — WhatsApp Message Notification Router  

---

## 1. THE UNIVERSAL TEST CASE CREATION WORKFLOW (4 STEPS)

In AI orchestration systems, testing by generating unit tests directly from implementation code causes **circular validation** — proving only that the code is internally consistent rather than correct against the problem specification.

To prevent circular validation, our test suite follows this 4-step workflow:

```
[ Step A: Spec-Only Oracle ]  ──►  [ Step B: Synthetic Fixture Generation ]
                                                       │
[ Step D: Regression Lock ]   ◄──  [ Step C: Golden Anchor Human Verification ]
```

### Step A — Spec-Only Oracle
* **Rule:** Identify the formal specification contract from written specifications (`problem_statement.md`, `schema_contract.json`) without inspecting implementation code.
* **Our Oracle:**
  * **Allowed Actions:** `["notify", "digest", "mute"]`
  * **Allowed Message Types:** `["text", "image", "audio", "multimodal"]`
  * **Confidence Range:** `[0.0, 1.0]`
  * **110-Row Completeness Invariant:** Every input `message_id` must map to exactly one output row.

### Step B — Synthetic Fixture Generation
* **Rule:** Feed the Spec-Only Oracle to an LLM to generate synthetic input/output fixture rows covering boundary conditions (e.g., OTPs, DND quiet hours, scam keywords, promo opt-outs).
* **Isolation Guarantee:** Zero Python source code is provided during fixture generation.

### Step C — Golden Anchor Human Verification
* **Rule:** Manually audit 10 critical edge-case rows ("Golden Anchors") against the specification to catch any LLM hallucination in synthetic fixtures.
* **Verified Anchors:**
  * Emergency keywords during DND $\rightarrow$ MUST route to `notify` (`emergency_override`).
  * Scam/phishing keywords $\rightarrow$ MUST route to `mute` (`scam_detected`).
  * Promotional keywords from opted-out businesses $\rightarrow$ MUST route to `mute` (`promo_opt_out`).

### Step D — Regression Lock
* **Rule:** Commit verified fixtures as an immutable regression baseline. Any pull request that causes a Golden Anchor or regression fixture to fail is blocked from merging.

---

## 2. DECOUPLED SUB-SYSTEM EVALUATION (OFFLINE MOCK TESTING)

Testing an AI pipeline end-to-end over live network calls makes failures ambiguous (network timeout vs. prompt drift vs. business rule bug).

### The Decoupling Law
Every domain invariant layer must be tested in **complete isolation using mock structured objects** (`SensorObservation`) without calling live external LLM/VLM/STT APIs.

### What This Unlocks:
1. **0ms Latency & $0.00 API Cost:** Full test suite executes in under 2 seconds.
2. **Pinpoint Fault Isolation:** A test failure points to exactly one class or function.
3. **CI/CD Sandbox Execution:** Runs in automated pipelines with zero secrets or network access.

---

## 3. PROPERTY-BASED TESTING WITH `HYPOTHESIS`

Hand-crafted unit tests check discrete examples. Property-based testing with **`Hypothesis`** verifies that domain invariants hold across the **entire valid input space**, fuzzing boundary values and adversarial strings.

### The Exact `Hypothesis` Vocabulary Contracts

| Vocabulary Phrase | What It Tests in Our WhatsApp Router |
| :--- | :--- |
| `@given(st.text())` | String inputs for `reasoning` and `intent` — proves zero crashes on Unicode, emojis, or empty strings. |
| `@given(st.integers(min_value=0, max_value=23))` | Hours of day — verifies DND boundary conditions (`22:00` to `07:00`) never suffer off-by-one errors. |
| `@given(st.sampled_from(["low", "medium", "high", "critical"]))` | All valid urgency enum levels — verifies exhaustive matching without default fallback traps. |
| `@given(st.lists(st.text(), min_size=0))` | Evidence message ID lists — verifies empty or large historical evidence sets never crash. |
| `@settings(max_examples=500)` | Fuzzes 500 generated permutations per test run to uncover obscure edge cases. |

---

## 4. SYSTEM ACCEPTANCE UNIT TESTING (UAT / ACCEPTANCE CRITERIA)

**System Acceptance Unit Testing** bridges unit tests and full system delivery. While standard unit tests verify isolated functions (`is_scam -> True`), **System Acceptance Unit Tests** verify that the integrated system satisfies formal **Contractual Acceptance Criteria** before release.

### 1. What is an Acceptance Criterion in AI Orchestration?
An acceptance criterion is a non-negotiable business or dataset rule that the system must satisfy across an entire batch or end-to-end pipeline run to be deemed production-ready.

### 2. Our 4 Formal System Acceptance Criteria
1. **110-Row Completeness Criterion:** Given `dataset/messages.csv` containing 110 rows, the system MUST output exactly 110 prediction rows in `dataset/output.csv`, with 0 dropped rows and 0 duplicate `message_id`s.
2. **Schema Vocabulary Criterion:** Exactly 100% of output rows must contain valid vocabulary values (`action` in `{"notify", "digest", "mute"}`, float confidence in `[0.0, 1.0]`).
3. **Safety & Emergency Acceptance Criterion:** 100% of messages classified as medical/physical safety emergencies must output `action="notify"`, even during DND hours (`is_dnd=True`).
4. **Scam & Fraud Suppression Criterion:** 100% of messages classified as financial phishing or scams must output `action="mute"`, regardless of urgency score.

### 3. How We Implement System Acceptance Unit Tests (`test_system_acceptance.py`)
```python
# Production Acceptance Test Pattern
def test_acceptance_110_row_completeness_invariant():
    """Verifies that running the router over sample messages produces exact 1-to-1 completeness."""
    input_rows = load_test_dataset()
    output_rows = run_batch_pipeline(input_rows, offline_mode=True)
    assert len(output_rows) == len(input_rows)
    assert set(r["message_id"] for r in output_rows) == set(r["message_id"] for r in input_rows)
```

---

## 5. 4-TIER TEST DIRECTORY ARCHITECTURE (`code/tests/`)

Our test suite in `code/tests/` enforces **four distinct testing tiers**, combining June-style practical helper builders with Staff-level invariant fuzzing and system acceptance testing:

```text
code/tests/
├── __init__.py
├── conftest.py                   # Shared offline mocks and builder helpers (claim, obs, decide)
├── test_schema_seams.py          # TIER 1: Parse-Don't-Validate boundary tests (Pydantic v2 seams)
├── test_regression_fixtures.py   # TIER 2: June-Style Regression Fixtures (helper builders + sample rows)
├── test_property_invariants.py   # TIER 3: Hypothesis property-based fuzzing (500 permutations)
└── test_system_acceptance.py     # TIER 4: System Acceptance Unit Tests (completeness & contract UAT)
```

### Why We Use June-Style Helper Builders in Tier 2 (`test_regression_fixtures.py`)
Adopting the clean helper-builder pattern from `hackerrank-orchestrate-june`, we encode representative sample rows and Golden Anchors as concise 5-line unit test fixtures:

```python
# June-Style Helper Builder Pattern in Tier 2
def obs(intent="transactional", urgency="medium", **kw):
    base = dict(intent=intent, urgency=urgency, sender_relationship="contact",
                contains_actionable_item=True, reasoning="test fixture")
    base.update(kw)
    return SensorObservation(**base)

def decide_obs(o, dnd=False, opt_out=False):
    return route_message(o, is_dnd=dnd, is_opted_out=opt_out)

def test_case_emergency_override_fixture():
    r = decide_obs(obs(intent="emergency", urgency="high"), dnd=True)
    assert (r.action, r.reason) == ("notify", "emergency_override")
```
