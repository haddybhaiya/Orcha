"""Test package import and version availability."""

import orcha
from orcha import (
    AppConfig,
    DatasetLoader,
    FinancialEvent,
    FinancialProfile,
    FinancialRequest,
    OutputRow,
    PaymentOption,
    validate_output_rows,
    write_output_csv,
)


def test_package_import() -> None:
    assert orcha.__version__ == "0.1.0"
    assert AppConfig is not None
    assert DatasetLoader is not None
    assert FinancialRequest is not None
    assert FinancialProfile is not None
    assert FinancialEvent is not None
    assert PaymentOption is not None
    assert OutputRow is not None
    assert callable(validate_output_rows)
    assert callable(write_output_csv)
