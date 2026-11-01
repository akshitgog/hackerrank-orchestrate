"""Policy engine encoding dataset/deletion_rules.csv governance requirements."""

from pathlib import Path
from typing import Optional
import pandas as pd


class PolicyEngine:
    """Evaluates resource compliance against deletion rules."""

    SYSTEM_TO_CATEGORY: dict[str, str] = {
        "account_service": "USER_PROFILE",
        "search_service": "SEARCH_INDEX_ENTRY",
        "support_platform": "SUPPORT_ATTACHMENT",
        "export_service": "USER_EXPORT",
        "analytics_platform": "ANALYTICS_PROFILE",
        "security_service": "SECURITY_AUDIT_LOG",
        "identity_service": "ACCOUNT_TOMBSTONE",
        "backup_service": "BACKUP_ARCHIVE",
        "integration_service": "CONNECTOR_DATA_FLOW",
        "cache_service": "CACHE_ENTRY",
        "marketing_platform": "MARKETING_PROFILE",
    }

    def __init__(self, rules_path: str | Path = "dataset/deletion_rules.csv") -> None:
        self.rules_path = Path(rules_path)
        self.rules_df = pd.read_csv(self.rules_path) if self.rules_path.exists() else pd.DataFrame()

    def get_data_category(self, system_id: str, resource_id: str) -> str:
        """Infer data category from system_id and resource_id prefix."""
        if resource_id.startswith("tombstone_"):
            return "ACCOUNT_TOMBSTONE"
        if resource_id.startswith("audit_record_"):
            return "SECURITY_AUDIT_LOG"
        if resource_id.startswith("data_flow_"):
            return "CONNECTOR_DATA_FLOW"
        if resource_id.startswith("backup_"):
            return "BACKUP_ARCHIVE"
        if resource_id.startswith("analytics_"):
            return "ANALYTICS_PROFILE"
        if resource_id.startswith("support_"):
            return "SUPPORT_ATTACHMENT"
        if resource_id.startswith("export_"):
            return "USER_EXPORT"
        if resource_id.startswith("search_"):
            return "SEARCH_INDEX_ENTRY"
        if resource_id.startswith("account_"):
            return "USER_PROFILE"
        return self.SYSTEM_TO_CATEGORY.get(system_id, "USER_PROFILE")

    def get_required_action(self, data_category: str) -> str:
        """Get required action from deletion_rules.csv."""
        if not self.rules_df.empty:
            match = self.rules_df[self.rules_df["data_category"] == data_category]
            if not match.empty:
                return str(match.iloc[0]["required_action"]).strip().upper()

        # Fallback defaults aligned with deletion_rules.csv
        defaults = {
            "USER_PROFILE": "DELETE",
            "SECONDARY_IDENTIFIER": "DELETE",
            "SEARCH_INDEX_ENTRY": "DELETE",
            "CACHE_ENTRY": "DELETE",
            "USER_EXPORT": "DELETE",
            "MARKETING_PROFILE": "DELETE",
            "SUPPORT_ATTACHMENT": "DELETE",
            "SUPPORT_MESSAGE": "REDACT",
            "ACCOUNT_TOMBSTONE": "REDACT",
            "EMAIL_DELIVERY_LOG": "REDACT",
            "ANALYTICS_PROFILE": "ANONYMIZE",
            "PRODUCT_TELEMETRY": "ANONYMIZE",
            "SECURITY_AUDIT_LOG": "RETAIN",
            "LEGAL_HOLD_RECORD": "RETAIN",
            "BACKUP_ARCHIVE": "RETAIN",
            "CONNECTOR_DATA_FLOW": "DISABLE",
        }
        return defaults.get(data_category, "DELETE")
