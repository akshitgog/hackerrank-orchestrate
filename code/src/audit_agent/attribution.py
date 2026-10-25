"""Evidence-bound resource attribution for deletion-worker orphan records.

The scanner can directly link a resource when an evidence record contains one
of the subject's identifiers.  Deletion-worker rows for primary accounts and
anonymized downstream records often contain no identifier, however.  This
module reproduces the safe part of the winner's attribution strategy:

* build resource -> user ownership from record/trace-local evidence;
* attach worker actions with an explicit owner to that user's case;
* assign genuinely orphaned worker resources in bounded report-time batches;
* never let a second resource of the same type leak into a case.

Inferred assignments are intended for verification targets only.  The scanner
does not use this index to create residual findings.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd


RESOURCE_RE = re.compile(
    r"\b(?:account|search|analytics|support|export|data_flow|backup|"
    r"audit_record|tombstone|legal_hold|marketing|object|email_delivery|"
    r"cache|telemetry)_\d+\b"
)

WORKER_ACTIONS = {
    "DELETE_RECORD",
    "ANONYMIZE_RECORD",
    "REDACT_RECORD",
    "DISABLE_DATA_FLOW",
    "BLOCK_RESTORE",
    "CHECK_DATA_FLOW",
    "CHECK_RESTORE_ACCESS",
    "RETAIN_RECORD",
}

STATUS_FOR_RESULT = {
    "SUCCESS": "COMPLETE",
    "PARTIAL": "PARTIALLY_COMPLETE",
    "FAILED": "NOT_STARTED",
}


def resource_prefix(resource_id: str) -> str:
    return resource_id.split("_", 1)[0]


@dataclass(frozen=True)
class AttributionCase:
    case_id: str
    user_id: str
    requested_at: pd.Timestamp
    reported_at: pd.Timestamp
    audit_at: pd.Timestamp
    reported_status: str
    request_text: str

    @property
    def number(self) -> int:
        try:
            return int(self.case_id.rsplit("_", 1)[1])
        except (ValueError, IndexError):
            return 10**9


class AttributionIndex:
    """Precompute direct ownership and bounded worker-batch assignments."""

    def __init__(self, dataset_root: str | Path = "dataset") -> None:
        self.dataset_root = Path(dataset_root)
        self.resource_owners: dict[str, set[str]] = defaultdict(set)
        self.resource_files: dict[str, set[str]] = defaultdict(set)
        self.file_users: dict[str, set[str]] = defaultdict(set)
        self.file_captured: dict[str, pd.Timestamp] = {}
        self.file_text: dict[str, str] = {}
        self.resource_actions: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.cases: list[AttributionCase] = []
        self.assignments: dict[str, set[str]] = defaultdict(set)
        self.assignment_sources: dict[tuple[str, str], str] = {}
        self._signatures: dict[str, set[str]] = defaultdict(set)
        self._token_users: dict[str, set[str]] = defaultdict(set)

        self._load_identity_signatures()
        self._load_cases()
        self._index_evidence()
        self._index_worker_actions()
        self._assign_resources()

    # ------------------------------------------------------------------ loading
    def _load_identity_signatures(self) -> None:
        identities_path = self.dataset_root / "user_identities.csv"
        audit_path = self.dataset_root / "user_audit_log.csv"
        if identities_path.exists():
            identities = pd.read_csv(identities_path).fillna("")
            for _, row in identities.iterrows():
                uid = str(row.get("user_id", "")).strip()
                if not uid:
                    continue
                values = {
                    uid,
                    str(row.get("email", "")).strip().casefold(),
                    str(row.get("email_hash", "")).strip().lower(),
                }
                for value in values:
                    if value:
                        self._add_signature(uid, value)
        if audit_path.exists():
            audit = pd.read_csv(audit_path).fillna("")
            for _, row in audit.iterrows():
                uid = str(row.get("user_id", "")).strip()
                if not uid:
                    continue
                for column in ("old_value", "new_value"):
                    value = str(row.get(column, "")).strip()
                    if not value:
                        continue
                    lowered = value.casefold()
                    self._add_signature(uid, lowered)
                    if "@" in lowered:
                        self._add_signature(uid, hashlib.sha256(lowered.encode("utf-8")).hexdigest())

        # Hashes for every known email are valid identifiers in this dataset.
        for uid, values in list(self._signatures.items()):
            for value in list(values):
                if "@" in value:
                    self._add_signature(uid, hashlib.sha256(value.encode("utf-8")).hexdigest())

    def _add_signature(self, user_id: str, value: str) -> None:
        value = value.strip().lower()
        if not value:
            return
        self._signatures[user_id].add(value)
        self._token_users[value].add(user_id)

    def _load_cases(self) -> None:
        seen: set[str] = set()
        for name in ("deletion_requests.csv", "sample_deletion_requests.csv"):
            path = self.dataset_root / name
            if not path.exists():
                continue
            rows = pd.read_csv(path).fillna("")
            for _, row in rows.iterrows():
                cid = str(row.get("case_id", ""))
                email = str(row.get("email", "")).strip().casefold()
                users = self._token_users.get(email, set())
                if not cid or cid in seen or len(users) != 1:
                    continue
                try:
                    self.cases.append(
                        AttributionCase(
                            cid,
                            next(iter(users)),
                            pd.to_datetime(row["requested_at"], utc=True),
                            pd.to_datetime(row["reported_at"], utc=True),
                            pd.to_datetime(row["audit_at"], utc=True),
                            str(row.get("reported_status", "")),
                            str(row.get("request_text", "")),
                        )
                    )
                    seen.add(cid)
                except (KeyError, ValueError, TypeError):
                    continue

    # -------------------------------------------------------------- evidence index
    def _index_evidence(self) -> None:
        manifest_path = self.dataset_root / "evidence_files.csv"
        if not manifest_path.exists():
            return
        manifest = pd.read_csv(manifest_path).fillna("")
        for _, row in manifest.iterrows():
            fid = str(row.get("file_id", ""))
            path = self.dataset_root / str(row.get("file_path", ""))
            try:
                self.file_captured[fid] = pd.to_datetime(str(row.get("captured_at", "")), utc=True)
            except (ValueError, TypeError):
                pass
            if not fid or not path.exists() or path.suffix.lower() not in {".json", ".sql", ".log", ".txt"}:
                continue
            try:
                self.file_text[fid] = path.read_text(encoding="utf-8", errors="ignore").lower()
                if path.suffix.lower() == ".json":
                    self._index_json_file(fid, path)
                else:
                    self._index_text_file(fid, path)
            except Exception:
                # One malformed evidence file must not prevent attribution from
                # using the other sources.
                continue

    def _violation_signal(self, resource_id: str, file_id: str) -> bool:
        """Return whether an evidence file shows a residual/risk state."""
        text = self.file_text.get(file_id, "")
        if resource_id not in text:
            return False
        # Do not let another customer's record in the same export contaminate
        # this resource's state.  Logs are line-oriented; JSON/SQL records are
        # close enough to the resource token for a bounded context window.
        position = text.find(resource_id.lower())
        line_start = text.rfind("\n", 0, position) + 1
        line_end = text.find("\n", position)
        if line_end < 0:
            line_end = len(text)
        snippet = text[line_start:line_end]
        if text.lstrip().startswith(("{", "[")):
            object_start = text.rfind("{", 0, position)
            object_end = text.find("}", position)
            if object_start >= 0 and object_end >= 0:
                snippet = text[object_start:object_end + 1]
        prefix = resource_prefix(resource_id)
        # Evidence exports use both key=value logs and JSON key/value pairs.
        # Normalize JSON punctuation before looking for state markers so the
        # ownership index does not treat an equivalent record differently.
        snippet = re.sub(r'''(["'])([A-Za-z_][A-Za-z0-9_]*)\1\s*:\s*''', r"\2=", snippet)
        snippet = re.sub(r'''(["'])([^"']*)\1''', r"\2", snippet)
        if prefix == "search":
            return not any(marker in snippet for marker in ("total_hits=0", "result=miss", '"rows": 0', "rows=0", "not_found"))
        if prefix == "account":
            if any(marker in snippet for marker in ('"status_code": 404', "http_status=404", "rows=0", "not_found", '"account_status": "deleted"')):
                return False
            return any(marker in snippet for marker in ("account_status\\\": \\\"active", "account_status=active", '"status_code": 200', "rows=1", '"account_status": "active"'))
        if prefix == "support":
            nearby = text[max(0, position - 1200):position + 1200]
            if "deletion_marker_check" in nearby and "marker_found=false" in nearby:
                return True
            return any(marker in snippet for marker in ("requester_email=", '"requester_email":', "requester_name=", "identifiable", '"status": "active"')) and not all(
                marker in snippet for marker in ("requester_email=null", '"requester_email": null', "requester_name=null", '"requester_name": null')
            )
        if prefix == "analytics":
            return any(marker in snippet for marker in ("email=", '"email":', "customer_reference=", '"customer_reference":', '"user_id":')) and not all(
                marker in snippet for marker in ("email=null", '"email": null', "customer_reference=null", '"customer_reference": null', '"user_id": null')
            )
        if prefix == "data":
            return any(marker in snippet for marker in ("enabled=true", '"enabled": true', "status=active", "', '1',", ",1,"))
        if prefix == "backup":
            return any(marker in snippet for marker in ("restore_allowed=true", '"restore_allowed": true', "deletion_block=false", "eligible=true", "'1',", ", 1,"))
        if prefix == "export":
            return any(marker in snippet for marker in ('"download_available": true', "download_available=true", "| found", "customer_exports", "export_"))
        if prefix == "tombstone":
            return any(marker in snippet for marker in ("email=", '"email":', "phone=", '"phone":', '"name":')) and not all(
                marker in snippet for marker in ("email=null", '"email": null', "phone=null", '"phone": null', '"name": null')
            )
        return False

    def _users_in_text(self, text: str) -> set[str]:
        lowered = text.lower()
        users: set[str] = set()
        for token, owners in self._token_users.items():
            if token and token in lowered:
                users.update(owners)
        return users

    def _record(self, fid: str, resource_id: str, users: set[str]) -> None:
        self.resource_files[resource_id].add(fid)
        for uid in users:
            self.resource_owners[resource_id].add(uid)
            self.file_users[fid].add(uid)

    def _index_json_file(self, fid: str, path: Path) -> None:
        data = json.loads(path.read_text(encoding="utf-8"))

        def walk(value: Any) -> None:
            if isinstance(value, dict):
                rid = value.get("resource_id")
                if isinstance(rid, str) and RESOURCE_RE.fullmatch(rid):
                    text = json.dumps(value, ensure_ascii=False).lower()
                    self._record(fid, rid, self._users_in_text(text))
                for child in value.values():
                    if isinstance(child, (dict, list)):
                        walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)

        walk(data)
        # Keep case/file co-observation even when a JSON record has no resource
        # id (for example a full snapshot containing a subject reference).
        self.file_users[fid].update(self._users_in_text(json.dumps(data, ensure_ascii=False)))

    def _index_text_file(self, fid: str, path: Path) -> None:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        traces: dict[str, list[str]] = defaultdict(list)
        for line in lines:
            m = re.search(r"(?:trace_id|requestId)=?\"?([A-Za-z0-9_.-]+)", line)
            traces[m.group(1) if m else f"line:{len(traces)}"].append(line)
        for trace_lines in traces.values():
            trace_text = "\n".join(trace_lines)
            users = self._users_in_text(trace_text)
            self.file_users[fid].update(users)
            resources = set(RESOURCE_RE.findall(trace_text))
            for rid in resources:
                self._record(fid, rid, users)

    # -------------------------------------------------------------- worker batches
    def _index_worker_actions(self) -> None:
        path = self.dataset_root / "system_activity.csv"
        if not path.exists():
            return
        activity = pd.read_csv(path).fillna("")
        for _, row in activity.iterrows():
            if str(row.get("source_system", "")) != "deletion_worker":
                continue
            event_type = str(row.get("event_type", ""))
            if event_type not in WORKER_ACTIONS:
                continue
            rid = str(row.get("resource_id", ""))
            if not RESOURCE_RE.fullmatch(rid):
                continue
            try:
                item = {
                    "activity_id": str(row.get("activity_id", "")),
                    "t": pd.to_datetime(row["event_time"], utc=True),
                    "event_type": event_type,
                    "target_system": str(row.get("target_system", "")),
                    "result": str(row.get("reported_result", "")),
                }
            except (KeyError, ValueError, TypeError):
                continue
            self.resource_actions[rid].append(item)
        for actions in self.resource_actions.values():
            actions.sort(key=lambda a: (a["t"], a["activity_id"]))

    @staticmethod
    def _is_authorized(case: AttributionCase) -> bool:
        text = case.request_text.lower()
        negative = (
            "do not delete",
            "don't delete",
            "not delete",
            "marketing opt-out",
            "marketing opt out",
            "retain my account",
            "keep my account",
            "data export request",
        )
        return not any(marker in text for marker in negative)

    def _assign_resources(self) -> None:
        cases = [c for c in self.cases if self._is_authorized(c)]
        ordered_cases = sorted(cases, key=lambda c: c.number)
        direct: dict[str, set[str]] = defaultdict(set)
        case_files: dict[str, set[str]] = defaultdict(set)
        has_findings: dict[str, bool] = defaultdict(bool)

        for case in cases:
            for rid, owners in self.resource_owners.items():
                if case.user_id not in owners:
                    continue
                # File-level timestamps are deliberately conservative here. The
                # scanner itself handles inner snapshot clocks for compliant proofs.
                admissible_files = {
                    fid
                    for fid in self.resource_files[rid]
                    if fid in self.file_captured
                    and case.requested_at <= self.file_captured[fid] <= case.audit_at
                }
                if admissible_files:
                    direct[case.case_id].add(rid)
                    for fid in admissible_files:
                        case_files[case.case_id].add(fid)

                    # Findings are decided by the scanner's state engine, not
                    # by worker claims or by a broad export snippet.  Keep
                    # orphan assignment independent of those claims so an
                    # anonymized analytics row can still be distributed across
                    # the cases in its bounded batch.
                    latest_file = max(admissible_files, key=lambda fid: self.file_captured.get(fid, pd.Timestamp.min))
                    if self._violation_signal(rid, latest_file):
                        has_findings[case.case_id] = True

        # Explicitly owned worker actions are safer than orphan inference.
        for rid, actions in self.resource_actions.items():
            owners = self.resource_owners.get(rid, set())
            if not owners:
                continue
            for case in cases:
                if case.user_id not in owners:
                    continue
                if any(abs(a["t"] - case.reported_at) <= pd.Timedelta(hours=2) and a["t"] <= case.audit_at for a in actions):
                    self.assignments[case.case_id].add(rid)
                    self.assignment_sources[(case.case_id, rid)] = "owner_batch"

        orphans = [
            (rid, min(actions, key=lambda a: (a["t"], a["activity_id"])))
            for rid, actions in self.resource_actions.items()
            if not self.resource_owners.get(rid)
        ]
        orphans.sort(key=lambda item: (item[1]["t"], item[1]["activity_id"]))

        def eligible(rid: str, action: dict[str, Any], case: AttributionCase) -> bool:
            if abs(action["t"] - case.reported_at) > pd.Timedelta(hours=2) or action["t"] > case.audit_at:
                return False
            if resource_prefix(rid) in {resource_prefix(x) for x in direct[case.case_id] | self.assignments[case.case_id]}:
                return False
            # A resource-local co-observation is stronger than a broad case
            # state.  Keep co-observed downstream resources eligible even when
            # another resource in the batch is still problematic.
            return (
                resource_prefix(rid) == "account"
                or not has_findings[case.case_id]
                or coobserved(rid, case)
            )

        def status_match(rid: str, action: dict[str, Any], case: AttributionCase) -> bool:
            return resource_prefix(rid) == "account" and STATUS_FOR_RESULT.get(action["result"]) == case.reported_status

        def coobserved(rid: str, case: AttributionCase) -> bool:
            return bool(self.resource_files[rid] & case_files[case.case_id])

        passes = (
            ("coobserved+status", lambda rid, a, c: status_match(rid, a, c) and coobserved(rid, c)),
            ("status", status_match),
            ("coobserved", lambda rid, a, c: coobserved(rid, c)),
            ("case_order", lambda rid, a, c: True),
        )
        assigned: set[str] = set()
        for name, predicate in passes:
            for rid, action in orphans:
                if rid in assigned:
                    continue
                candidates = [c for c in ordered_cases if eligible(rid, action, c) and predicate(rid, action, c)]
                if not candidates:
                    continue
                chosen = candidates[0]
                self.assignments[chosen.case_id].add(rid)
                self.assignment_sources[(chosen.case_id, rid)] = f"batch:{name}"
                assigned.add(rid)

    # ---------------------------------------------------------------- public API
    def resources_for(self, case_id: str) -> set[str]:
        return set(self.assignments.get(case_id, set()))

    def primary_account_for(self, case_id: str) -> str | None:
        candidates = [rid for rid in self.resources_for(case_id) if resource_prefix(rid) == "account"]
        if not candidates:
            return None
        case = next((c for c in self.cases if c.case_id == case_id), None)
        if case is not None:
            return min(
                candidates,
                key=lambda rid: min(
                    (abs(a["t"] - case.reported_at), a["activity_id"])
                    for a in self.resource_actions.get(
                        rid, [{"t": pd.Timestamp.max, "activity_id": ""}]
                    )
                ),
            )
        return min(
            candidates,
            key=lambda rid: min((a["t"], a["activity_id"]) for a in self.resource_actions.get(rid, [{"t": pd.Timestamp.max, "activity_id": ""}]))
        )

    def source_for(self, case_id: str, resource_id: str) -> str:
        return self.assignment_sources.get((case_id, resource_id), "")

    def files_for(self, resource_id: str) -> set[str]:
        return set(self.resource_files.get(resource_id, set()))

    def actions_for(self, resource_id: str) -> list[dict[str, Any]]:
        return list(self.resource_actions.get(resource_id, []))
