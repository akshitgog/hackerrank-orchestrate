"""Universal LiteLLM Gateway with retry logic and token usage auditing.

Provides robust, multi-provider LLM calling with 3 retries, exponential backoff,
environment-based secret loading, and token tracking for evaluation/usage_report.md.
"""

import os
import time
from pathlib import Path
from typing import Any, Optional
import dotenv
import litellm

# Load secrets from code/.env if present
ENV_PATH = Path(__file__).resolve().parent.parent.parent / ".env"
if ENV_PATH.exists():
    dotenv.load_dotenv(ENV_PATH)
else:
    # Also attempt loading from workspace root .env if present
    dotenv.load_dotenv()


class TokenUsageTracker:
    """Tracks token consumption and model calls across runs for challenge reporting."""

    def __init__(self) -> None:
        self.call_count: int = 0
        self.prompt_tokens: int = 0
        self.completion_tokens: int = 0
        self.total_tokens: int = 0
        self.model_breakdown: dict[str, dict[str, int]] = {}

    def record_usage(self, model: str, prompt_tokens: int, completion_tokens: int) -> None:
        self.call_count += 1
        self.prompt_tokens += prompt_tokens
        self.completion_tokens += completion_tokens
        self.total_tokens += (prompt_tokens + completion_tokens)

        if model not in self.model_breakdown:
            self.model_breakdown[model] = {
                "calls": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            }
        self.model_breakdown[model]["calls"] += 1
        self.model_breakdown[model]["prompt_tokens"] += prompt_tokens
        self.model_breakdown[model]["completion_tokens"] += completion_tokens
        self.model_breakdown[model]["total_tokens"] += (prompt_tokens + completion_tokens)

    def summary(self) -> dict[str, Any]:
        return {
            "total_calls": self.call_count,
            "total_prompt_tokens": self.prompt_tokens,
            "total_completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "by_model": self.model_breakdown,
        }


# Global tracker instance
USAGE_TRACKER = TokenUsageTracker()


class RobustLLMClient:
    """Wraps litellm.completion with 3 retries, exponential backoff, and usage logging."""

    @classmethod
    def complete(
        cls,
        model: str,
        messages: list[dict[str, str]],
        temperature: float = 0.0,
        timeout: int = 15,
        max_retries: int = 3,
        initial_backoff: float = 1.0,
        **kwargs: Any,
    ) -> Optional[str]:
        """Execute a completion with exponential backoff retries.

        Args:
            model: LiteLLM model string (e.g. 'gemini/gemini-2.5-flash', 'gpt-4o-mini').
            messages: List of role-content message dicts.
            temperature: Sampling temperature (default 0.0).
            timeout: Per-call timeout in seconds.
            max_retries: Number of attempts before failing (default 3).
            initial_backoff: Initial backoff sleep in seconds.

        Returns:
            Completion text string or None if all retries failed.
        """
        # Auto-format fireworks_ai provider prefix if user passed accounts/fireworks/
        if model.startswith("accounts/fireworks/"):
            model = f"fireworks_ai/{model}"

        delay = initial_backoff
        last_exception = None

        for attempt in range(1, max_retries + 1):
            try:
                response = litellm.completion(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    timeout=timeout,
                    **kwargs,
                )

                # Record usage statistics if available
                usage = getattr(response, "usage", None)
                if usage:
                    prompt_toks = getattr(usage, "prompt_tokens", 0) or 0
                    comp_toks = getattr(usage, "completion_tokens", 0) or 0
                    USAGE_TRACKER.record_usage(model, prompt_toks, comp_toks)

                content = response.choices[0].message.content
                return str(content).strip() if content else ""

            except Exception as e:
                last_exception = e
                # Do not retry on permanent bad request / authentication errors
                err_str = str(e).lower()
                if "authenticationerror" in err_str or "invalid_api_key" in err_str:
                    break

                if attempt < max_retries:
                    time.sleep(delay)
                    delay *= 2.0  # Exponential backoff

        return None
