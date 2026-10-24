"""Guardrail for the Logging Agent (Identity Tracker).

Enforces structural validity, identifier integrity, and zero temporal leakage.
"""

import re
from typing import Optional
import pandas as pd

from code.src.logging_agent.models import UserIdentityProfile


class IdentityGuardrail:
    """Validates that a UserIdentityProfile conforms strictly to system invariants."""

    USER_ID_PATTERN = re.compile(r"^user_\d+$")

    def __init__(self, audit_log_df: Optional[pd.DataFrame] = None) -> None:
        self.audit_log_df = audit_log_df

    def validate(self, profile: Optional[UserIdentityProfile]) -> tuple[bool, list[str]]:
        """Validate an identity profile against system invariants.

        Returns:
            (is_valid, errors) where errors is a list of violation messages.
        """
        errors: list[str] = []

        if profile is None:
            return False, ["Identity profile is None (user could not be resolved)."]

        # 1. User ID check
        if not profile.user_id or not self.USER_ID_PATTERN.match(profile.user_id):
            errors.append(f"Invalid user_id format: '{profile.user_id}'. Expected 'user_<number>'.")

        # 2. Email set non-empty check
        if not profile.all_emails:
            errors.append("Profile has empty 'all_emails' set; at least one email is required.")

        for email in profile.all_emails:
            if email != email.lower().strip():
                errors.append(f"Email '{email}' is not normalized (lowercase/stripped).")

        # 3. Temporal Cutoff Leakage Check (Zero Tolerance)
        if self.audit_log_df is not None and profile.audit_at:
            # Query audit log for events after audit_at for this user
            post_cutoff_events = self.audit_log_df[
                (self.audit_log_df["user_id"] == profile.user_id)
                & (self.audit_log_df["event_time"] > profile.audit_at)
            ]

            # Ensure none of the post-cutoff values exist in the profile unless they are in the primary snapshot
            for _, row in post_cutoff_events.iterrows():
                field_name = str(row.get("field_name", "")).strip()
                new_val = str(row.get("new_value", "")).strip()
                if not new_val:
                    continue

                if field_name == "email":
                    val_norm = new_val.lower().strip()
                    if val_norm in profile.all_emails and val_norm != profile.primary_email.lower():
                        errors.append(
                            f"Temporal leakage: Post-cutoff email '{new_val}' "
                            f"(timestamp {row['event_time']} > {profile.audit_at}) leaked into profile."
                        )
                elif field_name == "phone":
                    if new_val in profile.all_phones and new_val != profile.primary_phone:
                        errors.append(
                            f"Temporal leakage: Post-cutoff phone '{new_val}' "
                            f"(timestamp {row['event_time']} > {profile.audit_at}) leaked into profile."
                        )

        is_valid = len(errors) == 0
        return is_valid, errors
