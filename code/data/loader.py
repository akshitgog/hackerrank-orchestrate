from __future__ import annotations

import csv
from collections import defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable

from models.domain import (
    Dataset, FinancialEvent, ImageLink, Message, PaymentOption, Profile, Request,
)


class DataValidationError(ValueError):
    pass


def parse_decimal(value: str, field: str, *, optional: bool = False) -> Decimal | None:
    raw = value.strip()
    if optional and raw == "":
        return None
    try:
        result = Decimal(raw)
    except (InvalidOperation, ValueError) as exc:
        raise DataValidationError(f"invalid Decimal in {field}: {value!r}") from exc
    if not result.is_finite():
        raise DataValidationError(f"non-finite Decimal in {field}: {value!r}")
    return result


def parse_date(value: str, field: str, *, optional: bool = False) -> date | None:
    raw = value.strip()
    if optional and raw == "":
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise DataValidationError(f"invalid date in {field}: {value!r}") from exc


def _rows(path: Path, required: Iterable[str]) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = set(required) - set(reader.fieldnames or ())
        if missing:
            raise DataValidationError(f"{path.name} missing columns: {sorted(missing)}")
        return list(reader)


def _pipe_set(value: str) -> frozenset[str]:
    return frozenset(item.strip() for item in value.split("|") if item.strip())


