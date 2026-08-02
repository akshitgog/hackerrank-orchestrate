#!/usr/bin/env python3
"""
main.py — CLI entry point for the HackerRank Orchestrate Message Notification Router.

Pipeline: Load Config -> Load Dataset -> For each of 110 messages (asyncio):
  1. Pre-fetch context (pure Python, zero network)
  2. Extract media if present (STT/VLM, async with retry)
  3. Build prompt with context + media transcription
  4. Call LLM for semantic labels (async with cache)
  5. Run deterministic decision tree (pure Python)
  6. Calibrate confidence (pure Python)
  7. On ANY exception: emit Universal Safe-Default Row
-> Sort by row_index -> Validate -> Write output.csv
"""

import asyncio
import csv
import os
import sys
import logging
from pathlib import Path

# Resolve project root so imports work from any CWD
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from config.settings import load_config
from context.load_dataset import load_all_data, DatasetContext
from context.message_history import get_sender_history, get_business_history, get_group_history, get_sender_events
from context.user_profiles import get_user_profile, is_in_dnd, get_group_membership, get_business_relationship, get_notification_fatigue, get_source_engagement
from classifiers.response_cache import ResponseCache
from classifiers.llm_client import LLMAdapter
from classifiers.schema_models import SensorObservation, MediaExtraction
from classifiers.media_extractor import extract_image, extract_audio
from classifiers.prompt_loader import build_msg_observer_prompt, build_msg_router_prompt
from routing_engine.decision_tree import route_message, RoutingDecision
from routing_engine.confidence_calibrator import calibrate_confidence
from routing_engine.safe_fallback import get_safe_default_row
from output_validator.validate_output_csv import validate_output

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


