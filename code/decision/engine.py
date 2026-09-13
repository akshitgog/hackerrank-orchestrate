from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from decimal import Decimal, ROUND_FLOOR
from itertools import combinations, product
from typing import Iterable

from models.domain import FinancialEvent, Occurrence, PaymentOption, Profile, Request


@dataclass(frozen=True)
class Payment:
    date: date
    amount: Decimal


@dataclass(frozen=True)
class SpendingChange:
    action: str
    event_id: str
    original_amount: Decimal
    new_amount: Decimal | None = None
    series_key: str | None = None

    def serialize(self) -> str:
        if self.action == "stop":
            return f"stop:{self.event_id}"
        return f"reduce_to:{self.event_id}:{decimal_text(self.new_amount)}"


@dataclass(frozen=True)
class SimulationResult:
    safe: bool
    minimum_balance: Decimal
    minimum_date: date
    ledger: tuple[dict[str, str], ...]
    rejection_reason: str | None = None


@dataclass(frozen=True)
class PaymentCandidate:
    candidate_id: str
    method: str
    payments: tuple[Payment, ...]
    total_payable: Decimal
    start_date: date
    completion_date: date
    payment_option_id: str | None = None
    spending_changes: tuple[SpendingChange, ...] = ()
    eligible: bool = True
    completes_by_deadline: bool = True
    simulation: SimulationResult | None = None
    rejection_reason: str | None = None


@dataclass(frozen=True)
class FinalDecision:
    request_id: str
    amount_safe_to_pay: Decimal
    affordability_status: str
    recommended_payment_method: str
    payment_plan: str
    earliest_date_for_full_payment: date | None
    spending_changes_needed: str
    decision_explanation: str
    winning_candidate: PaymentCandidate | None = None
    fallback_used: bool = False


def decimal_text(value: Decimal | None) -> str:
    if value is None:
        return ""
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def serialize_payments(payments: Iterable[Payment]) -> str:
    values = list(payments)
    if not values:
        return "none"
    return "|".join(
        f"{payment.date.isoformat()}:{decimal_text(payment.amount)}"
        for payment in sorted(values, key=lambda item: item.date)
    )


def simulate(
    occurrences: Iterable[Occurrence],
    profile: Profile,
    payments: Iterable[Payment] = (),
    spending_changes: Iterable[SpendingChange] = (),
) -> SimulationResult:
    changes = list(spending_changes)
    entries: list[tuple[date, int, str, Decimal, str, str]] = []
    for occurrence in occurrences:
        signed = occurrence.signed_amount
        matching = next(
            (
                change for change in changes
                if change.event_id == occurrence.event_id
                or (change.series_key and change.series_key == occurrence.series_key)
            ),
            None,
        )
        if matching and occurrence.direction == "debit" and occurrence.flexible:
            if matching.action == "stop":
                continue
            if matching.new_amount is not None and matching.original_amount > 0:
                signed = signed * matching.new_amount / matching.original_amount
        priority = 0 if occurrence.direction == "credit" else (1 if occurrence.protected or not occurrence.flexible else 2)
        source_type = "reserve" if occurrence.occurrence_id.startswith("reserve:") else "baseline_event"
        entries.append((occurrence.date, priority, occurrence.occurrence_id, signed, source_type, occurrence.category))
    for ordinal, payment in enumerate(payments):
        entries.append((payment.date, 3, f"candidate_payment:{ordinal}", -payment.amount, "candidate_payment", "request"))

    balance = profile.current_available_balance
    minimum = balance
    minimum_date = min((entry[0] for entry in entries), default=date.min)
    ledger: list[dict[str, str]] = []
    for when, priority, source_id, signed, source_type, category in sorted(entries):
        balance += signed
        ledger.append({
            "date": when.isoformat(),
            "source_type": source_type,
            "source_id": source_id,
            "category": category,
            "signed_amount": decimal_text(signed),
            "running_balance": decimal_text(balance),
            "priority": str(priority),
        })
        if balance < minimum:
            minimum = balance
            minimum_date = when
    safe = minimum >= profile.minimum_balance_to_keep
    return SimulationResult(
        safe=safe,
        minimum_balance=minimum,
        minimum_date=minimum_date,
        ledger=tuple(ledger),
        rejection_reason=None if safe else "minimum_balance_breach",
    )


