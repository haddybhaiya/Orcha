"""Search and validation for permissible spending changes."""

from __future__ import annotations

import itertools
from collections import defaultdict
from decimal import Decimal

from orcha.ledger.models import ResolvedFinancialEvent
from orcha.models import (
    EventFlexibility,
    FinancialProfile,
    SpendingChange,
    SpendingChangeAction,
)


def find_eligible_spending_actions(
    profile: FinancialProfile,
    events: list[ResolvedFinancialEvent],
) -> list[tuple[SpendingChange, Decimal, str]]:
    """Identify individual valid spending reduction/stopping actions for a user.

    Returns list of tuples: (SpendingChange, monthly_savings, category).
    Criteria:
    - Category must NOT be in profile.expense_categories_to_protect
    - If stoppable: category in profile.expense_categories_user_is_willing_to_stop
    - If reducible: category in profile.expense_categories_user_is_willing_to_reduce
    - recurrence must be supported and projected into the current forecast
    - all amounts are in the user's home currency
    """
    actions: list[tuple[SpendingChange, Decimal, str]] = []
    streams: dict[tuple[tuple[str, ...], str], list[ResolvedFinancialEvent]] = defaultdict(list)
    for event in events:
        if (
            event.direction.value == "debit"
            and event.is_future_cash_outflow
            and event.is_recurring
            and event.recurrence_pattern is not None
            and event.source_event_ids
        ):
            streams[(event.source_event_ids, event.category)].append(event)

    for (source_ids, category), occurrences in sorted(
        streams.items(), key=lambda item: (item[0][1], item[0][0])
    ):
        if category in profile.expense_categories_to_protect:
            continue
        latest = max(occurrences, key=lambda event: event.settlement_date)
        target_event_id = source_ids[-1]
        flexibility = latest.flexibility
        total_amount = sum((event.amount_home_currency for event in occurrences), Decimal("0"))

        if (
            flexibility in (EventFlexibility.STOPPABLE, EventFlexibility.REDUCIBLE_OR_STOPPABLE)
            and category in profile.expense_categories_user_is_willing_to_stop
        ):
            change = SpendingChange(
                action=SpendingChangeAction.STOP,
                event_id=target_event_id,
            )
            actions.append((change, total_amount, category))

        if (
            flexibility in (EventFlexibility.REDUCIBLE, EventFlexibility.REDUCIBLE_OR_STOPPABLE)
            and category in profile.expense_categories_user_is_willing_to_reduce
            and latest.minimum_allowed_amount is not None
        ):
            minimum = latest.minimum_allowed_amount
            if all(minimum < event.amount_home_currency for event in occurrences):
                savings = sum(
                    (event.amount_home_currency - minimum for event in occurrences),
                    Decimal("0"),
                )
                change = SpendingChange(
                    action=SpendingChangeAction.REDUCE_TO,
                    event_id=target_event_id,
                    new_amount=minimum,
                )
                actions.append((change, savings, category))

    return actions


def generate_spending_change_combinations(
    profile: FinancialProfile,
    events: list[ResolvedFinancialEvent],
    max_changes: int = 3,
) -> list[list[SpendingChange]]:
    """Generate all valid subsets of up to max_changes spending changes.

    The search is exhaustive within the contract's maximum of three actions.
    Alternative stop/reduce actions for the same stream are mutually exclusive.
    """
    eligible = find_eligible_spending_actions(profile, events)
    combinations: list[tuple[int, Decimal, list[SpendingChange]]] = []

    for k in range(1, min(len(eligible) + 1, max_changes + 1)):
        for combo in itertools.combinations(eligible, k):
            # Check mutual exclusivity of event_ids
            event_ids = {item[0].event_id for item in combo}
            if len(event_ids) != k:
                continue

            total_savings = sum((item[1] for item in combo), Decimal("0"))
            changes = [item[0] for item in combo]
            combinations.append((k, total_savings, changes))

    # Sort: fewest changes first, then smallest savings (minimal reduction)
    combinations.sort(key=lambda x: (x[0], x[1]))
    return [c[2] for c in combinations]