async def process_single_message(
    row_index: int,
    message: dict,
    ctx: DatasetContext,
    llm_adapter: LLMAdapter,
    config,
) -> dict:
    """Process a single message through the full pipeline. Never raises — always returns a valid row."""
    message_id = message.get("message_id", f"unknown_{row_index}")

    try:
        user_id = message.get("user_id", "")
        group_id = message.get("group_id", "")
        business_id = message.get("business_id", "")
        sender_user_id = message.get("sender_user_id", "")
        media_type = message.get("media_type", "")
        media_id = message.get("media_id", "")

        # ── Step 1: Pre-fetch context (pure Python, zero network) ──
        user_profile = get_user_profile(ctx, user_id)
        group_membership = get_group_membership(ctx, user_id, group_id) if group_id else None
        business_rel = get_business_relationship(ctx, user_id, business_id) if business_id else None
        dnd_active = is_in_dnd(user_profile, message.get("created_at", ""))

        # Build history context for LLM prompt
        history_context = []
        if sender_user_id:
            history_context.extend(get_sender_history(ctx, user_id, sender_user_id, limit=3))
        if business_id:
            history_context.extend(get_business_history(ctx, user_id, business_id, limit=3))
        if group_id:
            history_context.extend(get_group_history(ctx, user_id, group_id, limit=3))
        # Deduplicate by message_id
        seen_ids = set()
        unique_history = []
        for h in history_context:
            hid = h.get("message_id", "")
            if hid not in seen_ids:
                seen_ids.add(hid)
                unique_history.append(h)
        history_context = unique_history[:5]
        
        # Build interaction history
        fatigue_score = get_notification_fatigue(ctx, user_id)
        sender_events = get_sender_events(ctx, user_id, sender_user_id) if sender_user_id else {}
        engagement = get_source_engagement(ctx, user_id, sender_user_id, group_id, business_id)
        interaction_history = {
            "global_fatigue_score": fatigue_score,
            "sender_dismiss_rate": sender_events.get("dismiss_rate", 0.0),
            "sender_reply_rate": sender_events.get("reply_rate", 0.0),
            "sender_open_rate": sender_events.get("open_rate", 1.0),
            "sender_sent_count": sender_events.get("sent", 0),
            "business_allows_promotions": business_rel.get("allows_promotions", "1") if business_rel else "1",
        }

        # ── Step 2: Extract media if present (async with retry) ──
        media_extraction = None
        media_text = ""
        media_ok = True

        if media_type == "image" and media_id:
            media_extraction = await extract_image(message, ctx.images, config, llm_adapter)
            if media_extraction.media_status != "success":
                media_ok = False
            else:
                media_text = media_extraction.transcribed_text
        elif media_type == "voice" and media_id:
            media_extraction = await extract_audio(media_id, ctx.voice_notes, config, llm_adapter)
            if media_extraction.media_status != "success":
                media_ok = False
            else:
                media_text = media_extraction.transcribed_text

        # ── Step 3: Build prompt with context + media transcription ──
        # Combine message_text with any media transcription
        message_text = message.get("message_text", "") or ""
        if media_text:
            combined_text = f"{message_text}\n\n[Extracted media content]: {media_text}" if message_text else media_text
        else:
            combined_text = message_text

        # Create an enriched message dict for the prompt builder
        enriched_message = {**message, "message_text": combined_text}

        group_info = None
        if group_id:
            group_info = ctx.groups.get(group_id)

        business_info = None
        if business_id:
            business_info = ctx.business_accounts.get(business_id)

        system_prompt, user_prompt = build_msg_observer_prompt(
            message=enriched_message,
            user_profile=user_profile,
            group_info=group_info,
        )

        # ── Step 4a: Call LLM for signal extraction (async with cache) ──
        signal_json = await llm_adapter.extract_message_signals(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=config.models.llm_model,
        )
        
        # ── Step 4b: Call LLM for intent routing (async with cache) ──
        router_sys_prompt, router_user_prompt = build_msg_router_prompt(
            message=enriched_message,
            history_context=history_context,
            interaction_history=interaction_history,
            msg_observer_output_json=signal_json,
        )
        
        sensor_obs = await llm_adapter.classify_message(
            system_prompt=router_sys_prompt,
            user_prompt=router_user_prompt,
            model=config.models.llm_model,
        )

        # Convert SensorObservation to dict for the router (deterministic layer boundary)
        sensor_dict = None
        if sensor_obs is not None:
            sensor_dict = sensor_obs.model_dump()

        # ── Step 5: Run deterministic decision tree (pure Python) ──
        # Build the profile dict the router expects
        router_user_profile = {
            **user_profile,
            "dnd_active": "1" if dnd_active else "0",
            **interaction_history,
            **engagement,
        }
        # Merge business opt-out info into profile for Gate 2
        router_business = None
        if business_id:
            router_business = {}
            if business_info:
                router_business.update(business_info)
            if business_rel:
                router_business.update(business_rel)
            router_user_profile["allows_promotions"] = router_business.get("allows_promotions", "1")

        router_group = None
        if group_id:
            sender_membership = get_group_membership(ctx, sender_user_id, group_id) if sender_user_id else None
            is_sender_admin = "1" if (sender_membership and sender_membership.get("role") == "admin") else "0"
            
            router_group = {
                "is_admin": "1" if (group_membership and group_membership.get("role") == "admin") else "0",
                "is_sender_admin": is_sender_admin,
                "is_muted": group_membership.get("group_muted_by_user", "0") if group_membership else "0",
            }

        decision = route_message(
            sensor_obs=sensor_dict,
            user_profile=router_user_profile,
            group_membership=router_group,
            business_relationship=router_business,
            message=message,
            config=config,
        )

        # ── Step 6: Calibrate confidence (pure Python) ──
        gate_name = _determine_gate_name(decision)
        calibrated_conf = calibrate_confidence(decision, gate_name, media_ok, config)
        decision.confidence = calibrated_conf

        # ── Step 7: Format evidence IDs ──
        evidence_ids = "none"
        if sensor_obs and sensor_obs.best_evidence_ids:
            # Validate evidence IDs against message_history
            valid_ids = []
            for eid in sensor_obs.best_evidence_ids:
                if eid != "none" and eid in ctx.message_history:
                    valid_ids.append(eid)
            evidence_ids = ";".join(valid_ids) if valid_ids else "none"
        decision.evidence_message_ids = evidence_ids

        return _format_output_row(row_index, message_id, decision)

    except Exception as e:
        logger.error(f"Row {row_index} ({message_id}) failed: {e}")
        default_dec = get_safe_default_row(message_id, config)
        return _format_output_row(row_index, message_id, default_dec)