def earliest_full_payment_date(
    request: Request,
    profile: Profile,
    occurrences: Iterable[Occurrence],
    horizon_days: int,
) -> date | None:
    occurrence_list = tuple(occurrences)
    for offset in range(horizon_days + 1):
        candidate_date = request.request_date + timedelta(days=offset)
        result = simulate(
            occurrence_list, profile, (Payment(candidate_date, request.requested_amount),)
        )
        if result.safe:
            return candidate_date
    return None


def _installment_payments(option: PaymentOption) -> tuple[Payment, ...]:
    if option.number_of_payments == 1:
        return (Payment(option.first_payment_date, option.payment_amount),)
    if not option.payment_frequency_days:
        return ()
    return tuple(
        Payment(
            option.first_payment_date + timedelta(days=index * option.payment_frequency_days),
            option.payment_amount,
        )
        for index in range(option.number_of_payments)
    )


def generate_candidates(
    request: Request,
    profile: Profile,
    options: Iterable[PaymentOption],
    amount_safe_to_pay: Decimal,
    earliest_full_date: date | None,
    forecast_end: date,
) -> list[PaymentCandidate]:
    candidates: list[PaymentCandidate] = []
    methods = profile.payment_methods
    if "full_payment" in methods:
        candidates.append(PaymentCandidate(
            candidate_id="full_payment",
            method="full_payment",
            payments=(Payment(request.request_date, request.requested_amount),),
            total_payable=request.requested_amount,
            start_date=request.request_date,
            completion_date=request.request_date,
        ))
    if (
        "partial_payment" in methods
        and request.allows_partial_payment
        and Decimal("0") < amount_safe_to_pay < request.requested_amount
        and earliest_full_date is not None
    ):
        payments = (
            Payment(request.request_date, amount_safe_to_pay),
            Payment(earliest_full_date, request.requested_amount - amount_safe_to_pay),
        )
        candidates.append(PaymentCandidate(
            candidate_id="partial_payment",
            method="partial_payment",
            payments=payments,
            total_payable=request.requested_amount,
            start_date=request.request_date,
            completion_date=earliest_full_date,
            completes_by_deadline=earliest_full_date <= request.desired_completion_date,
            rejection_reason=(
                None if earliest_full_date <= request.desired_completion_date
                else "completion_after_desired_date"
            ),
        ))
    if "installments" in methods:
        for option in options:
            if option.payment_method != "installments":
                continue
            payments = _installment_payments(option)
            if not payments:
                continue
            within_user_limit = (
                profile.max_installment_months is not None
                and option.number_of_payments <= profile.max_installment_months
            )
            completion = payments[-1].date
            deadline_ok = completion <= request.desired_completion_date and completion <= forecast_end
            candidates.append(PaymentCandidate(
                candidate_id=option.payment_option_id,
                method="installments",
                payments=payments,
                total_payable=option.total_payable_amount,
                start_date=payments[0].date,
                completion_date=completion,
                payment_option_id=option.payment_option_id,
                eligible=within_user_limit,
                completes_by_deadline=deadline_ok,
                rejection_reason=(
                    "exceeds_max_installment_months" if not within_user_limit
                    else ("completion_after_desired_date" if not deadline_ok else None)
                ),
            ))
    if (
        "full_payment" in methods
        and earliest_full_date is not None
        and earliest_full_date > request.request_date
    ):
        deadline_ok = earliest_full_date <= request.desired_completion_date
        candidates.append(PaymentCandidate(
            candidate_id="wait",
            method="wait",
            payments=(Payment(earliest_full_date, request.requested_amount),),
            total_payable=request.requested_amount,
            start_date=earliest_full_date,
            completion_date=earliest_full_date,
            completes_by_deadline=deadline_ok,
            rejection_reason=None if deadline_ok else "completion_after_desired_date",
        ))
    return candidates


