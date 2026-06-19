import sys
from pathlib import Path

# Add project root to path for imports
sys.path.append(str(Path(__file__).resolve().parent.parent))

from src.core.config import config
from src.core.data_loader import load_data
from src.tools.risk_engine import process_user_risk

def run_integration_test():
    print("=== Risk Engine Integration Test ===")
    
    env_name = "production"
    print(f"\n--- Testing '{env_name.upper()}' Environment (REAL DATA) ---")
    paths = config.get_dataset_paths(env_name)
    history_file = paths["user_history_file"]
    
    print(f"Loading Data Loader on: {history_file}")
    
    try:
        users = load_data(history_file)
        print(f"Success! Loaded {len(users)} users.")
        
        flagged_count = 0
        for user in users:
            flags = process_user_risk(user)
            if flags:
                flagged_count += 1
                
        print(f"Result: {flagged_count} out of {len(users)} users received risk flags.")
        
    except Exception as e:
        print(f"Failed: {str(e)}")

if __name__ == "__main__":
    run_integration_test()
