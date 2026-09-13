from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class Request:
    request_id: str
    user_id: str
    request_date: date
    request_type: str
    requested_amount: Decimal
    desired_completion_date: date
    allows_partial_payment: bool
    request_text: str


@dataclass(frozen=True)
class Profile:
    user_id: str
    home_currency: str
    current_available_balance: Decimal
    minimum_balance_to_keep: Decimal
    protected_categories: frozenset[str]
    reducible_categories: frozenset[str] = frozenset()
    stoppable_categories: frozenset[str] = frozenset()
    payment_methods: frozenset[str] = frozenset()
    max_installment_months: int | None = None
    financial_priorities: tuple[str, ...] = ()


@dataclass(frozen=True)
class FinancialEvent:
    event_id: str
    user_id: str
    event_type: str
    description: str
    category: str
    direction: str
    amount: Decimal | None
    currency: str
    event_date: date
    settlement_date: date | None
    status: str
    linked_event_id: str | None
    flexibility: str
    minimum_allowed_amount: Decimal | None
    excluded: bool = False
    evidence_sources: tuple[str, ...] = ()
    recurrence_frequency: str | None = None
    recurrence_end_date: date | None = None

    def updated(self, **changes: Any) -> "FinancialEvent":
        return replace(self, **changes)


@dataclass(frozen=True)
class Message:
    message_id: str
    user_id: str
    request_id: str | None
    related_event_id: str | None
    sent_at: str
    source_type: str
    message_text: str


@dataclass(frozen=True)
class ImageLink:
    image_id: str
    user_id: str
    request_id: str | None
    related_event_id: str | None


@dataclass(frozen=True)
class Occurrence:
    occurrence_id: str
    event_id: str
    date: date
    signed_amount: Decimal
    category: str
    direction: str
    protected: bool
    flexible: bool
    series_key: str | None = None


@dataclass(frozen=True)
class PaymentOption:
    payment_option_id: str
    request_id: str
    payment_method: str
    payment_amount: Decimal
    number_of_payments: int
    first_payment_date: date
    payment_frequency_days: int | None
    financing_fee: Decimal
    total_payable_amount: Decimal


@dataclass(frozen=True)
class CapacityResult:
    request_id: str
    home_currency: str
    requested_amount: Decimal
    minimum_baseline_balance: Decimal | None
    baseline_headroom: Decimal | None
    amount_safe_to_pay: Decimal | None
    valid: bool
    evidence_status: str
    warnings: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class Dataset:
    requests: tuple[Request, ...]
    profiles: dict[str, Profile]
    events_by_user: dict[str, tuple[FinancialEvent, ...]]
    messages_by_user: dict[str, tuple[Message, ...]]
    images_by_user: dict[str, tuple[ImageLink, ...]]
    exchange_rates: dict[tuple[date, str, str], Decimal]
    payment_options_by_request: dict[str, tuple[PaymentOption, ...]] = field(default_factory=dict)
