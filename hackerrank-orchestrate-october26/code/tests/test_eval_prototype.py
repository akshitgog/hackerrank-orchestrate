import json
import re
from pathlib import Path
import pandas as pd
from code.src.logging_agent.tracker import IdentityTracker
from code.src.audit_agent.scanner import AuditScanner
from code.src.step_json_agent.builder import StepJsonBuilder
from code.src.audit_agent.models import AuditFinding, AuditVerificationProof, AuditResult

req_df = pd.read_csv("dataset/sample_deletion_requests.csv")
truth_df = pd.read_csv("dataset/sample_output.csv")
act_df = pd.read_csv("dataset/system_activity.csv")

del_acc = act_df[(act_df["source_system"] == "deletion_worker") & (act_df["target_system"] == "account_service")].copy()
del_acc["event_dt"] = pd.to_datetime(del_acc["event_time"])

tracker = IdentityTracker("dataset/user_identities.csv", "dataset/user_audit_log.csv")
scanner = AuditScanner("dataset/evidence_files.csv", "dataset/system_activity.csv", "dataset/deletion_rules.csv", "cache/multimodal_cache.json")

print("Ready to evaluate...")
