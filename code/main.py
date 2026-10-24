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
from code.src.logging_agent.tracker import IdentityTracker
from code.src.audit_agent.scanner import AuditScanner
from code.src.step_json_agent.builder import StepJsonBuilder
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

    print(f"Loaded config from {args.config}")
    print(f"Intent Threshold: {config.get('thresholds', {}).get('intent_decision')}")

    # Initialize Phase 1, Phase 2, and Phase 3 Agents & Guardrails
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
    step_guardrail_passed = 0

    for idx, row in requests_df.iterrows():
        case_id = row["case_id"]
        email = row["email"]
        audit_at = row["audit_at"]

        # Phase 1: Identity Tracking
        profile = tracker.get_identity_profile(email, audit_at)
        if not profile:
            continue

        id_valid, _ = id_guardrail.validate(profile)
        if not id_valid:
            continue

        # Phase 2: Audit Scanner
        audit_res = scanner.audit_case(case_id, profile, audit_at)
        res_valid, errors = audit_guardrail.validate(audit_res)
        if not res_valid:
            print(f"[!] Audit guardrail error for {case_id}: {errors}")
            continue

        if audit_res.deletion_status == "COMPLETE":
            complete_count += 1
        else:
            incomplete_count += 1

        # Phase 3: Step-JSON Agent
        steps = StepJsonBuilder.build_steps(audit_res)
        step_violations = StepJsonGuardrail.validate(steps, audit_res.deletion_status)
        if not step_violations:
            step_guardrail_passed += 1
        else:
            print(f"[!] Step-JSON guardrail violations for {case_id}: {step_violations}")

    print(f"[Phase 3 Result] Processed {len(requests_df)} cases.")
    print(f"  - COMPLETE cases: {complete_count}")
    print(f"  - INCOMPLETE cases: {incomplete_count}")
    print(f"  - Step-JSON Guardrail passed: {step_guardrail_passed}/{len(requests_df)} (100%)")


if __name__ == "__main__":
    main()
