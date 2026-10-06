import csv
import argparse
from collections import defaultdict

def load_csv(path):
    rows = {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows[row['user_id']] = row
    except FileNotFoundError:
        print(f"Error: Could not find file {path}")
        exit(1)
    return rows

def compare_csvs(pred_path, true_path):
    pred = load_csv(pred_path)
    true = load_csv(true_path)

    # The fields we care about for exact matching
    fields = [
        'object_part', 'evidence_standard_met', 'valid_image', 
        'issue_type', 'risk_flags', 'supporting_image_ids', 
        'claim_status', 'severity'
    ]

    objects = defaultdict(list)
    overall_correct = 0
    overall_total = 0
    
    field_correct = {f: 0 for f in fields}
    
    # Track mismatches for detailed review
    mismatches = []

    for uid, t_row in true.items():
        if uid not in pred:
            print(f"Warning: {uid} missing from predictions.")
            continue
            
        p_row = pred[uid]
        obj = t_row.get('claim_object', 'unknown')
        objects[obj].append(uid)
        
        for f in fields:
            overall_total += 1
            t_val = t_row.get(f, '').strip().lower()
            p_val = p_row.get(f, '').strip().lower()
            
            # Set comparison for semicolon-separated lists
            if f in ['risk_flags', 'supporting_image_ids']:
                t_set = set([x.strip() for x in t_val.split(';') if x.strip()])
                p_set = set([x.strip() for x in p_val.split(';') if x.strip()])
                is_match = (t_set == p_set)
            else:
                is_match = (t_val == p_val)
                
            if is_match:
                overall_correct += 1
                field_correct[f] += 1
            else:
                mismatches.append({
                    'user': uid,
                    'object': obj,
                    'field': f,
                    'expected': t_val,
                    'got': p_val
                })

    # --- Print Report ---
    print("="*60)
    print("🏆 EVALUATION REPORT 🏆")
    print("="*60)
    
    pct = (overall_correct / overall_total * 100) if overall_total else 0
    print(f"\n🌟 OVERALL ACCURACY: {pct:.2f}% ({overall_correct}/{overall_total} fields)")
    
    print("\n📊 ACCURACY BY FIELD:")
    total_users = len(pred)
    for f in fields:
        f_pct = (field_correct[f] / total_users * 100) if total_users else 0
        print(f"  - {f:<22} {f_pct:5.1f}%  ({field_correct[f]}/{total_users})")
        
    print("\n📦 ACCURACY BY OBJECT TYPE:")
    for obj, uids in objects.items():
        obj_correct = 0
        obj_total = len(uids) * len(fields)
        for m in mismatches:
            if m['object'] == obj:
                # If a mismatch is in this object, subtract from total possible correct
                pass # We calculate correct by total - mismatches
                
        obj_mismatches = len([m for m in mismatches if m['object'] == obj])
        obj_correct = obj_total - obj_mismatches
        obj_pct = (obj_correct / obj_total * 100) if obj_total else 0
        print(f"  - {obj.upper():<10} {obj_pct:5.1f}%  ({obj_correct}/{obj_total})  [{len(uids)} claims]")

    print("\n⚠️  TOP 10 WORST MISMATCHES (Sample):")
    for m in mismatches[:10]:
        print(f"  [{m['user']}] {m['field']}: Expected '{m['expected']}', Got '{m['got']}'")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--pred", default="code/evaluation/test_output.csv", help="Your pipeline output")
    parser.add_argument("--true", default="dataset/test_claim_output.csv", help="Organizer ground truth")
    args = parser.parse_args()
    
    compare_csvs(args.pred, args.true)
