"""Synthetic scenario tests A through H for cash-flow forecasting."""

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
        user_id="user_scenarios",
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
    description: str = "Test event",
    amount_source: str = "event",
) -> ResolvedFinancialEvent:
    return ResolvedFinancialEvent(
        canonical_event_id=event_id,
        user_id="user_scenarios",
        event_type="scenario_event",
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
        amount_source=amount_source,
    )


def test_scenario_a_future_rent_reduces_headroom() -> None:
    """Scenario A: Upcoming scheduled rent debit reduces safe capacity today."""
    prof = _make_profile(Decimal("5000"), Decimal("1000"))
    start = date(2025, 6, 1)
    start_date, end_date = get_forecast_window(start, 90)

    rent = _make_event(
        "ev_rent",
        date(2025, 6, 15),
        date(2025, 6, 15),
        Decimal("2500"),
        EventDirection.DEBIT,
        ForecastBehavior.FUTURE_CONFIRMED_DEBIT,
        description="Apartment rent",
    )
    baseline = simulate(prof, [rent], start_date, end_date)
    assert baseline.min_headroom_projected == Decimal("1500")

    safe_today = calculate_amount_safe_to_pay(
        prof, Decimal("3000"), start_date, end_date, baseline, [rent]
    )
    assert safe_today == Decimal("1500")


def test_scenario_b_delayed_salary_moves_earliest_date() -> None:
    """Scenario B: Delaying confirmed salary moves earliest safe date for full payment."""
    prof = _make_profile(Decimal("2000"), Decimal("1000"))
    start = date(2025, 6, 1)
    start_date, end_date = get_forecast_window(start, 90)

    salary_day15 = _make_event(
        "ev_salary1",
        date(2025, 6, 15),
        date(2025, 6, 15),
        Decimal("5000"),
        EventDirection.CREDIT,
        ForecastBehavior.FUTURE_CONFIRMED_CREDIT,
        description="Employer payroll",
    )
    b1 = simulate(prof, [salary_day15], start_date, end_date)
    earliest1 = calculate_earliest_date_for_full_payment(
        prof, Decimal("4000"), start_date, end_date, b1, [salary_day15]
    )
    assert earliest1 == date(2025, 6, 15)

    salary_day20 = _make_event(
        "ev_salary2",
        date(2025, 6, 20),
        date(2025, 6, 20),
        Decimal("5000"),
        EventDirection.CREDIT,
        ForecastBehavior.FUTURE_CONFIRMED_CREDIT,
        description="Employer payroll delayed",
    )
    b2 = simulate(prof, [salary_day20], start_date, end_date)
    earliest2 = calculate_earliest_date_for_full_payment(
        prof, Decimal("4000"), start_date, end_date, b2, [salary_day20]
    )
    assert earliest2 == date(2025, 6, 20)


def test_scenario_c_pending_credit_never_counted() -> None:
    """Scenario C: Unsettled incoming credit must NOT increase cash or headroom."""
    prof = _make_profile(Decimal("2000"), Decimal("1000"))
    start = date(2025, 6, 1)
    start_date, end_date = get_forecast_window(start, 90)

    pending_bonus = _make_event(
        "ev_bonus",
        date(2025, 6, 10),
        date(2025, 6, 10),
        Decimal("10000"),
        EventDirection.CREDIT,
        ForecastBehavior.IGNORED_PENDING_CREDIT,
        description="Expected bonus payout",
    )
    baseline = simulate(prof, [pending_bonus], start_date, end_date)
    assert baseline.min_headroom_projected == Decimal("1000")

    safe = calculate_amount_safe_to_pay(
        prof, Decimal("5000"), start_date, end_date, baseline, [pending_bonus]
    )
    assert safe == Decimal("1000")

    earliest = calculate_earliest_date_for_full_payment(
        prof, Decimal("5000"), start_date, end_date, baseline, [pending_bonus]
    )
    assert earliest is None


def test_scenario_d_scheduled_pending_debit_reserved() -> None:
    """Scenario D: Pending or scheduled debit is strictly reserved against available cash."""
    prof = _make_profile(Decimal("5000"), Decimal("1000"))
    start = date(2025, 6, 1)
    start_date, end_date = get_forecast_window(start, 90)

    pending_debit = _make_event(
        "ev_pend_deb",
        date(2025, 6, 5),
        date(2025, 6, 5),
        Decimal("2000"),
        EventDirection.DEBIT,
        ForecastBehavior.FUTURE_PENDING_DEBIT,
        description="Pending card pre-authorization",
    )
    baseline = simulate(prof, [pending_debit], start_date, end_date)
    assert baseline.min_headroom_projected == Decimal("2000")
    safe = calculate_amount_safe_to_pay(
        prof, Decimal("3000"), start_date, end_date, baseline, [pending_debit]
    )
    assert safe == Decimal("2000")


