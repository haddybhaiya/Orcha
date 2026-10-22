"""Unit tests for 90-day daily cash-flow simulation and timeline continuity."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from orcha.ledger.models import ForecastBehavior, ResolvedFinancialEvent
from orcha.models import (
    EventDirection,
    EventStatus,
    FinancialProfile,
    FlexibilityType,
    RecommendedPaymentMethod,
)
from orcha.simulation.forecast import simulate
from orcha.simulation.timeline import get_forecast_window


def _make_dummy_profile(
    current_balance: Decimal = Decimal("10000"),
    min_balance: Decimal = Decimal("2000"),
    currency: str = "USD",
) -> FinancialProfile:
    return FinancialProfile(
        user_id="user_test",
        home_currency=currency,
        current_available_balance=current_balance,
        minimum_balance_to_keep=min_balance,
        payment_methods_user_will_consider=[RecommendedPaymentMethod.FULL_PAYMENT],
    )


def _make_resolved_event(
    event_id: str,
    event_date: date,
    settlement_date: date,
    amount: Decimal,
    direction: EventDirection,
    behavior: ForecastBehavior,
) -> ResolvedFinancialEvent:
    return ResolvedFinancialEvent(
        canonical_event_id=event_id,
        user_id="user_test",
        event_type="test_event",
        description="Test event description",
        category="general",
        direction=direction,
        amount_home_currency=amount,
        home_currency="USD",
        original_amount=amount,
        original_currency="USD",
        event_date=event_date,
        settlement_date=settlement_date,
        resolved_status=EventStatus.SETTLED,
        forecast_behavior=behavior,
        flexibility=FlexibilityType.FIXED,
    )


def test_forecast_window_calculation() -> None:
    start = date(2025, 1, 1)
    start_win, end_win = get_forecast_window(start, horizon_days=90)
    assert start_win == start
    # 90 days inclusive: Jan (31) + Feb (28) + Mar (31) = 90 days -> ends on Mar 31
    assert (end_win - start_win).days + 1 == 90
    assert end_win == date(2025, 3, 31)


def test_simulate_empty_ledger_continuity() -> None:
    prof = _make_dummy_profile(Decimal("5000"), Decimal("1000"))
    start = date(2025, 6, 1)
    start_date, end_date = get_forecast_window(start, 90)

    res = simulate(profile=prof, resolved_events=[], start_date=start_date, end_date=end_date)

    assert res.is_safe is True
    assert len(res.daily_records) == 90
    assert res.min_balance_projected == Decimal("5000")
    assert res.min_headroom_projected == Decimal("4000")

    # Verify chronological continuity: opening of day t+1 == closing of day t
    for i in range(len(res.daily_records) - 1):
        curr_rec = res.daily_records[i]
        next_rec = res.daily_records[i + 1]
        assert next_rec.record_date == curr_rec.record_date + timedelta(days=1)
        assert next_rec.opening_balance == curr_rec.closing_balance


def test_boundary_exact_minimum_balance_is_safe() -> None:
    """Balance dropping to exactly minimum_balance_to_keep is safe; 0.01 below is breach."""
    prof = _make_dummy_profile(Decimal("5000"), Decimal("2000"))
    start = date(2025, 6, 1)
    start_date, end_date = get_forecast_window(start, 90)

    # Debit that reduces balance exactly to 2000
    exact_debit = _make_resolved_event(
        "ev_exact",
        date(2025, 6, 10),
        date(2025, 6, 10),
        Decimal("3000"),
        EventDirection.DEBIT,
        ForecastBehavior.FUTURE_CONFIRMED_DEBIT,
    )
    res_exact = simulate(
        profile=prof,
        resolved_events=[exact_debit],
        start_date=start_date,
        end_date=end_date,
    )
    assert res_exact.is_safe is True
    assert res_exact.min_balance_projected == Decimal("2000")
    assert res_exact.min_headroom_projected == Decimal("0")
    assert len(res_exact.breach_dates) == 0

    # Debit of 3000.01 drops balance to 1999.99 -> breach!
    breach_debit = _make_resolved_event(
        "ev_breach",
        date(2025, 6, 10),
        date(2025, 6, 10),
        Decimal("3000.01"),
        EventDirection.DEBIT,
        ForecastBehavior.FUTURE_CONFIRMED_DEBIT,
    )
    res_breach = simulate(
        profile=prof,
        resolved_events=[breach_debit],
        start_date=start_date,
        end_date=end_date,
    )
    assert res_breach.is_safe is False
    assert res_breach.min_balance_projected == Decimal("1999.99")
    assert res_breach.min_headroom_projected == Decimal("-0.01")
    assert len(res_breach.breach_dates) == 81  # from June 10 through August 29 (inclusive)
    assert res_breach.breach_dates[0] == date(2025, 6, 10)


def test_historical_events_do_not_alter_available_balance() -> None:
    """Historical events already settled must NOT be double-counted in cash flow."""
    prof = _make_dummy_profile(Decimal("5000"), Decimal("1000"))
    start = date(2025, 6, 1)
    start_date, end_date = get_forecast_window(start, 90)

    hist_debit = _make_resolved_event(
        "ev_hist_deb",
        date(2025, 5, 20),
        date(2025, 5, 20),
        Decimal("2500"),
        EventDirection.DEBIT,
        ForecastBehavior.HISTORICAL_ALREADY_IN_BALANCE,
    )
    hist_credit = _make_resolved_event(
        "ev_hist_cred",
        date(2025, 5, 25),
        date(2025, 5, 25),
        Decimal("4000"),
        EventDirection.CREDIT,
        ForecastBehavior.HISTORICAL_ALREADY_IN_BALANCE,
    )

    res = simulate(
        profile=prof,
        resolved_events=[hist_debit, hist_credit],
        start_date=start_date,
        end_date=end_date,
    )
    # Balance must remain exactly 5000 with 0 inflows and 0 outflows
    assert res.is_safe is True
    assert res.min_balance_projected == Decimal("5000")
    for r in res.daily_records:
        assert r.cash_inflows == Decimal("0")
        assert r.cash_outflows == Decimal("0")
        assert r.closing_balance == Decimal("5000")


def test_hypothetical_payments_applied_on_exact_dates() -> None:
    prof = _make_dummy_profile(Decimal("10000"), Decimal("2000"))
    start = date(2025, 6, 1)
    start_date, end_date = get_forecast_window(start, 90)

    p1 = (date(2025, 6, 5), Decimal("3000"))
    p2 = (date(2025, 6, 20), Decimal("4000"))

    res = simulate(
        profile=prof,
        resolved_events=[],
        start_date=start_date,
        end_date=end_date,
        hypothetical_payments=(p1, p2),
    )

    assert res.is_safe is True
    day_4 = res.daily_balances[date(2025, 6, 4)]
    day_5 = res.daily_balances[date(2025, 6, 5)]
    day_19 = res.daily_balances[date(2025, 6, 19)]
    day_20 = res.daily_balances[date(2025, 6, 20)]

    assert day_4 == Decimal("10000")
    assert day_5 == Decimal("7000")
    assert day_19 == Decimal("7000")
    assert day_20 == Decimal("3000")
    assert res.min_balance_projected == Decimal("3000")


def test_invalid_simulation_date_range_raises() -> None:
    prof = _make_dummy_profile()
    with pytest.raises(ValueError, match="cannot be before"):
        simulate(
            profile=prof,
            resolved_events=[],
            start_date=date(2025, 6, 10),
            end_date=date(2025, 6, 5),
        )
