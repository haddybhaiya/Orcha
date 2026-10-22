"""Conservative recurrence detection, evidence adjustments, and expansion."""

from __future__ import annotations

import calendar
import math
import re
from collections import Counter, defaultdict
from datetime import date, timedelta
from decimal import Decimal
from statistics import median

from orcha.evidence.models import EvidenceType, MessageEvidence
from orcha.ledger.classify import classify_for_forecast
from orcha.ledger.models import RecurrencePattern, ResolvedFinancialEvent
from orcha.models import (
    EventDirection,
    EventStatus,
    EventType,
    FlexibilityType,
    NormalizedFinancialEvent,
)

_RECURRING_EVENT_TYPES = {
    EventType.EXPENSE,
    EventType.DEBT_PAYMENT,
    EventType.SUBSCRIPTION,
    EventType.INCOME,
}
_ONGOING_SALARY_TYPES = {
    EvidenceType.SALARY_INCREASE,
    EvidenceType.SALARY_RESUMED,
}
_ONE_CYCLE_SALARY_TYPES = {
    EvidenceType.TEMPORARY_SALARY,
    EvidenceType.UNPAID_LEAVE_REDUCTION,
    EvidenceType.SALARY_ARREARS_ADJUSTMENT,
}
_VARIABLE_COMPENSATION_TERMS = ("commission", "bonus", "incentive")
_AGGREGATE_VARIABLE_CATEGORIES = {
    "dining",
    "entertainment",
    "groceries",
    "healthcare",
    "shopping",
    "transport",
}


def _event_date(event: NormalizedFinancialEvent) -> date:
    return event.settlement_date or event.event_date


def _is_end_of_month(value: date) -> bool:
    return value.day == calendar.monthrange(value.year, value.month)[1]


def _is_next_calendar_month(left: date, right: date) -> bool:
    month_delta = (right.year - left.year) * 12 + right.month - left.month
    return month_delta == 1 and (
        left.day == right.day or (_is_end_of_month(left) and _is_end_of_month(right))
    )


