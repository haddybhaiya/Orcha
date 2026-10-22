"""Tests for DatasetRepository indexing, lookups, normalization, and integrity audit."""

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from orcha.audit import format_audit_report, run_dataset_audit
from orcha.models import (
    EventDirection,
    EventStatus,
    EventType,
    FinancialEvent,
    FinancialProfile,
    FinancialRequest,
    ImageRecord,
    MessageRecord,
    MessageSourceType,
    PaymentOption,
    PaymentOptionMethod,
    RecommendedPaymentMethod,
    RequestType,
)
from orcha.money import ExchangeRateResolver
from orcha.planning.engine import DecisionEngine
from orcha.repository import DatasetRepository


@pytest.fixture
def mock_repository() -> DatasetRepository:
    """Construct an in-memory repository with representative records."""
    req = FinancialRequest(
        request_id="request_01",
        user_id="user_01",
        request_date=date(2024, 3, 3),
        request_type=RequestType.PURCHASE,
        requested_amount=Decimal("25256.00"),
        desired_completion_date=date(2024, 3, 20),
        allows_partial_payment=True,
        request_text="Laptop request",
    )
    prof = FinancialProfile(
        user_id="user_01",
        home_currency="ZAR",
        current_available_balance=Decimal("50000"),
        minimum_balance_to_keep=Decimal("15000"),
        financial_priorities=["education"],
        expense_categories_to_protect=["rent"],
        expense_categories_user_is_willing_to_reduce=["dining"],
        expense_categories_user_is_willing_to_stop=["streaming"],
        payment_methods_user_will_consider=[RecommendedPaymentMethod.FULL_PAYMENT],
    )
    # Event in home currency
    ev1 = FinancialEvent(
        event_id="event_01",
        user_id="user_01",
        event_type=EventType.EXPENSE,
        description="Rent",
        category="rent",
        direction=EventDirection.DEBIT,
        amount=Decimal("5000"),
        currency="ZAR",
        event_date=date(2024, 3, 1),
        status=EventStatus.SETTLED,
    )
    # Event with blank amount
    ev_blank = FinancialEvent(
        event_id="event_02",
        user_id="user_01",
        event_type=EventType.EXPENSE,
        description="Receipt missing amount",
        category="groceries",
        direction=EventDirection.DEBIT,
        amount=None,
        currency="ZAR",
        event_date=date(2024, 3, 2),
        status=EventStatus.SETTLED,
    )
    opt = PaymentOption(
        payment_option_id="opt_01",
        request_id="request_01",
        payment_method=PaymentOptionMethod.FULL_PAYMENT,
        payment_amount=Decimal("25256.00"),
        number_of_payments=1,
        first_payment_date=date(2024, 3, 3),
        total_payable_amount=Decimal("25256.00"),
    )
    msg = MessageRecord(
        message_id="msg_01",
        user_id="user_01",
        request_id="request_01",
        related_event_id="event_01",
        sent_at=datetime(2024, 3, 1, 12, 0, 0),
        source_type=MessageSourceType.BANK,
        message_text="Rent payment processed",
    )
    img = ImageRecord(
        image_id="img_01",
        user_id="user_01",
        request_id="request_01",
        related_event_id="event_02",
    )

    from orcha.models import NormalizedFinancialEvent

    norm1 = NormalizedFinancialEvent(
        event_id=ev1.event_id,
        user_id=ev1.user_id,
        event_type=ev1.event_type,
        description=ev1.description,
        category=ev1.category,
        direction=ev1.direction,
        amount=ev1.amount,
        currency=ev1.currency,
        event_date=ev1.event_date,
        status=ev1.status,
        amount_home_currency=Decimal("5000"),
        home_currency="ZAR",
    )
    norm_blank = NormalizedFinancialEvent(
        event_id=ev_blank.event_id,
        user_id=ev_blank.user_id,
        event_type=ev_blank.event_type,
        description=ev_blank.description,
        category=ev_blank.category,
        direction=ev_blank.direction,
        amount=None,
        currency=ev_blank.currency,
        event_date=ev_blank.event_date,
        status=ev_blank.status,
        amount_home_currency=None,
        home_currency="ZAR",
    )

    return DatasetRepository(
        requests=[req],
        profiles={"user_01": prof},
        events=[norm1, norm_blank],
        payment_options={"request_01": [opt]},
        messages=[msg],
        images=[img],
        fx_resolver=ExchangeRateResolver(),
    )


