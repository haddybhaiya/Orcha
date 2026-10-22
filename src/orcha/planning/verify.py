"""Deterministic contract validation and 90-day plan verification."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal

from orcha.ledger.models import ResolvedFinancialEvent
from orcha.models import (
    CandidatePlan,
    FinancialProfile,
    FinancialRequest,
    PaymentOption,
    RecommendedPaymentMethod,
    SimulationResult,
    SpendingChangeAction,
)
from orcha.planning.installments import build_installment_plan, is_option_eligible
from orcha.planning.spending_changes import find_eligible_spending_actions
from orcha.simulation.forecast import simulate


def apply_spending_changes_to_events(
    resolved_events: list[ResolvedFinancialEvent],
    plan: CandidatePlan,
    request_date: date,
) -> list[ResolvedFinancialEvent]:
    """Apply validated changes only to matching future recurring occurrences."""
    if not plan.spending_changes:
        return resolved_events

    stop_ids = {c.event_id for c in plan.spending_changes if c.action == SpendingChangeAction.STOP}
    reduce_map = {
        c.event_id: c.new_amount
        for c in plan.spending_changes
        if c.action == SpendingChangeAction.REDUCE_TO and c.new_amount is not None
    }

    modified: list[ResolvedFinancialEvent] = []
    for event in resolved_events:
        if event.settlement_date < request_date:
            modified.append(event)
            continue
        source_ids = set(event.source_event_ids) | {event.canonical_event_id}
        if source_ids & stop_ids:
            modified.append(replace(event, amount_home_currency=Decimal("0")))
            continue
        matching_reductions = source_ids & reduce_map.keys()
        if matching_reductions:
            target = min(matching_reductions)
            modified.append(replace(event, amount_home_currency=reduce_map[target]))
            continue
        modified.append(event)
    return modified


def _contract_error(
    profile: FinancialProfile,
    request: FinancialRequest,
    resolved_events: list[ResolvedFinancialEvent],
    plan: CandidatePlan,
    payment_options: list[PaymentOption],
    forecast_end_date: date,
) -> str | None:
    if not plan.payments:
        return "a recommended payment plan must contain payments"
    if len(plan.spending_changes) > 3:
        return "at most three spending changes are permitted"
    if any(payment.amount <= 0 for payment in plan.payments):
        return "payment amounts must be positive"
    dates = [payment.payment_date for payment in plan.payments]
    if dates != sorted(dates):
        return "payments must be chronological"
    if any(day < request.request_date or day > forecast_end_date for day in dates):
        return "every payment must be inside the verified forecast window"
    if plan.completion_date != dates[-1]:
        return "completion_date must equal the final payment date"
    if dates[-1] > request.desired_completion_date:
        return "the request must be completed by desired_completion_date"

    method = plan.recommended_payment_method
    if method == RecommendedPaymentMethod.PARTIAL_PAYMENT:
        if (
            not request.allows_partial_payment
            or method not in profile.payment_methods_user_will_consider
            or len(plan.payments) != 2
            or plan.payment_option_id is not None
            or plan.payments[0].payment_date != request.request_date
            or plan.payments[1].amount != request.requested_amount - plan.payments[0].amount
            or not Decimal("0") < plan.payments[0].amount < request.requested_amount
        ):
            return "partial payment violates its strict two-payment contract"
    elif method == RecommendedPaymentMethod.INSTALLMENTS:
        option = next(
            (o for o in payment_options if o.payment_option_id == plan.payment_option_id), None
        )
        if option is None or not is_option_eligible(option, profile):
            return "installment plan has no eligible supplied payment option"
        expected = build_installment_plan(option, request)
        if plan.payments != expected.payments or plan.total_cost != option.total_payable_amount:
            return "installment schedule does not exactly follow its supplied option"
    elif method in (RecommendedPaymentMethod.FULL_PAYMENT, RecommendedPaymentMethod.WAIT):
        if RecommendedPaymentMethod.FULL_PAYMENT not in profile.payment_methods_user_will_consider:
            return "the user does not accept full payment"
        if len(plan.payments) != 1 or plan.payments[0].amount != request.requested_amount:
            return "full/wait plan must contain one payment for the requested amount"
        if method == RecommendedPaymentMethod.WAIT and dates[0] <= request.request_date:
            return "wait must schedule payment after the request date"
    else:
        return "not_recommended is not a payable candidate plan"

    if method != RecommendedPaymentMethod.INSTALLMENTS:
        total = sum((payment.amount for payment in plan.payments), Decimal("0"))
        if total != request.requested_amount or plan.total_cost != total:
            return "payment amounts must sum exactly to the requested amount"

    eligible_changes = {
        action.to_str() for action, _, _ in find_eligible_spending_actions(profile, resolved_events)
    }
    serialized_changes = [change.to_str() for change in plan.spending_changes]
    if len({change.event_id for change in plan.spending_changes}) != len(plan.spending_changes):
        return "only one spending action may target each recurring stream"
    if any(change not in eligible_changes for change in serialized_changes):
        return "spending change is not a permitted flexible recurring action"
    return None


def verify_plan_safety(
    profile: FinancialProfile,
    resolved_events: list[ResolvedFinancialEvent],
    plan: CandidatePlan,
    request: FinancialRequest,
    payment_options: list[PaymentOption],
    forecast_end_date: date,
) -> tuple[bool, SimulationResult]:
    """Validate a candidate's contract, then replay every payment through simulation."""
    error = _contract_error(
        profile, request, resolved_events, plan, payment_options, forecast_end_date
    )
    if error is not None:
        return False, SimulationResult(
            is_safe=False,
            min_balance_projected=profile.current_available_balance,
            starting_balance=profile.current_available_balance,
            ending_balance=profile.current_available_balance,
            minimum_balance_to_keep=profile.minimum_balance_to_keep,
            min_headroom_projected=(
                profile.current_available_balance - profile.minimum_balance_to_keep
            ),
            failed_date=request.request_date,
            failure_reason=error,
        )

    modified_events = apply_spending_changes_to_events(resolved_events, plan, request.request_date)
    hypothetical = tuple((payment.payment_date, payment.amount) for payment in plan.payments)
    result = simulate(
        profile=profile,
        resolved_events=modified_events,
        start_date=request.request_date,
        end_date=forecast_end_date,
        hypothetical_payments=hypothetical,
    )
    return result.is_safe, result
