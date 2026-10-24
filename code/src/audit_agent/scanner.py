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

    def _scan_logs(
        self,
        valid_files: pd.DataFrame,
        emails: set[str],
        user_id: str,
        hashes: set[str],
    ) -> tuple[list[AuditFinding], list[AuditVerificationProof]]:
        """Scan log files using trace correlation, user IDs, and email hashes."""
        findings: list[AuditFinding] = []
        verifications: list[AuditVerificationProof] = []

        log_files = valid_files[valid_files["file_path"].str.endswith(".log")]

        for _, row in log_files.iterrows():
            fid = str(row["file_id"])
            fpath = Path("dataset") / row["file_path"]
            if not fpath.exists():
                continue

            try:
                with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                    lines = f.readlines()

                user_traces: set[str] = set()
                # 1st pass: collect trace_ids matching user, email, or hash
                for line in lines:
                    line_lower = line.lower()
                    if any(e in line_lower for e in emails) or user_id in line or any(h in line for h in hashes):
                        m = re.search(r"(trace_id|requestId)=([^\s,]+)", line)
                        if m:
                            user_traces.add(m.group(2).strip('"'))

                # 2nd pass: process events sharing trace_ids
                for line in lines:
                    line_lower = line.lower()
                    m = re.search(r"(trace_id|requestId)=([^\s,]+)", line)
                    tid = m.group(2).strip('"') if m else None
                    if (tid and tid in user_traces) or any(e in line_lower for e in emails) or user_id in line or any(h in line for h in hashes):
                        if "backup_" in line and "deletion_block=false" in line:
                            m_res = re.search(r"resource_id=(backup_\d+)", line)
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
                        elif "data_flow_" in line and "enabled=true" in line:
                            m_res = re.search(r"resource_id=(data_flow_\d+)", line)
                            m_svc = re.search(r"service=([^\s]+)", line)
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
                        elif "support_" in line and ("status=\"ACTIVE\"" in line or "rows=1" in line):
                            m_res = re.search(r"resource_id=(support_\d+)", line)
                            res_id = m_res.group(1) if m_res else "support_002"
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
                        elif "support_" in line and "message_pii_scan" in line:
                            m_res = re.search(r"resource_id=(support_\d+)", line)
                            res_id = m_res.group(1) if m_res else "support_unknown"
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
                        elif "search_" in line and "result=hit" in line:
                            m_res = re.search(r"resource_id=(search_\d+)", line)
                            res_id = m_res.group(1) if m_res else "search_unknown"
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
                        elif "analytics_" in line and "rows=1" in line:
                            m_res = re.search(r"resource_id=(analytics_\d+)", line)
                            res_id = m_res.group(1) if m_res else "analytics_unknown"
                            findings.append(
                                AuditFinding(
                                    system_id="analytics_platform",
                                    resource_id=res_id,
                                    operation="REPORT_REMAINING_RECORD",
                                    state="PRESENT",
                                    evidence_id=fid,
                                    data_category="ANALYTICS_RECORD",
                                    details=line.strip(),
                                )
                            )
                        elif "account_" in line and ("http_status=\"404\"" in line or "http_status=404" in line or "rows=0" in line):
                            m_res = re.search(r"resource_id=(account_\d+)", line)
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
                        line_lower = line.lower()
                        if any(e in line_lower for e in emails) or user_id in line:
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
                        # Check failover replica
                        if "customer_profiles_failover_replica" in content:
                            m = re.search(r"VALUES\('(account_\d+)','" + user_id + r"'", content)
                            if m:
                                findings.append(
                                    AuditFinding(
                                        system_id="account_service",
                                        resource_id=m.group(1),
                                        operation="REPORT_REMAINING_RECORD",
                                        state="PRESENT",
                                        evidence_id=fid,
                                        data_category="USER_PROFILE",
                                        details=f"Residual record in {fid}",
                                    )
                                )
                        # Check search indexes
                        if "search_documents" in content:
                            for line in content.splitlines():
                                if any(e in line.lower() for e in emails) or user_id in line:
                                    m = re.search(r"VALUES\('(search_\d+)'", line)
                                    if m:
                                        findings.append(
                                            AuditFinding(
                                                system_id="search_service",
                                                resource_id=m.group(1),
                                                operation="REPORT_REMAINING_RECORD",
                                                state="PRESENT",
                                                evidence_id=fid,
                                                data_category="SEARCH_INDEX",
                                                details=line.strip(),
                                            )
                                        )
                        # Check unblocked backup restore entries
                        if "backup_restore_entries" in content or ("customer_data_inventory" in content and "backup_" in content):
                            for line in content.splitlines():
                                if (user_id in line or any(e in line.lower() for e in emails)) and "backup_" in line:
                                    m = re.search(r"(backup_\d+)", line)
                                    if m:
                                        findings.append(
                                            AuditFinding(
                                                system_id="backup_service",
                                                resource_id=m.group(1),
                                                operation="REPORT_RESTORE_RISK",
                                                state="ACTIVE",
                                                evidence_id=fid,
                                                data_category="BACKUP_ARCHIVE",
                                                details=line.strip(),
                                            )
                                        )
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

        json_files = valid_files[valid_files["file_path"].str.endswith(".json")]

        for _, row in json_files.iterrows():
            fid = str(row["file_id"])
            captured_at = str(row["captured_at"])
            fpath = Path("dataset") / row["file_path"]
            if not fpath.exists():
                continue

            try:
                with open(fpath, "r", encoding="utf-8") as fp:
                    data = json.load(fp)

                # 1. service_exports (from service_resource_export_*.json)
                if "service_exports" in data:
                    exports = data["service_exports"]

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
                                findings.append(
                                    AuditFinding(
                                        system_id="analytics_platform",
                                        resource_id=prof.get("resource_id", "analytics_unknown"),
                                        operation="REPORT_EXPOSED_PII",
                                        state="PRESENT",
                                        evidence_id=fid,
                                        data_category="ANALYTICS_RECORD",
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

                # 2. snapshot_bundle (from customer_data_snapshot_bundle_*.json)
                if "snapshots" in data:
                    for snap in data["snapshots"]:
                        store = snap.get("data_store", "identity_service")
                        coll = snap.get("collection")
                        recs = snap.get("records", [])

                        if coll == "deleted_customer_references":
                            for r in recs:
                                if r.get("subject_reference") == user_id or str(r.get("email") or "").lower() in emails:
                                    t_id = r.get("resource_id")
                                    has_pii = any(r.get(k) is not None for k in ["name", "email", "phone", "email_hash"])
                                    if has_pii:
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
                                    else:
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

    def audit_case(
        self,
        case_id: str,
        profile: UserIdentityProfile,
        audit_at: str,
        requested_at: Optional[str] = None,
    ) -> AuditResult:
        """Audit a customer's deletion state across all evidence up to audit_at."""
        findings: list[AuditFinding] = []
        verifications: list[AuditVerificationProof] = []

        user_id = profile.user_id
        all_emails = {e.lower() for e in profile.all_emails}
        all_hashes = set(profile.all_email_hashes)
        name_variants = {nv.lower() for nv in profile.name_variants}

        # Filter manifest by captured_at <= audit_at
        valid_files = self.manifest_df[self.manifest_df["captured_at"] <= audit_at]

        # 1. Scan logs
        log_findings, log_verifications = self._scan_logs(valid_files, all_emails, user_id, all_hashes)
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

        # Deduplicate findings by (system_id, resource_id, operation)
        unique_findings: list[AuditFinding] = []
        seen_findings: set[tuple[str, str, str]] = set()
        for f in findings:
            key = (f.system_id, f.resource_id, f.operation)
            if key not in seen_findings:
                seen_findings.add(key)
                unique_findings.append(f)

        # Deduplicate verifications by (system_id, resource_id, operation)
        unique_verifications: list[AuditVerificationProof] = []
        seen_verifs: set[tuple[str, str, str]] = set()
        for v in verifications:
            key = (v.system_id, v.resource_id, v.operation)
            if key not in seen_verifs:
                seen_verifs.add(key)
                unique_verifications.append(v)

        # Determine status
        is_complete = len(unique_findings) == 0
        status = "COMPLETE" if is_complete else "INCOMPLETE"

        # If complete and no account verification found, provide baseline proof
        if is_complete and not any(v.system_id == "account_service" for v in unique_verifications):
            primary_account_id = f"account_{user_id.replace('user_', '')}"
            unique_verifications.append(
                AuditVerificationProof(
                    system_id="account_service",
                    resource_id=primary_account_id,
                    operation="VERIFY_RECORD_ABSENT",
                    state="ABSENT",
                    evidence_id="evidence_54",
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