def test_repository_lookups(mock_repository: DatasetRepository) -> None:
    repo = mock_repository
    assert repo.get_profile("user_01").home_currency == "ZAR"
    assert repo.get_request("request_01").requested_amount == Decimal("25256.00")
    assert len(repo.get_events_for_user("user_01")) == 2
    assert repo.get_event("event_01").amount_home_currency == Decimal("5000")
    assert repo.get_event("event_02").amount is None
    assert repo.get_event("event_02").amount_home_currency is None

    assert len(repo.get_payment_options("request_01")) == 1
    assert len(repo.get_messages_for_user("user_01")) == 1
    assert len(repo.get_messages_for_request("request_01")) == 1
    assert len(repo.get_messages_for_event("event_01")) == 1

    assert len(repo.get_images_for_user("user_01")) == 1
    assert repo.get_image_for_event("event_02") is not None
    assert repo.get_image_for_event("event_01") is None


def test_repository_missing_keys_raise(mock_repository: DatasetRepository) -> None:
    repo = mock_repository
    with pytest.raises(KeyError, match="Profile not found"):
        repo.get_profile("unknown_user")

    with pytest.raises(KeyError, match="Request not found"):
        repo.get_request("unknown_req")

    with pytest.raises(KeyError, match="Event not found"):
        repo.get_event("unknown_event")


def test_sample_id_collision_cannot_overwrite_production_request(
    mock_repository: DatasetRepository,
) -> None:
    production = mock_repository.get_request("request_01")
    sample = production.model_copy(update={"requested_amount": Decimal("1")})
    repo = DatasetRepository(
        requests=[production],
        profiles=mock_repository.all_profiles,
        events=mock_repository.all_events,
        payment_options=mock_repository.all_payment_options,
        messages=mock_repository.all_messages,
        images=mock_repository.all_images,
        fx_resolver=mock_repository.fx_resolver,
        sample_requests=[sample],
    )

    assert repo.get_request("request_01").requested_amount == Decimal("25256.00")
    assert repo.get_sample_request("request_01").requested_amount == Decimal("1")


def test_real_dataset_smoke_and_audit() -> None:
    """Load the full real dataset from dataset/ and verify exact observed counts."""
    dataset_dir = Path("dataset") if Path("dataset").is_dir() else Path("../dataset")
    repo = DatasetRepository.load_from_dir(dataset_dir, include_samples=True)

    # Assert the original dataset dimensions
    assert len(repo.all_requests) == 250
    assert len(repo.sample_requests) == 25
    assert len(repo.all_profiles) == 275
    assert len(repo.all_events) == 25342
    assert len(repo.all_messages) == 215
    assert len(repo.all_images) == 16
    assert len(repo.fx_resolver.supported_pairs) == 5

    # Run audit and verify zero defects
    audit_results = run_dataset_audit(repo)
    report_text = format_audit_report(audit_results)
    assert "PASS (Zero defects detected)" in report_text
    assert audit_results["blank_amounts"]["total_blank"] == 16
    assert audit_results["blank_amounts"]["covered_by_images"] == 16
    assert len(audit_results["blank_amounts"]["uncovered"]) == 0
    assert audit_results["foreign_events"]["total_foreign"] == 140
    assert audit_results["foreign_events"]["covered_by_fx"] == 140


def test_default_repository_load_excludes_sample_oracle() -> None:
    """Production construction is invariant to the presence of sample labels."""
    dataset_dir = Path("dataset") if Path("dataset").is_dir() else Path("../dataset")
    repo = DatasetRepository.load_from_dir(dataset_dir)

    assert len(repo.all_requests) == 250
    assert repo.sample_requests == []
    with pytest.raises(KeyError, match="Sample request not found"):
        repo.get_sample_request("request_01")


def test_consistent_request_and_user_id_rename_is_decision_invariant(
    mock_repository: DatasetRepository,
) -> None:
    """Identifiers are lookup keys only and cannot influence financial decisions."""
    request = mock_repository.get_request("request_01")
    profile = mock_repository.get_profile("user_01")
    option = mock_repository.get_payment_options("request_01")[0]
    clean_original = DatasetRepository(
        requests=[request],
        profiles={profile.user_id: profile},
        events=[],
        payment_options={request.request_id: [option]},
        messages=[],
        images=[],
        fx_resolver=mock_repository.fx_resolver,
    )
    renamed_request = request.model_copy(
        update={"request_id": "opaque_request_key", "user_id": "opaque_user_key"}
    )
    renamed_profile = profile.model_copy(update={"user_id": "opaque_user_key"})
    renamed_option = option.model_copy(update={"request_id": "opaque_request_key"})
    clean_renamed = DatasetRepository(
        requests=[renamed_request],
        profiles={renamed_profile.user_id: renamed_profile},
        events=[],
        payment_options={renamed_request.request_id: [renamed_option]},
        messages=[],
        images=[],
        fx_resolver=mock_repository.fx_resolver,
    )

    original = DecisionEngine(clean_original).evaluate_request(request.request_id)
    renamed = DecisionEngine(clean_renamed).evaluate_request(renamed_request.request_id)

    assert original.model_dump(exclude={"request_id"}) == renamed.model_dump(exclude={"request_id"})
