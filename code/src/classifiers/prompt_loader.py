"""
prompt_loader.py — Single declarative loader for all YAML prompt templates in code/prompts/.

Loads:
  - code/prompts/llm_labeler.yaml (LLM semantic classification prompt)
  - code/prompts/vlm_screener.yaml (VLM image OCR & instruction screening prompt)
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

_LLM_CACHE: dict | None = None
_VLM_CACHE: dict | None = None
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


def build_labeler_prompt(
    message: dict,
    history_context: list[dict],
    user_profile: dict,
    group_info: dict | None,
    business_info: dict | None,
) -> tuple[str, str]:
    """Build (system_prompt, user_prompt) for LLM semantic classification from llm_labeler.yaml."""
    global _LLM_CACHE
    template = _load_yaml("llm_labeler.yaml", _LLM_CACHE)
    _LLM_CACHE = template

    system_prompt = template["system"]
    user_template = template["user"]

    user_prompt = user_template.format(
        user_id=message.get("user_id", "unknown"),
        user_profile_json=json.dumps(user_profile, indent=2, ensure_ascii=False),
        group_info_json=json.dumps(group_info, indent=2, ensure_ascii=False) if group_info else "No group context (personal/business message)",
        business_info_json=json.dumps(business_info, indent=2, ensure_ascii=False) if business_info else "No business context",
        history_context_json=json.dumps(history_context, indent=2, ensure_ascii=False) if history_context else "No prior message history available",
        message_id=message.get("message_id", ""),
        conversation_type=message.get("conversation_type", ""),
        sender_user_id=message.get("sender_user_id", "unknown"),
        created_at=message.get("created_at", ""),
        forwarded_count=message.get("forwarded_count", 0),
        media_type=message.get("media_type", "none"),
        message_text=message.get("message_text", "[no text content]"),
    )

    return system_prompt, user_prompt


def build_vlm_prompt(image_context: str) -> tuple[str, str]:
    """Build (system_prompt, user_prompt) for VLM image screening from vlm_screener.yaml."""
    global _VLM_CACHE
    template = _load_yaml("vlm_screener.yaml", _VLM_CACHE)
    _VLM_CACHE = template

    system_prompt = template["system"]
    user_prompt = template["user"].format(image_context=image_context)
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
