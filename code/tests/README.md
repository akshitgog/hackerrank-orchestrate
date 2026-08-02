# 🧪 OFFLINE 4-TIER TEST SUITE (`code/tests/`)

**Module:** `code/tests/`  
**Purpose:** Pure-Python, Decoupled, Zero-Latency Verification Suite for HackerRank Orchestrate Message Notification Router  

---

## 1. QUICK START: RUNNING THE TEST SUITE

Run the entire 15-test verification suite from the repository root directory:

```powershell
# Set PYTHONPATH to code/ directory and run pytest in verbose mode
$env:PYTHONPATH = "C:\Users\Galactus\OneDrive\Desktop\orches\code"
python -m pytest code/tests/ -v
```

### Expected Output
```text
code/tests/test_property_invariants.py::test_property_invariants_500_permutations PASSED   [  6%]
code/tests/test_regression_fixtures.py::test_anchor_01_emergency_override_during_dnd PASSED [ 13%]
code/tests/test_regression_fixtures.py::test_anchor_02_scam_suppression_always_muted PASSED  [ 20%]
...
code/tests/test_system_acceptance.py::test_acceptance_dataset_context_referential_integrity PASSED [100%]

======================== 15 passed, 1 warning in 0.04s ========================
```

> [!NOTE]
> The percentage markers (`[  6%]`, `[ 13%]`, ..., `[100%]`) indicate **execution progress across the 15 tests**, not the pass rate. A result of `15 passed` confirms a **100% PASS RATE**.

---

## 2. THE 4 ARCHITECTURAL TIERS

```text
code/tests/
├── __init__.py
├── conftest.py                   # Shared offline mocks and builder helpers (claim, obs, decide)
├── test_schema_seams.py          # TIER 1: Parse-Don't-Validate boundary tests (Pydantic v2 seams)
├── test_regression_fixtures.py   # TIER 2: June-Style Regression Fixtures (helper builders + sample rows)
├── test_property_invariants.py   # TIER 3: Hypothesis/Property-based fuzzing (500 permutations)
└── test_system_acceptance.py     # TIER 4: System Acceptance Unit Tests (completeness & contract UAT)
```

| Tier | File | Purpose | What It Protects |
| :--- | :--- | :--- | :--- |
| **Tier 1** | `test_schema_seams.py` | Typed boundary validation | Protects against invalid enum actions, malformed API payloads, and out-of-bounds confidence scores. |
| **Tier 2** | `test_regression_fixtures.py` | Golden Anchor regression lock | Enforces our 9 critical business rules (Emergency override, Scam suppression, DND quiet hours, Promo opt-outs). |
| **Tier 3** | `test_property_invariants.py` | Invariant fuzzing (500 runs) | Proves the decision tree never crashes or violates vocabulary contracts across random permutations. |
| **Tier 4** | `test_system_acceptance.py` | Dataset & referential UAT | Verifies `dataset/messages.csv` has exactly 110 unique IDs and that `DatasetContext` loads all 11 CSVs. |

---

## 3. HOW TO USE JUNE-STYLE HELPER BUILDERS (`conftest.py`)

Our suite uses concise helper builder functions modeled after the clean June reference repository (`obs()`, `media()`, `decide_obs()`) to construct structured `SensorObservation` objects in 1–5 lines of code:

### Helper Functions Available in `conftest.py`
```python
# Create a valid SensorObservation with customized intent/priority/risk
def obs(
    intent="transactional_update",
    priority="medium",
    risk="none",
    sensitive=False,
    actionable=True,
    evidence_ids=None,
    reasoning="Test fixture observation",
    **kw
): ...

# Route an observation through the 7-Gate decision tree
def decide_obs(observation: SensorObservation, is_dnd=False, is_opted_out=False): ...
```

### Snippet: Writing a New Regression Test Case
To add a new Golden Anchor test in `test_regression_fixtures.py`, use `obs()` and `decide_obs()`:

```python
from tests.conftest import obs, decide_obs

def test_custom_emergency_rule():
    """Verify that critical emergencies override DND quiet hours."""
    observation = obs(intent="emergency", priority="critical", risk="none")
    decision = decide_obs(observation, is_dnd=True)
    
    # Assert exact tuple (action, message_type)
    assert (decision.action, decision.message_type) == ("notify", "urgent")
    assert "Critical priority message overrides all quiet settings" in decision.reason
```

---

## 4. ZERO-LATENCY OFFLINE GUARANTEE

By isolating our deterministic 7-Gate decision tree (`code/src/routing_engine/decision_tree.py`) from network-dependent LLM API calls, this suite executes in under **50 milliseconds** with **zero API costs**, making it ideal for automated CI/CD gating.
