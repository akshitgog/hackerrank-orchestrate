"""
check_output.py — Output contract validator.

Enforces the 110-Row Completeness Invariant, exact 6-column schema,
valid enum vocabularies, and evidence ID existence in message_history.csv.
"""

from typing import List, Set

# Exact allowed vocabulary (from problem_statement.md)
VALID_ACTIONS = {"notify", "digest", "mute"}
VALID_MESSAGE_TYPES = {
    "personal", "urgent", "event", "payment", "business_update",
    "promotion", "greeting", "forward", "spam", "scam", "unknown",
}
REQUIRED_COLUMNS = ["message_id", "action", "message_type", "reason", "confidence", "evidence_message_ids"]


def validate_output(
    output_rows: List[dict],
    expected_message_ids: List[str],
    history_ids: Set[str],
) -> List[str]:
    """
    Validate the output rows against the contract.

    Args:
        output_rows: List of output dicts (one per message).
        expected_message_ids: List of message_ids from messages.csv (110 items).
        history_ids: Set of valid message_ids from message_history.csv.

    Returns:
        List of error strings. Empty list = valid output.
    """
    errors = []

    # Check row count
    if len(output_rows) != len(expected_message_ids):
        errors.append(
            f"Row count mismatch: expected {len(expected_message_ids)}, got {len(output_rows)}"
        )

    # Check all expected message_ids are present
    output_ids = {row.get("message_id") for row in output_rows}
    missing_ids = set(expected_message_ids) - output_ids
    if missing_ids:
        errors.append(f"Missing message_ids: {sorted(missing_ids)}")

    extra_ids = output_ids - set(expected_message_ids)
    if extra_ids:
        errors.append(f"Unexpected message_ids: {sorted(extra_ids)}")

    # Per-row validation
    for i, row in enumerate(output_rows):
        msg_id = row.get("message_id", f"row_{i}")

        # Check required columns
        for col in REQUIRED_COLUMNS:
            if col not in row:
                errors.append(f"{msg_id}: missing column '{col}'")

        # Check action enum
        action = row.get("action", "")
        if action not in VALID_ACTIONS:
            errors.append(f"{msg_id}: invalid action '{action}' (must be one of {VALID_ACTIONS})")

        # Check message_type enum
        msg_type = row.get("message_type", "")
        if msg_type not in VALID_MESSAGE_TYPES:
            errors.append(f"{msg_id}: invalid message_type '{msg_type}' (must be one of {VALID_MESSAGE_TYPES})")

        # Check confidence is a valid float in [0.0, 1.0]
        try:
            conf = float(row.get("confidence", -1))
            if conf < 0.0 or conf > 1.0:
                errors.append(f"{msg_id}: confidence {conf} out of range [0.0, 1.0]")
        except (ValueError, TypeError):
            errors.append(f"{msg_id}: confidence '{row.get('confidence')}' is not a valid float")

        # Check evidence_message_ids
        evidence = row.get("evidence_message_ids", "none")
        if evidence and evidence != "none":
            for eid in evidence.split(";"):
                eid = eid.strip()
                if eid and eid != "none" and eid not in history_ids:
                    errors.append(f"{msg_id}: evidence_message_id '{eid}' not found in message_history.csv")

        # Check reason is non-empty
        reason = row.get("reason", "")
        if not reason or not reason.strip():
            errors.append(f"{msg_id}: reason is empty")

    return errors
