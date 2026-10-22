"""Deterministic, grounded financial decision explanations."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from orcha.models import (
    AffordabilityStatus,
    CandidatePlan,
    FinancialEvent,
    FinancialProfile,
    FinancialRequest,
    NormalizedFinancialEvent,
    RecommendedPaymentMethod,
    SpendingChangeAction,
)


def format_money(amount: Decimal) -> str:
    """Format decimal amount with commas: 25,256 or 15,952,906.67 or 620.40."""
    # Check if amount is an integer
    if amount == amount.to_integral_value():
        return f"{int(amount):,}"
    # Otherwise format with 2 decimal places
    return f"{amount:,.2f}"


def format_date_natural(d: date) -> str:
    """Format date naturally: e.g. 15 September 2026."""
    return f"{d.day} {d.strftime('%B')} {d.year}"


def generate_decision_explanation(
    request: FinancialRequest,
    profile: FinancialProfile,
    plan: CandidatePlan,
    affordability_status: AffordabilityStatus,
    earliest_date_for_full_payment: date | None,
    amount_safe_to_pay: Decimal,
    raw_events: list[NormalizedFinancialEvent] | list[FinancialEvent],
) -> str:
    """Construct a concise financial explanation grounded in verified results."""
    curr = profile.home_currency
    min_bal_str = format_money(profile.minimum_balance_to_keep)
    req_amt_str = format_money(request.requested_amount)

    event_desc_map = {e.event_id: e.description.lower() for e in raw_events}

    # 1. Affordable now (full payment on request_date with no spending changes)
    if (
        affordability_status == AffordabilityStatus.AFFORDABLE_NOW
        and plan.recommended_payment_method == RecommendedPaymentMethod.FULL_PAYMENT
    ):
        return (
            f"Pay {curr} {req_amt_str} today. "
            f"This leaves at least {curr} {min_bal_str} available over the next 90 days."
        )

    # 2. Affordable with plan - full payment with spending changes
    if (
        affordability_status == AffordabilityStatus.AFFORDABLE_WITH_PLAN
        and plan.recommended_payment_method == RecommendedPaymentMethod.FULL_PAYMENT
        and plan.spending_changes
    ):
        change_phrases = []
        for ch in plan.spending_changes:
            desc = event_desc_map.get(ch.event_id, "flexible expense")
            if ch.action == SpendingChangeAction.STOP:
                change_phrases.append(f"stop the {desc}")
            elif ch.action == SpendingChangeAction.REDUCE_TO and ch.new_amount is not None:
                amt_str = format_money(ch.new_amount)
                change_phrases.append(f"reduce the {desc} to {curr} {amt_str}")

        changes_summary = " and ".join(change_phrases).capitalize()
        return (
            f"{changes_summary}, then pay {curr} {req_amt_str} today. "
            f"This leaves at least {curr} {min_bal_str} available."
        )

    # 3. Affordable with plan - installments
    if (
        affordability_status == AffordabilityStatus.AFFORDABLE_WITH_PLAN
        and plan.recommended_payment_method == RecommendedPaymentMethod.INSTALLMENTS
        and plan.payments
    ):
        inst_count = len(plan.payments)
        first_amt = format_money(plan.payments[0].amount)
        first_date_str = format_date_natural(plan.payments[0].payment_date)
        return (
            f"Use {inst_count} installments of {curr} {first_amt}, starting {first_date_str}. "
            f"This leaves at least {curr} {min_bal_str} available."
        )

    # 4. Affordable with plan - partial payment
    if (
        affordability_status == AffordabilityStatus.AFFORDABLE_WITH_PLAN
        and plan.recommended_payment_method == RecommendedPaymentMethod.PARTIAL_PAYMENT
        and len(plan.payments) == 2
    ):
        p1_amt = format_money(plan.payments[0].amount)
        p2_amt = format_money(plan.payments[1].amount)
        p2_date_str = format_date_natural(plan.payments[1].payment_date)
        return (
            f"Pay {curr} {p1_amt} today and the remaining {curr} {p2_amt} on {p2_date_str}. "
            f"This completes the full request and keeps the {curr} {min_bal_str} minimum protected."
        )

    # 5. Affordable later - wait
    if (
        affordability_status == AffordabilityStatus.AFFORDABLE_LATER
        and plan.recommended_payment_method == RecommendedPaymentMethod.WAIT
        and earliest_date_for_full_payment is not None
    ):
        full_date_str = format_date_natural(earliest_date_for_full_payment)
        return (
            f"Pay {curr} {req_amt_str} in full on {full_date_str}. "
            f"Paying earlier would take the balance below the {curr} {min_bal_str} minimum."
        )

    # 6. Not affordable - not recommended
    deadline_str = format_date_natural(request.desired_completion_date)
    return (
        f"Do not make this payment by {deadline_str}. "
        f"None of the available options keeps the {curr} {min_bal_str} minimum protected."
    )
