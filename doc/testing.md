# 🧪 PRODUCTION-GRADE TESTING PLAYBOOK (`testing.md`)

**Document Name:** `testing.md`  
**Scope:** Universal Test Case Creation Workflow, Decoupled Sub-System Evaluation, and Property-Based Testing  
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

```python
# Production-grade offline mock pattern for WhatsApp Routing Engine
from src.classifiers.schema_models import SensorObservation
from src.routing_engine.decision_tree import route_message

def test_emergency_override_invariant():
    mock_obs = SensorObservation(
        intent="emergency",
        urgency="high",
        sender_relationship="contact",
        contains_actionable_item=True,
        reasoning="Medical emergency reported"
    )
    decision = route_message(mock_obs, is_dnd=True, is_opted_out=False)
    assert decision.action == "notify"
    assert decision.reason == "emergency_override"
```

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

```python
from hypothesis import given, settings, strategies as st
from src.classifiers.schema_models import SensorObservation
from src.routing_engine.decision_tree import route_message

ALLOWED_ACTIONS = {"notify", "digest", "mute"}

@given(
    intent=st.sampled_from(["emergency", "transactional", "promotional", "scam", "general"]),
    urgency=st.sampled_from(["low", "medium", "high", "critical"]),
    is_dnd=st.booleans(),
    is_opted_out=st.booleans()
)
@settings(max_examples=500)
def test_decision_tree_exhaustive_invariants(intent, urgency, is_dnd, is_opted_out):
    mock_obs = SensorObservation(
        intent=intent,
        urgency=urgency,
        sender_relationship="contact",
        contains_actionable_item=True,
        reasoning="Hypothesis fuzzed observation"
    )
    decision = route_message(mock_obs, is_dnd=is_dnd, is_opted_out=is_opted_out)
    
    # Invariant 1: Action must always be a valid spec vocabulary word
    assert decision.action in ALLOWED_ACTIONS
    
    # Invariant 2: Confidence must be within [0.0, 1.0]
    assert 0.0 <= decision.confidence <= 1.0
    
    # Invariant 3: Scam intent must always route to mute
    if intent == "scam":
        assert decision.action == "mute"
```

---

## 4. TEST DIRECTORY ARCHITECTURE

```text
test/
├── __init__.py
├── conftest.py                   # Pytest fixtures and synthetic data loaders
├── test_schema_models.py         # Verifies Parse-Don't-Validate typed seams
├── test_decision_tree.py         # Offline mock unit tests for 7-Gate routing rules
├── test_property_invariants.py   # Hypothesis property-based fuzzing tests
└── fixtures/
    └── golden_anchors.json       # Immutable Golden Anchor verification rows
```
