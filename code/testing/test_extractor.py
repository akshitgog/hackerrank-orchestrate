import sys
import argparse
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).resolve().parent.parent))

from src.core.config import config
from src.core.data_loader import load_data

def run_test(env: str, custom_path: str, use_api: bool):
    # If API mode is forced, override the YAML config before initializing the engine
    if use_api:
        if "extractor" not in config.providers:
            config.providers["extractor"] = {}
        config.providers["extractor"]["model"] = "gpt-4o" # Example LiteLLM string
        print("WARNING: Forced API mode. Ensure litellm is configured and API keys are set.")
        
    # Import AFTER config override so __init__ picks up the new model
    from src.tools.extractor_engine import extractor_engine
    
    if custom_path:
        data_path = custom_path
    else:
        paths = config.get_dataset_paths(env)
        data_path = paths.get("claims_file")
        
    print(f"Loading data from: {data_path}")
    data = load_data(data_path)
    
    print(f"\n=== Testing Extractor Engine (API Mode: {use_api}) ===")
    
    # Test on the first 3 rows to avoid massive API costs
    for row in data[:3]:
        claim = row.get("claim_input", row)
        user_id = claim.get("user_id", "unknown")
        user_claim = claim.get("user_claim", "No claim text provided.")
        
        print(f"\nUser ID: {user_id}")
        print(f"Raw Claim: {user_claim}")
        try:
            result = extractor_engine.extract_claim_details(user_id, user_claim)
            print("--- Extractor Output ---")
            print(f"Object:    {result.object}")
            print(f"Component: {result.component}")
            print(f"Issue:     {result.issue}")
        except Exception as e:
            print(f"Failed to extract: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test the Extractor Engine in isolation.")
    parser.add_argument("--env", default="mock", choices=["mock", "sample", "production"], help="Environment to test against.")
    parser.add_argument("--path", type=str, help="Direct path to a CSV or JSON file to test.")
    parser.add_argument("--api", action="store_true", help="Force the engine to bypass mock data and make real API calls.")
    args = parser.parse_args()
    
    run_test(args.env, args.path, args.api)
