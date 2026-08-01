import os
import csv
import sys
from typing import Dict, List, Any

class DatasetContext:
    def __init__(self):
        self.users: Dict[str, dict] = {}
        self.groups: Dict[str, dict] = {}
        self.group_members: Dict[tuple, dict] = {}
        self.business_accounts: Dict[str, dict] = {}
        self.user_business_history: Dict[tuple, dict] = {}
        self.message_history: Dict[str, dict] = {}
        self.message_events: Dict[str, dict] = {}
        self.messages: List[dict] = []
        self.images: Dict[str, dict] = {}
        self.voice_notes: Dict[str, dict] = {}
        self.daily_notification_summary: Dict[str, List[dict]] = {}

def _load_csv_dict(filepath: str, key_field: str | tuple) -> Dict:
    if not os.path.exists(filepath):
        print(f"WARNING: File not found {filepath}", file=sys.stderr)
        return {}
    
    result = {}
    with open(filepath, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if isinstance(key_field, tuple):
                key = tuple(row.get(k, "") for k in key_field)
            else:
                key = row.get(key_field, "")
            result[key] = row
    return result

def _load_csv_list(filepath: str) -> List[dict]:
    if not os.path.exists(filepath):
        print(f"WARNING: File not found {filepath}", file=sys.stderr)
        return []
    
    with open(filepath, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        return list(reader)

def load_all_data(dataset_dir: str) -> DatasetContext:
    ctx = DatasetContext()
    
    ctx.users = _load_csv_dict(os.path.join(dataset_dir, "users.csv"), "user_id")
    ctx.groups = _load_csv_dict(os.path.join(dataset_dir, "groups.csv"), "group_id")
    ctx.group_members = _load_csv_dict(os.path.join(dataset_dir, "group_members.csv"), ("group_id", "user_id"))
    ctx.business_accounts = _load_csv_dict(os.path.join(dataset_dir, "business_accounts.csv"), "business_id")
    ctx.user_business_history = _load_csv_dict(os.path.join(dataset_dir, "user_business_history.csv"), ("user_id", "business_id"))
    ctx.message_history = _load_csv_dict(os.path.join(dataset_dir, "message_history.csv"), "message_id")
    ctx.message_events = _load_csv_dict(os.path.join(dataset_dir, "message_events.csv"), "message_id")
    
    messages_path = os.path.join(dataset_dir, "messages.csv")
    ctx.messages = _load_csv_list(messages_path)
    
    if len(ctx.messages) != 110:
        print(f"CRITICAL ERROR: messages.csv must have exactly 110 rows, found {len(ctx.messages)}", file=sys.stderr)
        sys.exit(1)
        
    ctx.images = _load_csv_dict(os.path.join(dataset_dir, "images.csv"), "image_id")
    ctx.voice_notes = _load_csv_dict(os.path.join(dataset_dir, "voice_notes.csv"), "voice_note_id")
    
    daily_summary_path = os.path.join(dataset_dir, "daily_notification_summary.csv")
    if os.path.exists(daily_summary_path):
        with open(daily_summary_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                uid = row.get("user_id")
                if uid not in ctx.daily_notification_summary:
                    ctx.daily_notification_summary[uid] = []
                ctx.daily_notification_summary[uid].append(row)
                
    return ctx
