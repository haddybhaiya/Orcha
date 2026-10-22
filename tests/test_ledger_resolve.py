"""Tests for end-to-end master canonical financial ledger resolution."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from orcha.evidence.images import ImageEvidenceExtractor
from orcha.evidence.messages import MessageEvidenceExtractor
from orcha.ledger.resolve import UnresolvedFinancialEvidenceError, resolve_canonical_ledger
from orcha.repository import DatasetRepository


@pytest.fixture
def dataset_dir() -> Path:
    return Path("dataset") if Path("dataset").is_dir() else Path("../dataset")


def test_resolve_user_03_image_blank_salary(dataset_dir: Path) -> None:
    repo = DatasetRepository.load_from_dir(dataset_dir)
    user_id = "user_03"
    req_date = date(2025, 8, 3)

    resolved = resolve_canonical_ledger(
        repository=repo,
        user_id=user_id,
        request_date=req_date,
    )

    # Event 253 was blank in raw data; must be resolved from image_01 (4365000 IDR)
    ev_253 = next((e for e in resolved if e.canonical_event_id == "event_253"), None)
    assert ev_253 is not None
    assert ev_253.amount_home_currency == Decimal("4365000.00")
    assert ev_253.amount_source == "image:image_01"
    assert "image_01" in ev_253.image_evidence_ids


def test_resolve_user_78_foreign_image_taxi(dataset_dir: Path) -> None:
    repo = DatasetRepository.load_from_dir(dataset_dir)
    user_id = "user_78"
    req_date = date(2025, 10, 1)

    resolved = resolve_canonical_ledger(
        repository=repo,
        user_id=user_id,
        request_date=req_date,
    )

    # Event 7307: Taxi fare from image_12 (33.50 USD converted to INR on 2025-10-01 at 83.33)
    ev_7307 = next((e for e in resolved if e.canonical_event_id == "event_7307"), None)
    assert ev_7307 is not None
    assert ev_7307.original_currency == "USD"
    assert ev_7307.home_currency == "INR"
    assert ev_7307.amount_source == "image:image_12"
    # 33.50 * 83.33 = 2791.555 -> quantized 2791.56
    expected_inr = (Decimal("33.50") * Decimal("83.33")).quantize(Decimal("0.01"))
    assert ev_7307.amount_home_currency == expected_inr


def test_resolve_user_33_image_and_breakdown(dataset_dir: Path) -> None:
    repo = DatasetRepository.load_from_dir(dataset_dir)
    user_id = "user_33"
    req_date = date(2026, 1, 7)

    resolved = resolve_canonical_ledger(
        repository=repo,
        user_id=user_id,
        request_date=req_date,
    )

    # Grocery invoice 3051 resolved from image_06 (1995.00 INR)
    ev_3051 = next((e for e in resolved if e.canonical_event_id == "event_3051"), None)
    assert ev_3051 is not None
    assert ev_3051.amount_home_currency == Decimal("1995.00")
    assert ev_3051.amount_source == "image:image_06"

    # Verify cash flow breakdown
    inflows = [e for e in resolved if e.is_future_cash_inflow]
    outflows = [e for e in resolved if e.is_future_cash_outflow]
    assert len(inflows) > 0
    assert len(outflows) > 0


def test_resolved_events_chronologically_sorted(dataset_dir: Path) -> None:
    repo = DatasetRepository.load_from_dir(dataset_dir)
    resolved = resolve_canonical_ledger(
        repository=repo,
        user_id="user_01",
        request_date=date(2025, 9, 13),
    )
    for i in range(1, len(resolved)):
        assert resolved[i].settlement_date >= resolved[i - 1].settlement_date


def test_missing_image_evidence_fails_instead_of_becoming_zero(
    dataset_dir: Path, tmp_path: Path
) -> None:
    repo = DatasetRepository.load_from_dir(dataset_dir)
    with pytest.raises(UnresolvedFinancialEvidenceError, match="event_253"):
        resolve_canonical_ledger(
            repository=repo,
            user_id="user_03",
            request_date=date(2025, 8, 3),
            image_extractor=ImageEvidenceExtractor(tmp_path / "missing-cache.json"),
        )


def test_all_evaluation_ledgers_resolve_without_duplicate_ids(dataset_dir: Path) -> None:
    repo = DatasetRepository.load_from_dir(dataset_dir)
    images = ImageEvidenceExtractor()
    messages = MessageEvidenceExtractor()
    for request in repo.all_requests:
        ledger = resolve_canonical_ledger(
            repository=repo,
            user_id=request.user_id,
            request_date=request.request_date,
            image_extractor=images,
            message_extractor=messages,
        )
        event_ids = [event.canonical_event_id for event in ledger]
        assert len(event_ids) == len(set(event_ids)), request.request_id
        assert all(event.amount_home_currency >= Decimal("0") for event in ledger)
