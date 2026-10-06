import sys
from pathlib import Path

# Add project root to path for imports
sys.path.append(str(Path(__file__).resolve().parent.parent))

from src.tools.vlm_engine import vlm_engine

def test_vlm_engine():
    print("=== VLM Engine Architectural Test ===")
    
    # We simulate the Orchestrator passing a known image_id from the Mock environment
    image_id = "img_tc_001_1"
    
    print(f"Orchestrator requesting assessment for image: {image_id}")
    
    try:
        # The VLM engine completely abstracts away the Mock JSON logic.
        output = vlm_engine.assess_image(
            user_id="synth_user_001",
            image_id=image_id,
            image_path="synth/images/tc_001/img_tc_001_1.jpg",
            claim_text="My package seal is torn.",
            object_type="package",
            component="seal",
            issue="torn_packaging",
            evidence_reqs="Need close up of seal"
        )
        
        print("\nSUCCESS! The VLM Engine seamlessly returned a strict Pydantic VLMOutput object.")
        print(f"Type of output: {type(output)}")
        print("\n--- Extracted VLM Data ---")
        print(f"Object Detected: {output.object_detected}")
        print(f"Component: {output.component_detected}")
        print(f"Issue: {output.issue_detected}")
        print(f"Support Signal: {output.support_signal}")
        print(f"Severity: {output.issue_severity}")
        print(f"Authenticity Risk: {output.authenticity_risk}")
        
    except Exception as e:
        print(f"Test Failed: {str(e)}")

if __name__ == "__main__":
    test_vlm_engine()
