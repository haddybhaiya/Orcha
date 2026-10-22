"""Test dataset loaders, file discovery, ID preservation, and error handling."""

from decimal import Decimal
from pathlib import Path

import pytest

from orcha.loaders import (
    DatasetLoader,
    load_payment_options,
    load_profiles,
    load_requests,
)
from orcha.models import RequestType


@pytest.fixture
def temp_dataset(tmp_path: Path) -> Path:
    """Create a minimal mock dataset directory with required files."""
    req_csv = tmp_path / "requests.csv"
    req_csv.write_text(
        "request_id,user_id,request_date,request_type,requested_amount,desired_completion_date,allows_partial_payment,request_text\n"
        'request_01,user_01,2024-03-03,purchase,25256.50,2024-03-20,true,"Laptop request"\n',
        encoding="utf-8",
    )

    prof_csv = tmp_path / "financial_profiles.csv"
    prof_csv.write_text(
        "user_id,home_currency,current_available_balance,minimum_balance_to_keep,financial_priorities,expense_categories_to_protect,expense_categories_user_is_willing_to_reduce,expense_categories_user_is_willing_to_stop,payment_methods_user_will_consider,max_installment_months\n"
        "user_01,ZAR,58481.10,18000,education|debt_repayment,rent|education,dining,delivery_membership,full_payment|installments,12\n",
        encoding="utf-8",
    )

    opts_csv = tmp_path / "request_payment_options.csv"
    opts_csv.write_text(
        "payment_option_id,request_id,payment_method,payment_amount,number_of_payments,first_payment_date,payment_frequency_days,financing_fee,total_payable_amount\n"
        "payment_option_01,request_01,full_payment,25256.50,1,2024-03-03,,0,25256.50\n"
        "payment_option_02,request_01,installments,1852.11,15,2024-03-06,30,2525.65,27781.65\n",
        encoding="utf-8",
    )

    # Empty stubs for remaining required files
    for filename in [
        "financial_events.csv",
        "exchange_rates.csv",
        "messages.csv",
        "images.csv",
        "output.csv",
    ]:
        (tmp_path / filename).write_text("stub\n", encoding="utf-8")

    return tmp_path


def test_missing_required_files_detection(tmp_path: Path) -> None:
    """Ensure missing required dataset files are identified and raise FileNotFoundError."""
    loader = DatasetLoader(tmp_path)
    missing = loader.check_missing_files()
    assert len(missing) == 8
    with pytest.raises(FileNotFoundError):
        loader.validate()


def test_dataset_loader_validation(temp_dataset: Path) -> None:
    """Verify validation passes when all required files are present."""
    loader = DatasetLoader(temp_dataset)
    assert loader.check_missing_files() == []
    loader.validate()


def test_id_and_decimal_preservation(temp_dataset: Path) -> None:
    """Ensure string IDs are preserved without numeric truncation and amounts remain Decimal."""
    requests = load_requests(temp_dataset / "requests.csv")
    assert len(requests) == 1
    req = requests[0]
    assert req.request_id == "request_01"
    assert req.user_id == "user_01"
    assert req.request_type == RequestType.PURCHASE
    assert req.requested_amount == Decimal("25256.50")
    assert req.allows_partial_payment is True

    profiles = load_profiles(temp_dataset / "financial_profiles.csv")
    assert "user_01" in profiles
    prof = profiles["user_01"]
    assert prof.home_currency == "ZAR"
    assert prof.current_available_balance == Decimal("58481.10")
    assert prof.minimum_balance_to_keep == Decimal("18000")
    assert prof.max_installment_months == 12
    assert "education" in prof.financial_priorities

    options = load_payment_options(temp_dataset / "request_payment_options.csv")
    assert "request_01" in options
    assert len(options["request_01"]) == 2
    assert options["request_01"][0].payment_amount == Decimal("25256.50")
