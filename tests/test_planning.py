"""Fast offline tests for payment planning, candidate generation, ranking, and explanation."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from orcha.ledger.models import (
    ForecastBehavior,
    RecurrencePattern,
    ResolvedFinancialEvent,
)
from orcha.models import (
    AffordabilityStatus,
    CandidatePlan,
    EventDirection,
    EventFlexibility,
    EventStatus,
    FinancialProfile,
    FinancialRequest,
    PaymentOption,
    PaymentOptionMethod,
    PlanPayment,
    RecommendedPaymentMethod,
    RequestType,
    SpendingChange,
    SpendingChangeAction,
)
from orcha.planning.engine import DecisionEngine
from orcha.planning.explanations import generate_decision_explanation
from orcha.planning.installments import build_installment_plan, is_option_eligible
from orcha.planning.partial import (
    build_partial_payment_plan,
    can_attempt_partial_payment,
)
from orcha.planning.rank import rank_candidate_plans
from orcha.planning.spending_changes import (
    find_eligible_spending_actions,
    generate_spending_change_combinations,
)
from orcha.planning.verify import verify_plan_safety
from orcha.repository import DatasetRepository


@pytest.fixture
def sample_profile() -> FinancialProfile:
    return FinancialProfile(
        user_id="user_test",
        home_currency="EUR",
        current_available_balance=Decimal("2000"),
        minimum_balance_to_keep=Decimal("500"),
        financial_priorities=["emergency_savings"],
        expense_categories_to_protect=["rent", "groceries"],
        expense_categories_user_is_willing_to_reduce=["dining"],
        expense_categories_user_is_willing_to_stop=["streaming"],
        payment_methods_user_will_consider=[
            RecommendedPaymentMethod.FULL_PAYMENT,
            RecommendedPaymentMethod.PARTIAL_PAYMENT,
            RecommendedPaymentMethod.INSTALLMENTS,
        ],
        max_installment_months=6,
    )


@pytest.fixture
def sample_request() -> FinancialRequest:
    return FinancialRequest(
        request_id="request_test_01",
        user_id="user_test",
        request_date=date(2026, 1, 10),
        request_type=RequestType.PURCHASE,
        requested_amount=Decimal("1200"),
        desired_completion_date=date(2026, 3, 15),
        allows_partial_payment=True,
        request_text="Can I afford this laptop?",
    )


def test_installments_builder(
    sample_request: FinancialRequest, sample_profile: FinancialProfile
) -> None:
    option = PaymentOption(
        payment_option_id="opt_01",
        request_id=sample_request.request_id,
        payment_method=PaymentOptionMethod.INSTALLMENTS,
        payment_amount=Decimal("400"),
        number_of_payments=3,
        first_payment_date=date(2026, 1, 15),
        payment_frequency_days=30,
        financing_fee=Decimal("50"),
        total_payable_amount=Decimal("1250"),
    )

    assert is_option_eligible(option, sample_profile) is True

    plan = build_installment_plan(option, sample_request)
    assert plan.recommended_payment_method == RecommendedPaymentMethod.INSTALLMENTS
    assert plan.payment_option_id == "opt_01"
    assert len(plan.payments) == 3
    assert plan.payments[0].payment_date == date(2026, 1, 15)
    assert plan.payments[1].payment_date == date(2026, 2, 14)
    assert plan.payments[2].payment_date == date(2026, 3, 16)
    assert plan.total_cost == Decimal("1250")
    assert plan.completion_date == date(2026, 3, 16)


def test_partial_payment_builder(
    sample_request: FinancialRequest, sample_profile: FinancialProfile
) -> None:
    safe_amt = Decimal("500")
    earliest_date = date(2026, 2, 15)

    assert (
        can_attempt_partial_payment(sample_request, sample_profile, safe_amt, earliest_date) is True
    )

    plan = build_partial_payment_plan(sample_request, safe_amt, earliest_date)
    assert plan.recommended_payment_method == RecommendedPaymentMethod.PARTIAL_PAYMENT
    assert len(plan.payments) == 2
    assert plan.payments[0].payment_date == sample_request.request_date
    assert plan.payments[0].amount == Decimal("500")
    assert plan.payments[1].payment_date == earliest_date
    assert plan.payments[1].amount == Decimal("700")
    assert plan.payments[0].amount + plan.payments[1].amount == sample_request.requested_amount
    assert plan.total_cost == sample_request.requested_amount
    assert plan.completion_date == earliest_date


def test_spending_changes_permissible(sample_profile: FinancialProfile) -> None:
    def recurring_event(
        event_id: str,
        category: str,
        amount: Decimal,
        flexibility: EventFlexibility,
        minimum: Decimal | None = None,
    ) -> ResolvedFinancialEvent:
        pattern = RecurrencePattern(
            category=category,
            frequency_days=30,
            anchor_date=date(2025, 12, 1),
            amount_home_currency=amount,
            direction=EventDirection.DEBIT,
            source_event_ids=(event_id,),
            flexibility=flexibility,
            minimum_allowed_amount=minimum,
        )
        return ResolvedFinancialEvent(
            canonical_event_id=f"rec_{event_id}",
            user_id=sample_profile.user_id,
            event_type="recurring_expense",
            description=f"Recurring {category}",
            category=category,
            direction=EventDirection.DEBIT,
            amount_home_currency=amount,
            home_currency="EUR",
            original_amount=amount,
            original_currency="EUR",
            event_date=date(2026, 1, 15),
            settlement_date=date(2026, 1, 15),
            resolved_status=EventStatus.SCHEDULED,
            forecast_behavior=ForecastBehavior.FUTURE_CONFIRMED_DEBIT,
            flexibility=flexibility,
            minimum_allowed_amount=minimum,
            is_recurring=True,
            recurrence_pattern=pattern,
            source_event_ids=(event_id,),
        )

    events = [
        recurring_event("e_rent", "rent", Decimal("800"), EventFlexibility.STOPPABLE),
        recurring_event("e_stream", "streaming", Decimal("20"), EventFlexibility.STOPPABLE),
        recurring_event(
            "e_dining",
            "dining",
            Decimal("100"),
            EventFlexibility.REDUCIBLE,
            Decimal("40"),
        ),
    ]

    actions = find_eligible_spending_actions(sample_profile, events)
    # Rent is protected, so only streaming and dining are eligible
    assert len(actions) == 2
    ch_map = {a[0].event_id: a for a in actions}

    assert "e_rent" not in ch_map
    assert "e_stream" in ch_map
    assert ch_map["e_stream"][0].action == SpendingChangeAction.STOP
    assert ch_map["e_stream"][1] == Decimal("20")

    assert "e_dining" in ch_map
    assert ch_map["e_dining"][0].action == SpendingChangeAction.REDUCE_TO
    assert ch_map["e_dining"][0].new_amount == Decimal("40")
    assert ch_map["e_dining"][1] == Decimal("60")

    combos = generate_spending_change_combinations(sample_profile, events, max_changes=3)
    assert len(combos) == 3  # (stream), (dining), (stream + dining)


def test_plan_ranking_hierarchy(sample_request: FinancialRequest) -> None:
    plan_on_time = CandidatePlan(
        plan_id="p1",
        recommended_payment_method=RecommendedPaymentMethod.FULL_PAYMENT,
        payments=[PlanPayment(payment_date=date(2026, 1, 10), amount=Decimal("1200"))],
        total_cost=Decimal("1200"),
        completion_date=date(2026, 1, 10),
    )
    plan_late = CandidatePlan(
        plan_id="p2",
        recommended_payment_method=RecommendedPaymentMethod.WAIT,
        payments=[PlanPayment(payment_date=date(2026, 4, 1), amount=Decimal("1200"))],
        total_cost=Decimal("1200"),
        completion_date=date(2026, 4, 1),
    )
    plan_with_change = CandidatePlan(
        plan_id="p3",
        recommended_payment_method=RecommendedPaymentMethod.FULL_PAYMENT,
        payments=[PlanPayment(payment_date=date(2026, 1, 10), amount=Decimal("1200"))],
        spending_changes=[SpendingChange(action=SpendingChangeAction.STOP, event_id="e1")],
        total_cost=Decimal("1200"),
        completion_date=date(2026, 1, 10),
    )

    ranked = rank_candidate_plans([plan_late, plan_with_change, plan_on_time], sample_request)
    assert ranked[0].plan_id == "p1"  # On-time with 0 changes
    assert ranked[1].plan_id == "p3"  # On-time with 1 change
    assert ranked[2].plan_id == "p2"  # Late completion


def test_plan_ranking_each_tiebreak_is_independent(sample_request: FinancialRequest) -> None:
    """Each published tie-break must decide the result, not insertion order."""

    def plan(
        plan_id: str,
        payments: list[PlanPayment],
        cost: Decimal = Decimal("1200"),
        changes: list[SpendingChange] | None = None,
        option_id: str | None = None,
    ) -> CandidatePlan:
        return CandidatePlan(
            plan_id=plan_id,
            recommended_payment_method=RecommendedPaymentMethod.INSTALLMENTS,
            payment_option_id=option_id,
            payments=payments,
            spending_changes=changes or [],
            total_cost=cost,
            completion_date=payments[-1].payment_date,
        )

    jan10 = PlanPayment(payment_date=date(2026, 1, 10), amount=Decimal("1200"))
    jan11 = PlanPayment(payment_date=date(2026, 1, 11), amount=Decimal("600"))
    feb10 = PlanPayment(payment_date=date(2026, 2, 10), amount=Decimal("600"))
    apr10 = PlanPayment(payment_date=date(2026, 4, 10), amount=Decimal("1200"))
    stop = SpendingChange(action=SpendingChangeAction.STOP, event_id="e_optional")

    cases = [
        (plan("late", [apr10]), plan("on_time", [jan10])),
        (plan("changed", [jan10], changes=[stop]), plan("unchanged", [jan10])),
        (plan("costly", [jan10], Decimal("1201")), plan("cheap", [jan10])),
        (plan("later_start", [jan11, feb10]), plan("earlier_start", [jan10, feb10])),
        (plan("more_payments", [jan10, jan11]), plan("fewer_payments", [jan10])),
        (
            plan("option_b", [jan10], option_id="option_b"),
            plan("option_a", [jan10], option_id="option_a"),
        ),
    ]
    for worse, better in cases:
        assert rank_candidate_plans([worse, better], sample_request)[0].plan_id == better.plan_id


def test_verifier_rejects_late_and_malformed_plans(
    sample_request: FinancialRequest, sample_profile: FinancialProfile
) -> None:
    late = CandidatePlan(
        plan_id="late",
        recommended_payment_method=RecommendedPaymentMethod.WAIT,
        payments=[PlanPayment(payment_date=date(2026, 4, 1), amount=Decimal("1200"))],
        total_cost=Decimal("1200"),
        completion_date=date(2026, 4, 1),
    )
    safe, result = verify_plan_safety(
        sample_profile,
        [],
        late,
        sample_request,
        [],
        date(2026, 4, 9),
    )
    assert safe is False
    assert result.failure_reason == "the request must be completed by desired_completion_date"

    malformed_partial = CandidatePlan(
        plan_id="bad_partial",
        recommended_payment_method=RecommendedPaymentMethod.PARTIAL_PAYMENT,
        payments=[
            PlanPayment(payment_date=sample_request.request_date, amount=Decimal("500")),
            PlanPayment(payment_date=date(2026, 2, 1), amount=Decimal("600")),
        ],
        total_cost=Decimal("1100"),
        completion_date=date(2026, 2, 1),
    )
    safe, result = verify_plan_safety(
        sample_profile,
        [],
        malformed_partial,
        sample_request,
        [],
        date(2026, 4, 9),
    )
    assert safe is False
    assert "two-payment contract" in (result.failure_reason or "")


def test_decision_explanation_formatting(
    sample_request: FinancialRequest, sample_profile: FinancialProfile
) -> None:
    plan = CandidatePlan(
        plan_id="p_inst",
        recommended_payment_method=RecommendedPaymentMethod.INSTALLMENTS,
        payments=[
            PlanPayment(payment_date=date(2026, 1, 15), amount=Decimal("400")),
            PlanPayment(payment_date=date(2026, 2, 14), amount=Decimal("400")),
            PlanPayment(payment_date=date(2026, 3, 16), amount=Decimal("400")),
        ],
        total_cost=Decimal("1200"),
        completion_date=date(2026, 3, 16),
    )
    expl = generate_decision_explanation(
        request=sample_request,
        profile=sample_profile,
        plan=plan,
        affordability_status=AffordabilityStatus.AFFORDABLE_WITH_PLAN,
        earliest_date_for_full_payment=date(2026, 3, 15),
        amount_safe_to_pay=Decimal("400"),
        raw_events=[],
    )
    assert "Use 3 installments of EUR 400" in expl
    assert "starting 15 January 2026" in expl
    assert "leaves at least EUR 500 available" in expl


def test_decision_engine_evaluation() -> None:
    dataset_dir = Path("dataset")
    if not dataset_dir.is_dir():
        pytest.skip("Dataset directory not present")

    repo = DatasetRepository.load_from_dir(dataset_dir)
    engine = DecisionEngine(repo)

    result = engine.evaluate_request("request_01")
    assert result.request_id == "request_01"
    assert result.affordability_status == AffordabilityStatus.AFFORDABLE_NOW
    assert result.recommended_payment_method == RecommendedPaymentMethod.FULL_PAYMENT
    assert result.payment_plan == "2024-03-03:25256"
    assert result.spending_changes_needed == "none"