def evaluate_candidates(
    candidates: Iterable[PaymentCandidate],
    occurrences: Iterable[Occurrence],
    profile: Profile,
) -> list[PaymentCandidate]:
    occurrence_list = tuple(occurrences)
    evaluated: list[PaymentCandidate] = []
    for candidate in candidates:
        if not candidate.eligible or not candidate.completes_by_deadline:
            evaluated.append(candidate)
            continue
        result = simulate(
            occurrence_list, profile, candidate.payments, candidate.spending_changes
        )
        evaluated.append(replace(
            candidate,
            simulation=result,
            rejection_reason=result.rejection_reason,
        ))
    return evaluated


def _modifiable_events(
    request: Request,
    profile: Profile,
    events: Iterable[FinancialEvent],
    occurrences: Iterable[Occurrence],
) -> list[tuple[FinancialEvent, str]]:
    event_map = {event.event_id: event for event in events}
    occurrence_groups: dict[tuple[str, str | None], list[Occurrence]] = {}
    for occurrence in occurrences:
        if occurrence.date < request.request_date or occurrence.direction != "debit" or not occurrence.flexible:
            continue
        occurrence_groups.setdefault((occurrence.event_id, occurrence.series_key), []).append(occurrence)
    rows: list[tuple[FinancialEvent, str]] = []
    for (event_id, key), future in occurrence_groups.items():
        event = event_map.get(event_id)
        if event is None or event.category in profile.protected_categories or len(future) < 2:
            continue
        stop_allowed = (
            event.category in profile.stoppable_categories
            and event.flexibility in {"stoppable", "reducible_or_stoppable"}
        )
        reduce_allowed = (
            event.category in profile.reducible_categories
            and event.flexibility in {"reducible", "reducible_or_stoppable"}
        )
        if stop_allowed:
            rows.append((event, "stop"))
        if reduce_allowed and event.amount is not None and event.amount > (event.minimum_allowed_amount or 0):
            rows.append((event, "reduce"))
    return rows


def _tighten_reductions(
    candidate: PaymentCandidate,
    occurrences: tuple[Occurrence, ...],
    profile: Profile,
    changes: tuple[SpendingChange, ...],
) -> tuple[SpendingChange, ...]:
    current = list(changes)
    for index, change in enumerate(current):
        if change.action != "reduce_to" or change.new_amount is None:
            continue
        low = change.new_amount
        high = change.original_amount
        for _ in range(32):
            if high - low < Decimal("0.01"):
                break
            midpoint = ((low + high) / 2).quantize(Decimal("0.01"), rounding=ROUND_FLOOR)
            if midpoint <= low:
                break
            trial = list(current)
            trial[index] = replace(change, new_amount=midpoint)
            if simulate(occurrences, profile, candidate.payments, trial).safe:
                low = midpoint
                current[index] = trial[index]
            else:
                high = midpoint
        change = current[index]
        if change.new_amount is not None:
            rounded = change.new_amount.quantize(Decimal("0.01"), rounding=ROUND_FLOOR)
            current[index] = replace(change, new_amount=rounded)
    return tuple(current)


