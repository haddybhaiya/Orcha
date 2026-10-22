"""Tests for event lifecycle resolution, state semantics, and conflict precedence."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from orcha.evidence.models import EvidenceType, MessageEvidence
from orcha.ledger.classify import classify_for_forecast
from orcha.ledger.lifecycle import resolve_event_lifecycles
from orcha.ledger.models import ForecastBehavior
from orcha.models import (
    EventDirection,
    EventFlexibility,
    EventStatus,
    EventType,
    NormalizedFinancialEvent,
)
from orcha.repository import DatasetRepository


@pytest.fixture
def dataset_dir() -> Path:
    return Path("dataset") if Path("dataset").is_dir() else Path("../dataset")


def make_event(
    event_id: str,
    status: EventStatus,
    direction: EventDirection,
    settlement_date: date,
    amount: Decimal = Decimal("1000"),
    linked_event_id: str | None = None,
    event_type: str = "expense",
) -> NormalizedFinancialEvent:
    return NormalizedFinancialEvent(
        event_id=event_id,
        user_id="user_test",
        event_type=EventType(event_type),
        description=f"Test event {event_id}",
        category="utilities",
        direction=direction,
        amount=amount,
        currency="INR",
        amount_home_currency=amount,
        home_currency="INR",
        event_date=settlement_date,
        settlement_date=settlement_date,
        status=status,
        linked_event_id=linked_event_id,
        flexibility=EventFlexibility.FIXED,
    )


def test_classify_for_forecast_rules() -> None:
    req_date = date(2026, 9, 13)

    # 1. Historical settled debit: already in balance, not replayed
    past_settled = classify_for_forecast(
        status=EventStatus.SETTLED,
        direction=EventDirection.DEBIT,
        settlement_date=date(2026, 9, 1),
        request_date=req_date,
    )
    assert past_settled == ForecastBehavior.HISTORICAL_ALREADY_IN_BALANCE

    # 2. Future scheduled debit: future confirmed obligation
    future_scheduled = classify_for_forecast(
        status=EventStatus.SCHEDULED,
        direction=EventDirection.DEBIT,
        settlement_date=date(2026, 9, 20),
        request_date=req_date,
    )
    assert future_scheduled == ForecastBehavior.FUTURE_CONFIRMED_DEBIT

    # 3. Pending debit: MUST be reserved conservatively
    pending_debit = classify_for_forecast(
        status=EventStatus.PENDING,
        direction=EventDirection.DEBIT,
        settlement_date=date(2026, 9, 15),
        request_date=req_date,
    )
    assert pending_debit == ForecastBehavior.FUTURE_PENDING_DEBIT

    # 4. Pending credit: MUST NOT be counted as spendable cash
    pending_credit = classify_for_forecast(
        status=EventStatus.PENDING,
        direction=EventDirection.CREDIT,
        settlement_date=date(2026, 9, 20),
        request_date=req_date,
    )
    assert pending_credit == ForecastBehavior.IGNORED_PENDING_CREDIT

    # 5. Failed and cancelled: ignored
    assert (
        classify_for_forecast(
            status=EventStatus.FAILED,
            direction=EventDirection.DEBIT,
            settlement_date=date(2026, 9, 20),
            request_date=req_date,
        )
        == ForecastBehavior.IGNORED_FAILED
    )
    assert (
        classify_for_forecast(
            status=EventStatus.CANCELLED,
            direction=EventDirection.DEBIT,
            settlement_date=date(2026, 9, 20),
            request_date=req_date,
        )
        == ForecastBehavior.IGNORED_CANCELLED
    )

    # 6. Unrealized / non-cash: ignored
    assert (
        classify_for_forecast(
            status=EventStatus.UNREALIZED,
            direction=EventDirection.NON_CASH,
            settlement_date=date(2026, 9, 20),
            request_date=req_date,
        )
        == ForecastBehavior.IGNORED_UNREALIZED
    )


def test_lifecycle_failed_debt_retry() -> None:
    e1 = make_event(
        "e1", EventStatus.FAILED, EventDirection.DEBIT, date(2026, 9, 1), event_type="debt_payment"
    )
    e2 = make_event(
        "e2",
        EventStatus.SCHEDULED,
        EventDirection.DEBIT,
        date(2026, 9, 15),
        linked_event_id="e1",
        event_type="debt_payment",
    )

    result = resolve_event_lifecycles([e1, e2])
    assert "e1" in result.superceded_event_ids
    assert "retry" in result.resolution_reasons["e1"].lower()
    assert "retry" in result.resolution_reasons["e2"].lower()


def test_lifecycle_cancelled_purchase_superceded() -> None:
    e1 = make_event("e1", EventStatus.CANCELLED, EventDirection.DEBIT, date(2026, 9, 1))
    e2 = make_event(
        "e2", EventStatus.SETTLED, EventDirection.DEBIT, date(2026, 9, 5), linked_event_id="e1"
    )

    result = resolve_event_lifecycles([e1, e2])
    assert "e1" in result.superceded_event_ids


def test_internal_transfer_neutralization() -> None:
    d = make_event(
        "d1", EventStatus.SETTLED, EventDirection.DEBIT, date(2026, 9, 10), amount=Decimal("5000")
    )
    c = make_event(
        "c1", EventStatus.SETTLED, EventDirection.CREDIT, date(2026, 9, 10), amount=Decimal("5000")
    )
    msg = MessageEvidence(
        message_id="msg_transfer",
        user_id="user_test",
        request_id=None,
        related_event_id=None,
        sent_at=None,
        source_type="bank",
        evidence_type=EvidenceType.INTERNAL_TRANSFER,
        amount=Decimal("5000"),
        currency="INR",
    )

    result = resolve_event_lifecycles([d, c], [msg])
    assert "d1" in result.neutralized_internal_transfer_ids
    assert "c1" in result.neutralized_internal_transfer_ids


def test_ambiguous_internal_transfer_does_not_erase_cash_flows() -> None:
    events = [
        make_event("d1", EventStatus.SETTLED, EventDirection.DEBIT, date(2026, 9, 10)),
        make_event("c1", EventStatus.SETTLED, EventDirection.CREDIT, date(2026, 9, 10)),
        make_event("d2", EventStatus.SETTLED, EventDirection.DEBIT, date(2026, 9, 11)),
        make_event("c2", EventStatus.SETTLED, EventDirection.CREDIT, date(2026, 9, 11)),
    ]
    message = MessageEvidence(
        message_id="ambiguous",
        user_id="user_test",
        request_id=None,
        related_event_id=None,
        sent_at=None,
        source_type="bank",
        evidence_type=EvidenceType.INTERNAL_TRANSFER,
        amount=Decimal("1000"),
        currency="INR",
    )
    result = resolve_event_lifecycles(events, [message])
    assert result.neutralized_internal_transfer_ids == set()


def test_real_dataset_58_linked_events_handled(dataset_dir: Path) -> None:
    repo = DatasetRepository.load_from_dir(dataset_dir)
    linked_events = [e for e in repo.all_events if e.linked_event_id]
    assert len(linked_events) == 58

    result = resolve_event_lifecycles(repo.all_events)
    # Every linked event has an explicit resolution reason
    for e in linked_events:
        assert e.event_id in result.resolution_reasons
