"""Fast, targeted candidate plan generator."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from orcha.ledger.models import ResolvedFinancialEvent
from orcha.models import (
    CandidatePlan,
    FinancialProfile,
    FinancialRequest,
    PaymentOption,
    PlanPayment,
    RecommendedPaymentMethod,
)
from orcha.planning.installments import build_installment_plan, is_option_eligible
from orcha.planning.partial import (
    build_partial_payment_plan,
    can_attempt_partial_payment,
)
from orcha.planning.spending_changes import generate_spending_change_combinations


def generate_candidate_plans(
    request: FinancialRequest,
    profile: FinancialProfile,
    options: list[PaymentOption],
    resolved_events: list[ResolvedFinancialEvent],
    amount_safe_to_pay: Decimal,
    earliest_date_for_full_payment: date | None,
) -> list[CandidatePlan]:
    """Generate prioritized candidate payment plans for evaluation."""
    candidates: list[CandidatePlan] = []

    # 1. Full payment now (without spending changes)
    if RecommendedPaymentMethod.FULL_PAYMENT in profile.payment_methods_user_will_consider:
        candidates.append(
            CandidatePlan(
                plan_id="full_payment_now",
                recommended_payment_method=RecommendedPaymentMethod.FULL_PAYMENT,
                payment_option_id=None,
                payments=[
                    PlanPayment(payment_date=request.request_date, amount=request.requested_amount)
                ],
                spending_changes=[],
                total_cost=request.requested_amount,
                is_safe=False,
                completion_date=request.request_date,
            )
        )

    # 2. Partial payment (strict 2 payments)
    if (
        can_attempt_partial_payment(
            request=request,
            profile=profile,
            amount_safe_to_pay=amount_safe_to_pay,
            earliest_date_for_full_payment=earliest_date_for_full_payment,
        )
        and earliest_date_for_full_payment is not None
    ):
        candidates.append(
            build_partial_payment_plan(
                request=request,
                amount_safe_to_pay=amount_safe_to_pay,
                earliest_date_for_full_payment=earliest_date_for_full_payment,
            )
        )

    # 3. Installments (from request_payment_options)
    for opt in options:
        if is_option_eligible(opt, profile):
            candidates.append(build_installment_plan(opt, request))

    # 4. Wait (full payment on earliest_date_for_full_payment)
    if (
        RecommendedPaymentMethod.FULL_PAYMENT in profile.payment_methods_user_will_consider
        and earliest_date_for_full_payment is not None
        and earliest_date_for_full_payment > request.request_date
    ):
        candidates.append(
            CandidatePlan(
                plan_id="wait_for_full_payment",
                recommended_payment_method=RecommendedPaymentMethod.WAIT,
                payment_option_id=None,
                payments=[
                    PlanPayment(
                        payment_date=earliest_date_for_full_payment, amount=request.requested_amount
                    )
                ],
                spending_changes=[],
                total_cost=request.requested_amount,
                is_safe=False,
                completion_date=earliest_date_for_full_payment,
            )
        )

    # Apply every valid (up to three action) change set to every plan type that can
    # complete the purchase. Safety verification and ranking decide whether any is
    # needed; no arbitrary first-N truncation is allowed.
    change_combos = generate_spending_change_combinations(profile, resolved_events, max_changes=3)
    changeable = [
        plan
        for plan in candidates
        if plan.recommended_payment_method
        in (
            RecommendedPaymentMethod.FULL_PAYMENT,
            RecommendedPaymentMethod.PARTIAL_PAYMENT,
            RecommendedPaymentMethod.INSTALLMENTS,
        )
    ]
    for plan in changeable:
        for index, combo in enumerate(change_combos):
            candidates.append(
                plan.model_copy(
                    update={
                        "plan_id": f"{plan.plan_id}_changes_{index}",
                        "spending_changes": combo,
                    }
                )
            )

    return candidates
