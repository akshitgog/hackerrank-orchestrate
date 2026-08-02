"""
prompt_loader.py — Single declarative loader for all YAML prompt templates in code/prompts/.

Loads:
  - code/prompts/msg_observer.yaml (LLM text message signal extraction prompt)
  - code/prompts/msg_router.yaml (LLM text message intent classification prompt)
  - code/prompts/vlm_observer.yaml (VLM image observation prompt)
  - code/prompts/img_router.yaml (LLM image classification prompt)
  - code/prompts/stt_config.yaml (STT audio normalization rules)

Edit any YAML file in code/prompts/ to change model behavior — zero code modifications required.
"""

import json
import re
import os
import yaml
from pathlib import Path

# Resolve prompts/ directory relative to project root (code/src/classifiers -> code/prompts)
_CODE_DIR = Path(__file__).resolve().parent.parent.parent
_PROMPTS_DIR = _CODE_DIR / "prompts"

_MSG_OBSERVER_CACHE: dict | None = None
_MSG_ROUTER_CACHE: dict | None = None
_VLM_CACHE: dict | None = None
_IMG_ROUTER_CACHE: dict | None = None
_STT_CACHE: dict | None = None


def _load_yaml(filename: str, cache_var: dict | None) -> dict:
    if cache_var is not None:
        return cache_var

    yaml_path = _PROMPTS_DIR / filename
    if not yaml_path.exists():
        raise FileNotFoundError(
            f"Prompt template not found at {yaml_path}. "
            f"Ensure code/prompts/{filename} exists."
        )

    with open(yaml_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def build_msg_observer_prompt(
    message: dict,
    user_profile: dict,
    group_info: dict | None,
) -> tuple[str, str]:
    """Build prompt for LLM signal extraction from msg_observer.yaml."""
    global _MSG_OBSERVER_CACHE
    template = _load_yaml("msg_observer.yaml", _MSG_OBSERVER_CACHE)
    _MSG_OBSERVER_CACHE = template

    system_prompt = template["system"]
    user_template = template["user"]

    user_prompt = user_template.format(
        user_id=message.get("user_id", "unknown"),
        user_profile_json=json.dumps(user_profile, indent=2, ensure_ascii=False),
        group_info_json=json.dumps(group_info, indent=2, ensure_ascii=False) if group_info else "No group context",
        message_id=message.get("message_id", ""),
        conversation_type=message.get("conversation_type", ""),
        sender_user_id=message.get("sender_user_id", "unknown"),
        created_at=message.get("created_at", ""),
        forwarded_count=message.get("forwarded_count", 0),
        media_type=message.get("media_type", "none"),
        message_text=message.get("message_text", "[no text content]"),
    )
    return system_prompt, user_prompt


def build_msg_router_prompt(
    message: dict,
    history_context: list[dict],
    interaction_history: dict,
    msg_observer_output_json: str,
) -> tuple[str, str]:
    """Build prompt for LLM intent classification from msg_router.yaml."""
    global _MSG_ROUTER_CACHE
    template = _load_yaml("msg_router.yaml", _MSG_ROUTER_CACHE)
    _MSG_ROUTER_CACHE = template

    system_prompt = template["system"]
    user_template = template["user"]

    user_prompt = user_template.format(
        user_id=message.get("user_id", "unknown"),
        message_id=message.get("message_id", ""),
        conversation_type=message.get("conversation_type", ""),
        sender_user_id=message.get("sender_user_id", "unknown"),
        sender_verified=str(message.get("sender_verified", False)),
        forwarded_count=message.get("forwarded_count", 0),
        history_context_json=json.dumps(history_context, indent=2, ensure_ascii=False) if history_context else "No prior message history available",
        interaction_history_json=json.dumps(interaction_history, indent=2, ensure_ascii=False),
        msg_observer_output_json=msg_observer_output_json,
    )
    return system_prompt, user_prompt


def build_vlm_prompt(sender_type: str, conversation_type: str) -> tuple[str, str]:
    """Build (system_prompt, user_prompt) for VLM image observation from vlm_observer.yaml."""
    global _VLM_CACHE
    template = _load_yaml("vlm_observer.yaml", _VLM_CACHE)
    _VLM_CACHE = template

    system_prompt = template["system"]
    user_prompt = template["user"].format(
        sender_type=sender_type,
        conversation_type=conversation_type,
    )
    return system_prompt, user_prompt

def build_img_router_prompt(
    sender_type: str,
    conversation_type: str,
    sender_verified: str,
    forwarded_count: int,
    vlm_observation_json: str,
) -> tuple[str, str]:
    """Build prompt for LLM image classification from img_router.yaml."""
    global _IMG_ROUTER_CACHE
    template = _load_yaml("img_router.yaml", _IMG_ROUTER_CACHE)
    _IMG_ROUTER_CACHE = template

    system_prompt = template["system"]
    user_prompt = template["user"].format(
        sender_type=sender_type,
        conversation_type=conversation_type,
        sender_verified=sender_verified,
        forwarded_count=forwarded_count,
        vlm_observation_json=vlm_observation_json,
    )
    return system_prompt, user_prompt


def clean_stt_transcription(raw_text: str) -> str:
    """Normalize common STT artifacts using rules defined in stt_config.yaml."""
    if not raw_text:
        return ""

    global _STT_CACHE
    try:
        config = _load_yaml("stt_config.yaml", _STT_CACHE)
        _STT_CACHE = config
    except FileNotFoundError:
        return raw_text.strip()

    rules = config.get("normalization_rules", {})
    replacements = rules.get("replacements", {})

    text = raw_text
    for pattern, replacement in replacements.items():
        text = text.replace(pattern, replacement)

    text = re.sub(r"\s+", " ", text).strip()
    return text
