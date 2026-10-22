"""Partial payment candidate builder (strict two-payment structure)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from orcha.models import (
    CandidatePlan,
    FinancialProfile,
    FinancialRequest,
    PlanPayment,
    RecommendedPaymentMethod,
)


def can_attempt_partial_payment(
    request: FinancialRequest,
    profile: FinancialProfile,
    amount_safe_to_pay: Decimal,
    earliest_date_for_full_payment: date | None,
) -> bool:
    """Determine if a partial payment plan can be considered.

    Rules from problem statement:
    1. The request allows partial payment (request.allows_partial_payment is True).
    2. The user accepts this method (partial_payment in payment_methods_user_will_consider).
    3. amount_safe_to_pay is greater than 0 but less than requested_amount.
    4. earliest_date_for_full_payment is on or before desired_completion_date.
    """
    if not request.allows_partial_payment:
        return False

    if RecommendedPaymentMethod.PARTIAL_PAYMENT not in profile.payment_methods_user_will_consider:
        return False

    if not (Decimal("0") < amount_safe_to_pay < request.requested_amount):
        return False

    if earliest_date_for_full_payment is None:
        return False

    if earliest_date_for_full_payment > request.desired_completion_date:
        return False

    return True


def build_partial_payment_plan(
    request: FinancialRequest,
    amount_safe_to_pay: Decimal,
    earliest_date_for_full_payment: date,
) -> CandidatePlan:
    """Build a strict two-payment partial payment CandidatePlan.

    Payment 1: amount_safe_to_pay on request_date.
    Payment 2: (requested_amount - amount_safe_to_pay) on earliest_date_for_full_payment.
    Total payments sum exactly to requested_amount.
    """
    remaining_amount = request.requested_amount - amount_safe_to_pay

    payments = [
        PlanPayment(payment_date=request.request_date, amount=amount_safe_to_pay),
        PlanPayment(payment_date=earliest_date_for_full_payment, amount=remaining_amount),
    ]

    return CandidatePlan(
        plan_id=f"partial_{request.request_id}",
        recommended_payment_method=RecommendedPaymentMethod.PARTIAL_PAYMENT,
        payment_option_id=None,
        payments=payments,
        spending_changes=[],
        total_cost=request.requested_amount,
        is_safe=False,
        completion_date=earliest_date_for_full_payment,
        explanation_notes=[
            f"Pay {amount_safe_to_pay} today and remaining "
            f"{remaining_amount} on {earliest_date_for_full_payment.isoformat()}"
        ],
    )
