"""Tests for BaselineEngine batch evaluation and request contract invariants."""

import csv
from decimal import Decimal
from pathlib import Path

import pytest

from orcha.repository import DatasetRepository
from orcha.simulation.engine import BaselineEngine
from orcha.simulation.forecast import simulate
from orcha.simulation.timeline import get_forecast_window


@pytest.fixture
def dataset_dir() -> Path:
    return Path("dataset") if Path("dataset").is_dir() else Path("../dataset")


def test_batch_evaluate_all_250_evaluation_requests(dataset_dir: Path) -> None:
    """Evaluate baseline affordability for all 250 evaluation requests.

    Verifies non-negotiable invariants:
    - 0 <= amount_safe_to_pay <= requested_amount
    - earliest_date_for_full_payment is None or >= request_date
    - If amount_safe_to_pay == requested_amount, earliest_date_for_full_payment == request_date
    - Simulator replay of amount_safe_to_pay never breaches minimum_balance_to_keep
    """
    repo = DatasetRepository.load_from_dir(dataset_dir)
    engine = BaselineEngine(repo)

    assert len(repo.all_requests) == 250

    for req in repo.all_requests:
        b = engine.evaluate(req.request_id)
        prof = repo.get_profile(req.user_id)

        # Invariant: 0 <= amount_safe_to_pay <= requested_amount
        assert Decimal("0") <= b.amount_safe_to_pay <= req.requested_amount

        # Invariant: earliest full payment date
        if b.earliest_date_for_full_payment is not None:
            assert b.earliest_date_for_full_payment >= req.request_date

        # If full amount is safe today, earliest date MUST be today
        if b.amount_safe_to_pay == req.requested_amount:
            assert b.earliest_date_for_full_payment == req.request_date

        # Replay verification: paying amount_safe_to_pay on request_date MUST be safe
        if b.amount_safe_to_pay > Decimal("0"):
            start_date, end_date = get_forecast_window(req.request_date, horizon_days=90)
            resolved_events = engine.get_or_resolve_ledger(
                req.user_id, req.request_date, req.request_id
            )
            replay = simulate(
                profile=prof,
                resolved_events=resolved_events,
                start_date=start_date,
                end_date=end_date,
                hypothetical_payments=((req.request_date, b.amount_safe_to_pay),),
            )
            assert replay.is_safe is True, (
                f"Replay unsafe for {req.request_id}: amount {b.amount_safe_to_pay} "
                f"breached on {replay.failed_date}"
            )


def test_sample_requests_baseline_sanity(dataset_dir: Path) -> None:
    """Sanity check baseline engine against sample requests oracle."""
    repo = DatasetRepository.load_from_dir(dataset_dir, include_samples=True)
    engine = BaselineEngine(repo)

    sample_csv = dataset_dir / "sample_requests.csv"
    with sample_csv.open("r", encoding="utf-8-sig") as f:
        samples = list(csv.DictReader(f))

    assert len(samples) == 25

    for s in samples:
        rid = s["request_id"]
        b = engine.evaluate_sample(rid)
        assert b.amount_safe_to_pay >= Decimal("0")
        assert b.baseline_simulation is not None
        assert len(b.baseline_simulation.daily_records) == 90

        assert b.amount_safe_to_pay <= repo.get_sample_request(rid).requested_amount