def load_dataset(dataset_dir: Path, requests_path: Path) -> Dataset:
    request_rows = _rows(
        requests_path,
        ("request_id", "user_id", "request_date", "request_type", "requested_amount",
         "desired_completion_date", "allows_partial_payment", "request_text"),
    )
    requests: list[Request] = []
    seen_request_ids: set[str] = set()
    for row in request_rows:
        request_id = row["request_id"].strip()
        if request_id in seen_request_ids:
            raise DataValidationError(f"duplicate request_id: {request_id}")
        seen_request_ids.add(request_id)
        requests.append(Request(
            request_id=request_id,
            user_id=row["user_id"].strip(),
            request_date=parse_date(row["request_date"], "request_date"),
            request_type=row["request_type"].strip(),
            requested_amount=parse_decimal(row["requested_amount"], "requested_amount"),
            desired_completion_date=parse_date(row["desired_completion_date"], "desired_completion_date"),
            allows_partial_payment=row["allows_partial_payment"].strip().lower() == "true",
            request_text=row["request_text"],
        ))

    profile_rows = _rows(
        dataset_dir / "financial_profiles.csv",
        ("user_id", "home_currency", "current_available_balance", "minimum_balance_to_keep",
         "financial_priorities", "expense_categories_to_protect",
         "expense_categories_user_is_willing_to_reduce",
         "expense_categories_user_is_willing_to_stop",
         "payment_methods_user_will_consider", "max_installment_months"),
    )
    profiles: dict[str, Profile] = {}
    for row in profile_rows:
        user_id = row["user_id"].strip()
        if user_id in profiles:
            raise DataValidationError(f"duplicate profile user_id: {user_id}")
        profiles[user_id] = Profile(
            user_id=user_id,
            home_currency=row["home_currency"].strip(),
            current_available_balance=parse_decimal(row["current_available_balance"], "current_available_balance"),
            minimum_balance_to_keep=parse_decimal(row["minimum_balance_to_keep"], "minimum_balance_to_keep"),
            protected_categories=_pipe_set(row["expense_categories_to_protect"]),
            reducible_categories=_pipe_set(row["expense_categories_user_is_willing_to_reduce"]),
            stoppable_categories=_pipe_set(row["expense_categories_user_is_willing_to_stop"]),
            payment_methods=_pipe_set(row["payment_methods_user_will_consider"]),
            max_installment_months=(
                int(row["max_installment_months"])
                if row["max_installment_months"].strip() else None
            ),
            financial_priorities=tuple(
                item.strip() for item in row["financial_priorities"].split("|") if item.strip()
            ),
        )

    event_rows = _rows(
        dataset_dir / "financial_events.csv",
        ("event_id", "user_id", "event_type", "description", "category", "direction",
         "amount", "currency", "event_date", "settlement_date", "status",
         "linked_event_id", "flexibility", "minimum_allowed_amount"),
    )
    events_by_user: defaultdict[str, list[FinancialEvent]] = defaultdict(list)
    seen_event_ids: set[str] = set()
    for row in event_rows:
        event_id = row["event_id"].strip()
        if event_id in seen_event_ids:
            raise DataValidationError(f"duplicate event_id: {event_id}")
        seen_event_ids.add(event_id)
        event = FinancialEvent(
            event_id=event_id,
            user_id=row["user_id"].strip(),
            event_type=row["event_type"].strip(),
            description=row["description"].strip(),
            category=row["category"].strip(),
            direction=row["direction"].strip(),
            amount=parse_decimal(row["amount"], f"{event_id}.amount", optional=True),
            currency=row["currency"].strip(),
            event_date=parse_date(row["event_date"], f"{event_id}.event_date"),
            settlement_date=parse_date(row["settlement_date"], f"{event_id}.settlement_date", optional=True),
            status=row["status"].strip(),
            linked_event_id=row["linked_event_id"].strip() or None,
            flexibility=row["flexibility"].strip(),
            minimum_allowed_amount=parse_decimal(
                row["minimum_allowed_amount"], f"{event_id}.minimum_allowed_amount", optional=True
            ),
        )
        events_by_user[event.user_id].append(event)

    message_rows = _rows(
        dataset_dir / "messages.csv",
        ("message_id", "user_id", "request_id", "related_event_id", "sent_at",
         "source_type", "message_text"),
    )
    messages_by_user: defaultdict[str, list[Message]] = defaultdict(list)
    for row in message_rows:
        message = Message(
            message_id=row["message_id"].strip(),
            user_id=row["user_id"].strip(),
            request_id=row["request_id"].strip() or None,
            related_event_id=row["related_event_id"].strip() or None,
            sent_at=row["sent_at"].strip(),
            source_type=row["source_type"].strip(),
            message_text=row["message_text"],
        )
        messages_by_user[message.user_id].append(message)

    image_rows = _rows(dataset_dir / "images.csv", ("image_id", "user_id", "request_id", "related_event_id"))
    images_by_user: defaultdict[str, list[ImageLink]] = defaultdict(list)
    for row in image_rows:
        image_link = ImageLink(
            image_id=row["image_id"].strip(),
            user_id=row["user_id"].strip(),
            request_id=row["request_id"].strip() or None,
            related_event_id=row["related_event_id"].strip() or None,
        )
        images_by_user[image_link.user_id].append(image_link)

    rate_rows = _rows(dataset_dir / "exchange_rates.csv", ("rate_date", "from_currency", "to_currency", "rate"))
    exchange_rates: dict[tuple[date, str, str], Decimal] = {}
    for row in rate_rows:
        key = (
            parse_date(row["rate_date"], "rate_date"),
            row["from_currency"].strip(),
            row["to_currency"].strip(),
        )
        if key in exchange_rates:
            raise DataValidationError(f"duplicate exchange-rate key: {key}")
        exchange_rates[key] = parse_decimal(row["rate"], "rate")

    option_rows = _rows(
        dataset_dir / "request_payment_options.csv",
        ("payment_option_id", "request_id", "payment_method", "payment_amount",
         "number_of_payments", "first_payment_date", "payment_frequency_days",
         "financing_fee", "total_payable_amount"),
    )
    payment_options_by_request: defaultdict[str, list[PaymentOption]] = defaultdict(list)
    seen_option_ids: set[str] = set()
    for row in option_rows:
        option_id = row["payment_option_id"].strip()
        if option_id in seen_option_ids:
            raise DataValidationError(f"duplicate payment_option_id: {option_id}")
        seen_option_ids.add(option_id)
        count = int(row["number_of_payments"])
        frequency = row["payment_frequency_days"].strip()
        payment_options_by_request[row["request_id"].strip()].append(PaymentOption(
            payment_option_id=option_id,
            request_id=row["request_id"].strip(),
            payment_method=row["payment_method"].strip(),
            payment_amount=parse_decimal(row["payment_amount"], f"{option_id}.payment_amount"),
            number_of_payments=count,
            first_payment_date=parse_date(row["first_payment_date"], f"{option_id}.first_payment_date"),
            payment_frequency_days=int(frequency) if frequency else None,
            financing_fee=parse_decimal(row["financing_fee"], f"{option_id}.financing_fee"),
            total_payable_amount=parse_decimal(
                row["total_payable_amount"], f"{option_id}.total_payable_amount"
            ),
        ))

    for request in requests:
        if request.user_id not in profiles:
            raise DataValidationError(f"missing profile for {request.request_id}: {request.user_id}")

    return Dataset(
        requests=tuple(requests),
        profiles=profiles,
        events_by_user={key: tuple(value) for key, value in events_by_user.items()},
        messages_by_user={key: tuple(value) for key, value in messages_by_user.items()},
        images_by_user={key: tuple(value) for key, value in images_by_user.items()},
        exchange_rates=exchange_rates,
        payment_options_by_request={
            key: tuple(sorted(value, key=lambda item: item.payment_option_id))
            for key, value in payment_options_by_request.items()
        },
    )
