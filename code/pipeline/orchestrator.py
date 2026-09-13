from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from decision.engine import (
    FinalDecision, build_decision, decimal_text, earliest_full_payment_date,
    evaluate_candidates, fallback_decision, generate_candidates,
    rank_candidates, recover_with_spending_changes, simulate,
)
from evidence.gateway import LiteLLMGateway
from evidence.resolver import ResolutionResult, resolve_evidence
from finance.recurrence import detect_series
from finance.simulator import build_baseline_occurrences, calculate_capacity
from models.domain import CapacityResult, Dataset, FinancialEvent, Occurrence, Profile, Request
from validation.guardrails import validate_decision


@dataclass(frozen=True)
class RunSummary:
    processed: int
    successful: int
    fallback: int
    failed_request_ids: tuple[str, ...]
    model_records: tuple[dict[str, Any], ...]


def run_amount_safe_stage(
    dataset: Dataset,
    config: dict[str, Any],
    *,
    image_dir: Path,
    artifacts_dir: Path,
) -> list[CapacityResult]:
    """Backward-compatible API retained for capacity-stage callers and tests."""
    gateway = LiteLLMGateway(config["evidence"], artifacts_dir)
    runtime = config["runtime"]
    results: list[CapacityResult] = []
    for request in dataset.requests:
        profile = dataset.profiles[request.user_id]
        resolution = resolve_evidence(
            request,
            dataset.events_by_user.get(request.user_id, ()),
            dataset.messages_by_user.get(request.user_id, ()),
            dataset.images_by_user.get(request.user_id, ()),
            image_dir,
            gateway,
            config["evidence"]["failure_policy"],
        )
        if not resolution.valid:
            results.append(CapacityResult(
                request_id=request.request_id,
                home_currency=profile.home_currency,
                requested_amount=request.requested_amount,
                minimum_baseline_balance=None,
                baseline_headroom=None,
                amount_safe_to_pay=None,
                valid=False,
                evidence_status=resolution.status,
                warnings=resolution.warnings,
            ))
            continue
        results.append(calculate_capacity(
            request,
            profile,
            resolution.events,
            dataset.exchange_rates,
            horizon_days=int(runtime["forecast_horizon_days"]),
            lookback_days=int(runtime["variable_essential_lookback_days"]),
            bucket_days=int(runtime["variable_essential_bucket_days"]),
            evidence_status=resolution.status,
            inherited_warnings=resolution.warnings,
        ))
    return results


def _event_dict(event: FinancialEvent) -> dict[str, Any]:
    return {
        "event_id": event.event_id, "event_type": event.event_type,
        "description": event.description, "category": event.category,
        "direction": event.direction, "amount": decimal_text(event.amount),
        "currency": event.currency, "event_date": event.event_date.isoformat(),
        "settlement_date": event.settlement_date.isoformat() if event.settlement_date else None,
        "status": event.status, "linked_event_id": event.linked_event_id,
        "flexibility": event.flexibility,
        "minimum_allowed_amount": decimal_text(event.minimum_allowed_amount),
        "excluded": event.excluded, "evidence_sources": list(event.evidence_sources),
    }


def _occurrence_dict(occurrence: Occurrence) -> dict[str, Any]:
    return {
        "date": occurrence.date.isoformat(), "occurrence_id": occurrence.occurrence_id,
        "event_id": occurrence.event_id, "series_key": occurrence.series_key,
        "category": occurrence.category, "direction": occurrence.direction,
        "signed_amount": decimal_text(occurrence.signed_amount),
        "protected": occurrence.protected, "flexible": occurrence.flexible,
    }


def _candidate_dict(candidate: Any) -> dict[str, Any]:
    result = candidate.simulation
    return {
        "candidate_id": candidate.candidate_id, "candidate_type": candidate.method,
        "payment_method": candidate.method,
        "payments": [{"date": p.date.isoformat(), "amount": decimal_text(p.amount)} for p in candidate.payments],
        "total_payable": decimal_text(candidate.total_payable),
        "start_date": candidate.start_date.isoformat(),
        "completion_date": candidate.completion_date.isoformat(),
        "payment_option_id": candidate.payment_option_id,
        "spending_changes": [change.serialize() for change in candidate.spending_changes],
        "eligible": candidate.eligible, "completes_by_deadline": candidate.completes_by_deadline,
        "simulated_minimum_balance": decimal_text(result.minimum_balance) if result else None,
        "minimum_balance_date": result.minimum_date.isoformat() if result else None,
        "safe": result.safe if result else False,
        "rejection_reason": candidate.rejection_reason,
    }


