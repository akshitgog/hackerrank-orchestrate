import csv
import sys
from pathlib import Path

def main():
    project_root = Path(__file__).resolve().parent.parent.parent
    ground_truth_path = project_root / "dataset" / "sample_messages.csv"
    predictions_path = project_root / "code" / "evaluation" / "output.csv"

    if not ground_truth_path.exists():
        print(f"Ground truth not found: {ground_truth_path}")
        return
    if not predictions_path.exists():
        print(f"Predictions not found: {predictions_path}")
        return

    # Load ground truth
    ground_truth = {}
    with open(ground_truth_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ground_truth[row["message_id"]] = {
                "action": row["action"].strip().lower(),
                "message_type": row["message_type"].strip().lower(),
                "reason": row["reason"],
            }

    # Load predictions
    predictions = {}
    with open(predictions_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            predictions[row["message_id"]] = {
                "action": row["action"].strip().lower(),
                "message_type": row["message_type"].strip().lower(),
            }

    # Compare
    total = 0
    action_correct = 0
    type_correct = 0
    
    mismatches = []

    for msg_id, truth in ground_truth.items():
        if msg_id not in predictions:
            continue
            
        pred = predictions[msg_id]
        total += 1
        
        act_match = (truth["action"] == pred["action"])
        typ_match = (truth["message_type"] == pred["message_type"])
        
        if act_match:
            action_correct += 1
        if typ_match:
            type_correct += 1
            
        if not act_match:
            mismatches.append(f"[{msg_id}] Expected Action: '{truth['action']}', Got: '{pred['action']}' | Reason: {truth['reason']}")

    if total == 0:
        print("No matching message_ids found between ground truth and predictions.")
        return

    print("=" * 50)
    print(" EVALUATION REPORT")
    print("=" * 50)
    print(f"Total Evaluated: {total}")
    print(f"Action Accuracy: {action_correct}/{total} ({(action_correct/total)*100:.2f}%)")
    print(f"Type Accuracy:   {type_correct}/{total} ({(type_correct/total)*100:.2f}%)")
    
    if mismatches:
        print("\n" + "-" * 50)
        print(" ACTION MISMATCHES")
        print("-" * 50)
        for m in mismatches:
            print(m)

if __name__ == "__main__":
    main()
