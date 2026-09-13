from __future__ import annotations

import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from data.config import load_config
from evidence.gateway import GatewayError, LiteLLMGateway


class ConfigTests(unittest.TestCase):
    def test_code_dotenv_overrides_stale_process_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "code").mkdir()
            (root / "code" / ".env").write_text("PROVIDER_TEST_KEY=file-value\n", encoding="utf-8")
            config_path = root / "config.yaml"
            config_path.write_text(json.dumps({
                "version": 1,
                "paths": {},
                "runtime": {"forecast_horizon_days": 90},
                "evidence": {"failure_policy": "mark_invalid"},
            }), encoding="utf-8")
            with patch.dict(os.environ, {"PROVIDER_TEST_KEY": "process-value"}, clear=False):
                load_config(config_path, root)
                self.assertEqual(os.environ["PROVIDER_TEST_KEY"], "file-value")


class GatewayTests(unittest.TestCase):
    def test_bedrock_placeholder_is_not_called(self) -> None:
        gateway = LiteLLMGateway(
            {
                "enabled": True,
                "text_model": "bedrock/your-text-model-id",
                "vision_model": "bedrock/your-vision-model-id",
                "fallback_models": [],
            },
            Path("artifacts"),
        )
        with self.assertRaisesRegex(GatewayError, "no usable text_model configured"):
            gateway.complete_json([], vision=False)

    def test_primary_failure_uses_configured_fallback(self):
        calls = []

        def completion(**kwargs):
            calls.append(kwargs["model"])
            if kwargs["model"] == "provider/primary":
                raise RuntimeError("primary unavailable")
            return types.SimpleNamespace(
                choices=[types.SimpleNamespace(message=types.SimpleNamespace(content='{"facts": []}'))],
                usage={"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
            )

        fake_module = types.SimpleNamespace(completion=completion)
        settings = {
            "enabled": True,
            "text_model": "provider/primary",
            "vision_model": "provider/vision",
            "fallback_models": ["provider/fallback"],
            "max_retries_per_model": 1,
            "cache_enabled": False,
        }
        with tempfile.TemporaryDirectory() as directory, patch.dict(sys.modules, {"litellm": fake_module}):
            payload = LiteLLMGateway(settings, Path(directory)).complete_json(
                [{"role": "user", "content": "resolve"}], vision=False
            )
        self.assertEqual(payload, {"facts": []})
        self.assertEqual(calls, ["provider/primary", "provider/fallback"])

    def test_authentication_failure_is_not_retried(self):
        calls = []

        class AuthenticationError(RuntimeError):
            pass

        def completion(**kwargs):
            calls.append(kwargs["model"])
            raise AuthenticationError("expired credential")

        settings = {
            "enabled": True, "text_model": "provider/primary",
            "fallback_models": [], "max_retries_per_model": 4, "cache_enabled": False,
        }
        fake_module = types.SimpleNamespace(completion=completion)
        with tempfile.TemporaryDirectory() as directory, patch.dict(sys.modules, {"litellm": fake_module}):
            with self.assertRaises(GatewayError):
                LiteLLMGateway(settings, Path(directory)).complete_json([], vision=False)
        self.assertEqual(calls, ["provider/primary"])


if __name__ == "__main__":
    unittest.main()
