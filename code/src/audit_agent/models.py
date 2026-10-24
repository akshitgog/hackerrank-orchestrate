"""Data models for the Audit Agent (Verification Scanner)."""

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass(frozen=True)
class AuditFinding:
    """Represents a discovered compliance violation or active recreation risk."""
    system_id: str
    resource_id: str
    operation: str  # REPORT_REMAINING_RECORD, REPORT_EXPOSED_PII, REPORT_ACTIVE_DATA_FLOW, REPORT_RESTORE_RISK
    state: str      # PRESENT, ACTIVE
    evidence_id: str  # file_id, activity_id, or audit_id
    data_category: str = ""
    rule_id: str = ""
    details: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert finding to dictionary representation."""
        return {
            "system_id": self.system_id,
            "resource_id": self.resource_id,
            "operation": self.operation,
            "state": self.state,
            "evidence_id": self.evidence_id,
            "data_category": self.data_category,
            "rule_id": self.rule_id,
            "details": self.details,
        }


@dataclass(frozen=True)
class AuditVerificationProof:
    """Represents evidence-backed verification of compliant state at audit_at."""
    system_id: str
    resource_id: str
    operation: str  # VERIFY_RECORD_ABSENT, VERIFY_RECORD_PRESENT, VERIFY_RECORD_REDACTED, VERIFY_RECORD_ANONYMIZED
    state: str      # ABSENT, PRESENT, REDACTED, ANONYMIZED, DISABLED, BLOCKED
    evidence_id: str  # Evidence confirming this state at audit_at

    def to_dict(self) -> dict[str, Any]:
        """Convert proof to dictionary representation."""
        return {
            "system_id": self.system_id,
            "resource_id": self.resource_id,
            "operation": self.operation,
            "state": self.state,
            "evidence_id": self.evidence_id,
        }


@dataclass(frozen=True)
class AuditResult:
    """Consolidated audit outcome produced by the Audit Agent."""
    case_id: str
    user_id: str
    is_complete: bool
    deletion_status: str  # 'COMPLETE' or 'INCOMPLETE'
    findings: tuple[AuditFinding, ...] = field(default_factory=tuple)
    verifications: tuple[AuditVerificationProof, ...] = field(default_factory=tuple)

    @property
    def has_violations(self) -> bool:
        """True if any findings/risks were discovered."""
        return len(self.findings) > 0
