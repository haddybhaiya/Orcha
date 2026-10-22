"""Invariance and monotonicity tests for cash-flow simulation and baseline capacity."""

import random
from datetime import date
from decimal import Decimal

from orcha.ledger.models import ForecastBehavior, ResolvedFinancialEvent
from orcha.models import (
    EventDirection,
    EventStatus,
    FinancialProfile,
    FlexibilityType,
    RecommendedPaymentMethod,
)
from orcha.simulation.capacity import (
    calculate_amount_safe_to_pay,
    calculate_earliest_date_for_full_payment,
)
from orcha.simulation.forecast import simulate
from orcha.simulation.timeline import get_forecast_window


def _make_profile(
    current_balance: Decimal = Decimal("5000"),
    min_balance: Decimal = Decimal("1000"),
    currency: str = "USD",
) -> FinancialProfile:
    return FinancialProfile(
        user_id="user_inv",
        home_currency=currency,
        current_available_balance=current_balance,
        minimum_balance_to_keep=min_balance,
        payment_methods_user_will_consider=[RecommendedPaymentMethod.FULL_PAYMENT],
    )


def _make_event(
    event_id: str,
    event_date: date,
    settlement_date: date,
    amount: Decimal,
    direction: EventDirection,
    behavior: ForecastBehavior,
    description: str = "Invariant event",
) -> ResolvedFinancialEvent:
    return ResolvedFinancialEvent(
        canonical_event_id=event_id,
        user_id="user_inv",
        event_type="test_event",
        description=description,
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


def test_inv_a_input_order_invariance() -> None:
    """INV-A: Permuting the order of input events produces identical simulation results."""
    prof = _make_profile(Decimal("10000"), Decimal("2000"))
    start = date(2025, 6, 1)
    start_date, end_date = get_forecast_window(start, 90)

    events = [
        _make_event(
            "e1",
            date(2025, 6, 5),
            date(2025, 6, 5),
            Decimal("1500"),
            EventDirection.DEBIT,
            ForecastBehavior.FUTURE_CONFIRMED_DEBIT,
        ),
        _make_event(
            "e2",
            date(2025, 6, 15),
            date(2025, 6, 15),
            Decimal("4000"),
            EventDirection.CREDIT,
            ForecastBehavior.FUTURE_CONFIRMED_CREDIT,
        ),
        _make_event(
            "e3",
            date(2025, 6, 25),
            date(2025, 6, 25),
            Decimal("800"),
            EventDirection.DEBIT,
            ForecastBehavior.FUTURE_CONFIRMED_DEBIT,
        ),
        _make_event(
            "e4",
            date(2025, 7, 10),
            date(2025, 7, 10),
            Decimal("1200"),
            EventDirection.DEBIT,
            ForecastBehavior.FUTURE_CONFIRMED_DEBIT,
        ),
    ]

    base_sim = simulate(prof, events, start_date, end_date)
    base_safe = calculate_amount_safe_to_pay(
        prof, Decimal("5000"), start_date, end_date, base_sim, events
    )
    base_earliest = calculate_earliest_date_for_full_payment(
        prof, Decimal("5000"), start_date, end_date, base_sim, events
    )

    # Permute 5 times
    rng = random.Random(42)
    for _ in range(5):
        shuffled = list(events)
        rng.shuffle(shuffled)
        perm_sim = simulate(prof, shuffled, start_date, end_date)
        perm_safe = calculate_amount_safe_to_pay(
            prof, Decimal("5000"), start_date, end_date, perm_sim, shuffled
        )
        perm_earliest = calculate_earliest_date_for_full_payment(
            prof, Decimal("5000"), start_date, end_date, perm_sim, shuffled
        )

        assert perm_sim.is_safe == base_sim.is_safe
        assert perm_sim.min_balance_projected == base_sim.min_balance_projected
        assert perm_sim.min_headroom_projected == base_sim.min_headroom_projected
        assert perm_sim.daily_balances == base_sim.daily_balances
        assert perm_safe == base_safe
        assert perm_earliest == base_earliest


def test_inv_b_pending_credit_invariance() -> None:
    """INV-B: Unsettled pending credit cannot increase capacity or advance earliest date."""
    prof = _make_profile(Decimal("5000"), Decimal("1000"))
    start = date(2025, 6, 1)
    start_date, end_date = get_forecast_window(start, 90)

    deb = _make_event(
        "d1",
        date(2025, 6, 10),
        date(2025, 6, 10),
        Decimal("2000"),
        EventDirection.DEBIT,
        ForecastBehavior.FUTURE_CONFIRMED_DEBIT,
    )
    b_without = simulate(prof, [deb], start_date, end_date)
    safe_without = calculate_amount_safe_to_pay(
        prof, Decimal("5000"), start_date, end_date, b_without, [deb]
    )
    earliest_without = calculate_earliest_date_for_full_payment(
        prof, Decimal("5000"), start_date, end_date, b_without, [deb]
    )

    pending_cred = _make_event(
        "pc1",
        date(2025, 6, 5),
        date(2025, 6, 5),
        Decimal("100000"),
        EventDirection.CREDIT,
        ForecastBehavior.IGNORED_PENDING_CREDIT,
    )
    b_with = simulate(prof, [deb, pending_cred], start_date, end_date)
    safe_with = calculate_amount_safe_to_pay(
        prof, Decimal("5000"), start_date, end_date, b_with, [deb, pending_cred]
    )
    earliest_with = calculate_earliest_date_for_full_payment(
        prof, Decimal("5000"), start_date, end_date, b_with, [deb, pending_cred]
    )

    assert safe_with == safe_without
    assert earliest_with == earliest_without
    assert b_with.min_balance_projected == b_without.min_balance_projected


def test_inv_c_debit_monotonicity() -> None:
    """INV-C: Increasing an outflow cannot increase amount_safe_to_pay or advance earliest date."""
    prof = _make_profile(Decimal("5000"), Decimal("1000"))
    start = date(2025, 6, 1)
    start_date, end_date = get_forecast_window(start, 90)

    # Smaller debit 1000 vs larger debit 2500
    deb_small = _make_event(
        "d_small",
        date(2025, 6, 10),
        date(2025, 6, 10),
        Decimal("1000"),
        EventDirection.DEBIT,
        ForecastBehavior.FUTURE_CONFIRMED_DEBIT,
    )
    b_small = simulate(prof, [deb_small], start_date, end_date)
    safe_small = calculate_amount_safe_to_pay(
        prof, Decimal("4000"), start_date, end_date, b_small, [deb_small]
    )

    deb_large = _make_event(
        "d_large",
        date(2025, 6, 10),
        date(2025, 6, 10),
        Decimal("2500"),
        EventDirection.DEBIT,
        ForecastBehavior.FUTURE_CONFIRMED_DEBIT,
    )
    b_large = simulate(prof, [deb_large], start_date, end_date)
    safe_large = calculate_amount_safe_to_pay(
        prof, Decimal("4000"), start_date, end_date, b_large, [deb_large]
    )

    assert safe_large <= safe_small


def test_inv_d_minimum_balance_safety_guarantee() -> None:
    """INV-D: Paying safe amount today guarantees balance >= min_balance on all days."""
    prof = _make_profile(Decimal("6000"), Decimal("2000"))
    start = date(2025, 6, 1)
    start_date, end_date = get_forecast_window(start, 90)

    events = [
        _make_event(
            "deb1",
            date(2025, 6, 8),
            date(2025, 6, 8),
            Decimal("1500"),
            EventDirection.DEBIT,
            ForecastBehavior.FUTURE_CONFIRMED_DEBIT,
        ),
        _make_event(
            "sal1",
            date(2025, 6, 15),
            date(2025, 6, 15),
            Decimal("3000"),
            EventDirection.CREDIT,
            ForecastBehavior.FUTURE_CONFIRMED_CREDIT,
        ),
        _make_event(
            "deb2",
            date(2025, 7, 5),
            date(2025, 7, 5),
            Decimal("2800"),
            EventDirection.DEBIT,
            ForecastBehavior.FUTURE_CONFIRMED_DEBIT,
        ),
    ]

    baseline = simulate(prof, events, start_date, end_date)
    safe_amount = calculate_amount_safe_to_pay(
        prof, Decimal("10000"), start_date, end_date, baseline, events
    )

    # Replay simulation with hypothetical payment of safe_amount on start_date
    replay = simulate(
        profile=prof,
        resolved_events=events,
        start_date=start_date,
        end_date=end_date,
        hypothetical_payments=((start_date, safe_amount),),
    )

    assert replay.is_safe is True
    assert len(replay.breach_dates) == 0
    assert replay.min_balance_projected >= prof.minimum_balance_to_keep


def test_inv_e_income_monotonicity() -> None:
    """INV-E: Increasing confirmed income cannot decrease safe amount or delay earliest date."""
    prof = _make_profile(Decimal("2000"), Decimal("1000"))
    start = date(2025, 6, 1)
    start_date, end_date = get_forecast_window(start, 90)

    sal_lower = _make_event(
        "s_low",
        date(2025, 6, 15),
        date(2025, 6, 15),
        Decimal("3000"),
        EventDirection.CREDIT,
        ForecastBehavior.FUTURE_CONFIRMED_CREDIT,
    )
    b_low = simulate(prof, [sal_lower], start_date, end_date)
    earliest_low = calculate_earliest_date_for_full_payment(
        prof, Decimal("3500"), start_date, end_date, b_low, [sal_lower]
    )

    sal_higher = _make_event(
        "s_high",
        date(2025, 6, 15),
        date(2025, 6, 15),
        Decimal("6000"),
        EventDirection.CREDIT,
        ForecastBehavior.FUTURE_CONFIRMED_CREDIT,
    )
    b_high = simulate(prof, [sal_higher], start_date, end_date)
    earliest_high = calculate_earliest_date_for_full_payment(
        prof, Decimal("3500"), start_date, end_date, b_high, [sal_higher]
    )

    # If lower was safe on 6-15, higher must also be safe on or before 6-15
    assert earliest_high is not None
    if earliest_low is not None:
        assert earliest_high <= earliest_low


def test_inv_f_delayed_income_cannot_advance_earliest_date() -> None:
    """INV-F: Delaying salary from day 15 to day 25 cannot make full payment safe earlier."""
    prof = _make_profile(Decimal("1000"), Decimal("1000"))
    start = date(2025, 6, 1)
    start_date, end_date = get_forecast_window(start, 90)

    s15 = _make_event(
        "s15",
        date(2025, 6, 15),
        date(2025, 6, 15),
        Decimal("5000"),
        EventDirection.CREDIT,
        ForecastBehavior.FUTURE_CONFIRMED_CREDIT,
    )
    b15 = simulate(prof, [s15], start_date, end_date)
    e15 = calculate_earliest_date_for_full_payment(
        prof, Decimal("3000"), start_date, end_date, b15, [s15]
    )

    s25 = _make_event(
        "s25",
        date(2025, 6, 25),
        date(2025, 6, 25),
        Decimal("5000"),
        EventDirection.CREDIT,
        ForecastBehavior.FUTURE_CONFIRMED_CREDIT,
    )
    b25 = simulate(prof, [s25], start_date, end_date)
    e25 = calculate_earliest_date_for_full_payment(
        prof, Decimal("3000"), start_date, end_date, b25, [s25]
    )

    assert e15 == date(2025, 6, 15)
    assert e25 == date(2025, 6, 25)
    assert e25 > e15


def test_inv_g_unrealized_and_non_cash_neutrality() -> None:
    """INV-G: Unrealized investment values and non-cash events do not affect balances."""
    prof = _make_profile(Decimal("5000"), Decimal("1000"))
    start = date(2025, 6, 1)
    start_date, end_date = get_forecast_window(start, 90)

    b_clean = simulate(prof, [], start_date, end_date)

    unrealized = _make_event(
        "unrealized_inv",
        date(2025, 6, 10),
        date(2025, 6, 10),
        Decimal("50000"),
        EventDirection.CREDIT,
        ForecastBehavior.IGNORED_UNREALIZED,
    )
    non_cash = _make_event(
        "non_cash_flow",
        date(2025, 6, 12),
        date(2025, 6, 12),
        Decimal("25000"),
        EventDirection.NON_CASH,
        ForecastBehavior.IGNORED_NON_CASH,
    )

    b_with_ignored = simulate(prof, [unrealized, non_cash], start_date, end_date)

    assert b_with_ignored.is_safe == b_clean.is_safe
    assert b_with_ignored.min_balance_projected == b_clean.min_balance_projected
    assert b_with_ignored.min_headroom_projected == b_clean.min_headroom_projected
    assert b_with_ignored.daily_balances == b_clean.daily_balances