def _determine_gate_name(decision: RoutingDecision) -> str:
    """Map a routing decision to its config confidence gate name."""
    if decision.message_type == "scam":
        return "gate_scam"
    elif decision.message_type == "promotion" and decision.action == "mute":
        return "gate_promo_optout"
    elif decision.message_type == "urgent" and decision.action == "notify":
        return "gate_emergency"
    elif decision.action == "notify":
        return "gate_actionable"
    elif "low engagement" in decision.reason:
        return "gate_low_engagement"
    elif decision.action == "digest":
        return "gate_dnd_digest"
    return "default"


def _format_output_row(row_index: int, message_id: str, decision: RoutingDecision) -> dict:
    """Format a RoutingDecision into the output CSV row dict."""
    return {
        "row_index": row_index,
        "message_id": message_id,
        "action": decision.action,
        "message_type": decision.message_type,
        "reason": decision.reason,
        "confidence": f"{decision.confidence:.2f}",
        "evidence_message_ids": decision.evidence_message_ids,
    }


async def run_pipeline(config_path: str | None = None) -> None:
    """Main batch pipeline: load -> process 110 messages -> validate -> write output.csv."""
    if config_path is None or config_path in ("--help", "-h"):
        if config_path in ("--help", "-h"):
            print("Usage: python code/main.py [path/to/config.yaml]")
            return
        config_path = str(PROJECT_ROOT / "code" / "config" / "config.yaml")
    config = load_config(config_path)
    logger.info(f"Config loaded. LLM={config.models.llm_model}, VLM={config.models.vlm_model}")

    # ── 2. Load dataset (DatasetContext) ──
    dataset_dir = str(PROJECT_ROOT / config.paths.dataset_dir)
    ctx = load_all_data(dataset_dir, config.paths.messages_file)
    logger.info(f"Dataset loaded: {len(ctx.messages)} messages, {len(ctx.users)} users, {len(ctx.message_history)} history rows")

    # ── 3. Initialize LLM adapter with cache ──
    cache_dir = str(PROJECT_ROOT / config.paths.cache_dir)
    cache = ResponseCache(cache_dir)
    llm_adapter = LLMAdapter(config, cache)

    # ── 4. Process all 110 messages concurrently ──
    sem = asyncio.Semaphore(config.execution.max_concurrency)

    async def bound_process(idx: int, msg: dict) -> dict:
        async with sem:
            return await process_single_message(idx, msg, ctx, llm_adapter, config)

    tasks = [bound_process(i, msg) for i, msg in enumerate(ctx.messages)]
    results = await asyncio.gather(*tasks)

    # ── 5. Sort results by original row_index (deterministic ordering) ──
    results = sorted(results, key=lambda x: x["row_index"])

    # Remove row_index from output
    output_rows = []
    for r in results:
        row = {k: v for k, v in r.items() if k != "row_index"}
        output_rows.append(row)

    # ── 6. Validate output ──
    expected_ids = [m["message_id"] for m in ctx.messages]
    history_ids = set(ctx.message_history.keys())
    errors = validate_output(output_rows, expected_ids, history_ids)
    if errors:
        logger.warning(f"Validation found {len(errors)} issue(s):")
        for err in errors:
            logger.warning(f"  - {err}")

    # ── 7. Write output.csv ──
    output_path = str(PROJECT_ROOT / config.paths.output_file)
    fieldnames = ["message_id", "action", "message_type", "reason", "confidence", "evidence_message_ids"]
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(output_rows)

    logger.info(f"Pipeline completed. Wrote {len(output_rows)} rows to {output_path}")


if __name__ == "__main__":
    config_path = sys.argv[1] if len(sys.argv) > 1 else None
    asyncio.run(run_pipeline(config_path))