def _write_debug_trace(
    path: Path,
    *,
    request: Request,
    profile: Profile,
    raw_events: tuple[FinancialEvent, ...],
    dataset: Dataset,
    resolution: ResolutionResult,
    occurrences: tuple[Occurrence, ...],
    capacity: CapacityResult | None,
    earliest_full: date | None,
    candidates: list[Any],
    winner: Any,
    decision: FinalDecision,
    warnings: list[str],
    error: str | None,
) -> None:
    resolved_map = {event.event_id: event for event in resolution.events}
    lifecycle = []
    for event in raw_events:
        resolved = resolved_map.get(event.event_id, event)
        included = not resolved.excluded and resolved.status not in {"failed", "cancelled", "unrealized"}
        lifecycle.append({
            "event_id": event.event_id, "included": included,
            "reason": "active" if included else ("evidence_excluded" if resolved.excluded else f"status_{resolved.status}"),
            "status": resolved.status,
            "settlement_date": resolved.settlement_date.isoformat() if resolved.settlement_date else None,
            "linked_event_id": resolved.linked_event_id,
        })
    series = detect_series(resolution.events, request.request_date) if resolution.valid else {}
    baseline_sim = simulate(occurrences, profile) if occurrences else None
    event_map = {event.event_id: event for event in resolution.events}
    fx_rows = []
    for occurrence in occurrences:
        event = event_map.get(occurrence.event_id)
        if event and event.currency != profile.home_currency:
            fx_rows.append({
                "event_id": event.event_id, "source_currency": event.currency,
                "target_currency": profile.home_currency, "date": occurrence.date.isoformat(),
                "rate": decimal_text(dataset.exchange_rates.get((occurrence.date, event.currency, profile.home_currency))),
                "converted_signed_amount": decimal_text(occurrence.signed_amount),
            })
    selected_messages = [
        asdict(message) for message in dataset.messages_by_user.get(request.user_id, ())
        if message.message_id in resolution.selected_message_ids
    ]
    selected_images = [
        asdict(image) for image in dataset.images_by_user.get(request.user_id, ())
        if image.image_id in resolution.selected_image_ids
    ]
    trace = {
        "request_id": request.request_id, "user_id": request.user_id,
        "request_date": request.request_date.isoformat(),
        "request": {**asdict(request), "requested_amount": decimal_text(request.requested_amount)},
        "opening_current_available_balance": decimal_text(profile.current_available_balance),
        "minimum_balance_to_keep": decimal_text(profile.minimum_balance_to_keep),
        "requested_amount": decimal_text(request.requested_amount),
        "selected_raw_events": [_event_dict(event) for event in raw_events],
        "selected_messages": selected_messages, "selected_images": selected_images,
        "evidence_sent_to_model": {"message_ids": list(resolution.selected_message_ids), "image_ids": list(resolution.selected_image_ids)},
        "evidence_resolution_result": {"status": resolution.status, "valid": resolution.valid, "facts": list(resolution.facts)},
        "evidence_validation_errors": list(resolution.validation_errors),
        "canonical_financial_events": [_event_dict(event) for event in resolution.events],
        "event_lifecycle_classification": lifecycle,
        "detected_recurring_series": [
            {"series_key": key, "supporting_event_ids": list(item.support_event_ids),
             "cadence": item.frequency, "projected_amount": decimal_text(item.latest_event.amount)}
            for key, item in sorted(series.items())
        ],
        "explicit_and_generated_future_occurrences": [_occurrence_dict(item) for item in occurrences if not item.occurrence_id.startswith("reserve:")],
        "protected_variable_reserve": [_occurrence_dict(item) for item in occurrences if item.occurrence_id.startswith("reserve:")],
        "fx_conversions": fx_rows,
        "chronological_90_day_ledger": list(baseline_sim.ledger) if baseline_sim else [],
        "minimum_projected_balance": decimal_text(capacity.minimum_baseline_balance) if capacity else None,
        "minimum_balance_date": baseline_sim.minimum_date.isoformat() if baseline_sim else None,
        "baseline_headroom": decimal_text(capacity.baseline_headroom) if capacity else None,
        "amount_safe_to_pay": decimal_text(decision.amount_safe_to_pay),
        "earliest_date_for_full_payment": earliest_full.isoformat() if earliest_full else None,
        "candidates_generated": [_candidate_dict(candidate) for candidate in candidates],
        "winning_candidate": _candidate_dict(winner) if winner else None,
        "final_structured_output": {
            "request_id": decision.request_id, "amount_safe_to_pay": decimal_text(decision.amount_safe_to_pay),
            "affordability_status": decision.affordability_status,
            "recommended_payment_method": decision.recommended_payment_method,
            "payment_plan": decision.payment_plan,
            "earliest_date_for_full_payment": earliest_full.isoformat() if earliest_full else "",
            "spending_changes_needed": decision.spending_changes_needed,
            "decision_explanation": decision.decision_explanation,
        },
        "warnings": warnings, "error": error,
        "debug_mode_affects_decision_logic": False,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(trace, indent=2, default=str, ensure_ascii=False), encoding="utf-8")