def _add_month(value: date, preferred_day: int | None = None) -> date:
    year = value.year + value.month // 12
    month = value.month % 12 + 1
    day = min(preferred_day or value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _subtract_month(value: date) -> date:
    year = value.year if value.month > 1 else value.year - 1
    month = value.month - 1 if value.month > 1 else 12
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _message_date(message: MessageEvidence, fallback: date) -> date:
    if message.effective_date is not None:
        return message.effective_date
    if message.sent_at is not None:
        return message.sent_at.date()
    return fallback


def _message_sort_key(message: MessageEvidence) -> tuple[date, str]:
    return (_message_date(message, date.min), message.message_id)


def _rent_multiplier(message: MessageEvidence) -> Decimal | None:
    text = f"{message.notes} {message.raw_text}"
    match = re.search(r"(\d+(?:\.\d+)?)\s*%", text)
    if match is None:
        return None
    return Decimal("1") + Decimal(match.group(1)) / Decimal("100")


def _is_variable_compensation_pattern(pattern: RecurrencePattern) -> bool:
    text = f"{pattern.stream_id} {pattern.description}".casefold()
    return any(term in text for term in _VARIABLE_COMPENSATION_TERMS)


def _message_excludes_variable_compensation(message: MessageEvidence) -> bool:
    text = message.raw_text.casefold()
    mentions_variable_pay = any(term in text for term in _VARIABLE_COMPENSATION_TERMS)
    excludes_it = any(
        term in text
        for term in (
            "pending approval",
            "still pending",
            "belum disetujui",
            "subject to the final",
            "menunggu hasil akhir",
        )
    )
    return mentions_variable_pay and excludes_it


def _recurrence_cadence(events: list[NormalizedFinancialEvent]) -> tuple[int, bool] | None:
    dates = sorted({_event_date(event) for event in events})
    if len(dates) < 2:
        return None

    pairs = list(zip(dates, dates[1:], strict=False))
    monthly_matches = sum(_is_next_calendar_month(left, right) for left, right in pairs)
    required = max(1, math.ceil(len(pairs) * 0.75))
    if monthly_matches >= required:
        return (30, True)

    intervals = [(right - left).days for left, right in pairs]
    candidate = int(median(intervals))
    if candidate < 2 or candidate > 31:
        return None
    tolerance = max(1, round(candidate * 0.15))
    matches = sum(abs(interval - candidate) <= tolerance for interval in intervals)
    if matches < required:
        return None
    return (candidate, False)


def _follows_cadence(left: date, right: date, cadence: tuple[int, bool]) -> bool:
    frequency_days, calendar_monthly = cadence
    if calendar_monthly:
        return _is_next_calendar_month(left, right)
    tolerance = max(1, round(frequency_days * 0.15))
    return abs((right - left).days - frequency_days) <= tolerance


def _recurrence_core(
    events: list[NormalizedFinancialEvent],
) -> list[NormalizedFinancialEvent]:
    """Remove trailing exceptions that do not extend an established cadence."""
    ordered = sorted(events, key=_event_date)
    while len(ordered) >= 3:
        prior_cadence = _recurrence_cadence(ordered[:-1])
        if prior_cadence is None or _follows_cadence(
            _event_date(ordered[-2]), _event_date(ordered[-1]), prior_cadence
        ):
            break
        ordered.pop()
    return ordered


def _pattern_flexibility(
    events: list[NormalizedFinancialEvent],
) -> tuple[FlexibilityType, Decimal | None]:
    latest = max(events, key=_event_date)
    values = {event.flexibility or FlexibilityType.FIXED for event in events}
    if len(values) != 1:
        return (FlexibilityType.FIXED, None)
    flexibility = latest.flexibility or FlexibilityType.FIXED
    return (flexibility, latest.minimum_allowed_amount)


def _stable_historical_amount(events: list[NormalizedFinancialEvent]) -> Decimal:
    """Return the most supported amount, breaking ties with the newest occurrence."""
    valued = [event for event in events if event.amount_home_currency is not None]
    counts = Counter(event.amount_home_currency for event in valued)
    highest_count = max(counts.values())
    candidates = {amount for amount, count in counts.items() if count == highest_count}
    latest = max(
        (event for event in valued if event.amount_home_currency in candidates),
        key=_event_date,
    )
    assert latest.amount_home_currency is not None
    return latest.amount_home_currency


def _description_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_") or "unnamed"


def _recurrence_streams(
    events: list[NormalizedFinancialEvent],
) -> list[tuple[str, list[NormalizedFinancialEvent]]]:
    """Separate multiple supported obligations or income streams that share a category."""
    category_cadence = _recurrence_cadence(events)
    if events[0].category in _AGGREGATE_VARIABLE_CATEGORIES and category_cadence is not None:
        # Merchant descriptions identify individual purchases, not separate
        # contractual streams. Preserve the supported category-level cadence.
        return [("category", events)]
    by_description: dict[str, list[NormalizedFinancialEvent]] = defaultdict(list)
    for event in events:
        by_description[_description_key(event.description)].append(event)
    supported = [
        (key, group)
        for key, group in by_description.items()
        if len(group) >= 2 and _recurrence_cadence(group) is not None
    ]
    if len(supported) >= 2:
        return supported
    if len(supported) == 1 and category_cadence is None:
        return supported
    if category_cadence is not None:
        return [("category", events)]
    if supported:
        return supported
    return [("category", events)]


def _apply_messages(
    pattern: RecurrencePattern,
    messages: list[MessageEvidence],
    active_salary_stream_id: str | None = None,
    source_events: list[NormalizedFinancialEvent] | None = None,
) -> RecurrencePattern:
    amount_adjustments: list[tuple[date, Decimal]] = []
    single_amounts: list[tuple[date, Decimal]] = []
    evidence_ids: list[str] = []
    anchor = pattern.anchor_date
    calendar_day = pattern.calendar_day
    end_date = pattern.end_date
    rent_amount = pattern.amount_home_currency
    baseline_amount = pattern.amount_home_currency
    if (
        pattern.category == "salary"
        and not _is_variable_compensation_pattern(pattern)
        and source_events
        and any(message.evidence_type in _ONE_CYCLE_SALARY_TYPES for message in messages)
    ):
        baseline_amount = _stable_historical_amount(source_events)

    for message in sorted(messages, key=_message_sort_key):
        if pattern.category == "rent" and message.evidence_type == EvidenceType.RENT_INCREASE:
            effective = _message_date(message, _add_month(anchor))
            multiplier = _rent_multiplier(message)
            if message.amount is not None and message.currency in (None, "", pattern.home_currency):
                rent_amount = message.amount
                amount_adjustments.append((effective, rent_amount))
                evidence_ids.append(message.message_id)
            elif multiplier is not None:
                rent_amount *= multiplier
                amount_adjustments.append((effective, rent_amount))
                evidence_ids.append(message.message_id)
            continue

        if pattern.category != "salary":
            continue
        if message.currency and pattern.home_currency and message.currency != pattern.home_currency:
            continue
        if _is_variable_compensation_pattern(pattern):
            if _message_excludes_variable_compensation(message):
                end_date = _message_date(message, anchor)
                evidence_ids.append(message.message_id)
            # A general/base salary amount is not authority for a distinct
            # commission or bonus stream.
            continue
        if message.evidence_type == EvidenceType.EMPLOYMENT_ENDED_SALARY_REDUCTION:
            effective = _message_date(message, _add_month(anchor))
            if pattern.stream_id == active_salary_stream_id and message.amount is not None:
                amount_adjustments.append((effective, message.amount))
            else:
                end_date = effective
            evidence_ids.append(message.message_id)
            continue
        if message.evidence_type in _ONGOING_SALARY_TYPES and message.amount is not None:
            effective = _message_date(message, _add_month(anchor))
            amount_adjustments.append((effective, message.amount))
            evidence_ids.append(message.message_id)
        elif (
            message.evidence_type == EvidenceType.SALARY_ARREARS_ADJUSTMENT
            and message.amount is not None
        ):
            effective = _message_date(message, _add_month(anchor))
            total_payroll = message.amount + (message.additional_amount or Decimal("0"))
            single_amounts.append((effective, total_payroll))
            evidence_ids.append(message.message_id)
        elif message.evidence_type in _ONE_CYCLE_SALARY_TYPES and message.amount is not None:
            effective = _message_date(message, _add_month(anchor))
            single_amounts.append((effective, message.amount))
            evidence_ids.append(message.message_id)
        elif message.evidence_type == EvidenceType.SALARY_DATE_CHANGE:
            if message.effective_date is not None:
                # Expansion emits the occurrence after the anchor, so retain the
                # previous calendar month to include the revised pay date itself.
                anchor = _subtract_month(message.effective_date)
                calendar_day = message.effective_date.day
                evidence_ids.append(message.message_id)
        elif message.evidence_type in (
            EvidenceType.CONTRACT_ENDED,
            EvidenceType.EMPLOYMENT_ENDED_SALARY_REDUCTION,
            EvidenceType.PENDING_PAYOUT,
        ):
            end_date = _message_date(message, anchor)
            evidence_ids.append(message.message_id)

    return RecurrencePattern(
        category=pattern.category,
        frequency_days=pattern.frequency_days,
        anchor_date=anchor,
        amount_home_currency=baseline_amount,
        direction=pattern.direction,
        source_event_ids=pattern.source_event_ids,
        confidence=pattern.confidence,
        end_date=end_date,
        description=pattern.description,
        calendar_monthly=pattern.calendar_monthly,
        calendar_day=calendar_day,
        flexibility=pattern.flexibility,
        minimum_allowed_amount=pattern.minimum_allowed_amount,
        amount_adjustments=tuple(amount_adjustments),
        single_occurrence_amounts=tuple(single_amounts),
        message_evidence_ids=tuple(evidence_ids),
        home_currency=pattern.home_currency,
        stream_id=pattern.stream_id,
    )


def detect_recurrence_patterns(
    events: list[NormalizedFinancialEvent],
    user_messages: list[MessageEvidence] | None = None,
) -> list[RecurrencePattern]:
    """Detect cash-flow recurrence only when event dates support a stable cadence."""
    messages = user_messages or []
    patterns: list[RecurrencePattern] = []
    eligible = [
        event
        for event in events
        if event.amount_home_currency is not None
        and event.status in (EventStatus.SETTLED, EventStatus.SCHEDULED)
        and event.direction in (EventDirection.CREDIT, EventDirection.DEBIT)
        and event.event_type in _RECURRING_EVENT_TYPES
    ]

    groups: dict[tuple[str, EventDirection], list[NormalizedFinancialEvent]] = defaultdict(list)
    for event in eligible:
        groups[(event.category, event.direction)].append(event)

    for (category, direction), category_group in groups.items():
        for stream_id, group in _recurrence_streams(category_group):
            group = _recurrence_core(group)
            cadence = _recurrence_cadence(group)
            if cadence is None:
                continue
            frequency_days, calendar_monthly = cadence
            ordered = sorted(group, key=_event_date)
            latest = ordered[-1]
            assert latest.amount_home_currency is not None
            flexibility, minimum_amount = _pattern_flexibility(ordered)
            cadence_label = "monthly" if calendar_monthly else f"every {frequency_days} days"
            stream_label = latest.description if stream_id != "category" else category
            end_date = None
            if any(
                term in latest.description.casefold()
                for term in ("final", "terminated", "contract ended", "last")
            ):
                end_date = _event_date(latest)

            pattern = RecurrencePattern(
                category=category,
                frequency_days=frequency_days,
                anchor_date=_event_date(latest),
                # The newest supported record has authority over older amounts.
                amount_home_currency=latest.amount_home_currency,
                direction=direction,
                source_event_ids=tuple(event.event_id for event in ordered),
                confidence=1.0,
                end_date=end_date,
                description=f"Recurring {stream_label} ({cadence_label})",
                calendar_monthly=calendar_monthly,
                # The latest supported occurrence is the authoritative monthly
                # anchor. The sole exception is a proven end-of-month series:
                # retain its largest calendar day so February rolls into March
                # 31 rather than permanently moving to the 28th.
                calendar_day=(
                    max(_event_date(event).day for event in ordered)
                    if _is_end_of_month(_event_date(latest))
                    and all(_is_end_of_month(_event_date(event)) for event in ordered)
                    else _event_date(latest).day
                )
                if calendar_monthly
                else None,
                flexibility=flexibility,
                minimum_allowed_amount=minimum_amount,
                home_currency=latest.home_currency,
                stream_id=stream_id,
            )
            patterns.append(pattern)

    active_salary_stream_id: str | None = None
    if any(
        message.evidence_type == EvidenceType.EMPLOYMENT_ENDED_SALARY_REDUCTION
        for message in messages
    ):
        salary_patterns = [
            pattern
            for pattern in patterns
            if pattern.category == "salary"
            and pattern.direction == EventDirection.CREDIT
            and not _is_variable_compensation_pattern(pattern)
        ]
        if salary_patterns:
            # The most recently observed salary stream is the supported survivor;
            # stale household streams are ended by the employer amendment.
            active_salary_stream_id = max(
                salary_patterns, key=lambda pattern: (pattern.anchor_date, pattern.stream_id)
            ).stream_id

    event_by_id = {event.event_id: event for event in eligible}
    patterns = [
        _apply_messages(
            pattern,
            messages,
            active_salary_stream_id,
            [event_by_id[event_id] for event_id in pattern.source_event_ids],
        )
        for pattern in patterns
    ]

    salary_pattern_exists = any(
        pattern.category == "salary" and pattern.direction == EventDirection.CREDIT
        for pattern in patterns
    )
    if not salary_pattern_exists:
        first_salary = [
            message
            for message in messages
            if message.evidence_type == EvidenceType.FIRST_SALARY_CONFIRMED
            and message.amount is not None
            and message.effective_date is not None
        ]
        if first_salary:
            message = max(first_salary, key=_message_sort_key)
            assert message.amount is not None and message.effective_date is not None
            patterns.append(
                RecurrencePattern(
                    category="salary",
                    frequency_days=30,
                    anchor_date=_subtract_month(message.effective_date),
                    amount_home_currency=message.amount,
                    direction=EventDirection.CREDIT,
                    source_event_ids=(),
                    end_date=message.effective_date,
                    description="One confirmed salary payment from employer evidence",
                    calendar_monthly=True,
                    calendar_day=message.effective_date.day,
                    message_evidence_ids=(message.message_id,),
                    home_currency=message.currency,
                    stream_id="confirmed_salary",
                )
            )

    return patterns


def _amount_for_occurrence(
    pattern: RecurrencePattern, previous_occurrence: date, occurrence: date
) -> Decimal:
    amount = pattern.amount_home_currency
    for effective, adjusted in sorted(pattern.amount_adjustments):
        if occurrence >= effective:
            amount = adjusted
    for effective, override in pattern.single_occurrence_amounts:
        if previous_occurrence < effective <= occurrence:
            return override
    return amount


def _next_occurrence(pattern: RecurrencePattern, current: date) -> date:
    if pattern.calendar_monthly:
        return _add_month(current, pattern.calendar_day)
    return current + timedelta(days=pattern.frequency_days)


def expand_events(
    user_id: str,
    home_currency: str,
    start_date: date,
    end_date: date,
    patterns: list[RecurrencePattern],
    existing_events: list[NormalizedFinancialEvent],
) -> list[ResolvedFinancialEvent]:
    """Project supported recurring occurrences into ``[start_date, end_date]``."""
    projected: list[ResolvedFinancialEvent] = []
    existing_category_keys = {
        (event.category, event.direction, _event_date(event)) for event in existing_events
    }
    existing_stream_keys = {
        (
            event.category,
            event.direction,
            _description_key(event.description),
            _event_date(event),
        )
        for event in existing_events
    }

    for pattern in patterns:
        occurrence = pattern.anchor_date
        while occurrence <= end_date:
            previous_occurrence = occurrence
            occurrence = _next_occurrence(pattern, occurrence)
            if occurrence < start_date:
                continue
            if occurrence > end_date:
                break
            if pattern.end_date is not None and occurrence > pattern.end_date:
                break
            category_key = (pattern.category, pattern.direction, occurrence)
            stream_key = (pattern.category, pattern.direction, pattern.stream_id, occurrence)
            if (
                pattern.stream_id == "category"
                and category_key in existing_category_keys
                or pattern.stream_id != "category"
                and stream_key in existing_stream_keys
            ):
                continue

            amount = _amount_for_occurrence(pattern, previous_occurrence, occurrence)
            behavior = classify_for_forecast(
                status=EventStatus.SCHEDULED,
                direction=pattern.direction,
                settlement_date=occurrence,
                request_date=start_date,
            )
            canonical_id = (
                f"rec_{pattern.category}_{pattern.stream_id}_{user_id}_{occurrence.isoformat()}"
            )
            projected.append(
                ResolvedFinancialEvent(
                    canonical_event_id=canonical_id,
                    user_id=user_id,
                    event_type=(
                        "recurring_income"
                        if pattern.direction == EventDirection.CREDIT
                        else "recurring_expense"
                    ),
                    description=pattern.description,
                    category=pattern.category,
                    direction=pattern.direction,
                    amount_home_currency=amount,
                    home_currency=home_currency,
                    original_amount=amount,
                    original_currency=home_currency,
                    event_date=occurrence,
                    settlement_date=occurrence,
                    resolved_status=EventStatus.SCHEDULED,
                    forecast_behavior=behavior,
                    flexibility=pattern.flexibility,
                    minimum_allowed_amount=pattern.minimum_allowed_amount,
                    is_recurring=True,
                    recurrence_pattern=pattern,
                    source_event_ids=pattern.source_event_ids,
                    message_evidence_ids=pattern.message_evidence_ids,
                    image_evidence_ids=(),
                    resolution_reason=f"Projected from supported {pattern.category} cadence",
                    amount_source="recurrence_projection",
                )
            )

    return projected
