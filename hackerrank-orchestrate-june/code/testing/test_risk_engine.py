import sys
from pathlib import Path

# Add project root to path for imports
sys.path.append(str(Path(__file__).resolve().parent.parent))

from src.tools.risk_engine import process_user_risk

def test_risk_engine():
    print("Running Advanced Risk Engine Tests...")
    
    # Case 1: Pure string parsing
    h1 = {"history_flags": "user_history_risk", "rejected_claim": "0", "last_90_days_claim_count": "0"}
    assert "user_history_risk" in process_user_risk(h1), "Failed string parsing"
    
    # Case 2: High velocity trigger
    h2 = {"history_flags": "none", "rejected_claim": "0", "last_90_days_claim_count": "4"}
    flags2 = process_user_risk(h2)
    assert "user_history_risk" in flags2 and "frequent_recent_claims" in flags2, f"Failed velocity trigger. Got: {flags2}"
    
    # Case 3: High rejection trigger
    h3 = {"history_flags": "none", "rejected_claim": "3", "last_90_days_claim_count": "1"}
    flags3 = process_user_risk(h3)
    assert "user_history_risk" in flags3 and "multiple_rejections" in flags3, f"Failed rejection trigger. Got: {flags3}"
    
    print("Success: All Advanced Risk Engine tests passed!")

if __name__ == "__main__":
    test_risk_engine()
