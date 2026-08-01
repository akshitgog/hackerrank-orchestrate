from .load_dataset import DatasetContext
from typing import Dict, Optional
from datetime import datetime

def get_user_profile(ctx: DatasetContext, user_id: str) -> Dict:
    user = ctx.users.get(user_id, {})
    if not user:
        return {}
        
    opened_30d = int(user.get("messages_opened_30d") or 0)
    replied_30d = int(user.get("messages_replied_30d") or 0)
    dismissed_30d = int(user.get("notifications_dismissed_30d") or 0)
    
    return {
        "user_id": user_id,
        "do_not_disturb_window": user.get("do_not_disturb_window", ""),
        "messages_opened_30d": opened_30d,
        "messages_replied_30d": replied_30d,
        "notifications_dismissed_30d": dismissed_30d,
        "messages_reported_30d": int(user.get("messages_reported_30d") or 0)
    }

def is_in_dnd(user_profile: Dict, message_timestamp: str) -> bool:
    dnd_window = user_profile.get("do_not_disturb_window", "")
    if not dnd_window or "-" not in dnd_window:
        return False
        
    try:
        start_str, end_str = dnd_window.split("-")
        msg_time = datetime.fromisoformat(message_timestamp.replace("Z", "+00:00")).time()
        
        start_time = datetime.strptime(start_str.strip(), "%H:%M").time()
        end_time = datetime.strptime(end_str.strip(), "%H:%M").time()
        
        if start_time <= end_time:
            return start_time <= msg_time <= end_time
        else: # Overnight wrap
            return msg_time >= start_time or msg_time <= end_time
    except Exception:
        return False

def get_group_membership(ctx: DatasetContext, user_id: str, group_id: str) -> Optional[Dict]:
    return ctx.group_members.get((group_id, user_id))

def get_business_relationship(ctx: DatasetContext, user_id: str, business_id: str) -> Optional[Dict]:
    return ctx.user_business_history.get((user_id, business_id))

def get_notification_fatigue(ctx: DatasetContext, user_id: str) -> float:
    summaries = ctx.daily_notification_summary.get(user_id, [])
    if not summaries:
        return 0.0
        
    total_sent = sum(int(s.get("notifications_sent") or 0) for s in summaries)
    total_dismissed = sum(int(s.get("notifications_dismissed") or 0) for s in summaries)
    
    if total_sent == 0:
        return 0.0
        
    return total_dismissed / total_sent
