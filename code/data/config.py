from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


class ConfigError(ValueError):
    pass


def _load_dotenv_without_override(path: Path) -> None:
    if not path.exists():
        return
    try:
        from dotenv import load_dotenv
    except ImportError:
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if key:
                os.environ[key] = value.strip().strip('"').strip("'")
    else:
        # The repository-local file is the explicitly selected credential source for
        # this submission. Override stale shell values, but never print either value.
        load_dotenv(path, override=True)


def load_config(config_path: Path, repo_root: Path) -> dict[str, Any]:
    env_path = repo_root / "code" / ".env"
    _load_dotenv_without_override(env_path if env_path.exists() else repo_root / ".env")
    text = config_path.read_text(encoding="utf-8")
    try:
        config = json.loads(text)
    except json.JSONDecodeError:
        try:
            import yaml
        except ImportError as exc:
            raise ConfigError(
                "config.yaml is not JSON-compatible YAML and PyYAML is not installed"
            ) from exc
        config = yaml.safe_load(text)

    if not isinstance(config, dict) or config.get("version") != 1:
        raise ConfigError("config version must equal 1")
    for section in ("paths", "runtime", "evidence"):
        if not isinstance(config.get(section), dict):
            raise ConfigError(f"missing configuration section: {section}")

    evidence = config["evidence"]
    if os.environ.get("EVIDENCE_TEXT_MODEL"):
        evidence["text_model"] = os.environ["EVIDENCE_TEXT_MODEL"]
    if os.environ.get("EVIDENCE_VISION_MODEL"):
        evidence["vision_model"] = os.environ["EVIDENCE_VISION_MODEL"]
    if evidence.get("failure_policy") not in {"mark_invalid", "raise"}:
        raise ConfigError("evidence.failure_policy must be mark_invalid or raise")
    if int(config["runtime"].get("forecast_horizon_days", 0)) <= 0:
        raise ConfigError("runtime.forecast_horizon_days must be positive")
    return config


def resolve_repo_path(repo_root: Path, value: str) -> Path:
    candidate = Path(value)
    return candidate if candidate.is_absolute() else repo_root / candidate
