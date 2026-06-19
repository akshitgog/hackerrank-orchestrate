import sys
import argparse
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).resolve().parent.parent))

from src.core.config import config
from src.core.data_loader import load_data
from src.tools.risk_engine import process_user_risk

def run_test(env: str, custom_path: str):
    if custom_path:
        data_path = custom_path
    else:
        paths = config.get_dataset_paths(env)
        data_path = paths.get("user_history_file", paths.get("users_file"))
        
    print(f"Loading user history data from: {data_path}")
    data = load_data(data_path)
    
    print(f"\n=== Testing Risk Engine ===")
    
    for user in data[:5]:
        user_id = user.get("user_id", "unknown")
        
        print(f"\nUser ID: {user_id}")
        try:
            flags = process_user_risk(user)
            print(f"Calculated Risk Flags: {flags}")
        except Exception as e:
            print(f"Failed to calculate risk: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test the Risk Engine in isolation.")
    parser.add_argument("--env", default="mock", choices=["mock", "sample", "production"], help="Environment to test against.")
    parser.add_argument("--path", type=str, help="Direct path to a user history CSV file.")
    args = parser.parse_args()
    
    run_test(args.env, args.path)
