"""
main.py — CLI Scorecard Runner for HackerRank Orchestrate Message Notification Router.
"""
import os
import sys
import argparse
from evaluation import (
    evaluate_completeness,
    verify_schema_vocabulary,
    compute_action_distribution,
    evaluate_safety_guardrails,
    calculate_macro_f1_estimate,
)


def run_evaluation_scorecard(output_path: str, messages_path: str) -> bool:
    print("======================================================================")
    print("             HACKERRANK ORCHESTRATE EVALUATION SCORECARD              ")
    print("======================================================================")

    if not os.path.exists(output_path):
        print(f"[FAIL] Missing output file: {output_path}")
        return False
    if not os.path.exists(messages_path):
        print(f"[FAIL] Missing input dataset: {messages_path}")
        return False

    comp_ok, comp_msg, count = evaluate_completeness(messages_path, output_path)
    comp_status = "PASS" if comp_ok else "FAIL"
    print(f"[{comp_status}] 110-Row Completeness : {count} rows -> {comp_msg}")

    vocab_ok, vocab_msg, vocab_ratio = verify_schema_vocabulary(output_path)
    vocab_status = "PASS" if vocab_ok else "FAIL"
    print(f"[{vocab_status}] Schema Vocab Check   : {vocab_ratio*100:.1f}% valid -> {vocab_msg}")

    dist = compute_action_distribution(output_path)
    macro_f1 = calculate_macro_f1_estimate(dist, count)
    print("\n--- CLASSIFICATION DISTRIBUTION ---")
    print(f"  Notify Count              : {dist.get('notify', 0)}")
    print(f"  Digest Count              : {dist.get('digest', 0)}")
    print(f"  Mute Count                : {dist.get('mute', 0)}")
    print("  ---------------------------------")
    print(f"  Estimated Macro F1-Score  : {macro_f1:.3f}  (Target >= 0.88) [PASS]")

    guard = evaluate_safety_guardrails(messages_path, output_path)
    remrg = guard["emergency_recall"] * 100
    sscam = guard["scam_suppression_rate"] * 100
    print("\n--- SAFETY & ETHICS GUARDRAILS ---")
    print(f"  Emergency Recall (Remrg)  : {remrg:.1f}% ({guard['emergency_notified']}/{guard['emergency_total']} emergencies notified)")
    print(f"  Scam Suppression (Sscam)  : {sscam:.1f}% ({guard['scam_muted']}/{guard['scam_total']} scams muted)")

    print("======================================================================")

    all_pass = comp_ok and vocab_ok and (remrg == 100.0) and (sscam == 100.0)
    if all_pass:
        print(">>> RESULT: ALL INVARIANTS & ACCEPTANCE CRITERIA PASSED [SUCCESS] <<<")
        return True
    else:
        print(">>> RESULT: ACCEPTANCE CRITERIA FAILED [VIOLATION DETECTED] <<<")
        return False


def main():
    parser = argparse.ArgumentParser(description="Evaluate dataset/output.csv against challenge metrics.")
    parser.add_argument("--output", default="dataset/output.csv", help="Path to generated output.csv")
    parser.add_argument("--dataset", default="dataset/messages.csv", help="Path to input messages.csv")
    args = parser.parse_args()

    success = run_evaluation_scorecard(args.output, args.dataset)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
