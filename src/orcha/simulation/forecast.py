"""Deterministic daily cash-flow simulation engine for 90-day forecasting."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from orcha.ledger.models import ResolvedFinancialEvent
from orcha.models import DailyBalanceRecord, FinancialProfile, SimulationResult
from orcha.simulation.timeline import DailyCashFlow, group_cash_flows_by_date


def simulate(
    profile: FinancialProfile,
    resolved_events: list[ResolvedFinancialEvent],
    start_date: date,
    end_date: date,
    hypothetical_payments: tuple[tuple[date, Decimal], ...] = (),
) -> SimulationResult:
    """Run a deterministic day-by-day cash-flow simulation across the given window.

    Daily balance equation (Section 4):
        closing = opening + confirmed_credits - obligations_debits - hypothetical_payments

    A run is safe if and only if projected closing balance is >= minimum_balance_to_keep
    for every calendar day in the forecast window.
    """
    if end_date < start_date:
        raise ValueError(f"end_date {end_date} cannot be before start_date {start_date}")

    flows, included_ids, ignored_ids = group_cash_flows_by_date(
        resolved_events, start_date, end_date
    )

    hypo_by_date: dict[date, Decimal] = defaultdict(Decimal)
    for p_date, p_amt in hypothetical_payments:
        hypo_by_date[p_date] += p_amt

    min_balance_keep = profile.minimum_balance_to_keep
    current_balance = profile.current_available_balance
    starting_balance = current_balance

    daily_balances: dict[date, Decimal] = {}
    daily_headroom: dict[date, Decimal] = {}
    daily_records: list[DailyBalanceRecord] = []

    min_balance_reached = current_balance
    min_balance_date: date | None = start_date
    min_headroom = current_balance - min_balance_keep
    min_headroom_date: date | None = start_date

    breach_dates: list[date] = []
    failed_date: date | None = None
    failure_reason: str | None = None

    num_days = (end_date - start_date).days + 1
    for day_offset in range(num_days):
        cur_date = start_date + timedelta(days=day_offset)
        opening_bal = current_balance
        flow = flows.get(cur_date, DailyCashFlow())
        inflows = flow.inflows
        outflows = flow.outflows
        hypo = hypo_by_date.get(cur_date, Decimal("0"))

        closing_bal = opening_bal + inflows - outflows - hypo
        headroom = closing_bal - min_balance_keep

        daily_balances[cur_date] = closing_bal
        daily_headroom[cur_date] = headroom
        daily_records.append(
            DailyBalanceRecord(
                record_date=cur_date,
                opening_balance=opening_bal,
                cash_inflows=inflows,
                cash_outflows=outflows,
                hypothetical_payments=hypo,
                closing_balance=closing_bal,
                headroom=headroom,
            )
        )

        if closing_bal < min_balance_reached:
            min_balance_reached = closing_bal
            min_balance_date = cur_date

        if headroom < min_headroom:
            min_headroom = headroom
            min_headroom_date = cur_date

        if closing_bal < min_balance_keep:
            breach_dates.append(cur_date)
            if failed_date is None:
                failed_date = cur_date
                failure_reason = (
                    f"Balance {closing_bal} fell below minimum balance {min_balance_keep} "
                    f"on {cur_date}"
                )

        current_balance = closing_bal

    is_safe = len(breach_dates) == 0

    return SimulationResult(
        is_safe=is_safe,
        min_balance_projected=min_balance_reached,
        min_balance_date=min_balance_date,
        starting_balance=starting_balance,
        ending_balance=current_balance,
        minimum_balance_to_keep=min_balance_keep,
        min_headroom_projected=min_headroom,
        min_headroom_date=min_headroom_date,
        failed_date=failed_date,
        failure_reason=failure_reason,
        daily_balances=daily_balances,
        daily_headroom=daily_headroom,
        daily_records=daily_records,
        included_event_ids=included_ids,
        ignored_event_ids=ignored_ids,
        hypothetical_payments=hypothetical_payments,
        breach_dates=tuple(breach_dates),
    )
