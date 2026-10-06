"""TIER 4: System Acceptance Unit Testing (UAT / Contractual Completeness)."""
import os
import csv
import pytest
from src.context.load_dataset import load_all_data


def test_acceptance_messages_dataset_110_rows(project_root_dir):
    """Verifies that dataset/messages.csv contains exactly 110 messages."""
    messages_path = os.path.join(project_root_dir, "dataset", "messages.csv")
    assert os.path.exists(messages_path), f"Missing messages dataset at {messages_path}"

    with open(messages_path, mode="r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    assert len(rows) == 110, f"Expected exactly 110 rows in messages.csv, found {len(rows)}"
    message_ids = [r["message_id"] for r in rows]
    assert len(set(message_ids)) == 110, "Duplicate message_id detected in messages.csv"


def test_acceptance_dataset_context_referential_integrity(project_root_dir):
    """Verifies that load_all_data loads all 11 CSV files without referential integrity errors."""
    dataset_dir = os.path.join(project_root_dir, "dataset")
    context = load_all_data(dataset_dir)

    assert len(context.messages) == 110
    assert len(context.users) > 0
    assert len(context.groups) > 0
    assert len(context.business_accounts) > 0


@pytest.fixture
def project_root_dir():
    """Returns absolute path to the repository root directory."""
    current_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.abspath(os.path.join(current_dir, "..", ".."))
