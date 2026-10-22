"""Installment plan candidate builder from seller/provider payment options."""

from __future__ import annotations

from datetime import timedelta

from orcha.models import (
    CandidatePlan,
    FinancialProfile,
    FinancialRequest,
    PaymentOption,
    PaymentOptionMethod,
    PlanPayment,
    RecommendedPaymentMethod,
)


def is_option_eligible(option: PaymentOption, profile: FinancialProfile) -> bool:
    """Check if a payment option is eligible given user profile preferences."""
    if option.payment_method == PaymentOptionMethod.INSTALLMENTS:
        if RecommendedPaymentMethod.INSTALLMENTS not in profile.payment_methods_user_will_consider:
            return False
        if profile.max_installment_months is not None:
            # Estimate duration in months: (number_of_payments * frequency_days) / 30
            freq = option.payment_frequency_days or 30
            total_days = (option.number_of_payments - 1) * freq
            duration_months = (total_days + 29) // 30
            if duration_months > profile.max_installment_months:
                return False
    elif option.payment_method == PaymentOptionMethod.FULL_PAYMENT:
        if RecommendedPaymentMethod.FULL_PAYMENT not in profile.payment_methods_user_will_consider:
            return False

    return True


def build_installment_plan(
    option: PaymentOption,
    request: FinancialRequest,
) -> CandidatePlan:
    """Build a CandidatePlan from a PaymentOption exactly following its schedule."""
    payments: list[PlanPayment] = []
    freq = option.payment_frequency_days or 30

    for i in range(option.number_of_payments):
        pay_date = option.first_payment_date + timedelta(days=i * freq)
        payments.append(PlanPayment(payment_date=pay_date, amount=option.payment_amount))

    method = (
        RecommendedPaymentMethod.INSTALLMENTS
        if option.payment_method == PaymentOptionMethod.INSTALLMENTS
        else RecommendedPaymentMethod.FULL_PAYMENT
    )

    completion_date = payments[-1].payment_date if payments else option.first_payment_date

    return CandidatePlan(
        plan_id=f"option_{option.payment_option_id}",
        recommended_payment_method=method,
        payment_option_id=option.payment_option_id,
        payments=payments,
        spending_changes=[],
        total_cost=option.total_payable_amount,
        is_safe=False,
        completion_date=completion_date,
        explanation_notes=[
            f"Use {option.number_of_payments} installments of {option.payment_amount}"
        ],
    )
