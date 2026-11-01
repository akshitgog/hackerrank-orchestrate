"""Configuration loader utility for AI Deletion Audit Agent."""

import os
from pathlib import Path
from typing import Any
import yaml
from dotenv import load_dotenv

# Load local .env if present
ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
if ENV_PATH.exists():
    load_dotenv(ENV_PATH)


def load_config(config_path: str | Path | None = None) -> dict[str, Any]:
    """Load configuration from YAML file with environment variable overrides."""
    if config_path is None:
        config_path = Path(__file__).resolve().parent / "config.yaml"
    else:
        config_path = Path(config_path)

    if not config_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}

    # Environment overrides
    if "INTENT_THRESHOLD" in os.environ:
        try:
            config.setdefault("thresholds", {})["intent_decision"] = float(os.environ["INTENT_THRESHOLD"])
        except ValueError:
            pass

    return config
