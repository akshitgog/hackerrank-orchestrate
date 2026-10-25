"""Identity Tracker implementation for the Logging Agent.

Resolves current and historical user identities up to a strict audit_at cutoff.
"""

import hashlib
from pathlib import Path
from typing import Optional
import pandas as pd

from code.src.logging_agent.models import UserIdentityProfile
from code.src.logging_agent.normalizer import (
    normalize_text_nfc,
    strip_accents,
    get_name_variants,
)


class IdentityTracker:
    """Reconstructs complete customer identity signatures from current and audit data."""

    def __init__(
        self,
        identities_path: str | Path = "dataset/user_identities.csv",
        audit_log_path: str | Path = "dataset/user_audit_log.csv",
    ) -> None:
        self.identities_path = Path(identities_path)
        self.audit_log_path = Path(audit_log_path)
        self._load_datasets()

    def _load_datasets(self) -> None:
        """Load and index identity and audit log datasets."""
        if not self.identities_path.exists():
            raise FileNotFoundError(f"User identities file not found: {self.identities_path}")
        if not self.audit_log_path.exists():
            raise FileNotFoundError(f"User audit log file not found: {self.audit_log_path}")

        self.identities_df = pd.read_csv(self.identities_path)
        self.audit_log_df = pd.read_csv(self.audit_log_path)

        # Keep all temporal decisions timezone-aware.  Comparing timestamp
        # strings happens to work for the current ISO exports, but it silently
        # breaks as soon as offsets or mixed timestamp formats appear.
        self.audit_log_df["event_time_parsed"] = pd.to_datetime(
            self.audit_log_df["event_time"], errors="coerce", utc=True
        )

        # Normalize strings for robust lookups
        self.identities_df["email_normalized"] = (
            self.identities_df["email"].astype(str).str.strip().str.lower()
        )
        self.audit_log_df["old_value_normalized"] = (
            self.audit_log_df["old_value"].astype(str).str.strip().str.lower()
        )
        self.audit_log_df["new_value_normalized"] = (
            self.audit_log_df["new_value"].astype(str).str.strip().str.lower()
        )

        # Build fast index map for current emails
        self._current_email_to_user: dict[str, str] = dict(
            zip(self.identities_df["email_normalized"], self.identities_df["user_id"])
        )

        # Build fast index map for historical emails in audit log
        email_audit = self.audit_log_df[self.audit_log_df["field_name"] == "email"]
        self._historical_email_to_user: dict[str, str] = dict(
            zip(email_audit["old_value_normalized"], email_audit["user_id"])
        )

    def resolve_user_id(
        self, email: str, audit_at: Optional[str] = None
    ) -> tuple[Optional[str], str]:
        """Resolve a request email to a user_id, checking current and historical records.
        
        Returns:
            (user_id, match_source) where match_source is 'current_email', 
            'audit_log_historical', or 'unmatched'.
        """
        normalized_email = normalize_text_nfc(email)

        # 1. Try direct match in current identities
        if normalized_email in self._current_email_to_user:
            return self._current_email_to_user[normalized_email], "current_email"

        # 2. Try match against historical emails in audit log.  When a cutoff
        # is available, future identity changes must not leak into the case.
        audit_rows = self.audit_log_df[self.audit_log_df["field_name"] == "email"]
        if audit_at:
            cutoff = pd.to_datetime(audit_at, errors="coerce", utc=True)
            if not pd.isna(cutoff):
                audit_rows = audit_rows[audit_rows["event_time_parsed"] <= cutoff]
        historical = audit_rows[
            (audit_rows["old_value_normalized"] == normalized_email)
            | (audit_rows["new_value_normalized"] == normalized_email)
        ]
        if not historical.empty:
            # The latest admissible change is the strongest ownership signal.
            historical = historical.sort_values("event_time_parsed")
            return str(historical.iloc[-1]["user_id"]), "audit_log_historical"

        return None, "unmatched"

    def get_identity_profile(
        self,
        email: str,
        audit_at: str,
    ) -> Optional[UserIdentityProfile]:
        """Reconstruct the complete identity profile up to the audit_at cutoff.

        Args:
            email: Request email address.
            audit_at: ISO-8601 cutoff timestamp. Events after this timestamp are ignored.

        Returns:
            UserIdentityProfile or None if user cannot be resolved.
        """
        user_id, match_source = self.resolve_user_id(email, audit_at=audit_at)
        if not user_id:
            return None

        # Fetch current identity snapshot
        user_row = self.identities_df[self.identities_df["user_id"] == user_id]
        if user_row.empty:
            return None

        primary_row = user_row.iloc[0]
        primary_name = str(primary_row.get("name", "")).strip()
        primary_email = str(primary_row.get("email", "")).strip()
        primary_phone = str(primary_row.get("phone", "")).strip()
        primary_email_hash = str(primary_row.get("email_hash", "")).strip()

        all_names = {primary_name} if primary_name else set()
        all_emails = {primary_email.lower()} if primary_email else set()
        all_phones = {primary_phone} if primary_phone else set()
        all_email_hashes = {primary_email_hash} if primary_email_hash else set()

        # If incoming email is valid, include it in email variants
        req_email_clean = email.strip().lower()
        if req_email_clean:
            all_emails.add(req_email_clean)

        # Filter audit log strictly by user_id and event_time <= audit_at
        cutoff = pd.to_datetime(audit_at, errors="coerce", utc=True)
        user_audit = self.audit_log_df[self.audit_log_df["user_id"] == user_id]
        if not pd.isna(cutoff):
            user_audit = user_audit[user_audit["event_time_parsed"] <= cutoff]

        # Extract historical values from audit trail
        for _, change in user_audit.iterrows():
            field_name = str(change.get("field_name", "")).strip()
            old_val = str(change.get("old_value", "")).strip()
            new_val = str(change.get("new_value", "")).strip()

            if field_name == "email":
                if old_val:
                    all_emails.add(old_val.lower())
                if new_val:
                    all_emails.add(new_val.lower())
            elif field_name == "phone":
                if old_val:
                    all_phones.add(old_val)
                if new_val:
                    all_phones.add(new_val)
            elif field_name == "email_hash":
                if old_val:
                    all_email_hashes.add(old_val)
                if new_val:
                    all_email_hashes.add(new_val)
            elif field_name == "name":
                if old_val:
                    all_names.add(old_val)
                if new_val:
                    all_names.add(new_val)

        # Build complete alias search index containing accented and unaccented variants
        name_variants: set[str] = set()
        for n in all_names:
            name_variants.update(get_name_variants(n))

        # Guarantee that all emails in all_emails have their corresponding SHA256 hashes
        for e in list(all_emails):
            if e:
                h = hashlib.sha256(e.encode("utf-8")).hexdigest()
                all_email_hashes.add(h)

        return UserIdentityProfile(
            user_id=user_id,
            primary_name=primary_name,
            all_names=frozenset(all_names),
            name_variants=frozenset(name_variants),
            primary_email=primary_email,
            all_emails=frozenset(all_emails),
            primary_phone=primary_phone,
            all_phones=frozenset(all_phones),
            primary_email_hash=primary_email_hash,
            all_email_hashes=frozenset(all_email_hashes),
            audit_at=audit_at,
            matched_via=match_source,
        )
