import sys
import argparse
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).resolve().parent.parent))

from src.core.config import config
from src.core.data_loader import load_data

def run_test(env: str, custom_path: str, use_api: bool):
    # Override config if forcing real API calls
    if use_api:
        if "vlm" not in config.providers:
            config.providers["vlm"] = {}
        config.providers["vlm"]["model"] = "bedrock/anthropic.claude-3-sonnet-20240229-v1:0"
        print("WARNING: Forced API mode. Ensure litellm is configured and API keys are set.")
        
    # Import AFTER config override
    from src.tools.vlm_engine import vlm_engine
    
    if custom_path:
        data_path = custom_path
    else:
        paths = config.get_dataset_paths(env)
        data_path = paths.get("claims_file")
        
    print(f"Loading data from: {data_path}")
    data = load_data(data_path)
    
    print(f"\n=== Testing VLM Engine (API Mode: {use_api}) ===")
    
    # Process the first 2 claims
    for row in data[:2]:
        claim = row.get("claim_input", row)
        user_id = claim.get("user_id", "unknown")
        image_paths = claim.get("image_paths", "").split(";") if claim.get("image_paths") else []
        claim_text = claim.get("user_claim", "")
        
        print(f"\nEvaluating Claim for User: {user_id}")
        
        for path in image_paths:
            img_id = Path(path).stem
            print(f"-> Processing Image: {path} (ID: {img_id})")
            try:
                # Passing dummy values for isolated testing
                result = vlm_engine.assess_image(
                    user_id=user_id,
                    image_id=img_id,
                    image_path=path,
                    claim_text=claim_text,
                    object_type="unknown",
                    component="unknown",
                    issue="unknown",
                    evidence_reqs="Verify damage visually."
                )
                print("--- VLM Output ---")
                print(f"Signal: {result.support_signal} (Severity: {result.issue_severity})")
                print(f"Authenticity Risk: {result.authenticity_risk}")
                print(f"Reasoning: {result.reasoning.model_dump()}")
            except Exception as e:
                print(f"VLM Execution Failed: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test the VLM Engine in isolation.")
    parser.add_argument("--env", default="mock", choices=["mock", "sample", "production"], help="Environment to test against.")
    parser.add_argument("--path", type=str, help="Direct path to a CSV or JSON file to test.")
    parser.add_argument("--api", action="store_true", help="Force the engine to bypass mock data and make real API calls.")
    args = parser.parse_args()
    
    run_test(args.env, args.path, args.api)
