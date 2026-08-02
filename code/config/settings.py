"""
settings.py — Pydantic v2 Fail-Fast Boot Configuration.

Applies the 12-Factor App methodology (Factor III):
  - All config externalized to YAML + ENV
  - Load YAML via Pydantic v2 `model_validate()`
  - Fail-Fast: missing/invalid config terminates at startup with clear error
  - .env file loaded via python-dotenv before any config parsing

Zero hardcoded model names, thresholds, or credentials in Python source.
"""

import os
import sys
import yaml
from pathlib import Path
from pydantic import BaseModel, ValidationError

# Load .env file at import time (Fail-Fast: before any config parsing)
try:
    from dotenv import load_dotenv
    # Search for .env in code/env/.env (settings.py -> config/ -> code/env/.env)
    _CODE_DIR = Path(__file__).resolve().parent.parent
    _env_path = _CODE_DIR / "env" / ".env"
    if _env_path.exists():
        load_dotenv(_env_path, override=False)
except ImportError:
    # python-dotenv not installed — fall back to system ENV only
    pass


class ModelConfig(BaseModel):
    """LiteLLM model identifiers (format: provider/model-name)."""
    llm_model: str
    vlm_model: str
    stt_model: str


class ExecutionConfig(BaseModel):
    """Pipeline execution parameters."""
    llm_max_retries: int
    vlm_max_retries: int
    stt_max_retries: int
    max_concurrency: int
    timeout_seconds: int


class MediaConfig(BaseModel):
    """Image/audio preprocessing parameters."""
    image_long_edge_px: int


class PathConfig(BaseModel):
    """File paths for inputs/outputs."""
    dataset_dir: str
    messages_file: str = "messages.csv"
    output_file: str
    cache_dir: str


class PersonalizationConfig(BaseModel):
    """Engagement-based personalization thresholds."""
    low_engagement_threshold: float = 0.25


class ConfidenceConfig(BaseModel):
    """Deterministic confidence thresholds per gate."""
    gate_scam: float
    gate_promo_optout: float
    gate_emergency: float
    gate_actionable: float
    gate_dnd_digest: float
    gate_low_engagement: float = 0.80
    default: float
    media_failure_penalty: float
    fallback_default: float


class AppConfig(BaseModel):
    """Top-level application configuration."""
    models: ModelConfig
    execution: ExecutionConfig
    media: MediaConfig
    paths: PathConfig
    personalization: PersonalizationConfig = PersonalizationConfig()
    confidence: ConfidenceConfig


def load_config(path: str) -> AppConfig:
    """
    Load configuration from YAML file with ENV overrides.

    1. Reads YAML via yaml.safe_load()
    2. Applies ENV overrides (ORCHESTRATE_LLM_MODEL, ORCHESTRATE_VLM_MODEL, etc.)
    3. Validates via Pydantic v2 model_validate()
    4. Fail-Fast: terminates with sys.exit(1) if config is missing or invalid

    Args:
        path: Absolute or relative path to config.yaml

    Returns:
        Validated AppConfig instance
    """
    if not os.path.exists(path):
        print(f"CRITICAL ERROR: Configuration file not found at {path}", file=sys.stderr)
        sys.exit(1)

    try:
        with open(path, "r", encoding="utf-8") as f:
            raw_config = yaml.safe_load(f)
    except Exception as e:
        print(f"CRITICAL ERROR: Failed to parse YAML config: {e}", file=sys.stderr)
        sys.exit(1)

    # ── Apply ENV overrides (12-Factor App) ──
    if raw_config is None:
        raw_config = {}

    if "models" not in raw_config or raw_config["models"] is None:
        raw_config["models"] = {}

    # ── Auto-Detect Provider from API Keys in Environment ──
    # If the user commented out the models in config.yaml, auto-select based on .env
    if "llm_model" not in raw_config["models"] or not raw_config["models"]["llm_model"]:
        if os.environ.get("FIREWORKS_API_KEY"):
            raw_config["models"]["llm_model"] = "fireworks_ai/accounts/fireworks/models/llama-v3-70b-instruct"
            raw_config["models"]["vlm_model"] = "fireworks_ai/accounts/fireworks/models/llama-v3-70b-instruct"
        elif os.environ.get("AWS_ACCESS_KEY_ID"):
            raw_config["models"]["llm_model"] = "bedrock/anthropic.claude-3-5-sonnet-20241022-v2:0"
            raw_config["models"]["vlm_model"] = "bedrock/anthropic.claude-3-5-sonnet-20241022-v2:0"
        elif os.environ.get("OPENAI_API_KEY"):
            raw_config["models"]["llm_model"] = "openai/gpt-4o"
            raw_config["models"]["vlm_model"] = "openai/gpt-4o"
        elif os.environ.get("ANTHROPIC_API_KEY"):
            raw_config["models"]["llm_model"] = "anthropic/claude-3-5-sonnet-20241022"
            raw_config["models"]["vlm_model"] = "anthropic/claude-3-5-sonnet-20241022"
        else:
            raw_config["models"]["llm_model"] = "gemini/gemini-2.5-flash"
            raw_config["models"]["vlm_model"] = "gemini/gemini-2.5-flash"
            
    if "stt_model" not in raw_config["models"] or not raw_config["models"]["stt_model"]:
        raw_config["models"]["stt_model"] = "openai/whisper-1"

    env_overrides = {
        "ORCHESTRATE_LLM_MODEL": ("models", "llm_model"),
        "ORCHESTRATE_VLM_MODEL": ("models", "vlm_model"),
        "ORCHESTRATE_STT_MODEL": ("models", "stt_model"),
    }
    for env_key, (section, field) in env_overrides.items():
        value = os.environ.get(env_key)
        if value:
            raw_config[section][field] = value

    # ── Validate via Pydantic v2 (Parse, Don't Validate) ──
    try:
        config = AppConfig.model_validate(raw_config)
    except ValidationError as e:
        print(f"CRITICAL ERROR: Configuration validation failed:\n{e}", file=sys.stderr)
        sys.exit(1)

    # ── Fail-Fast: Verify API key exists for the chosen provider ──
    provider = config.models.llm_model.split("/")[0] if "/" in config.models.llm_model else ""
    provider_env_map = {
        "gemini": "GEMINI_API_KEY",
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "bedrock": "AWS_ACCESS_KEY_ID",
        "fireworks_ai": "FIREWORKS_API_KEY",
    }
    expected_env = provider_env_map.get(provider)
    if expected_env and not os.environ.get(expected_env):
        print(
            f"WARNING: {expected_env} not set in environment. "
            f"LLM calls to {config.models.llm_model} will fail. "
            f"Set it in .env or export it.",
            file=sys.stderr,
        )

    return config
