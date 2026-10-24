"""Main Orchestrator Entry Point for Ghost Data Still Exists.

Supports:
    python code/main.py --sample   # Runs on dataset/sample_deletion_requests.csv (32 cases)
    python code/main.py --whole    # Runs on dataset/deletion_requests.csv (518 cases)
"""

import argparse
import sys
from pathlib import Path

# Ensure repo root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pandas as pd

from code.config.loader import load_config
from code.src.orchestrator.classifier import IntentClassifier
from code.src.logging_agent.tracker import IdentityTracker
from code.src.audit_agent.scanner import AuditScanner
from code.src.step_json_agent.builder import StepJsonBuilder
from code.guardrails.intent_guardrail import IntentGuardrail
from code.guardrails.identity_guardrail import IdentityGuardrail
from code.guardrails.audit_guardrail import AuditGuardrail
from code.guardrails.jev_schema_guardrail import StepJsonGuardrail


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        description="Ghost Data Still Exists: AI Deletion Audit Agent"
    )
    group = parser.add_mutually_exclusive_group(required=False)
    group.add_argument(
        "--sample",
        action="store_true",
        help="Run audit agent against the 32 sample cases in sample_deletion_requests.csv",
    )
    group.add_argument(
        "--whole",
        action="store_true",
        help="Run audit agent against all 518 cases in deletion_requests.csv",
    )
    parser.add_argument(
        "--config",
        type=str,
        default="code/config/config.yaml",
        help="Path to YAML configuration file",
    )
    return parser.parse_args()


def main() -> None:
    """Main pipeline execution."""
    args = parse_args()
    config = load_config(args.config)

    is_sample = args.sample or not args.whole

    if is_sample:
        requests_file = "dataset/sample_deletion_requests.csv"
        print("=== Running in SAMPLE mode (32 cases) ===")
    else:
        requests_file = "dataset/deletion_requests.csv"
        print("=== Running in WHOLE mode (518 cases) ===")

    threshold = float(config.get("thresholds", {}).get("intent_decision", 0.80))
    print(f"Loaded config from {args.config}")
    print(f"Intent Threshold: {threshold}")

    # Initialize Agents across all phases
    intent_cfg = config.get("models", {}).get("intent_classifier", {})
    intent_model = intent_cfg.get("model") if intent_cfg.get("enabled", False) else None
    classifier = IntentClassifier(
        threshold=threshold,
        model_name=intent_model,
        timeout=int(intent_cfg.get("timeout_seconds", 15)),
        max_retries=int(intent_cfg.get("retries", 3)),
    )
    tracker = IdentityTracker(
        identities_path="dataset/user_identities.csv",
        audit_log_path="dataset/user_audit_log.csv",
    )
    id_guardrail = IdentityGuardrail(tracker.audit_log_df)

    scanner = AuditScanner(
        evidence_manifest_path="dataset/evidence_files.csv",
        system_activity_path="dataset/system_activity.csv",
        rules_path="dataset/deletion_rules.csv",
        cache_path="cache/multimodal_cache.json",
    )
    audit_guardrail = AuditGuardrail(evidence_manifest_path="dataset/evidence_files.csv")

    requests_df = pd.read_csv(requests_file)
    print(f"Total requests to process: {len(requests_df)}")

    complete_count = 0
    incomplete_count = 0
    not_applicable_count = 0
    guardrails_passed_count = 0

    results: list[dict[str, str]] = []

    for idx, row in requests_df.iterrows():
        case_id = str(row["case_id"])
        email = str(row["email"])
        audit_at = str(row["audit_at"])
        request_text = str(row.get("request_text", ""))

        # Phase 4: Intent Classification
        intent_res = classifier.classify(case_id, request_text)
        intent_violations = IntentGuardrail.validate(intent_res, threshold)
        if intent_violations:
            print(f"[!] Intent guardrail violations for {case_id}: {intent_violations}")

        # Check if request does NOT authorize deletion -> NOT_APPLICABLE
        if not intent_res.is_deletion_authorized:
            not_applicable_count += 1
            guardrails_passed_count += 1
            results.append({
                "case_id": case_id,
                "deletion_status": "NOT_APPLICABLE",
                "steps_json": "[]",
            })
            continue

        # Phase 1: Identity Tracking
        profile = tracker.get_identity_profile(email, audit_at)
        if not profile:
            print(f"[!] Could not resolve profile for {case_id} ({email})")
            continue

        id_valid, id_err = id_guardrail.validate(profile)
        if not id_valid:
            print(f"[!] Identity guardrail error for {case_id}: {id_err}")
            continue

        # Phase 2: Audit Scanner
        audit_res = scanner.audit_case(case_id, profile, audit_at)
        res_valid, audit_errs = audit_guardrail.validate(audit_res)
        if not res_valid:
            print(f"[!] Audit guardrail error for {case_id}: {audit_errs}")
            continue

        if audit_res.deletion_status == "COMPLETE":
            complete_count += 1
        else:
            incomplete_count += 1

        # Phase 3: Step-JSON Builder
        steps = StepJsonBuilder.build_steps(audit_res)
        step_violations = StepJsonGuardrail.validate(steps, audit_res.deletion_status)
        if step_violations:
            print(f"[!] Step-JSON guardrail violations for {case_id}: {step_violations}")
        else:
            guardrails_passed_count += 1

        steps_str = StepJsonBuilder.to_json_str(steps)
        results.append({
            "case_id": case_id,
            "deletion_status": audit_res.deletion_status,
            "steps_json": steps_str,
        })

    # Summary
    print(f"\n[Execution Summary] Processed {len(requests_df)} cases.")
    print(f"  - COMPLETE: {complete_count}")
    print(f"  - INCOMPLETE: {incomplete_count}")
    print(f"  - NOT_APPLICABLE: {not_applicable_count}")
    print(f"  - All Guardrails Passed: {guardrails_passed_count}/{len(requests_df)} ({guardrails_passed_count / len(requests_df) * 100:.1f}%)")

    # If running whole dataset, save output.csv
    if not is_sample:
        out_df = pd.DataFrame(results)
        # Sort by case_id numerically if case_XX format
        out_df["sort_key"] = out_df["case_id"].apply(
            lambda x: int(x.split("_")[1]) if "_" in x and x.split("_")[1].isdigit() else 9999
        )
        out_df = out_df.sort_values("sort_key").drop(columns=["sort_key"])
        out_df.to_csv("output.csv", index=False)
        print(f"Successfully generated root output.csv with {len(out_df)} sorted rows.")


if __name__ == "__main__":
    main()
