from .load_dataset import DatasetContext
from typing import List, Dict

def get_sender_history(ctx: DatasetContext, user_id: str, sender_user_id: str, limit: int = 5) -> List[Dict]:
    history = []
    for msg in ctx.message_history.values():
        if msg.get("user_id") == user_id and msg.get("sender_user_id") == sender_user_id:
            history.append(msg)
    history.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return history[:limit]

def get_business_history(ctx: DatasetContext, user_id: str, business_id: str, limit: int = 5) -> List[Dict]:
    history = []
    for msg in ctx.message_history.values():
        if msg.get("user_id") == user_id and msg.get("business_id") == business_id:
            history.append(msg)
    history.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return history[:limit]

def get_group_history(ctx: DatasetContext, user_id: str, group_id: str, limit: int = 5) -> List[Dict]:
    history = []
    for msg in ctx.message_history.values():
        if msg.get("user_id") == user_id and msg.get("group_id") == group_id:
            history.append(msg)
    history.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return history[:limit]

def get_sender_events(ctx: DatasetContext, user_id: str, sender_user_id: str) -> Dict:
    sent_count = 0
    opened_count = 0
    replied_count = 0
    dismissed_count = 0
    
    for msg in ctx.message_history.values():
        if msg.get("user_id") == user_id and msg.get("sender_user_id") == sender_user_id:
            sent_count += 1
            msg_id = msg.get("message_id")
            event = ctx.message_events.get(msg_id)
            if event:
                if event.get("message_opened") == "true": opened_count += 1
                if event.get("message_replied") == "true": replied_count += 1
                if event.get("notification_dismissed") == "true": dismissed_count += 1
                
    return {
        "sent": sent_count,
        "opened": opened_count,
        "replied": replied_count,
        "dismissed": dismissed_count,
        "open_rate": opened_count / sent_count if sent_count > 0 else 0.0,
        "reply_rate": replied_count / sent_count if sent_count > 0 else 0.0,
        "dismiss_rate": dismissed_count / sent_count if sent_count > 0 else 0.0
    }
