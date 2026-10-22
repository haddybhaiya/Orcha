"""Test output contract schema, column order, formatting, and file validation."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from orcha.models import (
    AffordabilityStatus,
    OutputRow,
    RecommendedPaymentMethod,
)
from orcha.output import (
    OUTPUT_COLUMNS,
    OutputValidationError,
    validate_output_dict,
    validate_output_file,
    validate_output_rows,
    write_output_csv,
)


def test_exact_output_columns_order() -> None:
    """Verify expected output columns and order exactly match financial output contract."""
    expected = [
        "request_id",
        "amount_safe_to_pay",
        "affordability_status",
        "recommended_payment_method",
        "payment_plan",
        "earliest_date_for_full_payment",
        "spending_changes_needed",
        "decision_explanation",
    ]
    assert OUTPUT_COLUMNS == expected


def test_validate_output_dict_valid() -> None:
    """Verify a valid output row dict passes validation."""
    valid_row = {
        "request_id": "request_01",
        "amount_safe_to_pay": "25256",
        "affordability_status": "affordable_now",
        "recommended_payment_method": "full_payment",
        "payment_plan": "2024-03-03:25256",
        "earliest_date_for_full_payment": "2024-03-03",
        "spending_changes_needed": "none",
        "decision_explanation": "Valid test explanation.",
    }
    validate_output_dict(valid_row)


def test_validate_output_dict_invalid_status() -> None:
    """Ensure invalid affordability status raises OutputValidationError."""
    bad_row = {
        "request_id": "request_01",
        "amount_safe_to_pay": "25256",
        "affordability_status": "maybe_affordable",
        "recommended_payment_method": "full_payment",
        "payment_plan": "none",
        "earliest_date_for_full_payment": "",
        "spending_changes_needed": "none",
        "decision_explanation": "Test.",
    }
    with pytest.raises(OutputValidationError, match="Invalid status"):
        validate_output_dict(bad_row)


def test_spending_changes_limit_exceeded() -> None:
    """Ensure more than 3 spending changes raises an error."""
    bad_row = {
        "request_id": "request_01",
        "amount_safe_to_pay": "100",
        "affordability_status": "affordable_with_plan",
        "recommended_payment_method": "installments",
        "payment_plan": "none",
        "earliest_date_for_full_payment": "",
        "spending_changes_needed": "stop:e1|stop:e2|stop:e3|stop:e4",
        "decision_explanation": "Too many changes.",
    }
    with pytest.raises(OutputValidationError, match="allows <= 3 actions"):
        validate_output_dict(bad_row)


def test_write_and_validate_output_csv(tmp_path: Path) -> None:
    """Verify CSV export and validation round-trip."""
    out_file = tmp_path / "test_output.csv"
    row = OutputRow(
        request_id="request_02",
        amount_safe_to_pay=Decimal("17229139.20"),
        affordability_status=AffordabilityStatus.AFFORDABLE_WITH_PLAN,
        recommended_payment_method=RecommendedPaymentMethod.INSTALLMENTS,
        payment_plan="2025-08-08:15952906.67|2025-09-07:15952906.67|2025-10-07:15952906.67",
        earliest_date_for_full_payment=date(2025, 9, 15),
        spending_changes_needed="none",
        decision_explanation="Use 3 installments safely.",
    )

    validate_output_rows([row])
    write_output_csv([row], out_file)

    assert out_file.is_file()
    count = validate_output_file(out_file)
    assert count == 1
