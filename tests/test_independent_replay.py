"""Regression tests for the independent final-audit replay path."""

from datetime import date
from decimal import Decimal

from orcha.ledger.models import ForecastBehavior, ResolvedFinancialEvent
from orcha.models import EventDirection, EventStatus, FinancialProfile, FlexibilityType
from orcha.simulation.forecast import simulate
from orcha.simulation.independent import (
    independently_find_earliest_full_payment,
    independently_replay,
    verify_capacity_boundary,
)
from orcha.simulation.timeline import get_forecast_window


def _profile() -> FinancialProfile:
    return FinancialProfile(
        user_id="u",
        home_currency="USD",
        current_available_balance=Decimal("100"),
        minimum_balance_to_keep=Decimal("20"),
    )


def _event(
    event_id: str,
    settlement_date: date,
    amount: Decimal,
    direction: EventDirection,
    behavior: ForecastBehavior,
) -> ResolvedFinancialEvent:
    return ResolvedFinancialEvent(
        canonical_event_id=event_id,
        user_id="u",
        event_type="test",
        description="test",
        category="test",
        direction=direction,
        amount_home_currency=amount,
        home_currency="USD",
        original_amount=amount,
        original_currency="USD",
        event_date=settlement_date,
        settlement_date=settlement_date,
        resolved_status=EventStatus.PENDING,
        forecast_behavior=behavior,
        flexibility=FlexibilityType.FIXED,
    )


def test_independent_replay_matches_production_for_mixed_cash_flow() -> None:
    profile = _profile()
    start, end = get_forecast_window(date(2026, 1, 1))
    events = [
        _event(
            "income",
            date(2026, 1, 3),
            Decimal("50"),
            EventDirection.CREDIT,
            ForecastBehavior.FUTURE_CONFIRMED_CREDIT,
        ),
        _event(
            "pending_debit",
            date(2025, 12, 30),
            Decimal("10"),
            EventDirection.DEBIT,
            ForecastBehavior.FUTURE_PENDING_DEBIT,
        ),
        _event(
            "scheduled_debit",
            date(2026, 1, 5),
            Decimal("40"),
            EventDirection.DEBIT,
            ForecastBehavior.FUTURE_CONFIRMED_DEBIT,
        ),
    ]
    payments = ((date(2026, 1, 1), Decimal("30")),)
    production = simulate(profile, events, start, end, payments)
    independent = independently_replay(profile, events, start, end, payments)

    assert independent.is_safe == production.is_safe
    assert independent.minimum_balance == production.min_balance_projected
    assert independent.minimum_balance_date == production.min_balance_date
    assert independent.ending_balance == production.ending_balance


def test_independent_capacity_boundary_rejects_next_cent() -> None:
    profile = _profile()
    start, end = get_forecast_window(date(2026, 1, 1))
    safe, next_is_unsafe = verify_capacity_boundary(
        profile,
        [],
        start,
        end,
        amount_safe_to_pay=Decimal("80"),
        requested_amount=Decimal("100"),
    )
    assert safe is True
    assert next_is_unsafe is True


def test_independent_earliest_full_payment_scans_candidate_dates() -> None:
    profile = _profile()
    start, end = get_forecast_window(date(2026, 1, 1))
    income = _event(
        "income",
        date(2026, 1, 4),
        Decimal("50"),
        EventDirection.CREDIT,
        ForecastBehavior.FUTURE_CONFIRMED_CREDIT,
    )
    assert independently_find_earliest_full_payment(
        profile, [income], start, end, Decimal("110")
    ) == date(2026, 1, 4)
