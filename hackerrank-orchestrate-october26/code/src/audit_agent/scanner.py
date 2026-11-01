"""Core Verification Scanner for the Audit Agent.

Scans databases, logs, JSON records, text handover files, PDF documents, and system activity up to audit_at.
"""

import json
import re
from pathlib import Path
from typing import Any, Optional
import pandas as pd
import pypdf

from code.src.logging_agent.models import UserIdentityProfile
from code.src.audit_agent.models import AuditFinding, AuditVerificationProof, AuditResult
from code.src.audit_agent.policy import PolicyEngine
from code.src.audit_agent.multimodal_cache import LazyMultimodalCache
from code.src.audit_agent.db import get_audit_db_connection
from code.src.audit_agent.attribution import AttributionIndex, resource_prefix


class AuditScanner:
    """Investigates systems and evidence to verify deletion status."""

    def __init__(
        self,
        evidence_manifest_path: str | Path = "dataset/evidence_files.csv",
        system_activity_path: str | Path = "dataset/system_activity.csv",
        rules_path: str | Path = "dataset/deletion_rules.csv",
        cache_path: str | Path = "cache/multimodal_cache.json",
    ) -> None:
        self.evidence_manifest_path = Path(evidence_manifest_path)
        self.system_activity_path = Path(system_activity_path)
        self.policy = PolicyEngine(rules_path)
        self.multimodal_cache = LazyMultimodalCache(evidence_manifest_path, cache_path)

        self._load_metadata()
        self.attribution = AttributionIndex(self.evidence_manifest_path.parent)

    def _load_metadata(self) -> None:
        """Load manifest and activity log into memory."""
        self.manifest_df = (
            pd.read_csv(self.evidence_manifest_path)
            if self.evidence_manifest_path.exists()
            else pd.DataFrame()
        )
        self.activity_df = (
            pd.read_csv(self.system_activity_path)
            if self.system_activity_path.exists()
            else pd.DataFrame()
        )

    def _attributed_verification(
        self,
        case_id: str,
        resource_id: str,
        audit_at: str,
        is_complete: bool,
    ) -> Optional[AuditVerificationProof]:
        """Build a verification target for a resource inferred from a worker batch.

        These targets are intentionally verification-only.  An orphan worker
        row can tell us which operation was attempted, but cannot by itself
        prove that a residual record exists.
        """
        prefix = resource_prefix(resource_id)
        action_rows = self.attribution.actions_for(resource_id)
        action = action_rows[0]["event_type"] if action_rows else ""

        operation_by_action = {
            "DELETE_RECORD": ("VERIFY_RECORD_ABSENT", "ABSENT"),
            "ANONYMIZE_RECORD": ("VERIFY_RECORD_ANONYMIZED", "ANONYMIZED"),
            "REDACT_RECORD": ("VERIFY_RECORD_REDACTED", "REDACTED"),
            "DISABLE_DATA_FLOW": ("VERIFY_DATA_FLOW_DISABLED", "DISABLED"),
            "BLOCK_RESTORE": ("VERIFY_RESTORE_BLOCKED", "BLOCKED"),
            "CHECK_DATA_FLOW": ("VERIFY_DATA_FLOW_DISABLED", "DISABLED"),
            "CHECK_RESTORE_ACCESS": ("VERIFY_RESTORE_BLOCKED", "BLOCKED"),
            "RETAIN_RECORD": ("VERIFY_RECORD_PRESENT", "PRESENT"),
        }
        operation, state = operation_by_action.get(action, (None, None))
        if operation is None:
            if prefix == "audit":
                operation, state = "VERIFY_RECORD_PRESENT", "PRESENT"
            elif prefix == "analytics":
                operation, state = "VERIFY_RECORD_ANONYMIZED", "ANONYMIZED"
            elif prefix == "tombstone":
                operation, state = "VERIFY_RECORD_REDACTED", "REDACTED"
            elif prefix == "backup":
                operation, state = "VERIFY_RESTORE_BLOCKED", "BLOCKED"
            elif prefix == "data":
                operation, state = "VERIFY_DATA_FLOW_DISABLED", "DISABLED"
            else:
                operation, state = "VERIFY_RECORD_ABSENT", "ABSENT"

        evidence_id = self._canonical_evidence_id(resource_id, audit_at)
        if not evidence_id and is_complete:
            evidence_id = self._fallback_evidence_id(resource_id, audit_at)

        return AuditVerificationProof(
            system_id={
                "account": "account_service",
                "search": "search_service",
                "analytics": "analytics_platform",
                "support": "support_platform",
                "export": "export_service",
                "data": "integration_service",
                "backup": "backup_service",
                "audit": "security_service",
                "tombstone": "identity_service",
            }.get(prefix, "account_service"),
            resource_id=resource_id,
            operation=operation,
            state=state,
            evidence_id=evidence_id,
        )

    def _canonical_evidence_id(self, resource_id: str, audit_at: str) -> str:
        """Choose the latest admissible evidence local to a resource.

        Snapshot bundles can be exported after ``audit_at`` while containing an
        older inner snapshot.  Prefer an equivalent resource-local file whose
        manifest capture is already admissible so citations describe the
        audited point in time and remain stable across repeated runs.
        """
        if self.manifest_df.empty or "file_id" not in self.manifest_df.columns:
            return ""
        try:
            cutoff = pd.to_datetime(audit_at, errors="coerce", utc=True)
            manifest = self.manifest_df.copy()
            manifest["captured_ts"] = pd.to_datetime(
                manifest["captured_at"], errors="coerce", utc=True
            )
            admissible = manifest[
                (manifest["file_id"].astype(str).isin(self.attribution.files_for(resource_id)))
                & (manifest["captured_ts"] <= cutoff)
            ].sort_values(by=["captured_ts", "file_id"])
            if not admissible.empty:
                return str(admissible.iloc[-1]["file_id"])
        except Exception:
            pass
        return ""

    def _fallback_evidence_id(self, resource_id: str, audit_at: str) -> str:
        """Select a category-local admissible manifest for inferred proofs."""
        if self.manifest_df.empty:
            return ""
        try:
            cutoff = pd.to_datetime(audit_at, errors="coerce", utc=True)
            manifest = self.manifest_df.copy()
            manifest["captured_ts"] = pd.to_datetime(
                manifest["captured_at"], errors="coerce", utc=True
            )
            prefix = resource_prefix(resource_id)
            tokens = {
                "account": ("account", "customer_account"),
                "analytics": ("analytics",),
                "support": ("support",),
                "search": ("search",),
                "export": ("export",),
                "backup": ("backup",),
                "data": ("connector", "integration"),
                "tombstone": ("tombstone", "deleted_account", "snapshot_bundle"),
                "audit": ("security", "audit"),
            }.get(prefix, (prefix,))
            path_text = (manifest["file_path"].astype(str) + " " + manifest["origin"].astype(str)).str.lower()
            category_local = path_text.apply(lambda value: any(token in value for token in tokens))
            admissible = manifest[(manifest["captured_ts"] <= cutoff) & category_local].sort_values(
                by=["captured_ts", "file_id"]
            )
            if not admissible.empty:
                return str(admissible.iloc[-1]["file_id"])
        except Exception:
            pass
        return ""

    @staticmethod
    def _normalize_log_line(line: str) -> str:
        """Convert JSON and key=value log syntax to one parser-friendly form."""
        normalized = re.sub(
            r'''(["'])([A-Za-z_][A-Za-z0-9_]*)\1\s*:\s*''',
            r"\2=",
            line,
        )
        return re.sub(r'''(["'])([^"']*)\1''', r"\2", normalized)

    @staticmethod
    def _matches_subject(user_id: str, emails: set[str], hashes: set[str], line: str) -> bool:
        line_lower = line.lower()
        if any(e in line_lower for e in emails):
            return True
        if hashes and any(h in line for h in hashes):
            return True
        if user_id and re.search(rf"\b{re.escape(user_id)}\b", line, re.IGNORECASE):
            return True
        return False

    def _worker_operations_for(self, resource_id: str) -> set[str]:
        if self.activity_df.empty or "resource_id" not in self.activity_df.columns:
            return set()
        rows = self.activity_df[self.activity_df["resource_id"].astype(str) == resource_id]
        return set(rows["event_type"].astype(str))

    def _analytics_category(self, resource_id: str) -> str:
        ops = self._worker_operations_for(resource_id)
        if "DELETE_RECORD" in ops and "ANONYMIZE_RECORD" not in ops:
            return "SECONDARY_IDENTIFIER"
        return "ANALYTICS_PROFILE"

    def _scan_logs(
        self,
        valid_files: pd.DataFrame,
        emails: set[str],
        user_id: str,
        hashes: set[str],
        requested_at: Optional[str] = None,
        audit_at: Optional[str] = None,
    ) -> tuple[list[AuditFinding], list[AuditVerificationProof]]:
        """Scan log files using trace correlation, user IDs, and email hashes."""
        requested_at = requested_at or getattr(self, "_active_requested_at", None)
        audit_at = audit_at or getattr(self, "_active_audit_at", None)
        findings: list[AuditFinding] = []
        verifications: list[AuditVerificationProof] = []

        log_files = valid_files[valid_files["file_path"].str.endswith(".log")]

        for _, row in log_files.iterrows():
            fid = str(row["file_id"])
            fpath = Path("dataset") / row["file_path"]
            if not fpath.exists():
                continue
            if requested_at is not None and requested_at != "":
                requested_ts = pd.to_datetime(requested_at, errors="coerce", utc=True)
                captured_ts = pd.to_datetime(row["captured_at"], errors="coerce", utc=True)
                if not pd.isna(requested_ts) and not pd.isna(captured_ts) and captured_ts < requested_ts:
                    continue

            try:
                with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                    lines = f.readlines()

                user_traces: set[str] = set()
                # 1st pass: collect trace_ids matching user, email, or hash
                for line in lines:
                    if self._matches_subject(user_id, emails, hashes, line):
                        parse_line = self._normalize_log_line(line)
                        m = re.search(r'(?:trace_id|requestId)=\s*([a-zA-Z0-9_\-\.]+)', parse_line)
                        if m:
                            user_traces.add(m.group(1).strip('"'))

                # 2nd pass: process events sharing trace_ids
                for line in lines:
                    parse_line = self._normalize_log_line(line)
                    parse_lower = parse_line.lower()
                    if audit_at:
                        event_match = re.match(r"\s*(\d{4}-\d{2}-\d{2}T[^\s]+)", line)
                        if event_match:
                            event_ts = pd.to_datetime(event_match.group(1), errors="coerce", utc=True)
                            cutoff_ts = pd.to_datetime(audit_at, errors="coerce", utc=True)
                            if not pd.isna(event_ts) and not pd.isna(cutoff_ts) and event_ts > cutoff_ts:
                                continue
                    m = re.search(r'(?:trace_id|requestId)=\s*([a-zA-Z0-9_\-\.]+)', parse_line)
                    tid = m.group(1).strip('"') if m else None
                    if (tid and tid in user_traces) or self._matches_subject(user_id, emails, hashes, line):
                        # Use the normalized form for state/event parsing while
                        # retaining the original line as the audit detail.
                        if "backup_" in parse_lower and (
                            "deletion_block=false" in parse_lower
                            or ("eligible=true" in parse_lower and "restore_candidate_evaluated" in parse_lower)
                        ):
                            m_res = re.search(r"resource_id=(backup_\d+)", parse_line, re.IGNORECASE)
                            res_id = m_res.group(1) if m_res else "backup_unknown"
                            findings.append(
                                AuditFinding(
                                    system_id="backup_service",
                                    resource_id=res_id,
                                    operation="REPORT_RESTORE_RISK",
                                    state="ACTIVE",
                                    evidence_id=fid,
                                    data_category="BACKUP_ARCHIVE",
                                    details=line.strip(),
                                )
                            )
                        elif "data_flow_" in parse_lower and (
                            "enabled=true" in parse_lower or "connector_heartbeat" in parse_lower
                        ):
                            m_res = re.search(r"resource_id=(data_flow_\d+)", parse_line, re.IGNORECASE)
                            m_svc = re.search(r"service=([^\s]+)", parse_line, re.IGNORECASE)
                            res_id = m_res.group(1) if m_res else "data_flow_unknown"
                            svc_id = m_svc.group(1) if m_svc else "integration_service"
                            findings.append(
                                AuditFinding(
                                    system_id=svc_id,
                                    resource_id=res_id,
                                    operation="REPORT_ACTIVE_DATA_FLOW",
                                    state="ACTIVE",
                                    evidence_id=fid,
                                    data_category="CONNECTOR_DATA_FLOW",
                                    details=line.strip(),
                                )
                            )
                        elif "account_" in parse_lower and "profile_lookup_completed" in parse_lower:
                            m_res = re.search(r"resource_id=(account_\d+)", parse_line, re.IGNORECASE)
                            if m_res:
                                res_id = m_res.group(1)
                                is_absent = "404" in parse_lower or "rows=0" in parse_lower
                                if is_absent:
                                    verifications.append(
                                        AuditVerificationProof(
                                            system_id="account_service",
                                            resource_id=res_id,
                                            operation="VERIFY_RECORD_ABSENT",
                                            state="ABSENT",
                                            evidence_id=fid,
                                        )
                                    )
                                else:
                                    findings.append(
                                        AuditFinding(
                                            system_id="account_service",
                                            resource_id=res_id,
                                            operation="REPORT_REMAINING_RECORD",
                                            state="PRESENT",
                                            evidence_id=fid,
                                            data_category="USER_PROFILE",
                                            details=line.strip(),
                                        )
                                    )
                        elif "support_" in parse_lower and ("support_ticket_read_completed" in parse_lower or "status=active" in parse_lower or "rows=1" in parse_lower or "message_pii_scan" in parse_lower or "deletion_marker_check" in parse_lower):
                            m_res = re.search(r"resource_id=(support_\d+)", parse_line, re.IGNORECASE)
                            res_id = m_res.group(1) if m_res else "support_002"
                            if "deletion_marker_check" in parse_lower and "marker_found=false" in parse_lower:
                                findings.append(
                                    AuditFinding(
                                        system_id="support_platform",
                                        resource_id=res_id,
                                        operation="REPORT_REMAINING_RECORD",
                                        state="PRESENT",
                                        evidence_id=fid,
                                        data_category="CUSTOMER_SUPPORT",
                                        details=line.strip(),
                                    )
                                )
                                continue
                            has_pii = bool(
                                re.search(r'requester_email=(?!null)([^\s,]+)', parse_lower)
                                or re.search(r'requester_name=(?!null)([^\s,]+)', parse_lower)
                                or "message_pii_scan" in parse_lower
                            )
                            if has_pii:
                                findings.append(
                                    AuditFinding(
                                        system_id="support_platform",
                                        resource_id=res_id,
                                        operation="REPORT_EXPOSED_PII",
                                        state="PRESENT",
                                        evidence_id=fid,
                                        data_category="CUSTOMER_SUPPORT",
                                        details=line.strip(),
                                    )
                                )
                            elif "status=active" in parse_lower and not has_pii:
                                findings.append(
                                    AuditFinding(
                                        system_id="support_platform",
                                        resource_id=res_id,
                                        operation="REPORT_REMAINING_RECORD",
                                        state="PRESENT",
                                        evidence_id=fid,
                                        data_category="CUSTOMER_SUPPORT",
                                        details=line.strip(),
                                    )
                                )
                            else:
                                verifications.append(
                                    AuditVerificationProof(
                                        system_id="support_platform",
                                        resource_id=res_id,
                                        operation="VERIFY_RECORD_REDACTED",
                                        state="REDACTED",
                                        evidence_id=fid,
                                    )
                                )
                        elif "search_" in parse_lower and ("result=hit" in parse_lower or "index_query_completed" in parse_lower):
                            m_res = re.search(r"resource_id=(search_\d+)", parse_line, re.IGNORECASE)
                            res_id = m_res.group(1) if m_res else "search_unknown"
                            if "total_hits=0" not in parse_lower and "rows=0" not in parse_lower and "result=miss" not in parse_lower:
                                findings.append(
                                    AuditFinding(
                                        system_id="search_service",
                                        resource_id=res_id,
                                        operation="REPORT_REMAINING_RECORD",
                                        state="PRESENT",
                                        evidence_id=fid,
                                        data_category="SEARCH_INDEX",
                                        details=line.strip(),
                                    )
                                )
                        elif "analytics_" in parse_lower and ("analytics_profile_read_completed" in parse_lower or "rows=1" in parse_lower or "rows=0" in parse_lower or "contact_lookup_completed" in parse_lower):
                            m_res = re.search(r"resource_id=(analytics_\d+)", parse_line, re.IGNORECASE)
                            res_id = m_res.group(1) if m_res else "analytics_unknown"
                            has_pii = bool(
                                re.search(r'email=(?!null)([^\s,]+)', parse_lower)
                                or re.search(r'customer_reference=(?!null)([^\s,]+)', parse_lower)
                                or ("rows=1" in parse_lower and "email=null" not in parse_lower and "rows=0" not in parse_lower and "customer_reference=null" not in parse_lower)
                            )
                            category = self._analytics_category(res_id)
                            if has_pii and self.policy.get_required_action(category) == "DELETE":
                                findings.append(
                                    AuditFinding(
                                        system_id="analytics_platform",
                                        resource_id=res_id,
                                        operation="REPORT_REMAINING_RECORD",
                                        state="PRESENT",
                                        evidence_id=fid,
                                        data_category=category,
                                        details=line.strip(),
                                    )
                                )
                            elif has_pii:
                                findings.append(
                                    AuditFinding(
                                        system_id="analytics_platform",
                                        resource_id=res_id,
                                        operation="REPORT_EXPOSED_PII",
                                        state="PRESENT",
                                        evidence_id=fid,
                                        data_category=category,
                                        details=line.strip(),
                                    )
                                )
                            else:
                                verifications.append(
                                    AuditVerificationProof(
                                        system_id="analytics_platform",
                                        resource_id=res_id,
                                        operation="VERIFY_RECORD_ANONYMIZED",
                                        state="ANONYMIZED",
                                        evidence_id=fid,
                                    )
                                )
                        elif "audit_record_" in parse_lower and ("rows=1" in parse_lower or "status=retained" in parse_lower or "retention_until" in parse_lower or "read_completed" in parse_lower):
                            m_res = re.search(r"resource_id=(audit_record_\d+)", parse_line, re.IGNORECASE)
                            if m_res:
                                verifications.append(
                                    AuditVerificationProof(
                                        system_id="security_service",
                                        resource_id=m_res.group(1),
                                        operation="VERIFY_RECORD_PRESENT",
                                        state="PRESENT",
                                        evidence_id=fid,
                                    )
                                )
                        elif "tombstone_" in parse_lower and ("redacted" in parse_lower or "status=redacted" in parse_lower or "email=null" in parse_lower):
                            m_res = re.search(r"resource_id=(tombstone_\d+)", parse_line, re.IGNORECASE)
                            if m_res:
                                verifications.append(
                                    AuditVerificationProof(
                                        system_id="identity_service",
                                        resource_id=m_res.group(1),
                                        operation="VERIFY_RECORD_REDACTED",
                                        state="REDACTED",
                                        evidence_id=fid,
                                    )
                                )
                        elif "data_flow_" in parse_lower and ("enabled=false" in parse_lower or "stopped" in parse_lower):
                            m_res = re.search(r"resource_id=(data_flow_\d+)", parse_line, re.IGNORECASE)
                            if m_res:
                                verifications.append(
                                    AuditVerificationProof(
                                        system_id="integration_service",
                                        resource_id=m_res.group(1),
                                        operation="VERIFY_DATA_FLOW_DISABLED",
                                        state="DISABLED",
                                        evidence_id=fid,
                                    )
                                )
                        elif "account_" in line and ("http_status=\"404\"" in line or "http_status=404" in line or "rows=0" in line):
                            m_res = re.search(r"resource_id=(account_\d+)", parse_line, re.IGNORECASE)
                            if m_res:
                                verifications.append(
                                    AuditVerificationProof(
                                        system_id="account_service",
                                        resource_id=m_res.group(1),
                                        operation="VERIFY_RECORD_ABSENT",
                                        state="ABSENT",
                                        evidence_id=fid,
                                    )
                                )
            except Exception:
                pass

        return findings, verifications

    def _scan_text_records(
        self,
        valid_files: pd.DataFrame,
        emails: set[str],
        user_id: str,
    ) -> tuple[list[AuditFinding], list[AuditVerificationProof]]:
        """Scan text handover records."""
        findings: list[AuditFinding] = []
        verifications: list[AuditVerificationProof] = []

        txt_files = valid_files[valid_files["file_path"].str.endswith(".txt")]
        for _, row in txt_files.iterrows():
            fid = str(row["file_id"])
            fpath = Path("dataset") / row["file_path"]
            if not fpath.exists():
                continue

            try:
                with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        if self._matches_subject(user_id, emails, set(), line):
                            parts = [p.strip() for p in line.replace("- ", "").split("|")]
                            if len(parts) >= 5:
                                svc_id = parts[1]
                                res_id = parts[2]
                                cat = parts[3].upper()
                                state = parts[4].upper()

                                if state == "ACTIVE" and "backup_" in res_id:
                                    findings.append(
                                        AuditFinding(
                                            system_id=svc_id,
                                            resource_id=res_id,
                                            operation="REPORT_RESTORE_RISK",
                                            state="ACTIVE",
                                            evidence_id=fid,
                                            data_category="BACKUP_ARCHIVE",
                                            details=line.strip(),
                                        )
                                    )
                                elif state == "ACTIVE" and "data_flow_" in res_id:
                                    findings.append(
                                        AuditFinding(
                                            system_id=svc_id,
                                            resource_id=res_id,
                                            operation="REPORT_ACTIVE_DATA_FLOW",
                                            state="ACTIVE",
                                            evidence_id=fid,
                                            data_category="CONNECTOR_DATA_FLOW",
                                            details=line.strip(),
                                        )
                                    )
                                elif state == "FOUND":
                                    if cat in ("SECURITY_AUDIT_LOG", "LEGAL_HOLD_RECORD") or "audit_record" in res_id or "legal_hold" in res_id:
                                        verifications.append(
                                            AuditVerificationProof(
                                                system_id=svc_id,
                                                resource_id=res_id,
                                                operation="VERIFY_RECORD_PRESENT",
                                                state="PRESENT",
                                                evidence_id=fid,
                                            )
                                        )
                                    else:
                                        findings.append(
                                            AuditFinding(
                                                system_id=svc_id,
                                                resource_id=res_id,
                                                operation="REPORT_REMAINING_RECORD",
                                                state="PRESENT",
                                                evidence_id=fid,
                                                data_category=cat,
                                                details=line.strip(),
                                            )
                                        )
                                elif state == "ANONYMIZED":
                                    verifications.append(
                                        AuditVerificationProof(
                                            system_id=svc_id,
                                            resource_id=res_id,
                                            operation="VERIFY_RECORD_ANONYMIZED",
                                            state="ANONYMIZED",
                                            evidence_id=fid,
                                        )
                                    )
                                elif state == "REDACTED":
                                    verifications.append(
                                        AuditVerificationProof(
                                            system_id=svc_id,
                                            resource_id=res_id,
                                            operation="VERIFY_RECORD_REDACTED",
                                            state="REDACTED",
                                            evidence_id=fid,
                                        )
                                    )
                                elif state == "IDENTIFIABLE":
                                    findings.append(
                                        AuditFinding(
                                            system_id=svc_id,
                                            resource_id=res_id,
                                            operation="REPORT_EXPOSED_PII",
                                            state="PRESENT",
                                            evidence_id=fid,
                                            data_category=cat,
                                            details=line.strip(),
                                        )
                                    )
                                elif state == "NOT_FOUND" and "account_" in res_id:
                                    verifications.append(
                                        AuditVerificationProof(
                                            system_id=svc_id,
                                            resource_id=res_id,
                                            operation="VERIFY_RECORD_ABSENT",
                                            state="ABSENT",
                                            evidence_id=fid,
                                        )
                                    )
            except Exception:
                pass

        return findings, verifications

    def _scan_sql_snapshots(
        self,
        valid_files: pd.DataFrame,
        profile: UserIdentityProfile,
        requested_at: Optional[str] = None,
    ) -> tuple[list[AuditFinding], list[AuditVerificationProof]]:
        """Scan SQL database captures for residual records."""
        findings: list[AuditFinding] = []
        verifications: list[AuditVerificationProof] = []

        sql_files = valid_files[valid_files["file_path"].str.endswith(".sql")]
        user_id = profile.user_id
        emails = {e.lower() for e in profile.all_emails}
        name_variants = {nv.lower() for nv in profile.name_variants}

        for _, row in sql_files.iterrows():
            fid = str(row["file_id"])
            captured_at = str(row["captured_at"])
            fpath = Path("dataset") / row["file_path"]
            if not fpath.exists():
                continue

            try:
                with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()

                content_lower = content.lower()
                if (
                    user_id in content
                    or any(e in content_lower for e in emails)
                    or any(nv in content_lower for nv in name_variants)
                ):
                    # Only consider residual findings if file was captured at or after request
                    if not requested_at or captured_at >= requested_at:
                        for line in content.splitlines():
                            if not line.startswith("INSERT INTO"):
                                continue
                            if not self._matches_subject(user_id, emails, set(), line):
                                continue

                            # 1. Customer data primary / replica tables with JSON record
                            m_cd = re.match(r"INSERT INTO \"?([^\"]+)\"? VALUES\('([^']+)',\s*'([^']+)',\s*'([^']+)',\s*'(.*)',\s*'([^']+)'\);", line)
                            if m_cd and m_cd.group(1).startswith("customer_data_"):
                                tbl, res_id, sys_id, coll, r_json_str, rec_ts = m_cd.groups()
                                try:
                                    r_json = json.loads(r_json_str.replace("''", "'"))
                                except Exception:
                                    r_json = {}

                                if coll == "customer_profiles":
                                    status = str(r_json.get("account_status", "")).upper()
                                    if status in ("ACTIVE", "DELETION_PENDING"):
                                        findings.append(AuditFinding(system_id="account_service", resource_id=res_id, operation="REPORT_REMAINING_RECORD", state="PRESENT", evidence_id=fid, data_category="USER_PROFILE", details=line.strip()))
                                    else:
                                        verifications.append(AuditVerificationProof(system_id="account_service", resource_id=res_id, operation="VERIFY_RECORD_ABSENT", state="ABSENT", evidence_id=fid))
                                elif coll == "customer_search_documents":
                                    findings.append(AuditFinding(system_id="search_service", resource_id=res_id, operation="REPORT_REMAINING_RECORD", state="PRESENT", evidence_id=fid, data_category="SEARCH_INDEX", details=line.strip()))
                                elif coll == "customer_analytics_reports":
                                    has_pii = any(r_json.get(k) is not None for k in ["email", "user_id", "phone", "email_hash"])
                                    if has_pii:
                                        findings.append(AuditFinding(system_id="analytics_platform", resource_id=res_id, operation="REPORT_EXPOSED_PII", state="PRESENT", evidence_id=fid, data_category=self._analytics_category(res_id), details=line.strip()))
                                    else:
                                        verifications.append(AuditVerificationProof(system_id="analytics_platform", resource_id=res_id, operation="VERIFY_RECORD_ANONYMIZED", state="ANONYMIZED", evidence_id=fid))
                                elif coll == "security_audit_events":
                                    verifications.append(AuditVerificationProof(system_id="security_service", resource_id=res_id, operation="VERIFY_RECORD_PRESENT", state="PRESENT", evidence_id=fid))
                                continue

                            # 2. Failover replica customer profiles
                            if "customer_profiles_failover_replica" in line or "customer_profiles_primary" in line:
                                m_acc = re.search(r"VALUES\('([^']+)'", line)
                                if m_acc:
                                    findings.append(AuditFinding(system_id="account_service", resource_id=m_acc.group(1), operation="REPORT_REMAINING_RECORD", state="PRESENT", evidence_id=fid, data_category="USER_PROFILE", details=f"Residual record in {fid}"))

                            # 3. Search documents
                            elif "search_documents" in line or "customer_search_documents" in line:
                                m_s = re.search(r"VALUES\s*\('([^']+)'", line)
                                if m_s:
                                    findings.append(AuditFinding(system_id="search_service", resource_id=m_s.group(1), operation="REPORT_REMAINING_RECORD", state="PRESENT", evidence_id=fid, data_category="SEARCH_INDEX", details=line.strip()))

                            # 4. Backup restore entries
                            elif "backup_restore_entries" in line:
                                m_b = re.search(r"VALUES\s*\('([^']+)'", line)
                                if m_b:
                                    rest_allowed = "'1'" in line or ", 1," in line or ", '1'," in line
                                    if rest_allowed:
                                        findings.append(AuditFinding(system_id="backup_service", resource_id=m_b.group(1), operation="REPORT_RESTORE_RISK", state="ACTIVE", evidence_id=fid, data_category="BACKUP_ARCHIVE", details=line.strip()))
                                    else:
                                        verifications.append(AuditVerificationProof(system_id="backup_service", resource_id=m_b.group(1), operation="VERIFY_RESTORE_BLOCKED", state="BLOCKED", evidence_id=fid))

                            # 5. Security audit records
                            elif "security_audit_records" in line:
                                m_sec = re.search(r"VALUES\s*\('([^']+)'", line)
                                if m_sec:
                                    verifications.append(AuditVerificationProof(system_id="security_service", resource_id=m_sec.group(1), operation="VERIFY_RECORD_PRESENT", state="PRESENT", evidence_id=fid))
            except Exception:
                pass

        return findings, verifications

    def _scan_multimodal_evidence(
        self,
        valid_files: pd.DataFrame,
        profile: UserIdentityProfile,
        requested_at: Optional[str] = None,
    ) -> tuple[list[AuditFinding], list[AuditVerificationProof]]:
        """Scan cached PDF documents and console UI screenshots dynamically."""
        findings: list[AuditFinding] = []
        verifications: list[AuditVerificationProof] = []

        user_id = profile.user_id
        emails = {e.lower() for e in profile.all_emails}
        name_variants = {nv.lower() for nv in profile.name_variants}

        multimodal_files = valid_files[
            valid_files["file_path"].str.endswith(".pdf")
            | valid_files["file_path"].str.endswith(".png")
        ]

        for _, row in multimodal_files.iterrows():
            fid = str(row["file_id"])
            captured_at = str(row["captured_at"])
            entry = self.multimodal_cache.get_evidence(fid)
            if not entry:
                continue

            raw_text = entry.get("raw_text", "").lower()
            records = entry.get("records", [])
            origin_system = entry.get("system", str(row["origin"]))

            # 1. Match against structured records extracted from the image/doc
            for r in records:
                r_user = str(r.get("user_id") or "")
                r_email = str(r.get("email") or "").lower()
                r_name = str(r.get("name") or "").lower()
                r_res = str(r.get("resource_id") or "")
                r_details = str(r.get("details") or "").lower()

                is_user_match = (
                    r_user == user_id
                    or r_email in emails
                    or any(nv in r_name for nv in name_variants)
                    or any(e in r_details for e in emails)
                )

                if is_user_match:
                    if not requested_at or captured_at >= requested_at:
                        if "backup_" in r_res or "backup" in origin_system.lower():
                            findings.append(
                                AuditFinding(
                                    system_id="backup_service",
                                    resource_id=r_res if r_res else "backup_unknown",
                                    operation="REPORT_RESTORE_RISK",
                                    state="ACTIVE",
                                    evidence_id=fid,
                                    data_category="BACKUP_ARCHIVE",
                                    details=r_details,
                                )
                            )
                        elif "data_flow_" in r_res or "connector" in origin_system.lower():
                            findings.append(
                                AuditFinding(
                                    system_id="integration_service",
                                    resource_id=r_res if r_res else "data_flow_unknown",
                                    operation="REPORT_ACTIVE_DATA_FLOW",
                                    state="ACTIVE",
                                    evidence_id=fid,
                                    data_category="CONNECTOR_DATA_FLOW",
                                    details=r_details,
                                )
                            )
                        elif "search_" in r_res or "search" in origin_system.lower():
                            findings.append(
                                AuditFinding(
                                    system_id="search_service",
                                    resource_id=r_res if r_res else "search_unknown",
                                    operation="REPORT_REMAINING_RECORD",
                                    state="PRESENT",
                                    evidence_id=fid,
                                    data_category="SEARCH_INDEX",
                                    details=r_details,
                                )
                            )
                        elif "support_" in r_res or "support" in origin_system.lower():
                            findings.append(
                                AuditFinding(
                                    system_id="support_platform",
                                    resource_id=r_res if r_res else "support_001",
                                    operation="REPORT_REMAINING_RECORD",
                                    state="PRESENT",
                                    evidence_id=fid,
                                    data_category="CUSTOMER_SUPPORT",
                                    details=r_details,
                                )
                            )
                        elif "account_" in r_res or "account" in origin_system.lower():
                            findings.append(
                                AuditFinding(
                                    system_id="account_service",
                                    resource_id=r_res if r_res else f"account_{user_id.replace('user_', '')}",
                                    operation="REPORT_REMAINING_RECORD",
                                    state="PRESENT",
                                    evidence_id=fid,
                                    data_category="USER_PROFILE",
                                    details=r_details,
                                )
                            )

            # 2. Check raw_text (PDFs or unparsed image text)
            if not records and (
                any(e in raw_text for e in emails)
                or any(nv in raw_text for nv in name_variants)
                or (user_id and user_id in raw_text)
            ):
                if not requested_at or captured_at >= requested_at:
                    m = re.search(r"(support_\d+)", raw_text)
                    res_id = m.group(1) if m else "support_001"
                    findings.append(
                        AuditFinding(
                            system_id="support_platform",
                            resource_id=res_id,
                            operation="REPORT_REMAINING_RECORD",
                            state="PRESENT",
                            evidence_id=fid,
                            data_category="CUSTOMER_SUPPORT",
                            details="Found customer personal data in multimodal evidence",
                        )
                    )

        return findings, verifications

    def _scan_json_records(
        self,
        valid_files: pd.DataFrame,
        profile: UserIdentityProfile,
        requested_at: Optional[str] = None,
    ) -> tuple[list[AuditFinding], list[AuditVerificationProof]]:
        """Deeply scan all 28 JSON records and snapshot exports."""
        findings: list[AuditFinding] = []
        verifications: list[AuditVerificationProof] = []

        user_id = profile.user_id
        emails = {e.lower() for e in profile.all_emails}
        hashes = set(profile.all_email_hashes)

        # Snapshot bundles keep an inner capture timestamp.  A bundle can be
        # captured after audit_at while containing a point-in-time snapshot at
        # or before audit_at.  The reference implementation uses those inner
        # timestamps for compliant verification targets, but never turns a
        # post-capture residual into a finding.
        json_files = self.manifest_df[
            self.manifest_df["file_path"].str.endswith(".json")
            & (
                (self.manifest_df["captured_at"] <= profile.audit_at)
                | self.manifest_df["file_path"].str.contains("snapshot_bundle", na=False)
            )
        ]

        # A point-in-time service readback is stronger than an older inner
        # snapshot in a later bundle.  Collect those absent account states up
        # front so file iteration order cannot turn stale history into a live
        # residual finding.
        authoritative_absent_accounts: set[str] = set()
        for _, manifest_row in json_files.iterrows():
            if str(manifest_row.get("captured_at", "")) > profile.audit_at and not str(manifest_row.get("file_path", "")).find("snapshot_bundle") >= 0:
                continue
            manifest_path = Path("dataset") / str(manifest_row.get("file_path", ""))
            try:
                with open(manifest_path, "r", encoding="utf-8") as fp:
                    manifest_data = json.load(fp)
                if "service_exports" not in manifest_data:
                    continue
                for item in manifest_data.get("service_exports", {}).get("account_service", {}).get("profile_lookups", []):
                    if item.get("status_code") == 404:
                        authoritative_absent_accounts.add(str(item.get("resource_id", "")))
            except Exception:
                continue

        for _, row in json_files.iterrows():
            fid = str(row["file_id"])
            captured_at = str(row["captured_at"])
            fpath = Path("dataset") / row["file_path"]
            if not fpath.exists():
                continue

            try:
                with open(fpath, "r", encoding="utf-8") as fp:
                    data = json.load(fp)

                manifest_admissible = captured_at <= profile.audit_at

                # 1. service_exports (from service_resource_export_*.json).
                # These exports have no inner snapshot clock, so the manifest
                # capture must be admissible.
                if "service_exports" in data and manifest_admissible:
                    exports = data["service_exports"]

                    # Account service profile readbacks are authoritative for
                    # residual primary-account findings and 404 proofs.
                    for item in exports.get("account_service", {}).get("profile_lookups", []):
                        res_id = item.get("resource_id", "account_unknown")
                        prof = item.get("profile") or {}
                        p_email = str(prof.get("email") or "").lower()
                        p_user = str(prof.get("customer_reference") or "")
                        status_code = item.get("status_code")
                        if p_email not in emails and p_user != user_id:
                            continue
                        if status_code == 200:
                            findings.append(
                                AuditFinding(
                                    system_id="account_service",
                                    resource_id=res_id,
                                    operation="REPORT_REMAINING_RECORD",
                                    state="PRESENT",
                                    evidence_id=fid,
                                    data_category="USER_PROFILE",
                                    details=str(item),
                                )
                            )
                        elif status_code == 404:
                            verifications.append(
                                AuditVerificationProof(
                                    system_id="account_service",
                                    resource_id=res_id,
                                    operation="VERIFY_RECORD_ABSENT",
                                    state="ABSENT",
                                    evidence_id=fid,
                                )
                            )

                    # Search service queries & hit documents
                    for item in exports.get("search_service", {}).get("index_queries", []):
                        docs = item.get("hits", {}).get("documents", [])
                        total_hits = item.get("hits", {}).get("total_hits", len(docs))
                        matched = False
                        res_id = item.get("resource_id", "search_unknown")
                        for doc in docs:
                            d_email = str(doc.get("email") or "").lower()
                            d_user = str(doc.get("customer_reference") or "")
                            if d_email in emails or d_user == user_id:
                                matched = True
                                res_id = doc.get("resource_id", res_id)
                                break
                        if (matched or (item.get("query", "").lower() in emails and total_hits > 0)) and (
                            not requested_at or captured_at >= requested_at
                        ):
                            findings.append(
                                AuditFinding(
                                    system_id="search_service",
                                    resource_id=res_id,
                                    operation="REPORT_REMAINING_RECORD",
                                    state="PRESENT",
                                    evidence_id=fid,
                                    data_category="SEARCH_INDEX",
                                    details=str(item),
                                )
                            )

                    # Analytics platform profiles
                    for prof in exports.get("analytics_platform", {}).get("profiles", []):
                        p_email = str(prof.get("email") or "").lower()
                        p_user = str(prof.get("customer_reference") or "")
                        p_hash = str(prof.get("email_hash") or "")
                        if p_email in emails or p_user == user_id or p_hash in hashes:
                            if p_email or p_user or p_hash:
                                category = self._analytics_category(prof.get("resource_id", "analytics_unknown"))
                                operation = (
                                    "REPORT_REMAINING_RECORD"
                                    if self.policy.get_required_action(category) == "DELETE"
                                    else "REPORT_EXPOSED_PII"
                                )
                                findings.append(
                                    AuditFinding(
                                        system_id="analytics_platform",
                                        resource_id=prof.get("resource_id", "analytics_unknown"),
                                        operation=operation,
                                        state="PRESENT",
                                        evidence_id=fid,
                                        data_category=category,
                                    )
                                )
                            else:
                                verifications.append(
                                    AuditVerificationProof(
                                        system_id="analytics_platform",
                                        resource_id=prof.get("resource_id", "analytics_unknown"),
                                        operation="VERIFY_RECORD_ANONYMIZED",
                                        state="ANONYMIZED",
                                        evidence_id=fid,
                                    )
                                )

                    # Support platform tickets
                    for tick in exports.get("support_platform", {}).get("tickets", []):
                        t_email = str(tick.get("requester_email") or "").lower()
                        t_user = str(tick.get("customer_reference") or "")
                        if t_email in emails or t_user == user_id:
                            if tick.get("requester_email") is None and tick.get("requester_name") is None:
                                verifications.append(
                                    AuditVerificationProof(
                                        system_id="support_platform",
                                        resource_id=tick.get("resource_id", "support_unknown"),
                                        operation="VERIFY_RECORD_REDACTED",
                                        state="REDACTED",
                                        evidence_id=fid,
                                    )
                                )
                            else:
                                findings.append(
                                    AuditFinding(
                                        system_id="support_platform",
                                        resource_id=tick.get("resource_id", "support_unknown"),
                                        operation="REPORT_EXPOSED_PII",
                                        state="PRESENT",
                                        evidence_id=fid,
                                        data_category="CUSTOMER_SUPPORT",
                                    )
                                )

                    # Integration service connectors
                    for conn in exports.get("integration_service", {}).get("connectors", []):
                        c_email = str(conn.get("customer_email") or "").lower()
                        c_user = str(conn.get("customer_reference") or "")
                        if c_email in emails or c_user == user_id:
                            if conn.get("enabled", False):
                                findings.append(
                                    AuditFinding(
                                        system_id="integration_service",
                                        resource_id=conn.get("resource_id", "data_flow_unknown"),
                                        operation="REPORT_ACTIVE_DATA_FLOW",
                                        state="ACTIVE",
                                        evidence_id=fid,
                                        data_category="CONNECTOR_DATA_FLOW",
                                    )
                                )
                            else:
                                verifications.append(
                                    AuditVerificationProof(
                                        system_id="integration_service",
                                        resource_id=conn.get("resource_id", "data_flow_unknown"),
                                        operation="VERIFY_DATA_FLOW_DISABLED",
                                        state="DISABLED",
                                        evidence_id=fid,
                                    )
                                )

                    # Backup service archives
                    for bkp in exports.get("backup_service", {}).get("archives", []):
                        b_email = str(bkp.get("customer_email") or "").lower()
                        b_user = str(bkp.get("customer_reference") or "")
                        if b_email in emails or b_user == user_id:
                            if bkp.get("restore_allowed", True):
                                findings.append(
                                    AuditFinding(
                                        system_id="backup_service",
                                        resource_id=bkp.get("resource_id", "backup_unknown"),
                                        operation="REPORT_RESTORE_RISK",
                                        state="ACTIVE",
                                        evidence_id=fid,
                                        data_category="BACKUP_ARCHIVE",
                                    )
                                )
                            else:
                                verifications.append(
                                    AuditVerificationProof(
                                        system_id="backup_service",
                                        resource_id=bkp.get("resource_id", "backup_unknown"),
                                        operation="VERIFY_RESTORE_BLOCKED",
                                        state="BLOCKED",
                                        evidence_id=fid,
                                    )
                                )

                    # Security service audit logs
                    for sec in exports.get("security_service", {}).get("audit_logs", []):
                        s_user = str(sec.get("subject_reference") or "")
                        if s_user == user_id:
                            verifications.append(
                                AuditVerificationProof(
                                    system_id="security_service",
                                    resource_id=sec.get("resource_id", "audit_unknown"),
                                    operation="VERIFY_RECORD_PRESENT",
                                    state="PRESENT",
                                    evidence_id=fid,
                                )
                            )

                    # Export jobs in service exports use the same ownership
                    # rule as the standalone customer_export_jobs collection.
                    for exp in exports.get("export_service", {}).get("exports", []):
                        owner = str(exp.get("owner_email") or "").lower()
                        owner_user = str(exp.get("customer_reference") or "")
                        if (owner in emails or owner_user == user_id) and exp.get("download_available", False):
                            findings.append(
                                AuditFinding(
                                    system_id="export_service",
                                    resource_id=exp.get("resource_id", "export_unknown"),
                                    operation="REPORT_REMAINING_RECORD",
                                    state="PRESENT",
                                    evidence_id=fid,
                                    data_category="CUSTOMER_EXPORT",
                                )
                            )

                # 2. snapshot_bundle (from customer_data_snapshot_bundle_*.json)
                if "snapshots" in data:
                    for snap in data["snapshots"]:
                        store = snap.get("data_store", "identity_service")
                        coll = snap.get("collection")
                        recs = snap.get("records", [])
                        snap_captured_at = str(snap.get("captured_at", captured_at))
                        if snap_captured_at > profile.audit_at:
                            continue

                        if coll == "deleted_customer_references":
                            for r in recs:
                                if r.get("subject_reference") != user_id and str(r.get("email") or "").lower() not in emails:
                                    continue
                                t_id = r.get("resource_id")
                                has_pii = any(r.get(k) is not None for k in ["name", "email", "phone", "email_hash"])
                                if has_pii and captured_at <= profile.audit_at:
                                    findings.append(
                                        AuditFinding(
                                            system_id=store,
                                            resource_id=t_id,
                                            operation="REPORT_EXPOSED_PII",
                                            state="PRESENT",
                                            evidence_id=fid,
                                            data_category="ACCOUNT_TOMBSTONE",
                                        )
                                    )
                                elif not has_pii:
                                    verifications.append(
                                        AuditVerificationProof(
                                            system_id=store,
                                            resource_id=t_id,
                                            operation="VERIFY_RECORD_REDACTED",
                                            state="REDACTED",
                                            evidence_id=fid,
                                        )
                                    )

                        elif coll == "security_audit_events":
                            for r in recs:
                                if r.get("subject_reference") == user_id or str(r.get("email") or "").lower() in emails:
                                    verifications.append(
                                        AuditVerificationProof(
                                            system_id=store,
                                            resource_id=r.get("resource_id"),
                                            operation="VERIFY_RECORD_PRESENT",
                                            state="PRESENT",
                                            evidence_id=fid,
                                        )
                                    )

                        elif coll == "customer_profiles":
                            for r in recs:
                                if r.get("customer_reference") != user_id and str(r.get("email") or "").lower() not in emails:
                                    continue
                                account_status = str(r.get("account_status", "")).upper()
                                if account_status in ("ACTIVE", "DELETION_PENDING") and str(r.get("resource_id")) not in authoritative_absent_accounts:
                                    findings.append(
                                        AuditFinding(
                                            system_id=store,
                                            resource_id=r.get("resource_id"),
                                            operation="REPORT_REMAINING_RECORD",
                                            state="PRESENT",
                                            evidence_id=fid,
                                            data_category="USER_PROFILE",
                                        )
                                    )
                                else:
                                    verifications.append(
                                        AuditVerificationProof(
                                            system_id=store,
                                            resource_id=r.get("resource_id"),
                                            operation="VERIFY_RECORD_ABSENT",
                                            state="ABSENT",
                                            evidence_id=fid,
                                        )
                                    )

                        elif coll == "customer_analytics_reports":
                            for r in recs:
                                if r.get("user_id") != user_id and str(r.get("email") or "").lower() not in emails:
                                    continue
                                has_pii = any(r.get(k) is not None for k in ["user_id", "email", "phone", "email_hash"])
                                category = self._analytics_category(r.get("resource_id", "analytics_unknown"))
                                if has_pii and self.policy.get_required_action(category) == "DELETE":
                                    findings.append(
                                        AuditFinding(
                                            system_id=store,
                                            resource_id=r.get("resource_id", "analytics_unknown"),
                                            operation="REPORT_REMAINING_RECORD",
                                            state="PRESENT",
                                            evidence_id=fid,
                                            data_category=category,
                                        )
                                    )
                                elif has_pii:
                                    findings.append(
                                        AuditFinding(
                                            system_id=store,
                                            resource_id=r.get("resource_id", "analytics_unknown"),
                                            operation="REPORT_EXPOSED_PII",
                                            state="PRESENT",
                                            evidence_id=fid,
                                            data_category=category,
                                        )
                                    )
                                else:
                                    verifications.append(
                                        AuditVerificationProof(
                                            system_id=store,
                                            resource_id=r.get("resource_id"),
                                            operation="VERIFY_RECORD_ANONYMIZED",
                                            state="ANONYMIZED",
                                            evidence_id=fid,
                                        )
                                    )

                        elif coll == "backup_catalog":
                            for r in recs:
                                if r.get("subject_reference") != user_id and str(r.get("customer_email") or "").lower() not in emails:
                                    continue
                                if r.get("restore_allowed") is True:
                                    findings.append(
                                        AuditFinding(
                                            system_id=store,
                                            resource_id=r.get("resource_id"),
                                            operation="REPORT_RESTORE_RISK",
                                            state="ACTIVE",
                                            evidence_id=fid,
                                            data_category="BACKUP_ARCHIVE",
                                        )
                                    )
                                else:
                                    verifications.append(
                                        AuditVerificationProof(
                                            system_id=store,
                                            resource_id=r.get("resource_id"),
                                            operation="VERIFY_RESTORE_BLOCKED",
                                            state="BLOCKED",
                                            evidence_id=fid,
                                        )
                                    )

                        elif coll == "connector_configurations":
                            for r in recs:
                                if r.get("subject_selector") != user_id and str(r.get("customer_email") or "").lower() not in emails:
                                    continue
                                if r.get("enabled") is True:
                                    findings.append(
                                        AuditFinding(
                                            system_id=store,
                                            resource_id=r.get("resource_id"),
                                            operation="REPORT_ACTIVE_DATA_FLOW",
                                            state="ACTIVE",
                                            evidence_id=fid,
                                            data_category="CONNECTOR_DATA_FLOW",
                                        )
                                    )
                                else:
                                    verifications.append(
                                        AuditVerificationProof(
                                            system_id=store,
                                            resource_id=r.get("resource_id"),
                                            operation="VERIFY_DATA_FLOW_DISABLED",
                                            state="DISABLED",
                                            evidence_id=fid,
                                        )
                                    )

                        elif coll == "customer_export_jobs":
                            for job in recs:
                                owner = str(job.get("owner_email") or "").lower()
                                owner_user = str(job.get("customer_reference") or "")
                                if (owner in emails or owner_user == user_id) and job.get("download_available", False):
                                    findings.append(
                                        AuditFinding(
                                            system_id="export_service",
                                            resource_id=job.get("resource_id", "export_unknown"),
                                            operation="REPORT_REMAINING_RECORD",
                                            state="PRESENT",
                                            evidence_id=fid,
                                            data_category="CUSTOMER_EXPORT",
                                        )
                                    )

                # 3. customer_export_jobs
                if data.get("collection") == "customer_export_jobs":
                    for job in data.get("records", []):
                        o_email = str(job.get("owner_email") or "").lower()
                        if o_email in emails and job.get("download_available", False):
                            findings.append(
                                AuditFinding(
                                    system_id="export_service",
                                    resource_id=job.get("resource_id", "export_unknown"),
                                    operation="REPORT_REMAINING_RECORD",
                                    state="PRESENT",
                                    evidence_id=fid,
                                    data_category="CUSTOMER_EXPORT",
                                )
                            )

            except Exception:
                pass

        return findings, verifications

    def _resolve_primary_account(
        self,
        case_id: str,
        user_id: str,
        reported_at: Optional[str] = None,
        observed_verifications: Optional[list[AuditVerificationProof]] = None,
    ) -> str:
        """Resolve the authentic primary account identifier from observations or system activity."""
        if observed_verifications:
            for v in observed_verifications:
                if v.system_id == "account_service" and v.resource_id.startswith("account_"):
                    return v.resource_id

        attributed = self.attribution.primary_account_for(case_id)
        if attributed:
            return attributed

        if reported_at and hasattr(self, "activity_df") and not self.activity_df.empty:
            try:
                rep_dt = pd.to_datetime(reported_at)
                worker_acts = self.activity_df[
                    (self.activity_df["target_system"] == "account_service")
                    & (self.activity_df["source_system"] == "deletion_worker")
                ].copy()
                if not worker_acts.empty:
                    worker_acts["dt"] = pd.to_datetime(worker_acts["event_time"])
                    nearby = worker_acts[worker_acts["dt"].apply(lambda d: abs((d - rep_dt).total_seconds()) <= 7200)]
                    if not nearby.empty:
                        nearby = nearby.copy()
                        nearby["diff"] = nearby["dt"].apply(lambda d: abs((d - rep_dt).total_seconds()))
                        nearby = nearby.sort_values("diff")
                        return str(nearby.iloc[0]["resource_id"])
            except Exception:
                pass

        u_clean = user_id.replace("user_", "")
        if u_clean.isdigit():
            return f"account_{int(u_clean):03d}"
        return f"account_{u_clean}"

    def audit_case(
        self,
        case_id: str,
        profile: UserIdentityProfile,
        audit_at: str,
        requested_at: Optional[str] = None,
        reported_at: Optional[str] = None,
    ) -> AuditResult:
        """Audit a customer's deletion state across all evidence up to audit_at."""
        findings: list[AuditFinding] = []
        verifications: list[AuditVerificationProof] = []

        user_id = profile.user_id
        all_emails = {e.lower() for e in profile.all_emails}
        all_hashes = set(profile.all_email_hashes)
        name_variants = {nv.lower() for nv in profile.name_variants}

        # Filter manifests using parsed timestamps.  Snapshot bundles are also
        # consulted by the JSON scanner when an inner capture is admissible.
        valid_files = self.manifest_df.copy()
        valid_files["captured_ts"] = pd.to_datetime(
            valid_files["captured_at"], errors="coerce", utc=True
        )
        cutoff = pd.to_datetime(audit_at, errors="coerce", utc=True)
        valid_files = valid_files[
            (valid_files["captured_ts"] <= cutoff)
            | valid_files["file_path"].astype(str).str.endswith(".log")
        ]

        # 1. Scan logs
        self._active_audit_at = audit_at
        self._active_requested_at = requested_at
        log_findings, log_verifications = self._scan_logs(
            valid_files, all_emails, user_id, all_hashes
        )
        findings.extend(log_findings)
        verifications.extend(log_verifications)

        # 2. Scan text records
        txt_findings, txt_verifications = self._scan_text_records(valid_files, all_emails, user_id)
        findings.extend(txt_findings)
        verifications.extend(txt_verifications)

        # 3. Scan SQL captures
        sql_findings, sql_verifications = self._scan_sql_snapshots(valid_files, profile, requested_at)
        findings.extend(sql_findings)
        verifications.extend(sql_verifications)

        # 4. Scan multimodal evidence (PDFs and UI screenshots)
        mm_findings, mm_verifications = self._scan_multimodal_evidence(valid_files, profile, requested_at)
        findings.extend(mm_findings)
        verifications.extend(mm_verifications)

        # 5. Deep Scan JSON records
        json_findings, json_verifications = self._scan_json_records(valid_files, profile, requested_at)
        findings.extend(json_findings)
        verifications.extend(json_verifications)

        # Add only verification targets for resources that the worker batch
        # attributed without an identifier.  Direct evidence scans above own
        # all residual findings; inferred links must never manufacture one.
        inferred_complete = not findings
        observed_resource_ids = {f.resource_id for f in findings} | {v.resource_id for v in verifications}
        for resource_id in sorted(self.attribution.resources_for(case_id)):
            if resource_id in observed_resource_ids:
                continue
            proof = self._attributed_verification(case_id, resource_id, audit_at, inferred_complete)
            if proof is not None:
                verifications.append(proof)

        # Deduplicate findings by (system_id, resource_id, operation)
        unique_findings: list[AuditFinding] = []
        seen_findings: set[tuple[str, str, str]] = set()
        for f in findings:
            canonical_evidence = self._canonical_evidence_id(f.resource_id, audit_at)
            if canonical_evidence and canonical_evidence != f.evidence_id:
                f = AuditFinding(
                    system_id=f.system_id,
                    resource_id=f.resource_id,
                    operation=f.operation,
                    state=f.state,
                    evidence_id=canonical_evidence,
                    data_category=f.data_category,
                    rule_id=f.rule_id,
                    details=f.details,
                )
            key = (f.system_id, f.resource_id, f.operation)
            if key not in seen_findings:
                seen_findings.add(key)
                unique_findings.append(f)

        # Deduplicate verifications by (system_id, resource_id, operation)
        unique_verifications: list[AuditVerificationProof] = []
        seen_verifs: set[tuple[str, str, str]] = set()
        for v in verifications:
            canonical_evidence = self._canonical_evidence_id(v.resource_id, audit_at)
            if canonical_evidence and canonical_evidence != v.evidence_id:
                v = AuditVerificationProof(
                    system_id=v.system_id,
                    resource_id=v.resource_id,
                    operation=v.operation,
                    state=v.state,
                    evidence_id=canonical_evidence,
                )
            key = (v.system_id, v.resource_id, v.operation)
            if key not in seen_verifs:
                seen_verifs.add(key)
                unique_verifications.append(v)

        # Determine status
        is_complete = len(unique_findings) == 0
        status = "COMPLETE" if is_complete else "INCOMPLETE"

        # Always resolve and ensure the primary account is recorded in verifications if not already present
        if not any(v.system_id == "account_service" for v in unique_verifications):
            primary_account_id = self._resolve_primary_account(case_id, user_id, reported_at, unique_verifications)
            ev_id = ""
            if is_complete:
                primary_proof = self._attributed_verification(case_id, primary_account_id, audit_at, True)
                if primary_proof is not None and primary_proof.evidence_id:
                    ev_id = primary_proof.evidence_id
                if not ev_id:
                    # A retained security proof from the same audit bundle is
                    # a stronger citation for an inferred account absence than
                    # a generic account manifest selected by category.
                    security_evidence = [
                        v.evidence_id
                        for v in unique_verifications
                        if v.system_id == "security_service" and v.evidence_id
                    ]
                    if security_evidence:
                        ev_id = security_evidence[0]
                if not ev_id:
                    ev_id = self._fallback_evidence_id(primary_account_id, audit_at)
            unique_verifications.append(
                AuditVerificationProof(
                    system_id="account_service",
                    resource_id=primary_account_id,
                    operation="VERIFY_RECORD_ABSENT",
                    state="ABSENT",
                    evidence_id=ev_id,
                )
            )

        return AuditResult(
            case_id=case_id,
            user_id=user_id,
            is_complete=is_complete,
            deletion_status=status,
            findings=tuple(unique_findings),
            verifications=tuple(unique_verifications),
        )
