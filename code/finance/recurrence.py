from __future__ import annotations

import calendar
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable

from models.domain import FinancialEvent


@dataclass(frozen=True)
class RecurringSeries:
    key: str
    support_event_ids: tuple[str, ...]
    frequency: str
    anchor_day: int
    latest_event: FinancialEvent


def normalize_description(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", value.casefold())).strip()


def series_key(event: FinancialEvent) -> str:
    return "|".join((
        normalize_description(event.description),
        event.event_type,
        event.category,
        event.direction,
        event.currency,
        event.flexibility,
    ))


def detect_series(events: Iterable[FinancialEvent], request_date: date) -> dict[str, RecurringSeries]:
    grouped: defaultdict[str, list[FinancialEvent]] = defaultdict(list)
    explicit: dict[str, RecurringSeries] = {}
    for event in events:
        if event.excluded or event.amount is None or event.settlement_date is None:
            continue
        key = series_key(event)
        if event.recurrence_frequency:
            explicit[key] = RecurringSeries(
                key=key,
                support_event_ids=(event.event_id,),
                frequency=event.recurrence_frequency,
                anchor_day=event.settlement_date.day,
                latest_event=event,
            )
        if event.status == "settled" and event.settlement_date <= request_date:
            grouped[key].append(event)

    result = dict(explicit)
    for key, rows in grouped.items():
        rows.sort(key=lambda item: (item.settlement_date, item.event_id))
        dates = [item.settlement_date for item in rows]
        frequency, run_length = _latest_pattern(dates)
        if frequency is None:
            continue
        support = rows[-run_length:]
        expected_next = next_date(
            support[-1].settlement_date,
            frequency,
            support[-1].settlement_date.day,
        )
        if expected_next < request_date:
            continue
        result[key] = RecurringSeries(
            key=key,
            support_event_ids=tuple(item.event_id for item in support),
            frequency=frequency,
            anchor_day=support[-1].settlement_date.day,
            latest_event=support[-1],
        )
    return result


def _category_key(event: FinancialEvent) -> str:
    return "|".join((event.category, event.direction, event.currency))


def detect_category_series(
    events: Iterable[FinancialEvent],
    request_date: date,
    categories: frozenset[str],
    existing_series: dict[str, RecurringSeries],
) -> dict[str, RecurringSeries]:
    """Detect weekly/biweekly recurrence at the category level for protected variable spending."""
    existing_support = {eid for s in existing_series.values() for eid in s.support_event_ids}
    grouped: defaultdict[str, list[FinancialEvent]] = defaultdict(list)
    for event in events:
        if (
            event.excluded
            or event.amount is None
            or event.settlement_date is None
            or event.status != "settled"
            or event.settlement_date > request_date
            or event.direction != "debit"
            or event.category not in categories
            or event.event_id in existing_support
        ):
            continue
        cat_key = _category_key(event)
        grouped[cat_key].append(event)

    result: dict[str, RecurringSeries] = {}
    for cat_key, rows in grouped.items():
        rows.sort(key=lambda item: (item.settlement_date, item.event_id))
        dates = [item.settlement_date for item in rows]
        if len(dates) < 5:
            continue
        run = _latest_gap_run(dates, 6, 8)
        if run >= 5:
            frequency = "weekly"
        elif len(dates) >= 4:
            run = _latest_gap_run(dates, 13, 15)
            if run >= 4:
                frequency = "biweekly"
            else:
                continue
        else:
            continue
        support = rows[-run:]
        latest = support[-1]
        expected_next = latest.settlement_date + timedelta(
            days=7 if frequency == "weekly" else 14
        )
        if expected_next < request_date:
            continue
        result[cat_key] = RecurringSeries(
            key=cat_key,
            support_event_ids=tuple(item.event_id for item in support),
            frequency=frequency,
            anchor_day=latest.settlement_date.day,
            latest_event=latest,
        )
    return result


def _latest_pattern(dates: list[date]) -> tuple[str | None, int]:
    if len(dates) >= 3:
        run = 1
        for index in range(len(dates) - 1, 0, -1):
            if _is_next_month(dates[index - 1], dates[index]):
                run += 1
            else:
                break
        if run >= 3:
            return "monthly", run
    if len(dates) >= 5:
        run = _latest_gap_run(dates, 6, 8)
        if run >= 5:
            return "weekly", run
    if len(dates) >= 4:
        run = _latest_gap_run(dates, 13, 15)
        if run >= 4:
            return "biweekly", run
    return None, 0


def _latest_gap_run(dates: list[date], low: int, high: int) -> int:
    run = 1
    for index in range(len(dates) - 1, 0, -1):
        gap = (dates[index] - dates[index - 1]).days
        if low <= gap <= high:
            run += 1
        else:
            break
    return run


def _is_next_month(previous: date, current: date) -> bool:
    year = previous.year + (1 if previous.month == 12 else 0)
    month = 1 if previous.month == 12 else previous.month + 1
    if (current.year, current.month) != (year, month):
        return False
    previous_last = calendar.monthrange(previous.year, previous.month)[1]
    current_last = calendar.monthrange(current.year, current.month)[1]
    if previous.day == previous_last and current.day == current_last:
        return True
    return current.day == min(previous.day, current_last)


def next_date(value: date, frequency: str, anchor_day: int) -> date:
    if frequency == "weekly":
        return value + timedelta(days=7)
    if frequency == "biweekly":
        return value + timedelta(days=14)
    if frequency != "monthly":
        raise ValueError(f"unsupported recurrence frequency: {frequency}")
    year = value.year + (1 if value.month == 12 else 0)
    month = 1 if value.month == 12 else value.month + 1
    return date(year, month, min(anchor_day, calendar.monthrange(year, month)[1]))
