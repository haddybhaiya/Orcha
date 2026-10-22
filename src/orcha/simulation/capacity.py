"""Baseline financial capacity: amount_safe_to_pay and earliest_date_for_full_payment."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from orcha.ledger.models import ResolvedFinancialEvent
from orcha.models import FinancialProfile, SimulationResult
from orcha.money import quantize_money
from orcha.simulation.forecast import simulate


def calculate_amount_safe_to_pay(
    profile: FinancialProfile,
    requested_amount: Decimal,
    request_date: date,
    end_date: date,
    baseline_result: SimulationResult,
    resolved_events: list[ResolvedFinancialEvent],
) -> Decimal:
    """Calculate the maximum amount the user can safely pay on request_date.

    Invariant:
        0 <= amount_safe_to_pay <= requested_amount
        Maintaining minimum_balance_to_keep for every day in the 90-day forecast.
    Calculated before optional spending changes and verified by replay simulation.
    """
    min_headroom = baseline_result.min_headroom_projected
    candidate = max(Decimal("0"), min(min_headroom, requested_amount))
    candidate = quantize_money(candidate)

    # Replay through simulator to verify safety
    if candidate > Decimal("0"):
        sim = simulate(
            profile=profile,
            resolved_events=resolved_events,
            start_date=request_date,
            end_date=end_date,
            hypothetical_payments=((request_date, candidate),),
        )
        # If any edge causes a breach, decrement by smallest currency unit (0.01) until safe
        step = Decimal("0.01")
        while not sim.is_safe and candidate > Decimal("0"):
            candidate = max(Decimal("0"), candidate - step)
            sim = simulate(
                profile=profile,
                resolved_events=resolved_events,
                start_date=request_date,
                end_date=end_date,
                hypothetical_payments=((request_date, candidate),),
            )

    return candidate


def calculate_earliest_date_for_full_payment(
    profile: FinancialProfile,
    requested_amount: Decimal,
    request_date: date,
    end_date: date,
    baseline_result: SimulationResult,
    resolved_events: list[ResolvedFinancialEvent],
) -> date | None:
    """Calculate the first date within the 90-day forecast where full payment is safe.

    Independent of payment-method preferences and optional spending changes.
    Returns:
        request_date if full payment is safe today,
        earliest safe candidate date if safe later,
        None if no candidate date within the 90-day forecast is safe.
    """
    num_days = (end_date - request_date).days + 1
    days = [request_date + timedelta(days=i) for i in range(num_days)]

    # If full payment is safe today on request_date
    safe_today = calculate_amount_safe_to_pay(
        profile=profile,
        requested_amount=requested_amount,
        request_date=request_date,
        end_date=end_date,
        baseline_result=baseline_result,
        resolved_events=resolved_events,
    )
    if safe_today >= requested_amount:
        return request_date

    # Test each future candidate date
    for i, candidate_date in enumerate(days):
        # Remaining horizon headroom check
        remaining_days = days[i:]
        min_remaining_headroom = min(
            baseline_result.daily_headroom.get(d, Decimal("-Infinity")) for d in remaining_days
        )
        if min_remaining_headroom >= requested_amount:
            # Replay and verify full payment through simulator
            sim = simulate(
                profile=profile,
                resolved_events=resolved_events,
                start_date=request_date,
                end_date=end_date,
                hypothetical_payments=((candidate_date, requested_amount),),
            )
            if sim.is_safe:
                return candidate_date

    return None
