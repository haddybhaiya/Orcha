"""Deterministic event classification for cash-flow forecasting."""

from datetime import date

from orcha.ledger.models import ForecastBehavior
from orcha.models import EventDirection, EventStatus


def classify_for_forecast(
    status: EventStatus,
    direction: EventDirection,
    settlement_date: date,
    request_date: date,
    is_confirmed_scheduled_credit: bool = True,
) -> ForecastBehavior:
    """Classify how an event behaves relative to request_date."""
    # 1. Ignored statuses
    if status == EventStatus.CANCELLED:
        return ForecastBehavior.IGNORED_CANCELLED
    if status == EventStatus.FAILED:
        return ForecastBehavior.IGNORED_FAILED
    if status == EventStatus.UNREALIZED:
        return ForecastBehavior.IGNORED_UNREALIZED

    # 2. Ignored directions
    if direction == EventDirection.NON_CASH:
        return ForecastBehavior.IGNORED_NON_CASH

    # 3. Credits (Inflows)
    if direction == EventDirection.CREDIT:
        # Rule: Pending credits are NEVER counted as spendable cash until settled
        if status == EventStatus.PENDING:
            return ForecastBehavior.IGNORED_PENDING_CREDIT

        if status == EventStatus.SETTLED:
            if settlement_date <= request_date:
                # Rule: Historical settled activity is already reflected in the starting balance
                return ForecastBehavior.HISTORICAL_ALREADY_IN_BALANCE
            return ForecastBehavior.FUTURE_CONFIRMED_CREDIT

        if status == EventStatus.SCHEDULED:
            if settlement_date < request_date:
                return ForecastBehavior.HISTORICAL_ALREADY_IN_BALANCE
            if is_confirmed_scheduled_credit:
                return ForecastBehavior.FUTURE_CONFIRMED_CREDIT
            return ForecastBehavior.IGNORED_PENDING_CREDIT

    # 4. Debits (Outflows)
    if status == EventStatus.PENDING:
        # Rule: Pending debits MUST be reserved conservatively
        return ForecastBehavior.FUTURE_PENDING_DEBIT

    if status == EventStatus.SCHEDULED:
        if settlement_date < request_date:
            return ForecastBehavior.HISTORICAL_ALREADY_IN_BALANCE
        return ForecastBehavior.FUTURE_CONFIRMED_DEBIT

    if settlement_date < request_date:
        return ForecastBehavior.HISTORICAL_ALREADY_IN_BALANCE
    return ForecastBehavior.FUTURE_CONFIRMED_DEBIT
