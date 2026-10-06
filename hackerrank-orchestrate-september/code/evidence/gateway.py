from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any


class GatewayError(RuntimeError):
    pass


class LiteLLMGateway:
    def __init__(self, settings: dict[str, Any], artifacts_dir: Path):
        self.settings = settings
        self.artifacts_dir = artifacts_dir
        self.cache_dir = artifacts_dir / "evidence_cache"
        self.usage_file = artifacts_dir / "usage.jsonl"
        self.records: list[dict[str, Any]] = []
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.usage_file.write_text("", encoding="utf-8")

    def complete_json(
        self,
        messages: list[dict[str, Any]],
        *,
        vision: bool,
        request_id: str = "unknown",
        call_type: str | None = None,
    ) -> dict[str, Any]:
        if not self.settings.get("enabled", False):
            raise GatewayError("evidence model is disabled in config.yaml")
        primary_key = "vision_model" if vision else "text_model"
        models = [self.settings.get(primary_key), *self.settings.get("fallback_models", [])]
        models = [
            model for model in models
            if model and "model-name" not in model and "/your-" not in model
        ]
        if not models:
            raise GatewayError(f"no usable {primary_key} configured")
        try:
            import litellm
        except ImportError as exc:
            raise GatewayError("LiteLLM is not installed; run pip install -r code/requirements.txt") from exc

        call_type = call_type or ("evidence_vision" if vision else "evidence_text")

        cache_key = hashlib.sha256(
            json.dumps({"models": models, "messages": messages}, sort_keys=True).encode("utf-8")
        ).hexdigest()
        cache_path = self.cache_dir / f"{cache_key}.json"
        if self.settings.get("cache_enabled", True) and cache_path.exists():
            self._record_usage(
                request_id, call_type, models[0], 0, 0.0, None, None,
                cache_hit=True, provider_call=False,
            )
            return json.loads(cache_path.read_text(encoding="utf-8"))

        failures: list[str] = []
        for model in models:
            for attempt in range(1, int(self.settings.get("max_retries_per_model", 2)) + 1):
                started = time.monotonic()
                try:
                    response = litellm.completion(
                        model=model,
                        messages=messages,
                        temperature=self.settings.get("temperature", 0),
                        max_tokens=int(self.settings.get("max_tokens", 1800)),
                        timeout=float(self.settings.get("timeout_seconds", 60)),
                        response_format={"type": "json_object"},
                    )
                    content = response.choices[0].message.content
                    import re
                    payload = None
                    # Try to extract the last ```json ... ``` block
                    blocks = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
                    if blocks:
                        for block in reversed(blocks):
                            try:
                                payload = json.loads(block)
                                break
                            except json.JSONDecodeError:
                                continue

                    if payload is None:
                        # Fallback: simple brace counting to find valid JSON blocks
                        # Since models might wrap it or include reasoning, we look for outermost objects
                        brace_count = 0
                        start_idx = -1
                        for i, char in enumerate(content):
                            if char == '{':
                                if brace_count == 0:
                                    start_idx = i
                                brace_count += 1
                            elif char == '}':
                                brace_count -= 1
                                if brace_count == 0 and start_idx != -1:
                                    try:
                                        payload = json.loads(content[start_idx:i+1])
                                        # Keep the last successfully parsed one
                                    except json.JSONDecodeError:
                                        pass
                                    start_idx = -1
                    if payload is None:
                        # Final fallback
                        try:
                            payload = json.loads(content)
                        except json.JSONDecodeError:
                            raise
                    usage = getattr(response, "usage", None)
                    self._record_usage(
                        request_id, call_type, model, attempt, time.monotonic() - started,
                        usage, None, cost=self._extract_cost(response),
                    )
                    if self.settings.get("cache_enabled", True):
                        self.cache_dir.mkdir(parents=True, exist_ok=True)
                        cache_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
                    return payload
                except Exception as exc:  # provider exceptions differ, keep a common boundary
                    failures.append(f"{model} attempt {attempt}: {type(exc).__name__}")
                    self._record_usage(
                        request_id, call_type, model, attempt, time.monotonic() - started,
                        getattr(exc, "usage", None), type(exc).__name__,
                    )
                    if not self._is_retryable(exc):
                        break
                    if attempt < int(self.settings.get("max_retries_per_model", 2)):
                        time.sleep(2 ** attempt)
        raise GatewayError("all configured evidence models failed: " + "; ".join(failures))

    @staticmethod
    def _is_retryable(exc: Exception) -> bool:
        name = type(exc).__name__.casefold()
        if any(marker in name for marker in ("authentication", "permission", "configuration", "notfound")):
            return False
        return any(marker in name for marker in (
            "timeout", "ratelimit", "serviceunavailable", "connection",
            "jsondecode", "apierror", "internalserver",
        ))

    @staticmethod
    def _extract_cost(response: Any) -> Any:
        hidden = getattr(response, "_hidden_params", None)
        if isinstance(hidden, dict):
            return hidden.get("response_cost")
        return None

    def _record_usage(
        self,
        request_id: str,
        call_type: str,
        model: str,
        attempt: int,
        latency: float,
        usage: Any,
        error: str | None,
        *,
        cost: Any = None,
        cache_hit: bool = False,
        provider_call: bool = True,
    ) -> None:
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        if usage is None:
            input_tokens = output_tokens = total_tokens = None
        elif isinstance(usage, dict):
            input_tokens = usage.get("prompt_tokens")
            output_tokens = usage.get("completion_tokens")
            total_tokens = usage.get("total_tokens")
        else:
            input_tokens = getattr(usage, "prompt_tokens", None)
            output_tokens = getattr(usage, "completion_tokens", None)
            total_tokens = getattr(usage, "total_tokens", None)
        record = {
            "request_id": request_id,
            "call_type": call_type,
            "provider": model.split("/", 1)[0] if "/" in model else "unknown",
            "model": model,
            "attempt": attempt,
            "latency_seconds": round(latency, 3),
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
            "cost": cost,
            "cache_hit": cache_hit,
            "provider_call": provider_call,
            "status": "cache_hit" if cache_hit else ("failed" if error else "success"),
            "error": error,
        }
        self.records.append(record)
        with self.usage_file.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
