"""
llm.py — Async LLM/VLM/STT adapter using LiteLLM.

Handles:
  - SHA-256 cache-first lookup (zero duplicate billing on re-runs)
  - asyncio.Semaphore rate limiting (prevents HTTP 429)
  - Exponential backoff retry (1s, 2s, 4s across max_retries attempts)
  - Pydantic v2 output validation (SensorObservation typed seam)
  - Self-correction retry on schema parse failure

All model names read from config — NEVER hardcoded.
"""

import asyncio
import json
import hashlib
import logging
from typing import Optional

from .schema_models import SensorObservation
from .response_cache import ResponseCache

logger = logging.getLogger(__name__)

try:
    import litellm
    # Suppress LiteLLM's verbose logging
    litellm.suppress_debug_info = True
except ImportError:
    raise ImportError(
        "litellm is required but not installed. "
        "Install it with: pip install litellm"
    )


class LLMAdapter:
    """
    Unified async adapter for LLM, VLM, and STT via LiteLLM.

    LiteLLM auto-routes to the correct provider based on the model string prefix:
      - "gemini/gemini-2.5-flash" → Google Gemini (uses GEMINI_API_KEY)
      - "openai/gpt-4o" → OpenAI (uses OPENAI_API_KEY)
      - "anthropic/claude-sonnet-4-20250514" → Anthropic (uses ANTHROPIC_API_KEY)
      - "openai/whisper-1" → OpenAI Whisper STT
    """

    def __init__(self, config, cache: ResponseCache):
        self.config = config
        self.cache = cache
        self._semaphore = asyncio.Semaphore(config.execution.max_concurrency)
        self.llm_max_retries = config.execution.llm_max_retries
        self.vlm_max_retries = config.execution.vlm_max_retries
        self.stt_max_retries = config.execution.stt_max_retries
        self.timeout = config.execution.timeout_seconds

    async def _acompletion_with_retry(self, max_retries: int, **kwargs):
        """Call litellm.acompletion with exponential backoff retry."""
        backoff = 1
        last_error = None
        for attempt in range(max_retries):
            try:
                async with self._semaphore:
                    return await litellm.acompletion(**kwargs, timeout=self.timeout)
            except Exception as e:
                last_error = e
                if attempt < max_retries - 1:
                    logger.warning(f"LLM call attempt {attempt + 1} failed: {e}. Retrying in {backoff}s...")
                    await asyncio.sleep(backoff)
                    backoff *= 2
        raise last_error

    async def classify_message(
        self,
        system_prompt: str,
        user_prompt: str,
        model: Optional[str] = None,
    ) -> Optional[SensorObservation]:
        """
        Call LLM for semantic classification. Returns SensorObservation or None on failure.

        Flow: Cache check → LiteLLM acompletion → Pydantic parse → Cache store
        On parse failure: 1 self-correction retry with schema error feedback.
        """
        model_name = model or self.config.models.llm_model

        # ── Cache check (SHA-256 keyed, zero duplicate billing) ──
        prompt_hash_data = f"{model_name}:{system_prompt}:{user_prompt}".encode("utf-8")
        prompt_hash = hashlib.sha256(prompt_hash_data).hexdigest()
        cache_key = self.cache.cache_key(model_name, prompt_hash)

        cached = self.cache.get(cache_key)
        if cached:
            try:
                return SensorObservation.model_validate(cached)
            except Exception:
                pass  # Cache entry corrupt — re-fetch

        # ── LiteLLM call with JSON mode ──
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        for attempt in range(2):  # 1 initial + 1 self-correction retry
            try:
                response = await self._acompletion_with_retry(
                    max_retries=self.llm_max_retries,
                    model=model_name,
                    messages=messages,
                    response_format={"type": "json_object"},
                )

                content = response.choices[0].message.content

                # ── Typed Seam: Pydantic v2 model_validate() ──
                parsed_json = json.loads(content)
                observation = SensorObservation.model_validate(parsed_json)

                # Cache successful response
                self.cache.put(cache_key, parsed_json)
                return observation

            except json.JSONDecodeError as e:
                logger.warning(f"LLM returned invalid JSON (attempt {attempt + 1}): {e}")
                if attempt == 0:
                    # Self-correction: feed the error back to the LLM
                    messages.append({"role": "assistant", "content": content if 'content' in dir() else ""})
                    messages.append({"role": "user", "content": f"Your response was not valid JSON: {e}. Please return ONLY valid JSON matching the SensorObservation schema."})
            except Exception as e:
                logger.warning(f"LLM classification failed (attempt {attempt + 1}): {e}")
                if attempt == 0 and 'content' in dir():
                    messages.append({"role": "assistant", "content": str(content)})
                    messages.append({"role": "user", "content": f"Schema validation failed: {e}. Fix the JSON to match the exact schema."})

        logger.error(f"classify_message failed after all retries for model={model_name}")
        return None

    async def extract_message_signals(
        self,
        system_prompt: str,
        user_prompt: str,
        model: Optional[str] = None,
    ) -> Optional[str]:
        """Call LLM text model to extract boolean signals from the raw message. Returns JSON string."""
        model_name = model or self.config.models.llm_model

        # ── Cache check ──
        prompt_hash_data = f"{model_name}:{system_prompt}:{user_prompt}".encode("utf-8")
        prompt_hash = hashlib.sha256(prompt_hash_data).hexdigest()
        cache_key = self.cache.cache_key(model_name, prompt_hash)

        cached = self.cache.get(cache_key)
        if cached and "raw" in cached:
            return cached["raw"]

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        try:
            response = await self._acompletion_with_retry(
                max_retries=self.llm_max_retries,
                model=model_name,
                messages=messages,
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content
            
            # Simple JSON parse test just to ensure it's valid JSON
            json.loads(content)
            
            self.cache.put(cache_key, {"raw": content})
            return content
        except Exception as e:
            logger.error(f"extract_message_signals failed: {e}")
            return None

    async def route_image_text(
        self,
        system_prompt: str,
        user_prompt: str,
        model: Optional[str] = None,
    ) -> Optional[str]:
        """Call LLM text model to route an image based on the VLM observer's text report. Returns JSON string."""
        model_name = model or self.config.models.llm_model

        # ── Cache check ──
        prompt_hash_data = f"{model_name}:{system_prompt}:{user_prompt}".encode("utf-8")
        prompt_hash = hashlib.sha256(prompt_hash_data).hexdigest()
        cache_key = self.cache.cache_key(model_name, prompt_hash)

        cached = self.cache.get(cache_key)
        if cached and "raw" in cached:
            return cached["raw"]

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        try:
            response = await self._acompletion_with_retry(
                max_retries=self.llm_max_retries,
                model=model_name,
                messages=messages,
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content
            
            # Simple JSON parse test just to ensure it's valid JSON
            json.loads(content)
            
            self.cache.put(cache_key, {"raw": content})
            return content
        except Exception as e:
            logger.error(f"route_image_text failed: {e}")
            return None

    async def analyze_image(
        self,
        image_base64: str,
        prompt: str,
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
    ) -> Optional[dict]:
        """
        Call VLM for image analysis. Returns raw response dict or None on failure.

        Sends base64 image with the VLM prompt via LiteLLM multimodal API.
        """
        model_name = model or self.config.models.vlm_model

        # ── Cache check ──
        media_hash = hashlib.sha256(image_base64[:1000].encode("utf-8")).hexdigest()
        prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        cache_key = self.cache.cache_key(model_name, prompt_hash, media_hash)

        cached = self.cache.get(cache_key)
        if cached:
            return cached

        # ── LiteLLM multimodal call ──
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append(
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}},
                ],
            }
        )

        try:
            response = await self._acompletion_with_retry(
                max_retries=self.vlm_max_retries,
                model=model_name,
                messages=messages,
            )
            content = response.choices[0].message.content
            result = {"raw": content}
            self.cache.put(cache_key, result)
            return result
        except Exception as e:
            logger.error(f"VLM image analysis failed: {e}")
            return None

    async def transcribe_audio(
        self,
        audio_bytes: bytes,
        model: Optional[str] = None,
    ) -> Optional[str]:
        """
        Call STT for audio transcription via LiteLLM.

        Note: LiteLLM's transcription support varies by provider.
        For OpenAI Whisper, uses litellm.atranscription().
        """
        model_name = model or self.config.models.stt_model

        # ── Cache check ──
        media_hash = hashlib.sha256(audio_bytes).hexdigest()
        cache_key = self.cache.cache_key(model_name, "stt", media_hash)

        cached = self.cache.get(cache_key)
        if cached and "text" in cached:
            return cached["text"]

        # STT audio with its own fail-fast retry logic
        backoff = 1
        last_error = None
        for attempt in range(self.stt_max_retries):
            try:
                # LiteLLM transcription API (fail-fast timeout)
                response = await litellm.atranscription(
                    model=model_name,
                    file=audio_bytes,
                    timeout=self.timeout,
                )
                text = response.text if hasattr(response, "text") else str(response)
                self.cache.put(cache_key, {"text": text})
                return text
            except Exception as e:
                last_error = e
                if attempt < self.stt_max_retries - 1:
                    logger.warning(f"STT call attempt {attempt + 1} failed: {e}. Retrying...")
                    await asyncio.sleep(backoff)
                    backoff *= 2

        logger.error(f"STT audio transcription failed: {last_error}")
        return None
