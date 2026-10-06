from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from typing import Iterable

from finance.recurrence import (
    RecurringSeries, detect_category_series, detect_series, next_date, series_key,
)
from models.domain import CapacityResult, FinancialEvent, Occurrence, Profile, Request


class ForecastError(ValueError):
    pass


def convert_amount(
    amount: Decimal,
    currency: str,
    home_currency: str,
    settlement_date: date,
    rates: dict[tuple[date, str, str], Decimal],
) -> Decimal:
    if currency == home_currency:
        return amount
    key = (settlement_date, currency, home_currency)
    if key not in rates:
        raise ForecastError(
            f"missing exact FX rate for {settlement_date} {currency}->{home_currency}"
        )
    return amount * rates[key]


def calculate_capacity(
    request: Request,
    profile: Profile,
    events: Iterable[FinancialEvent],
    rates: dict[tuple[date, str, str], Decimal],
    *,
    horizon_days: int,
    lookback_days: int,
    bucket_days: int,
    evidence_status: str,
    inherited_warnings: tuple[str, ...] = (),
) -> CapacityResult:
    event_list = list(events)
    try:
        occurrences = build_baseline_occurrences(
            request,
            profile,
            event_list,
            rates,
            horizon_days=horizon_days,
            lookback_days=lookback_days,
            bucket_days=bucket_days,
        )
        balance = profile.current_available_balance
        minimum_balance = balance
        for occurrence in sorted(occurrences, key=_occurrence_sort_key):
            balance += occurrence.signed_amount
            minimum_balance = min(minimum_balance, balance)
        headroom = minimum_balance - profile.minimum_balance_to_keep
        safe = min(request.requested_amount, max(Decimal("0"), headroom))
        return CapacityResult(
            request_id=request.request_id,
            home_currency=profile.home_currency,
            requested_amount=request.requested_amount,
            minimum_baseline_balance=minimum_balance,
            baseline_headroom=headroom,
            amount_safe_to_pay=safe,
            valid=True,
            evidence_status=evidence_status,
            warnings=inherited_warnings,
        )
    except ForecastError as exc:
        return CapacityResult(
            request_id=request.request_id,
            home_currency=profile.home_currency,
            requested_amount=request.requested_amount,
            minimum_baseline_balance=None,
            baseline_headroom=None,
            amount_safe_to_pay=None,
            valid=False,
            evidence_status=evidence_status,
            warnings=inherited_warnings + (str(exc),),
        )


def build_baseline_occurrences(
    request: Request,
    profile: Profile,
    events: list[FinancialEvent],
    rates: dict[tuple[date, str, str], Decimal],
    *,
    horizon_days: int,
    lookback_days: int,
    bucket_days: int,
) -> list[Occurrence]:
    forecast_end = request.request_date + timedelta(days=horizon_days)
    active = [
        event for event in events
        if not event.excluded
        and event.status not in {"failed", "cancelled", "unrealized"}
        and event.direction in {"credit", "debit"}
        and event.event_type != "investment_valuation"
    ]
    series = detect_series(active, request.request_date)
    _add_confirmed_salary_continuations(series, active, request.request_date)
    supplied_future: set[tuple[str, date]] = set()
    supplied_signatures: set[tuple[str, str, str, Decimal, date]] = set()
    result: list[Occurrence] = []

    for event in active:
        settlement = event.settlement_date
        if event.status == "pending" and event.direction == "debit":
            settlement = max(request.request_date, settlement or request.request_date)
        if settlement is None:
            if event.status == "scheduled":
                raise ForecastError(f"scheduled event has no settlement date: {event.event_id}")
            continue
        if settlement < request.request_date or settlement > forecast_end:
            continue
        if event.status == "settled":
            if settlement > request.request_date:
                raise ForecastError(f"future settled event leaks snapshot state: {event.event_id}")
            continue
        if event.direction == "credit" and event.status != "scheduled":
            continue
        if event.direction == "debit" and event.status not in {"pending", "scheduled"}:
            continue
        if event.amount is None:
            raise ForecastError(f"required future event amount unresolved: {event.event_id}")
        key = series_key(event)
        supplied_future.add((key, settlement))
        supplied_signatures.add((event.category, event.direction, event.currency, event.amount, settlement))
        result.append(_occurrence_from_event(event, settlement, profile, rates, key))

    emitted_signatures: set[tuple[str, str, str, Decimal, date]] = set(supplied_signatures)
    for key, recurring in sorted(series.items()):
        event = recurring.latest_event
        if event.amount is None or event.settlement_date is None:
            continue
        generated_date = event.settlement_date
        while generated_date <= request.request_date:
            generated_date = next_date(generated_date, recurring.frequency, recurring.anchor_day)
        while generated_date <= forecast_end:
            if event.recurrence_end_date and generated_date > event.recurrence_end_date:
                break
            signature = (event.category, event.direction, event.currency, event.amount, generated_date)
            if (key, generated_date) not in supplied_future and signature not in emitted_signatures:
                result.append(_occurrence_from_event(event, generated_date, profile, rates, key))
                emitted_signatures.add(signature)
            generated_date = next_date(generated_date, recurring.frequency, recurring.anchor_day)

    result.extend(_variable_essential_reserves(
        request,
        profile,
        active,
        rates,
        series,
        result,
        lookback_days=lookback_days,
        bucket_days=bucket_days,
        forecast_end=forecast_end,
    ))
    return result


