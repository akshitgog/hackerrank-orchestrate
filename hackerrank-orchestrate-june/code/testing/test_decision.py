import sys
import argparse
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).resolve().parent.parent))

from src.tools.decision_engine import decision_engine
from src.models.vlm import VLMOutput, VLMReasoning

def run_test():
    print("=== Testing Decision Engine Logic ===\n")
    
    # Simulate a scenario where the user has a risky history, but the image contradicts
    print("Scenario 1: User has 'user_history_risk'. VLM output says 'contradict'.")
    print("Expected: Claim is contradicted. NO manual review assigned (Auto-Reject Rule).")
    
    vlm_mock = {
        "img_1": VLMOutput(
            user_id="user_1",
            image_id="img_1",
            object_detected="car", object_confidence=5, object_match=True,
            component_detected="door", component_visible=True, component_visibility=5, component_match=True,
            issue_detected="dent", issue_visible=True, issue_strength=5, issue_match=True,
            issue_location_description="middle", issue_severity="minor",
            image_quality="good", image_quality_strength=5, quality_issues=[],
            authenticity_risk="low", authenticity_flags=["none"],
            visibility_obstruction="none",
            support_signal="contradict", support_strength=5,
            requirement_failures=[],
            reasoning=VLMReasoning(object_evidence="car", component_evidence="door", issue_evidence="No damage visible")
        )
    }
    
    history_flags = ["user_history_risk"]
    
    decision = decision_engine.decide(vlm_mock, history_flags)
    print(f"Result Status: {decision['claim_status']}")
    print(f"Result Flags:  {decision['risk_flags_array']}\n")
    
    
    print("Scenario 2: User has 'user_history_risk'. VLM output says 'support'.")
    print("Expected: Claim is supported. Manual review IS assigned.")
    vlm_mock["img_1"].support_signal = "support"
    
    decision2 = decision_engine.decide(vlm_mock, history_flags)
    print(f"Result Status: {decision2['claim_status']}")
    print(f"Result Flags:  {decision2['risk_flags_array']}\n")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test the Decision Engine in isolation via simulated state injections.")
    args = parser.parse_args()
    run_test()
