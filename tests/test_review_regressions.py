"""Reproductions of the financial integrity failures found in the read-only review."""

import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from dotenv import dotenv_values

from orcha.demo import DATASET_DIR
from orcha.evaluation import validate_final_rows
from orcha.evidence.gemma import GemmaConfig
from orcha.evidence.images import ImageEvidenceExtractor
from orcha.evidence.models import ImageEvidence
from orcha.ledger.models import ForecastBehavior
from orcha.ledger.resolve import resolve_canonical_ledger
from orcha.loaders import load_profiles
from orcha.models import (
    EventDirection,
    EventStatus,
    EventType,
    ExchangeRate,
    FinancialProfile,
    FinancialRequest,
    MessageRecord,
    MessageSourceType,
    NormalizedFinancialEvent,
    PaymentOption,
    PaymentOptionMethod,
    RecommendedPaymentMethod,
    RequestType,
)
from orcha.money import ExchangeRateNotFoundError, ExchangeRateResolver
from orcha.planning.budget import PlanningBudgetExceeded
from orcha.planning.engine import DecisionEngine
from orcha.repository import DatasetRepository
from orcha.simulation.forecast import simulate

DAY = date(2026, 10, 25)


def profile() -> FinancialProfile:
    return FinancialProfile(
        user_id="u",
        home_currency="INR",
        current_available_balance=Decimal("10000"),
        minimum_balance_to_keep=Decimal("1000"),
        payment_methods_user_will_consider=[
            RecommendedPaymentMethod.FULL_PAYMENT,
            RecommendedPaymentMethod.INSTALLMENTS,
        ],
    )


def event(identifier: str = "e", amount: str = "1000") -> NormalizedFinancialEvent:
    return NormalizedFinancialEvent(
        event_id=identifier,
        user_id="u",
        event_type=EventType.EXPENSE,
        description="Bill",
        category="bill",
        direction=EventDirection.DEBIT,
        amount=Decimal(amount),
        currency="INR",
        amount_home_currency=Decimal(amount),
        home_currency="INR",
        event_date=DAY,
        settlement_date=DAY,
        status=EventStatus.SCHEDULED,
    )


def repository(
    events: list[NormalizedFinancialEvent] | None = None,
    messages: list[MessageRecord] | None = None,
    rates: list[ExchangeRate] | None = None,
) -> DatasetRepository:
    return DatasetRepository(
        [], {"u": profile()}, events or [], {}, messages or [], [], ExchangeRateResolver(rates)
    )


def message(text: str, linked: str | None = None) -> MessageRecord:
    return MessageRecord(
        message_id="m",
        user_id="u",
        related_event_id=linked,
        sent_at=datetime(2026, 10, 24),
        source_type=MessageSourceType.EMPLOYER,
        message_text=text,
    )


@pytest.mark.parametrize("field", ["amount", "amount_home_currency", "minimum_allowed_amount"])
def test_negative_event_values_cannot_enter_repository(field: str) -> None:
    with pytest.raises(ValueError, match="non-negative"):
        repository([event().model_copy(update={field: Decimal("-1000")})])


def test_duplicate_income_id_cannot_inflate_balance() -> None:
    income = event().model_copy(update={"direction": "credit", "event_type": "income"})
    with pytest.raises(ValueError, match="Duplicate event"):
        repository([income, income])


def test_duplicate_profile_id_cannot_replace_balance(tmp_path: Path) -> None:
    source = tmp_path / "profiles.csv"
    source.write_text(
        "user_id,home_currency,current_available_balance,minimum_balance_to_keep\n"
        "u,INR,100,10\nu,INR,999999,10\n"
    )
    with pytest.raises(ValueError, match="Duplicate profile"):
        load_profiles(source)


def test_inconsistent_installments_cannot_buy_an_underfunded_purchase() -> None:
    request = FinancialRequest(
        request_id="r",
        user_id="u",
        request_date=DAY,
        request_type=RequestType.PURCHASE,
        requested_amount=Decimal("20000"),
        desired_completion_date=date(2026, 11, 30),
        allows_partial_payment=False,
        request_text="Purchase",
    )
    option = PaymentOption(
        payment_option_id="o",
        request_id="r",
        payment_method=PaymentOptionMethod.INSTALLMENTS,
        payment_amount=Decimal("100"),
        number_of_payments=2,
        first_payment_date=DAY,
        payment_frequency_days=30,
        total_payable_amount=Decimal("20000"),
    )
    repo = DatasetRepository(
        [request], {"u": profile()}, [], {"r": [option]}, [], [], ExchangeRateResolver()
    )
    result = DecisionEngine(repo).evaluate_request("r")
    validate_final_rows([result], repo)
    assert result.affordability_status == "not_affordable"
    assert result.payment_plan == "none"


@pytest.mark.parametrize("phrase", ["is not confirmed", "might arrive", "is unconfirmed"])
def test_uncertain_salary_is_not_spendable(phrase: str) -> None:
    repo = repository(messages=[message(f"First salary INR 50000 {phrase} for 2026-10-26")])
    assert resolve_canonical_ledger(repo, "u", DAY) == []


