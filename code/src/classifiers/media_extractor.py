"""
media.py — Async media extraction with Pillow preprocessing and VLM/STT API calls.

Handles image OCR via VLM and voice note transcription via STT.
On ANY exception: returns MediaExtraction(media_status='extraction_failed').
Never crashes the batch.
"""

import base64
import io
import logging
import os
from pathlib import Path
from .schema_models import MediaExtraction
from .prompt_loader import build_vlm_prompt, build_img_router_prompt, clean_stt_transcription

logger = logging.getLogger(__name__)

try:
    from PIL import Image
    HAS_PILLOW = True
except ImportError:
    HAS_PILLOW = False
    logger.warning("Pillow not installed. Image preprocessing will be skipped; raw bytes sent to VLM.")


async def extract_image(message: dict, images_index: dict, config, llm_adapter) -> MediaExtraction:
    """
    Extract text/content from an image via VLM.

    Steps:
      1. Look up file_path from images.csv index
      2. Open with Pillow, resize if long edge > config.media.image_long_edge_px
      3. Encode to base64
      4. Call VLM for OCR/content analysis (up to max_retries attempts)
      5. Return MediaExtraction with transcribed_text from VLM

    On ANY exception: returns MediaExtraction(media_status='extraction_failed')
    """
    if not HAS_PILLOW:
        return MediaExtraction(transcribed_text="", media_status="extraction_failed", media_type="image")

    try:
        image_id = message.get("media_id", "")
        if image_id not in images_index:
            logger.warning(f"Image {image_id} not found in images index")
            return MediaExtraction(transcribed_text="", media_status="file_missing", media_type="image")

        file_info = images_index[image_id]
        # images_index stores dict rows from images.csv
        relative_path = file_info.get("file_path", "") if isinstance(file_info, dict) else str(file_info)

        # Resolve relative to dataset dir
        dataset_dir = config.paths.dataset_dir
        full_path = os.path.join(dataset_dir, relative_path)
        if not os.path.exists(full_path):
            logger.warning(f"Image file not found: {full_path}")
            return MediaExtraction(transcribed_text="", media_status="file_missing", media_type="image")

        # ── Pillow preprocessing: resize if oversized ──
        with Image.open(full_path) as img:
            max_edge = config.media.image_long_edge_px
            if max(img.size) > max_edge:
                img.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
                logger.info(f"Resized {image_id} to {img.size}")

            # Convert to RGB if necessary (handles RGBA, P mode, etc.)
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")

            buffer = io.BytesIO()
            img.save(buffer, format="JPEG", quality=95)
            img_b64 = base64.b64encode(buffer.getvalue()).decode("utf-8")

        # ── Call VLM for OCR/content analysis ──
        sender_type = message.get("sender_type", "unknown")
        conversation_type = message.get("conversation_type", "unknown")
        
        system_prompt, user_prompt = build_vlm_prompt(sender_type, conversation_type)
        logger.info(f"Sending image {image_id} to VLM model ({config.models.vlm_model})...")
        vlm_result = await llm_adapter.analyze_image(
            image_base64=img_b64,
            prompt=user_prompt,
            system_prompt=system_prompt,
            model=config.models.vlm_model,
        )

        vlm_json = vlm_result["raw"] if vlm_result and "raw" in vlm_result else ""
        if not vlm_json:
            logger.warning(f"VLM returned no content for {image_id}")
            return MediaExtraction(transcribed_text="", media_status="extraction_failed", media_type="image")

        # ── Call Image Router (LLM) ──
        sender_verified = str(message.get("sender_verified", False))
        forwarded_count = message.get("forwarded_count", 0)
        img_sys_prompt, img_user_prompt = build_img_router_prompt(
            sender_type, conversation_type, sender_verified, forwarded_count, vlm_json
        )
        
        img_router_result = await llm_adapter.route_image_text(
            system_prompt=img_sys_prompt,
            user_prompt=img_user_prompt,
            model=config.models.llm_model,
        )
        
        router_json = img_router_result if img_router_result else "{}"
        
        combined_text = (
            "--- VLM Observer ---\n"
            f"{vlm_json}\n\n"
            "--- Image Router ---\n"
            f"{router_json}"
        )

        return MediaExtraction(
            transcribed_text=combined_text,
            media_status="success",
            media_type="image",
        )

    except Exception as e:
        logger.error(f"Failed to extract image {message.get('media_id', 'unknown')}: {e}")
        return MediaExtraction(transcribed_text="", media_status="extraction_failed", media_type="image")


async def extract_audio(voice_note_id: str, voice_notes_index: dict, config, llm_adapter) -> MediaExtraction:
    """
    Transcribe a voice note via STT.

    Steps:
      1. Look up file_path from voice_notes.csv index
      2. Read .mp3 bytes
      3. Call STT API via LLMAdapter (up to max_retries attempts)
      4. Return MediaExtraction with transcribed_text

    On ANY exception: returns MediaExtraction(media_status='extraction_failed')
    """
    try:
        if voice_note_id not in voice_notes_index:
            logger.warning(f"Voice note {voice_note_id} not found in voice_notes index")
            return MediaExtraction(transcribed_text="", media_status="file_missing", media_type="voice")

        file_info = voice_notes_index[voice_note_id]
        relative_path = file_info.get("file_path", "") if isinstance(file_info, dict) else str(file_info)

        dataset_dir = config.paths.dataset_dir
        full_path = os.path.join(dataset_dir, relative_path)
        if not os.path.exists(full_path):
            logger.warning(f"Audio file not found: {full_path}")
            return MediaExtraction(transcribed_text="", media_status="file_missing", media_type="voice")

        # ── Read audio bytes ──
        with open(full_path, "rb") as f:
            audio_bytes = f.read()

        if not audio_bytes:
            return MediaExtraction(transcribed_text="", media_status="extraction_failed", media_type="voice")

        # ── Call STT for transcription ──
        logger.info(f"Sending voice note {voice_note_id} to STT model ({config.models.stt_model})...")
        transcribed = await llm_adapter.transcribe_audio(
            audio_bytes=audio_bytes,
            model=config.models.stt_model,
        )

        if transcribed:
            # Post-process: normalize common STT artifacts
            transcribed = clean_stt_transcription(transcribed)

        return MediaExtraction(
            transcribed_text=transcribed or "",
            media_status="success" if transcribed else "extraction_failed",
            media_type="voice",
        )

    except Exception as e:
        logger.error(f"Failed to extract audio {voice_note_id}: {e}")
        return MediaExtraction(transcribed_text="", media_status="extraction_failed", media_type="voice")
