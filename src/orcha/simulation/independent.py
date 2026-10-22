"""Independent, deliberately simple replay checks for final financial audits.

This module does not call the production simulator or its timeline aggregation.
It exists to catch errors in capacity calculation or grouping logic before output
is emitted.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from orcha.ledger.models import ResolvedFinancialEvent
from orcha.models import FinancialProfile


@dataclass(frozen=True)
class IndependentReplayResult:
    """Result of an independent daily cash-balance replay."""

    is_safe: bool
    minimum_balance: Decimal
    minimum_balance_date: date
    ending_balance: Decimal
    breach_date: date | None


def independently_replay(
    profile: FinancialProfile,
    resolved_events: list[ResolvedFinancialEvent],
    request_date: date,
    forecast_end_date: date,
    payments: tuple[tuple[date, Decimal], ...] = (),
) -> IndependentReplayResult:
    """Replay cash flow directly from resolved events without production helpers."""
    if forecast_end_date < request_date:
        raise ValueError("forecast_end_date cannot precede request_date")

    inflows: dict[date, Decimal] = {}
    outflows: dict[date, Decimal] = {}
    for event in resolved_events:
        if event.is_ignored:
            continue
        effective_date = event.settlement_date
        if event.is_future_cash_outflow and effective_date < request_date:
            effective_date = request_date
        if not request_date <= effective_date <= forecast_end_date:
            continue
        if event.is_future_cash_inflow:
            inflows[effective_date] = inflows.get(effective_date, Decimal("0")) + (
                event.amount_home_currency
            )
        elif event.is_future_cash_outflow:
            outflows[effective_date] = outflows.get(effective_date, Decimal("0")) + (
                event.amount_home_currency
            )

    scheduled_payments: dict[date, Decimal] = {}
    for payment_date, amount in payments:
        if not request_date <= payment_date <= forecast_end_date:
            raise ValueError("payment falls outside the independently verified forecast window")
        scheduled_payments[payment_date] = (
            scheduled_payments.get(payment_date, Decimal("0")) + amount
        )

    balance = profile.current_available_balance
    minimum = balance
    minimum_date = request_date
    breach_date: date | None = None
    day = request_date
    while day <= forecast_end_date:
        balance += inflows.get(day, Decimal("0"))
        balance -= outflows.get(day, Decimal("0"))
        balance -= scheduled_payments.get(day, Decimal("0"))
        if balance < minimum:
            minimum = balance
            minimum_date = day
        if breach_date is None and balance < profile.minimum_balance_to_keep:
            breach_date = day
        day += timedelta(days=1)

    return IndependentReplayResult(
        is_safe=breach_date is None,
        minimum_balance=minimum,
        minimum_balance_date=minimum_date,
        ending_balance=balance,
        breach_date=breach_date,
    )


def verify_capacity_boundary(
    profile: FinancialProfile,
    resolved_events: list[ResolvedFinancialEvent],
    request_date: date,
    forecast_end_date: date,
    amount_safe_to_pay: Decimal,
    requested_amount: Decimal,
    smallest_currency_unit: Decimal = Decimal("0.01"),
) -> tuple[bool, bool | None]:
    """Return whether capacity is safe and whether its next cent is unsafe.

    The second result is ``None`` when capacity is already capped by the request.
    """
    safe = independently_replay(
        profile,
        resolved_events,
        request_date,
        forecast_end_date,
        ((request_date, amount_safe_to_pay),),
    ).is_safe
    if amount_safe_to_pay >= requested_amount:
        return safe, None
    next_amount = amount_safe_to_pay + smallest_currency_unit
    next_is_unsafe = not independently_replay(
        profile,
        resolved_events,
        request_date,
        forecast_end_date,
        ((request_date, next_amount),),
    ).is_safe
    return safe, next_is_unsafe


def independently_find_earliest_full_payment(
    profile: FinancialProfile,
    resolved_events: list[ResolvedFinancialEvent],
    request_date: date,
    forecast_end_date: date,
    requested_amount: Decimal,
) -> date | None:
    """Find first safe full-payment date by direct replay of every candidate day."""
    day = request_date
    while day <= forecast_end_date:
        result = independently_replay(
            profile,
            resolved_events,
            request_date,
            forecast_end_date,
            ((day, requested_amount),),
        )
        if result.is_safe:
            return day
        day += timedelta(days=1)
    return None
