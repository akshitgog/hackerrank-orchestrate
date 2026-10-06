import sys
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).resolve().parent.parent))

from src.tools.explanation_generator import explanation_generator

def run_test():
    print("=== Testing Explanation Generator ===\n")
    
    scenarios = [
        {"claim_status": "supported", "best_image_vlm_reasoning": {}},
        {"claim_status": "contradicted", "best_image_vlm_reasoning": {}},
        {"claim_status": "not_enough_information", "best_image_vlm_reasoning": {}},
    ]
    
    for s in scenarios:
        print(f"Input Decision Status: {s['claim_status']}")
        out = explanation_generator.generate(s)
        print(f"-> Evidence Met Reason: {out['evidence_standard_met_reason']}")
        print(f"-> Justification:       {out['claim_status_justification']}\n")

if __name__ == "__main__":
    run_test()