def recover_with_spending_changes(
    candidates: Iterable[PaymentCandidate],
    request: Request,
    profile: Profile,
    events: Iterable[FinancialEvent],
    occurrences: Iterable[Occurrence],
) -> list[PaymentCandidate]:
    occurrence_list = tuple(occurrences)
    legal = _modifiable_events(request, profile, events, occurrence_list)
    by_event: dict[str, tuple[FinancialEvent, set[str]]] = {}
    for event, action in legal:
        if event.event_id not in by_event:
            by_event[event.event_id] = (event, set())
        by_event[event.event_id][1].add(action)
    # The highest-relief events dominate an exhaustive <=3 search and keep runtime bounded.
    selectable = sorted(
        by_event.values(),
        key=lambda item: (-(item[0].amount or Decimal("0")), item[0].event_id),
    )[:12]
    recovered: list[PaymentCandidate] = []
    for candidate in candidates:
        if not candidate.eligible or not candidate.completes_by_deadline:
            continue
        found: PaymentCandidate | None = None
        for size in range(1, min(3, len(selectable)) + 1):
            for subset in combinations(selectable, size):
                action_sets = [sorted(actions) for _, actions in subset]
                for action_choice in product(*action_sets):
                    changes: list[SpendingChange] = []
                    for (event, _), action in zip(subset, action_choice):
                        original = event.amount or Decimal("0")
                        key = next(
                            (occ.series_key for occ in occurrence_list if occ.event_id == event.event_id),
                            None,
                        )
                        changes.append(SpendingChange(
                            action="stop" if action == "stop" else "reduce_to",
                            event_id=event.event_id,
                            original_amount=original,
                            new_amount=(event.minimum_allowed_amount or Decimal("0")) if action == "reduce" else None,
                            series_key=key,
                        ))
                    result = simulate(occurrence_list, profile, candidate.payments, changes)
                    if not result.safe:
                        continue
                    tightened = _tighten_reductions(
                        candidate, occurrence_list, profile, tuple(changes)
                    )
                    result = simulate(occurrence_list, profile, candidate.payments, tightened)
                    found = replace(
                        candidate,
                        candidate_id=f"{candidate.candidate_id}+changes",
                        spending_changes=tightened,
                        simulation=result,
                        rejection_reason=None,
                    )
                    break
                if found:
                    break
            if found:
                break
        if found:
            recovered.append(found)
    return recovered


def rank_candidates(candidates: Iterable[PaymentCandidate]) -> list[PaymentCandidate]:
    valid = [
        candidate for candidate in candidates
        if candidate.eligible
        and candidate.completes_by_deadline
        and candidate.simulation is not None
        and candidate.simulation.safe
    ]
    return sorted(valid, key=lambda candidate: (
        bool(candidate.spending_changes),
        candidate.total_payable,
        candidate.start_date,
        len(candidate.payments),
        candidate.payment_option_id or "",
        candidate.candidate_id,
    ))


def build_decision(
    request: Request,
    amount_safe_to_pay: Decimal,
    earliest_full_date: date | None,
    winner: PaymentCandidate | None,
    minimum_balance: Decimal,
    home_currency: str,
) -> FinalDecision:
    if winner is None:
        explanation = (
            f"No eligible payment schedule keeps the projected balance above the required minimum; "
            f"{decimal_text(amount_safe_to_pay)} {home_currency} is safe today."
        )
        return FinalDecision(
            request.request_id, amount_safe_to_pay, "not_affordable", "not_recommended",
            "none", earliest_full_date, "none", explanation,
        )
    if winner.method == "full_payment" and not winner.spending_changes:
        status = "affordable_now"
    elif winner.method == "wait":
        status = "affordable_later"
    else:
        status = "affordable_with_plan"
    changes = "|".join(change.serialize() for change in winner.spending_changes) or "none"
    if winner.method == "wait":
        explanation = (
            f"Wait until {winner.completion_date.isoformat()} for one safe full payment while "
            f"maintaining at least {decimal_text(minimum_balance)} {home_currency}."
        )
    elif winner.spending_changes:
        explanation = (
            f"Use {winner.method} with {changes}; the verified 90-day plan preserves the required balance."
        )
    else:
        explanation = (
            f"Use {winner.method}; the verified schedule keeps the 90-day balance at or above "
            f"{decimal_text(minimum_balance)} {home_currency}."
        )
    return FinalDecision(
        request.request_id,
        amount_safe_to_pay,
        status,
        winner.method,
        serialize_payments(winner.payments),
        earliest_full_date,
        changes,
        explanation,
        winner,
    )


def fallback_decision(request: Request) -> FinalDecision:
    return FinalDecision(
        request.request_id,
        Decimal("0"),
        "not_affordable",
        "not_recommended",
        "none",
        None,
        "none",
        "Unable to verify financial safety because required data could not be resolved.",
        fallback_used=True,
    )