def test_scenario_e_temporary_salary_dip_and_recovery() -> None:
    """Scenario E: Single-month salary dip recovers in subsequent month."""
    prof = _make_profile(Decimal("3500"), Decimal("1000"))
    start = date(2025, 6, 1)
    start_date, end_date = get_forecast_window(start, 90)

    # Monthly expense 2000 on the 10th
    exp1 = _make_event(
        "e1",
        date(2025, 6, 10),
        date(2025, 6, 10),
        Decimal("2000"),
        EventDirection.DEBIT,
        ForecastBehavior.FUTURE_CONFIRMED_DEBIT,
    )
    exp2 = _make_event(
        "e2",
        date(2025, 7, 10),
        date(2025, 7, 10),
        Decimal("2000"),
        EventDirection.DEBIT,
        ForecastBehavior.FUTURE_CONFIRMED_DEBIT,
    )

    # June salary has temporary dip to 2000, July salary recovers to 3500
    sal1 = _make_event(
        "s1",
        date(2025, 6, 15),
        date(2025, 6, 15),
        Decimal("2000"),
        EventDirection.CREDIT,
        ForecastBehavior.FUTURE_CONFIRMED_CREDIT,
    )
    sal2 = _make_event(
        "s2",
        date(2025, 7, 15),
        date(2025, 7, 15),
        Decimal("3500"),
        EventDirection.CREDIT,
        ForecastBehavior.FUTURE_CONFIRMED_CREDIT,
    )

    events = [exp1, exp2, sal1, sal2]
    baseline = simulate(prof, events, start_date, end_date)
    assert baseline.is_safe is True
    # Min balance occurs on June 10 after exp1 (3500 - 2000 = 1500) and July 10 (3500 - 2000 = 1500)
    assert baseline.min_balance_projected == Decimal("1500")
    assert baseline.min_headroom_projected == Decimal("500")


def test_scenario_f_weekly_essentials_stepped_drawdown() -> None:
    """Scenario F: Weekly grocery debits step down balance every 7 days."""
    prof = _make_profile(Decimal("5000"), Decimal("1000"))
    start = date(2025, 6, 1)
    start_date, end_date = get_forecast_window(start, 90)

    events = []
    for week in range(1, 5):
        d = date(2025, 6, 1 + (week * 7))
        events.append(
            _make_event(
                f"g_{week}",
                d,
                d,
                Decimal("500"),
                EventDirection.DEBIT,
                ForecastBehavior.FUTURE_CONFIRMED_DEBIT,
                description="Weekly grocery",
            )
        )

    baseline = simulate(prof, events, start_date, end_date)
    assert baseline.is_safe is True
    assert baseline.daily_balances[date(2025, 6, 8)] == Decimal("4500")
    assert baseline.daily_balances[date(2025, 6, 15)] == Decimal("4000")
    assert baseline.daily_balances[date(2025, 6, 22)] == Decimal("3500")
    assert baseline.daily_balances[date(2025, 6, 29)] == Decimal("3000")


def test_scenario_g_month_boundary_progression() -> None:
    """Scenario G: End of month dates step correctly across 28/30/31 days."""
    prof = _make_profile(Decimal("10000"), Decimal("1000"))
    start = date(2025, 1, 31)
    start_date, end_date = get_forecast_window(start, 90)

    deb_jan = _make_event(
        "d_jan",
        date(2025, 1, 31),
        date(2025, 1, 31),
        Decimal("1000"),
        EventDirection.DEBIT,
        ForecastBehavior.FUTURE_CONFIRMED_DEBIT,
    )
    deb_feb = _make_event(
        "d_feb",
        date(2025, 2, 28),
        date(2025, 2, 28),
        Decimal("1000"),
        EventDirection.DEBIT,
        ForecastBehavior.FUTURE_CONFIRMED_DEBIT,
    )
    deb_mar = _make_event(
        "d_mar",
        date(2025, 3, 31),
        date(2025, 3, 31),
        Decimal("1000"),
        EventDirection.DEBIT,
        ForecastBehavior.FUTURE_CONFIRMED_DEBIT,
    )

    baseline = simulate(prof, [deb_jan, deb_feb, deb_mar], start_date, end_date)
    assert baseline.daily_balances[date(2025, 1, 31)] == Decimal("9000")
    assert baseline.daily_balances[date(2025, 2, 28)] == Decimal("8000")
    assert baseline.daily_balances[date(2025, 3, 31)] == Decimal("7000")


def test_scenario_h_image_receipt_source_outflow() -> None:
    """Scenario H: Blank amount resolved from image is accounted for as a cash outflow."""
    prof = _make_profile(Decimal("5000"), Decimal("1000"))
    start = date(2025, 6, 1)
    start_date, end_date = get_forecast_window(start, 90)

    image_event = _make_event(
        "ev_img_receipt",
        date(2025, 6, 5),
        date(2025, 6, 5),
        Decimal("1250.75"),
        EventDirection.DEBIT,
        ForecastBehavior.FUTURE_CONFIRMED_DEBIT,
        description="Resolved medical bill from image",
        amount_source="image:image_03",
    )
    baseline = simulate(prof, [image_event], start_date, end_date)
    assert baseline.is_safe is True
    assert baseline.min_balance_projected == Decimal("3749.25")
    assert baseline.min_headroom_projected == Decimal("2749.25")
    assert "ev_img_receipt" in baseline.included_event_ids