def _add_confirmed_salary_continuations(
    series: dict[str, RecurringSeries],
    events: list[FinancialEvent],
    request_date: date,
) -> None:
    existing_salary_anchors: dict[tuple[str, int], str] = {}
    for key, s in series.items():
        if s.latest_event.direction == "credit" and s.latest_event.category == "salary":
            existing_salary_anchors[(s.latest_event.currency, s.anchor_day)] = key

    historical_salaries = [
        event for event in events
        if event.status == "settled"
        and event.direction == "credit"
        and event.category == "salary"
        and event.amount is not None
        and event.settlement_date is not None
        and event.settlement_date <= request_date
    ]
    for scheduled in events:
        if (
            scheduled.status != "scheduled"
            or scheduled.direction != "credit"
            or scheduled.category != "salary"
            or scheduled.amount is None
            or scheduled.settlement_date is None
            or scheduled.settlement_date < request_date
        ):
            continue
        if scheduled.event_id.startswith("derived:") and not scheduled.recurrence_frequency:
            has_settled_salary = any(
                e.currency == scheduled.currency for e in historical_salaries
            )
            if has_settled_salary:
                continue
        anchor = (scheduled.currency, scheduled.settlement_date.day)
        if anchor in existing_salary_anchors:
            continue
        matching_history = [
            event for event in historical_salaries
            if event.currency == scheduled.currency
        ]
        if not matching_history:
            continue
        key = series_key(scheduled)
        if key in series:
            continue
        series[key] = RecurringSeries(
            key=key,
            support_event_ids=(matching_history[-1].event_id, scheduled.event_id),
            frequency="monthly",
            anchor_day=scheduled.settlement_date.day,
            latest_event=scheduled,
        )
        existing_salary_anchors[anchor] = key


def _occurrence_from_event(
    event: FinancialEvent,
    occurrence_date: date,
    profile: Profile,
    rates: dict[tuple[date, str, str], Decimal],
    key: str,
) -> Occurrence:
    amount = convert_amount(event.amount, event.currency, profile.home_currency, occurrence_date, rates)
    signed = amount if event.direction == "credit" else -amount
    return Occurrence(
        occurrence_id=f"{event.event_id}@{occurrence_date.isoformat()}",
        event_id=event.event_id,
        date=occurrence_date,
        signed_amount=signed,
        category=event.category,
        direction=event.direction,
        protected=event.category in profile.protected_categories,
        flexible=event.flexibility != "fixed",
        series_key=key,
    )


def _variable_essential_reserves(
    request: Request,
    profile: Profile,
    events: list[FinancialEvent],
    rates: dict[tuple[date, str, str], Decimal],
    recurring: dict[str, RecurringSeries],
    future_occurrences: list[Occurrence],
    *,
    lookback_days: int,
    bucket_days: int,
    forecast_end: date,
) -> list[Occurrence]:
    cat_series = detect_category_series(
        events, request.request_date, profile.protected_categories, recurring,
    )
    cat_series_categories = {cs.latest_event.category for cs in cat_series.values()}

    all_recurrent_support = {
        event_id for item in recurring.values() for event_id in item.support_event_ids
    }

    bucket_count = lookback_days // bucket_days
    category_buckets: defaultdict[str, list[Decimal]] = defaultdict(
        lambda: [Decimal("0") for _ in range(bucket_count)]
    )
    lookback_start = request.request_date - timedelta(days=lookback_days)
    for event in events:
        if (
            event.status != "settled"
            or event.direction != "debit"
            or event.category not in profile.protected_categories
            or event.event_id in all_recurrent_support
            or event.amount is None
            or event.settlement_date is None
            or not (lookback_start <= event.settlement_date < request.request_date)
        ):
            continue
        age = (request.request_date - event.settlement_date).days
        index = min(bucket_count - 1, (age - 1) // bucket_days)
        category_buckets[event.category][index] += convert_amount(
            event.amount,
            event.currency,
            profile.home_currency,
            event.settlement_date,
            rates,
        )

    known_by_category_bucket: defaultdict[tuple[str, int], Decimal] = defaultdict(lambda: Decimal("0"))
    for occurrence in future_occurrences:
        if occurrence.direction != "debit" or occurrence.category not in profile.protected_categories:
            continue
        index = (occurrence.date - request.request_date - timedelta(days=1)).days // bucket_days
        if 0 <= index < bucket_count and occurrence.series_key not in recurring:
            known_by_category_bucket[(occurrence.category, index)] += -occurrence.signed_amount

    result: list[Occurrence] = []
    for category, totals in category_buckets.items():
        if category in cat_series_categories:
            monthly_reserve = totals[0]
        else:
            monthly_reserve = max(totals)
        for index in range(bucket_count):
            reserve_date = request.request_date + timedelta(days=1 + index * bucket_days)
            if reserve_date > forecast_end:
                continue
            amount = max(
                Decimal("0"),
                monthly_reserve - known_by_category_bucket[(category, index)],
            )
            if amount == 0:
                continue
            result.append(Occurrence(
                occurrence_id=f"reserve:{category}:{index}",
                event_id=f"reserve:{category}",
                date=reserve_date,
                signed_amount=-amount,
                category=category,
                direction="debit",
                protected=True,
                flexible=False,
                series_key=None,
            ))
    return result


def _occurrence_sort_key(item: Occurrence) -> tuple[date, int, str]:
    if item.direction == "credit":
        priority = 0
    elif item.protected or not item.flexible:
        priority = 1
    else:
        priority = 2
    return item.date, priority, item.occurrence_id
