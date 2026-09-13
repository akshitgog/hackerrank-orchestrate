from __future__ import annotations

from datetime import timedelta
from decimal import Decimal, InvalidOperation
from typing import Iterable

from decision.engine import FinalDecision, Payment, decimal_text
from models.domain import FinancialEvent, PaymentOption, Profile, Request


OUTPUT_COLUMNS = [
    "request_id",
    "amount_safe_to_pay",
    "affordability_status",
    "recommended_payment_method",
    "payment_plan",
    "earliest_date_for_full_payment",
    "spending_changes_needed",
    "decision_explanation",
]
STATUSES = {"affordable_now", "affordable_with_plan", "affordable_later", "not_affordable"}
METHODS = {"full_payment", "partial_payment", "installments", "wait", "not_recommended"}


class GuardrailError(ValueError):
    pass


def parse_payment_plan(value: str) -> tuple[Payment, ...]:
    if value == "none":
        return ()
    payments: list[Payment] = []
    from datetime import date
    for item in value.split("|"):
        try:
            raw_date, raw_amount = item.split(":", 1)
            amount = Decimal(raw_amount)
            payment_date = date.fromisoformat(raw_date)
        except (ValueError, InvalidOperation) as exc:
            raise GuardrailError(f"invalid payment plan entry: {item!r}") from exc
        if not amount.is_finite() or amount <= 0:
            raise GuardrailError("payment amounts must be positive finite Decimals")
        payments.append(Payment(payment_date, amount))
    if payments != sorted(payments, key=lambda item: item.date):
        raise GuardrailError("payment plan is not chronological")
    return tuple(payments)


def option_payments(option: PaymentOption) -> tuple[Payment, ...]:
    frequency = option.payment_frequency_days or 0
    return tuple(
        Payment(option.first_payment_date + timedelta(days=index * frequency), option.payment_amount)
        for index in range(option.number_of_payments)
    )


def validate_decision(
    decision: FinalDecision,
    request: Request,
    profile: Profile,
    options: Iterable[PaymentOption],
    events: Iterable[FinancialEvent],
    frozen_amount: Decimal,
) -> None:
    if decision.request_id != request.request_id:
        raise GuardrailError("request_id changed during processing")
    if decision.amount_safe_to_pay < 0 or decision.amount_safe_to_pay > request.requested_amount:
        raise GuardrailError("amount_safe_to_pay is outside the permitted range")
    if decision.fallback_used:
        if decision.amount_safe_to_pay != 0:
            raise GuardrailError("operational fallback must use zero safe amount")
    elif decision.amount_safe_to_pay != frozen_amount:
        raise GuardrailError("frozen amount_safe_to_pay was modified")
    if decision.affordability_status not in STATUSES:
        raise GuardrailError("invalid affordability_status")
    if decision.recommended_payment_method not in METHODS:
        raise GuardrailError("invalid recommended_payment_method")
    payments = parse_payment_plan(decision.payment_plan)
    method = decision.recommended_payment_method
    if method == "not_recommended":
        if decision.affordability_status != "not_affordable" or payments:
            raise GuardrailError("not_recommended cross-field inconsistency")
    elif not payments:
        raise GuardrailError("recommended payment method requires a plan")
    if decision.affordability_status == "affordable_now":
        if method != "full_payment" or decision.earliest_date_for_full_payment != request.request_date:
            raise GuardrailError("affordable_now cross-field inconsistency")
    if method == "full_payment":
        if len(payments) != 1 or payments[0].date != request.request_date or payments[0].amount != request.requested_amount:
            raise GuardrailError("full_payment must be one complete request-date payment")
    elif method == "partial_payment":
        if (
            decision.affordability_status != "affordable_with_plan"
            or not request.allows_partial_payment
            or "partial_payment" not in profile.payment_methods
            or len(payments) != 2
            or payments[0] != Payment(request.request_date, frozen_amount)
            or decision.earliest_date_for_full_payment is None
            or payments[1].date != decision.earliest_date_for_full_payment
            or sum((item.amount for item in payments), Decimal("0")) != request.requested_amount
        ):
            raise GuardrailError("partial_payment violates the required two-payment contract")
    elif method == "installments":
        matches = [option for option in options if option_payments(option) == payments]
        if not matches:
            raise GuardrailError("installment plan does not match a supplied option")
        if sum((item.amount for item in payments), Decimal("0")) != matches[0].total_payable_amount:
            raise GuardrailError("installment total differs from supplied total")
    elif method == "wait":
        if (
            decision.affordability_status != "affordable_later"
            or decision.earliest_date_for_full_payment is None
            or len(payments) != 1
            or payments[0] != Payment(decision.earliest_date_for_full_payment, request.requested_amount)
            or payments[0].date <= request.request_date
        ):
            raise GuardrailError("wait plan must pay in full on the earliest later safe date")
    changes = [] if decision.spending_changes_needed == "none" else decision.spending_changes_needed.split("|")
    if len(changes) > 3:
        raise GuardrailError("more than three spending changes")
    event_map = {event.event_id: event for event in events}
    seen: set[str] = set()
    for raw in changes:
        parts = raw.split(":")
        if len(parts) not in {2, 3} or parts[0] not in {"stop", "reduce_to"}:
            raise GuardrailError(f"invalid spending change: {raw}")
        event = event_map.get(parts[1])
        if event is None or event.event_id in seen:
            raise GuardrailError("spending change references unknown or repeated event")
        seen.add(event.event_id)
        if event.direction != "debit" or event.category in profile.protected_categories:
            raise GuardrailError("spending change targets protected/non-debit event")
        if parts[0] == "stop":
            if event.category not in profile.stoppable_categories or event.flexibility not in {"stoppable", "reducible_or_stoppable"}:
                raise GuardrailError("illegal stop action")
        else:
            if event.category not in profile.reducible_categories or event.flexibility not in {"reducible", "reducible_or_stoppable"}:
                raise GuardrailError("illegal reduce action")
            try:
                amount = Decimal(parts[2])
            except InvalidOperation as exc:
                raise GuardrailError("invalid reduce_to amount") from exc
            if event.amount is None or amount < (event.minimum_allowed_amount or 0) or amount >= event.amount:
                raise GuardrailError("reduce_to amount violates event bounds")
    if decision.winning_candidate is not None:
        result = decision.winning_candidate.simulation
        if result is None or not result.safe:
            raise GuardrailError("winning candidate did not pass the simulator")


def decision_row(decision: FinalDecision) -> dict[str, str]:
    return {
        "request_id": decision.request_id,
        "amount_safe_to_pay": decimal_text(decision.amount_safe_to_pay),
        "affordability_status": decision.affordability_status,
        "recommended_payment_method": decision.recommended_payment_method,
        "payment_plan": decision.payment_plan,
        "earliest_date_for_full_payment": (
            decision.earliest_date_for_full_payment.isoformat()
            if decision.earliest_date_for_full_payment else ""
        ),
        "spending_changes_needed": decision.spending_changes_needed,
        "decision_explanation": decision.decision_explanation,
    }
