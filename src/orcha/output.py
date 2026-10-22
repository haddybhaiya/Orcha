"""Output contract definition, validation, and serialization for Orcha"""

import csv
import re
from collections.abc import Sequence
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from orcha.models import (
    AffordabilityStatus,
    OutputRow,
    RecommendedPaymentMethod,
)

OUTPUT_COLUMNS = [
    "request_id",
    "amount_safe_to_pay",
    "affordability_status",
    "recommended_payment_method",
    "payment_plan",
    "earliest_date_for_full_payment",
    "spending_changes_needed",
    "decision_explanation",
]

_DATE_REGEX = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_PLAN_ITEM_REGEX = re.compile(r"^\d{4}-\d{2}-\d{2}:[0-9]+(\.[0-9]+)?$")
_STOP_REGEX = re.compile(r"^stop:[a-zA-Z0-9_]+$")
_REDUCE_REGEX = re.compile(r"^reduce_to:[a-zA-Z0-9_]+:[0-9]+(\.[0-9]+)?$")


class OutputValidationError(Exception):
    """Raised when output data violates the financial output contract."""


def validate_plan_string(plan_str: str) -> None:
    """Validate payment_plan format."""
    if plan_str == "none":
        return
    items = plan_str.split("|")
    if not items:
        raise OutputValidationError(
            "payment_plan cannot be empty; use 'none' when no payment plan applies."
        )
    for item in items:
        if not _PLAN_ITEM_REGEX.match(item.strip()):
            raise OutputValidationError(
                f"Invalid payment plan entry '{item}'. Expected 'YYYY-MM-DD:amount' or 'none'."
            )


def validate_spending_changes_string(changes_str: str) -> None:
    """Validate spending_changes_needed format and limit."""
    if changes_str == "none":
        return
    items = changes_str.split("|")
    if len(items) > 3:
        raise OutputValidationError(
            f"spending_changes_needed allows <= 3 actions, found {len(items)}: '{changes_str}'"
        )
    for item in items:
        cleaned = item.strip()
        if not (_STOP_REGEX.match(cleaned) or _REDUCE_REGEX.match(cleaned)):
            raise OutputValidationError(
                f"Invalid change '{cleaned}'. Expected stop:<id> or reduce_to:<id>:<amount>."
            )


def validate_output_dict(row: dict[str, str], row_idx: int = 1) -> None:
    """Validate a single row dictionary against the output contract."""
    # Check all required keys exist
    for col in OUTPUT_COLUMNS:
        if col not in row:
            raise OutputValidationError(f"Row {row_idx}: Missing required column '{col}'.")

    req_id = row["request_id"].strip()
    if not req_id:
        raise OutputValidationError(f"Row {row_idx}: 'request_id' cannot be blank.")

    # Validate amount_safe_to_pay
    amt_str = row["amount_safe_to_pay"].strip()
    try:
        amt = Decimal(amt_str)
        if amt < Decimal("0"):
            raise OutputValidationError(
                f"Row {row_idx} ({req_id}): amount_safe_to_pay ({amt}) cannot be negative."
            )
    except (InvalidOperation, ValueError) as e:
        raise OutputValidationError(
            f"Row {row_idx} ({req_id}): Invalid amount_safe_to_pay '{amt_str}': {e}"
        ) from e

    # Validate affordability_status
    aff_str = row["affordability_status"].strip()
    valid_aff = {s.value for s in AffordabilityStatus}
    if aff_str not in valid_aff:
        raise OutputValidationError(
            f"Row {row_idx} ({req_id}): Invalid status '{aff_str}'. Allowed: {sorted(valid_aff)}"
        )

    # Validate recommended_payment_method
    method_str = row["recommended_payment_method"].strip()
    valid_methods = {m.value for m in RecommendedPaymentMethod}
    if method_str not in valid_methods:
        raise OutputValidationError(f"Row {row_idx} ({req_id}): Invalid method '{method_str}'.")

    # Validate payment_plan
    validate_plan_string(row["payment_plan"].strip())

    # Validate earliest_date_for_full_payment
    earliest_str = row["earliest_date_for_full_payment"].strip()
    if earliest_str:
        if not _DATE_REGEX.match(earliest_str):
            raise OutputValidationError(
                f"Row {row_idx} ({req_id}): Invalid date '{earliest_str}'. Expected YYYY-MM-DD."
            )
        try:
            date.fromisoformat(earliest_str)
        except ValueError as e:
            raise OutputValidationError(
                f"Row {row_idx} ({req_id}): Invalid date '{earliest_str}': {e}"
            ) from e

    # Validate spending_changes_needed
    validate_spending_changes_string(row["spending_changes_needed"].strip())

    # Validate decision_explanation
    if not row["decision_explanation"].strip():
        raise OutputValidationError(
            f"Row {row_idx} ({req_id}): 'decision_explanation' cannot be empty."
        )


def validate_output_file(file_path: Path) -> int:
    """Validate an existing output CSV file against the exact specification."""
    if not file_path.is_file():
        raise FileNotFoundError(f"Output file does not exist: {file_path}")

    with file_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        try:
            header = next(reader)
        except StopIteration:
            raise OutputValidationError(f"Output file is empty: {file_path}") from None

        if header != OUTPUT_COLUMNS:
            raise OutputValidationError(
                f"Header mismatch in {file_path}. Expected:\n{OUTPUT_COLUMNS}\nGot:\n{header}"
            )

        row_count = 0
        dict_reader = csv.DictReader(f, fieldnames=header)
        for idx, row in enumerate(dict_reader, start=2):
            validate_output_dict(row, row_idx=idx)
            row_count += 1

    return row_count


def validate_output_rows(rows: Sequence[OutputRow]) -> None:
    """Validate typed OutputRow objects before serialization."""
    for idx, row in enumerate(rows, start=1):
        validate_output_dict(row.to_csv_dict(), row_idx=idx)


def write_output_csv(rows: Sequence[OutputRow], output_path: Path) -> None:
    """Serialize OutputRow objects to CSV preserving exact column order and headers."""
    validate_output_rows(rows)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(row.to_csv_dict())