def run_pipeline(
    dataset: Dataset,
    config: dict[str, Any],
    *,
    image_dir: Path,
    artifacts_dir: Path,
    debug_dir: Path | None = None,
) -> tuple[list[FinalDecision], RunSummary]:
    gateway = LiteLLMGateway(config["evidence"], artifacts_dir)
    runtime = config["runtime"]
    horizon_days = int(runtime["forecast_horizon_days"])
    decisions: list[FinalDecision] = []
    failures: list[str] = []
    total = len(dataset.requests)
    for index, request in enumerate(dataset.requests, 1):
        if index % 25 == 0 or index == total or index == 1:
            print(f"[{index}/{total}] Processing {request.request_id}...", flush=True)
        profile = dataset.profiles[request.user_id]
        raw_events = dataset.events_by_user.get(request.user_id, ())
        resolution = ResolutionResult(raw_events, False, "not_started", ())
        occurrences: tuple[Occurrence, ...] = ()
        capacity: CapacityResult | None = None
        earliest_full: date | None = None
        candidates: list[Any] = []
        winner = None
        warnings: list[str] = []
        error: str | None = None
        try:
            resolution = resolve_evidence(
                request, raw_events,
                dataset.messages_by_user.get(request.user_id, ()),
                dataset.images_by_user.get(request.user_id, ()),
                image_dir, gateway, config["evidence"]["failure_policy"],
            )
            warnings.extend(resolution.warnings)
            if not resolution.valid:
                raise ValueError("required evidence could not be resolved")
            capacity = calculate_capacity(
                request, profile, resolution.events, dataset.exchange_rates,
                horizon_days=horizon_days,
                lookback_days=int(runtime["variable_essential_lookback_days"]),
                bucket_days=int(runtime["variable_essential_bucket_days"]),
                evidence_status=resolution.status,
                inherited_warnings=resolution.warnings,
            )
            if not capacity.valid or capacity.amount_safe_to_pay is None:
                raise ValueError("; ".join(capacity.warnings) or "baseline forecast failed")
            occurrences = tuple(build_baseline_occurrences(
                request, profile, list(resolution.events), dataset.exchange_rates,
                horizon_days=horizon_days,
                lookback_days=int(runtime["variable_essential_lookback_days"]),
                bucket_days=int(runtime["variable_essential_bucket_days"]),
            ))
            earliest_full = earliest_full_payment_date(request, profile, occurrences, horizon_days)
            generated = generate_candidates(
                request, profile, dataset.payment_options_by_request.get(request.request_id, ()),
                capacity.amount_safe_to_pay, earliest_full,
                request.request_date + timedelta(days=horizon_days),
            )
            candidates = evaluate_candidates(generated, occurrences, profile)
            ranked = rank_candidates(candidates)
            if not ranked:
                candidates.extend(recover_with_spending_changes(
                    candidates, request, profile, resolution.events, occurrences
                ))
                ranked = rank_candidates(candidates)
            winner = ranked[0] if ranked else None
            decision = build_decision(
                request, capacity.amount_safe_to_pay, earliest_full, winner,
                profile.minimum_balance_to_keep, profile.home_currency,
            )
            validate_decision(
                decision, request, profile,
                dataset.payment_options_by_request.get(request.request_id, ()),
                resolution.events, capacity.amount_safe_to_pay,
            )
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            warnings.append(error)
            failures.append(request.request_id)
            decision = fallback_decision(request)
            validate_decision(
                decision, request, profile,
                dataset.payment_options_by_request.get(request.request_id, ()),
                resolution.events, Decimal("0"),
            )
        decisions.append(decision)
        if debug_dir is not None:
            _write_debug_trace(
                debug_dir / f"{request.request_id}.json", request=request, profile=profile,
                raw_events=raw_events, dataset=dataset, resolution=resolution,
                occurrences=occurrences, capacity=capacity, earliest_full=earliest_full,
                candidates=candidates, winner=winner, decision=decision,
                warnings=warnings, error=error,
            )
    return decisions, RunSummary(
        processed=len(decisions), successful=len(decisions) - len(failures),
        fallback=len(failures), failed_request_ids=tuple(failures),
        model_records=tuple(gateway.records),
    )
