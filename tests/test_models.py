"""Test typed data models, Decimal preservation, and enum validation."""

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from orcha.models import (
    AffordabilityStatus,
    CandidatePlan,
    OutputRow,
    PlanPayment,
    RecommendedPaymentMethod,
    SimulationResult,
    SpendingChange,
    SpendingChangeAction,
)


def test_decimal_preservation() -> None:
    """Ensure exact decimal values are preserved without floating-point drift."""
    amt = Decimal("15952906.67")
    payment = PlanPayment(payment_date=date(2025, 8, 8), amount=amt)
    assert payment.amount == Decimal("15952906.67")
    assert payment.to_str() == "2025-08-08:15952906.67"

    reparsed = PlanPayment.from_str("2025-08-08:15952906.67")
    assert reparsed.amount == amt
    assert reparsed.payment_date == date(2025, 8, 8)


def test_spending_change_formatting_and_parsing() -> None:
    """Test spending change string representations and conversions."""
    stop_change = SpendingChange(action=SpendingChangeAction.STOP, event_id="event_14")
    assert stop_change.to_str() == "stop:event_14"
    assert SpendingChange.from_str("stop:event_14") == stop_change

    reduce_change = SpendingChange(
        action=SpendingChangeAction.REDUCE_TO,
        event_id="event_21",
        new_amount=Decimal("100.50"),
    )
    assert reduce_change.to_str() == "reduce_to:event_21:100.5"
    assert SpendingChange.from_str("reduce_to:event_21:100.5") == SpendingChange(
        action=SpendingChangeAction.REDUCE_TO,
        event_id="event_21",
        new_amount=Decimal("100.5"),
    )


def test_output_row_dict_serialization() -> None:
    """Test serialization to dictionary matching output CSV format."""
    row = OutputRow(
        request_id="request_01",
        amount_safe_to_pay=Decimal("25256"),
        affordability_status=AffordabilityStatus.AFFORDABLE_NOW,
        recommended_payment_method=RecommendedPaymentMethod.FULL_PAYMENT,
        payment_plan="2024-03-03:25256",
        earliest_date_for_full_payment=date(2024, 3, 3),
        spending_changes_needed="none",
        decision_explanation="Pay ZAR 25,256 today safely.",
    )
    d = row.to_csv_dict()
    assert d["request_id"] == "request_01"
    assert d["amount_safe_to_pay"] == "25256"
    assert d["affordability_status"] == "affordable_now"
    assert d["recommended_payment_method"] == "full_payment"
    assert d["earliest_date_for_full_payment"] == "2024-03-03"


def test_invalid_enum_rejection() -> None:
    """Ensure invalid enum values fail with ValidationError."""
    with pytest.raises(ValidationError):
        OutputRow(
            request_id="req_err",
            amount_safe_to_pay=Decimal("100"),
            affordability_status="invalid_status",  # type: ignore[arg-type]
            recommended_payment_method=RecommendedPaymentMethod.FULL_PAYMENT,
            payment_plan="none",
            earliest_date_for_full_payment=None,
            spending_changes_needed="none",
            decision_explanation="Test error",
        )


def test_candidate_plan_and_simulation_result() -> None:
    """Verify CandidatePlan and SimulationResult instantiations."""
    plan = CandidatePlan(
        plan_id="plan_01",
        recommended_payment_method=RecommendedPaymentMethod.INSTALLMENTS,
        payment_option_id="payment_option_02",
        total_cost=Decimal("27781.65"),
        is_safe=True,
    )
    assert plan.is_safe is True
    assert plan.total_cost == Decimal("27781.65")

    sim = SimulationResult(
        is_safe=True,
        min_balance_projected=Decimal("18500.00"),
        min_balance_date=date(2024, 4, 1),
    )
    assert sim.is_safe is True
    assert sim.min_balance_projected == Decimal("18500.00")
