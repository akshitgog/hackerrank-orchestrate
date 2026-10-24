"""Data models for the Logging Agent (Identity Tracker)."""

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass(frozen=True)
class UserIdentityProfile:
    """Represents a customer's consolidated current and historical identity.
    
    All identifiers are strictly bounded by the case's audit_at cutoff.
    """
    user_id: str
    primary_name: str
    all_names: frozenset[str] = field(default_factory=frozenset)
    primary_email: str = ""
    all_emails: frozenset[str] = field(default_factory=frozenset)
    primary_phone: str = ""
    all_phones: frozenset[str] = field(default_factory=frozenset)
    primary_email_hash: str = ""
    all_email_hashes: frozenset[str] = field(default_factory=frozenset)
    audit_at: str = ""
    matched_via: str = "current_email"  # 'current_email' or 'audit_log_historical'

    def to_dict(self) -> dict[str, Any]:
        """Convert identity profile to a serializable dictionary."""
        return {
            "user_id": self.user_id,
            "primary_name": self.primary_name,
            "all_names": sorted(list(self.all_names)),
            "primary_email": self.primary_email,
            "all_emails": sorted(list(self.all_emails)),
            "primary_phone": self.primary_phone,
            "all_phones": sorted(list(self.all_phones)),
            "primary_email_hash": self.primary_email_hash,
            "all_email_hashes": sorted(list(self.all_email_hashes)),
            "audit_at": self.audit_at,
            "matched_via": self.matched_via,
        }