def test_foreign_salary_requires_a_rate_and_converts_exactly() -> None:
    notice = message("First salary USD 1000 confirmed for 2026-10-26")
    with pytest.raises(ExchangeRateNotFoundError):
        resolve_canonical_ledger(repository(messages=[notice]), "u", DAY)
    repo = repository(
        messages=[notice],
        rates=[
            ExchangeRate(
                rate_date=date(2026, 10, 26),
                from_currency="USD",
                to_currency="INR",
                rate=Decimal("84"),
            )
        ],
    )
    ledger = resolve_canonical_ledger(repo, "u", DAY)
    assert ledger[0].amount_home_currency == Decimal("84000.00")
    assert ledger[0].home_currency == "INR"


def test_linked_salary_amendment_preserves_other_employers() -> None:
    events = []
    for employer, amount in [("A", "1000"), ("B", "500")]:
        for month in [8, 9]:
            events.append(
                event(f"{employer}{month}", amount).model_copy(
                    update={
                        "direction": "credit",
                        "event_type": "income",
                        "category": "salary",
                        "description": f"Employer {employer}",
                        "status": "settled",
                        "event_date": date(2026, month, 25),
                        "settlement_date": date(2026, month, 25),
                    }
                )
            )
    repo = repository(events, [message("Salary increased to INR 2000 effective 2026-10-25", "A9")])
    amounts = {
        item.description: item.amount_home_currency
        for item in resolve_canonical_ledger(repo, "u", DAY)
        if item.settlement_date == DAY and item.is_recurring
    }
    assert amounts == {
        "Recurring Employer A (monthly)": Decimal("2000"),
        "Recurring Employer B (monthly)": Decimal("500"),
    }


def test_overdue_scheduled_debit_remains_reserved() -> None:
    overdue = event().model_copy(
        update={"event_date": date(2026, 10, 24), "settlement_date": date(2026, 10, 24)}
    )
    ledger = resolve_canonical_ledger(repository([overdue]), "u", DAY)
    assert simulate(profile(), ledger, DAY, DAY).ending_balance == Decimal("9000")


@pytest.mark.parametrize("direction", ["debit", "credit"])
def test_settled_today_is_already_in_available_balance(direction: str) -> None:
    settled = event().model_copy(update={"status": "settled", "direction": direction})
    ledger = resolve_canonical_ledger(repository([settled]), "u", DAY)
    assert ledger[0].forecast_behavior == ForecastBehavior.HISTORICAL_ALREADY_IN_BALANCE
    assert simulate(profile(), ledger, DAY, DAY).ending_balance == Decimal("10000")


def test_replaced_image_cannot_reuse_old_amount(tmp_path: Path) -> None:
    source = tmp_path / "image.png"
    source.write_bytes(b"reviewed image")
    evidence = ImageEvidence(
        image_id="image",
        user_id="u",
        request_id=None,
        related_event_id="e",
        amount=Decimal("100"),
        currency="INR",
        document_date=None,
        document_type="receipt",
        description="Receipt",
        source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
    )
    assert ImageEvidenceExtractor.matches_source(evidence, source)
    source.write_bytes(b"new receipt with different amount")
    assert not ImageEvidenceExtractor.matches_source(evidence, source)


def test_large_search_fails_closed_instead_of_returning_partial_result() -> None:
    repo = repository()
    events = []
    categories = [f"category_{i}" for i in range(30)]
    for category in categories:
        for month in [8, 9]:
            events.append(
                event(f"{category}_{month}", "10").model_copy(
                    update={
                        "category": category,
                        "description": category,
                        "status": "settled",
                        "flexibility": "stoppable",
                        "event_date": date(2026, month, 25),
                        "settlement_date": date(2026, month, 25),
                    }
                )
            )
    p = profile().model_copy(update={"expense_categories_user_is_willing_to_stop": categories})
    request = FinancialRequest(
        request_id="r",
        user_id="u",
        request_date=DAY,
        request_type=RequestType.PURCHASE,
        requested_amount=Decimal("100"),
        desired_completion_date=DAY,
        allows_partial_payment=False,
        request_text="Purchase",
    )
    large = DatasetRepository([request], {"u": p}, events, {}, [], [], repo.fx_resolver)
    with pytest.raises(PlanningBudgetExceeded):
        DecisionEngine(large).evaluate_request("r")


def test_dotenv_edits_reload_without_overwriting_process_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("orcha.environment.dotenv_values", dotenv_values)
    monkeypatch.delenv("GEMMA_API_KEY", raising=False)
    source = tmp_path / ".env"
    source.write_text("GEMMA_API_KEY=first-key\n")
    assert GemmaConfig.from_environment().api_key == "first-key"
    source.write_text("GEMMA_API_KEY=second-key\n")
    assert GemmaConfig.from_environment().api_key == "second-key"
    monkeypatch.setenv("GEMMA_API_KEY", "process-key")
    assert GemmaConfig.from_environment().api_key == "process-key"


def test_packaged_demo_matches_documented_checkout_demo() -> None:
    for source in Path("demo/dataset").glob("*.csv"):
        assert source.read_bytes() == (DATASET_DIR / source.name).read_bytes()
    for source in Path("demo").glob("*.json"):
        assert json.loads(source.read_text()) == json.loads(
            (DATASET_DIR.parent / source.name).read_text()
        )
