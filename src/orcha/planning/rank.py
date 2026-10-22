"""Deterministic 6-stage plan ranking."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from orcha.models import CandidatePlan, FinancialRequest


def plan_sort_key(
    plan: CandidatePlan,
    request: FinancialRequest,
) -> tuple[int, int, Decimal, date, int, str]:
    """6-stage tie-breaking key matching problem_statement.md § Choosing Between Safe Plans:

    1. Complete the full request by desired_completion_date (0 if completed on time, else 1).
    2. Require no spending changes (unchanged plans before any changed plan).
    3. Minimize total amount paid (total_cost ascending).
    4. Start payment earlier (first payment date ascending).
    5. Use fewer payments (number of payments ascending).
    6. Use lowest payment_option_id as final tie-breaker (alphabetical).
    """
    # 1. On-time completion
    completed_on_time = 0
    if plan.completion_date is not None:
        completed_on_time = 0 if plan.completion_date <= request.desired_completion_date else 1
    else:
        completed_on_time = 1

    # 2. The contract distinguishes no changes from changes; it does not assign
    # preference among one, two, or three permitted actions.
    spending_changes_flag = 1 if plan.spending_changes else 0

    # 3. Total amount paid
    total_cost = plan.total_cost

    # 4. Start date (earliest first payment date)
    first_payment_date = plan.payments[0].payment_date if plan.payments else date.max

    # 5. Fewer payments
    payments_count = len(plan.payments)

    # 6. Lowest payment_option_id
    option_id = plan.payment_option_id or "zzzzzzzz"

    return (
        completed_on_time,
        spending_changes_flag,
        total_cost,
        first_payment_date,
        payments_count,
        option_id,
    )


def rank_candidate_plans(
    safe_plans: list[CandidatePlan],
    request: FinancialRequest,
) -> list[CandidatePlan]:
    """Sort safe candidate plans from highest to lowest rank."""
    return sorted(safe_plans, key=lambda p: plan_sort_key(p, request))
