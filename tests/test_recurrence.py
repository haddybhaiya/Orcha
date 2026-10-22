"""Tests for recurrence detection, message adjustments, and forecast expansion."""

from datetime import date, timedelta
from decimal import Decimal

from orcha.evidence.messages import MessageEvidenceExtractor
from orcha.evidence.models import EvidenceType, MessageEvidence
from orcha.ledger.recurrence import detect_recurrence_patterns, expand_events
from orcha.models import (
    EventDirection,
    EventFlexibility,
    EventStatus,
    EventType,
    NormalizedFinancialEvent,
)


def make_event(
    event_id: str,
    category: str,
    direction: EventDirection,
    event_date: date,
    amount: Decimal,
    flexibility: EventFlexibility = EventFlexibility.FIXED,
    minimum_allowed_amount: Decimal | None = None,
    description: str | None = None,
    event_type: EventType | None = None,
) -> NormalizedFinancialEvent:
    return NormalizedFinancialEvent(
        event_id=event_id,
        user_id="user_rec_test",
        event_type=event_type
        or (EventType.INCOME if direction == EventDirection.CREDIT else EventType.EXPENSE),
        description=description or f"Test {category}",
        category=category,
        direction=direction,
        amount=amount,
        currency="INR",
        amount_home_currency=amount,
        home_currency="INR",
        event_date=event_date,
        settlement_date=event_date,
        status=EventStatus.SETTLED,
        linked_event_id=None,
        flexibility=flexibility,
        minimum_allowed_amount=minimum_allowed_amount,
    )


def test_detect_monthly_salary_and_rent() -> None:
    events = [
        # 3 monthly salaries (~30 days apart)
        make_event("s1", "salary", EventDirection.CREDIT, date(2026, 6, 15), Decimal("50000")),
        make_event("s2", "salary", EventDirection.CREDIT, date(2026, 7, 15), Decimal("50000")),
        make_event("s3", "salary", EventDirection.CREDIT, date(2026, 8, 15), Decimal("50000")),
        # 3 monthly rents
        make_event("r1", "rent", EventDirection.DEBIT, date(2026, 6, 1), Decimal("15000")),
        make_event("r2", "rent", EventDirection.DEBIT, date(2026, 7, 1), Decimal("15000")),
        make_event("r3", "rent", EventDirection.DEBIT, date(2026, 8, 1), Decimal("15000")),
        # One-off dinner (must NOT be marked recurring)
        make_event("d1", "dining", EventDirection.DEBIT, date(2026, 7, 10), Decimal("1200")),
    ]

    patterns = detect_recurrence_patterns(events)
    categories = {p.category for p in patterns}
    assert "salary" in categories
    assert "rent" in categories
    assert "dining" not in categories


def test_message_rent_increase_updates_pattern() -> None:
    events = [
        make_event("r1", "rent", EventDirection.DEBIT, date(2026, 6, 1), Decimal("10000")),
        make_event("r2", "rent", EventDirection.DEBIT, date(2026, 7, 1), Decimal("10000")),
    ]
    msg = MessageEvidence(
        message_id="msg_rent",
        user_id="user_rec_test",
        request_id=None,
        related_event_id=None,
        sent_at=None,
        source_type="service_provider",
        evidence_type=EvidenceType.RENT_INCREASE,
        notes="Rent increased by 12%",
    )

    patterns = detect_recurrence_patterns(events, [msg])
    assert len(patterns) == 1
    expanded = expand_events(
        user_id="user_rec_test",
        home_currency="INR",
        start_date=date(2026, 7, 2),
        end_date=date(2026, 8, 31),
        patterns=patterns,
        existing_events=events,
    )
    assert expanded[0].amount_home_currency == Decimal("11200.00")


def test_message_contract_ended_stops_expansion() -> None:
    events = [
        make_event("s1", "salary", EventDirection.CREDIT, date(2026, 6, 15), Decimal("30000")),
        make_event("s2", "salary", EventDirection.CREDIT, date(2026, 7, 15), Decimal("30000")),
    ]
    msg = MessageEvidence(
        message_id="msg_ended",
        user_id="user_rec_test",
        request_id=None,
        related_event_id=None,
        sent_at=None,
        source_type="employer",
        evidence_type=EvidenceType.CONTRACT_ENDED,
        effective_date=date(2026, 7, 15),
    )

    patterns = detect_recurrence_patterns(events, [msg])
    assert len(patterns) == 1
    assert patterns[0].end_date == date(2026, 7, 15)

    # Expanding past 2026-07-15 should yield NO new future events
    expanded = expand_events(
        user_id="user_rec_test",
        home_currency="INR",
        start_date=date(2026, 8, 1),
        end_date=date(2026, 10, 31),
        patterns=patterns,
        existing_events=events,
    )
    assert len(expanded) == 0


def test_deduplication_against_explicit_future_events() -> None:
    events = [
        make_event("r1", "rent", EventDirection.DEBIT, date(2026, 6, 1), Decimal("10000")),
        make_event("r2", "rent", EventDirection.DEBIT, date(2026, 7, 1), Decimal("10000")),
        # Explicit scheduled rent for August already in dataset
        make_event("r3_future", "rent", EventDirection.DEBIT, date(2026, 8, 1), Decimal("10000")),
    ]
    patterns = detect_recurrence_patterns(events)
    expanded = expand_events(
        user_id="user_rec_test",
        home_currency="INR",
        start_date=date(2026, 7, 15),
        end_date=date(2026, 9, 30),
        patterns=patterns,
        existing_events=events,
    )
    # August already exists, so expand should only generate September
    aug_expanded = [e for e in expanded if e.event_date.month == 8]
    assert len(aug_expanded) == 0
    sep_expanded = [e for e in expanded if e.event_date.month == 9]
    assert len(sep_expanded) == 1


def test_two_irregular_events_do_not_invent_recurrence() -> None:
    events = [
        make_event("a", "shopping", EventDirection.DEBIT, date(2026, 6, 1), Decimal("100")),
        make_event("b", "shopping", EventDirection.DEBIT, date(2026, 6, 2), Decimal("200")),
    ]
    assert detect_recurrence_patterns(events) == []


def test_weekly_deduplication_is_occurrence_specific() -> None:
    events = [
        make_event("g1", "groceries", EventDirection.DEBIT, date(2026, 1, 1), Decimal("100")),
        make_event("g2", "groceries", EventDirection.DEBIT, date(2026, 1, 8), Decimal("100")),
        make_event("g3", "groceries", EventDirection.DEBIT, date(2026, 1, 15), Decimal("100")),
    ]
    expanded = expand_events(
        user_id="user_rec_test",
        home_currency="INR",
        start_date=date(2026, 1, 16),
        end_date=date(2026, 1, 31),
        patterns=detect_recurrence_patterns(events),
        existing_events=events,
    )
    assert [event.settlement_date for event in expanded] == [date(2026, 1, 22), date(2026, 1, 29)]


def test_calendar_monthly_schedule_and_flexibility_are_preserved() -> None:
    events = [
        make_event(
            "s1",
            "streaming",
            EventDirection.DEBIT,
            date(2026, 1, 31),
            Decimal("30"),
            EventFlexibility.REDUCIBLE,
            Decimal("10"),
        ),
        make_event(
            "s2",
            "streaming",
            EventDirection.DEBIT,
            date(2026, 2, 28),
            Decimal("30"),
            EventFlexibility.REDUCIBLE,
            Decimal("10"),
        ),
    ]
    patterns = detect_recurrence_patterns(events)
    expanded = expand_events(
        user_id="user_rec_test",
        home_currency="INR",
        start_date=date(2026, 3, 1),
        end_date=date(2026, 4, 30),
        patterns=patterns,
        existing_events=events,
    )
    assert [event.settlement_date for event in expanded] == [date(2026, 3, 31), date(2026, 4, 30)]
    assert all(event.flexibility == EventFlexibility.REDUCIBLE for event in expanded)
    assert all(event.minimum_allowed_amount == Decimal("10") for event in expanded)


def test_temporary_salary_override_applies_to_one_cycle_only() -> None:
    events = [
        make_event("s1", "salary", EventDirection.CREDIT, date(2026, 1, 15), Decimal("1000")),
        make_event("s2", "salary", EventDirection.CREDIT, date(2026, 2, 15), Decimal("1000")),
    ]
    message = MessageEvidence(
        message_id="temporary",
        user_id="user_rec_test",
        request_id=None,
        related_event_id=None,
        sent_at=None,
        source_type="employer",
        evidence_type=EvidenceType.TEMPORARY_SALARY,
        amount=Decimal("600"),
        currency="INR",
        effective_date=date(2026, 3, 15),
    )
    expanded = expand_events(
        user_id="user_rec_test",
        home_currency="INR",
        start_date=date(2026, 3, 1),
        end_date=date(2026, 4, 30),
        patterns=detect_recurrence_patterns(events, [message]),
        existing_events=events,
    )
    assert [event.amount_home_currency for event in expanded] == [
        Decimal("600"),
        Decimal("1000"),
    ]


def test_separate_obligations_in_same_category_remain_separate() -> None:
    events = [
        make_event(
            "a1",
            "subscriptions",
            EventDirection.DEBIT,
            date(2026, 1, 5),
            Decimal("20"),
            description="Service A",
            event_type=EventType.SUBSCRIPTION,
        ),
        make_event(
            "a2",
            "subscriptions",
            EventDirection.DEBIT,
            date(2026, 2, 5),
            Decimal("20"),
            description="Service A",
            event_type=EventType.SUBSCRIPTION,
        ),
        make_event(
            "b1",
            "subscriptions",
            EventDirection.DEBIT,
            date(2026, 1, 20),
            Decimal("40"),
            description="Service B",
            event_type=EventType.SUBSCRIPTION,
        ),
        make_event(
            "b2",
            "subscriptions",
            EventDirection.DEBIT,
            date(2026, 2, 20),
            Decimal("40"),
            description="Service B",
            event_type=EventType.SUBSCRIPTION,
        ),
    ]
    patterns = detect_recurrence_patterns(events)
    assert len(patterns) == 2
    expanded = expand_events(
        user_id="user_rec_test",
        home_currency="INR",
        start_date=date(2026, 3, 1),
        end_date=date(2026, 3, 31),
        patterns=patterns,
        existing_events=events,
    )
    assert [(event.settlement_date, event.amount_home_currency) for event in expanded] == [
        (date(2026, 3, 5), Decimal("20")),
        (date(2026, 3, 20), Decimal("40")),
    ]


def test_latest_supported_amount_overrides_historical_mode() -> None:
    events = [
        make_event("r1", "rent", EventDirection.DEBIT, date(2026, 1, 1), Decimal("100")),
        make_event("r2", "rent", EventDirection.DEBIT, date(2026, 2, 1), Decimal("100")),
        make_event("r3", "rent", EventDirection.DEBIT, date(2026, 3, 1), Decimal("125")),
    ]
    assert detect_recurrence_patterns(events)[0].amount_home_currency == Decimal("125")


def test_rent_increase_without_amount_does_not_invent_percentage() -> None:
    events = [
        make_event("r1", "rent", EventDirection.DEBIT, date(2026, 1, 1), Decimal("100")),
        make_event("r2", "rent", EventDirection.DEBIT, date(2026, 2, 1), Decimal("100")),
    ]
    message = MessageEvidence(
        message_id="rent_unknown",
        user_id="user_rec_test",
        request_id=None,
        related_event_id=None,
        sent_at=None,
        source_type="service_provider",
        evidence_type=EvidenceType.RENT_INCREASE,
        raw_text="Your rent will increase next month.",
    )
    pattern = detect_recurrence_patterns(events, [message])[0]
    assert pattern.amount_adjustments == ()


def test_first_salary_evidence_confirms_one_payment_not_a_cadence() -> None:
    message = MessageEvidence(
        message_id="first_salary",
        user_id="user_rec_test",
        request_id=None,
        related_event_id=None,
        sent_at=None,
        source_type="employer",
        evidence_type=EvidenceType.FIRST_SALARY_CONFIRMED,
        amount=Decimal("1000"),
        currency="INR",
        effective_date=date(2026, 3, 15),
    )
    patterns = detect_recurrence_patterns([], [message])
    expanded = expand_events(
        user_id="user_rec_test",
        home_currency="INR",
        start_date=date(2026, 3, 1),
        end_date=date(2026, 5, 31),
        patterns=patterns,
        existing_events=[],
    )
    assert [(event.settlement_date, event.amount_home_currency) for event in expanded] == [
        (date(2026, 3, 15), Decimal("1000"))
    ]


def test_salary_date_change_updates_future_calendar_day() -> None:
    events = [
        make_event("s1", "salary", EventDirection.CREDIT, date(2026, 1, 15), Decimal("1000")),
        make_event("s2", "salary", EventDirection.CREDIT, date(2026, 2, 15), Decimal("1000")),
    ]
    message = MessageEvidence(
        message_id="new_payday",
        user_id="user_rec_test",
        request_id=None,
        related_event_id=None,
        sent_at=None,
        source_type="employer",
        evidence_type=EvidenceType.SALARY_DATE_CHANGE,
        effective_date=date(2026, 3, 20),
    )
    expanded = expand_events(
        user_id="user_rec_test",
        home_currency="INR",
        start_date=date(2026, 3, 1),
        end_date=date(2026, 4, 30),
        patterns=detect_recurrence_patterns(events, [message]),
        existing_events=events,
    )
    assert [event.settlement_date for event in expanded] == [
        date(2026, 3, 20),
        date(2026, 4, 20),
    ]


def test_confirmed_base_salary_does_not_confirm_pending_commission() -> None:
    events = [
        make_event(
            "base_1",
            "salary",
            EventDirection.CREDIT,
            date(2026, 1, 15),
            Decimal("1000"),
            description="Base salary",
        ),
        make_event(
            "base_2",
            "salary",
            EventDirection.CREDIT,
            date(2026, 2, 15),
            Decimal("1000"),
            description="Base salary",
        ),
        make_event(
            "commission_1",
            "salary",
            EventDirection.CREDIT,
            date(2026, 1, 24),
            Decimal("300"),
            description="Sales commission",
        ),
        make_event(
            "commission_2",
            "salary",
            EventDirection.CREDIT,
            date(2026, 2, 24),
            Decimal("400"),
            description="Sales commission",
        ),
    ]
    message = MessageEvidence(
        message_id="base_only",
        user_id="user_rec_test",
        request_id=None,
        related_event_id=None,
        sent_at=None,
        source_type="employer",
        evidence_type=EvidenceType.SALARY_RESUMED,
        amount=Decimal("1100"),
        currency="INR",
        effective_date=date(2026, 3, 15),
        raw_text=(
            "Confirmed base salary is INR 1100. Commission from open deals is "
            "still pending approval."
        ),
    )
    expanded = expand_events(
        user_id="user_rec_test",
        home_currency="INR",
        start_date=date(2026, 3, 1),
        end_date=date(2026, 4, 30),
        patterns=detect_recurrence_patterns(events, [message]),
        existing_events=events,
    )

    assert [(event.settlement_date, event.amount_home_currency) for event in expanded] == [
        (date(2026, 3, 15), Decimal("1100")),
        (date(2026, 4, 15), Decimal("1100")),
    ]


def test_ended_household_income_becomes_one_remaining_salary_stream() -> None:
    events = [
        make_event(
            "primary_1",
            "salary",
            EventDirection.CREDIT,
            date(2026, 1, 15),
            Decimal("1000"),
            description="Primary household salary",
        ),
        make_event(
            "primary_2",
            "salary",
            EventDirection.CREDIT,
            date(2026, 2, 15),
            Decimal("1000"),
            description="Primary household salary",
        ),
        make_event(
            "primary_3",
            "salary",
            EventDirection.CREDIT,
            date(2026, 3, 15),
            Decimal("1000"),
            description="Primary household salary",
        ),
        make_event(
            "secondary_1",
            "salary",
            EventDirection.CREDIT,
            date(2026, 1, 20),
            Decimal("800"),
            description="Second household income",
        ),
        make_event(
            "secondary_2",
            "salary",
            EventDirection.CREDIT,
            date(2026, 2, 20),
            Decimal("800"),
            description="Second household income",
        ),
    ]
    message = MessageEvidence(
        message_id="one_income_ended",
        user_id="user_rec_test",
        request_id=None,
        related_event_id=None,
        sent_at=None,
        source_type="employer",
        evidence_type=EvidenceType.EMPLOYMENT_ENDED_SALARY_REDUCTION,
        amount=Decimal("1700"),
        currency="INR",
        effective_date=date(2026, 3, 25),
        raw_text="One household employment ended. Remaining monthly salary is INR 1700.",
    )
    expanded = expand_events(
        user_id="user_rec_test",
        home_currency="INR",
        start_date=date(2026, 4, 1),
        end_date=date(2026, 5, 31),
        patterns=detect_recurrence_patterns(events, [message]),
        existing_events=events,
    )

    assert [(event.settlement_date, event.amount_home_currency) for event in expanded] == [
        (date(2026, 4, 15), Decimal("1700")),
        (date(2026, 5, 15), Decimal("1700")),
    ]


def test_trailing_one_off_does_not_reanchor_established_recurrence() -> None:
    events = [
        make_event("g1", "groceries", EventDirection.DEBIT, date(2026, 1, 1), Decimal("80")),
        make_event("g2", "groceries", EventDirection.DEBIT, date(2026, 1, 8), Decimal("90")),
        make_event("g3", "groceries", EventDirection.DEBIT, date(2026, 1, 15), Decimal("100")),
        make_event(
            "invoice",
            "groceries",
            EventDirection.DEBIT,
            date(2026, 1, 19),
            Decimal("500"),
            description="Bulk grocery invoice",
        ),
    ]
    pattern = detect_recurrence_patterns(events)[0]
    expanded = expand_events(
        user_id="user_rec_test",
        home_currency="INR",
        start_date=date(2026, 1, 20),
        end_date=date(2026, 1, 31),
        patterns=[pattern],
        existing_events=events,
    )

    assert pattern.anchor_date == date(2026, 1, 15)
    assert pattern.amount_home_currency == Decimal("100")
    assert [(event.settlement_date, event.amount_home_currency) for event in expanded] == [
        (date(2026, 1, 22), Decimal("100")),
        (date(2026, 1, 29), Decimal("100")),
    ]


def test_salary_arrears_message_adds_one_time_amount_to_regular_pay() -> None:
    events = [
        make_event("s1", "salary", EventDirection.CREDIT, date(2026, 1, 15), Decimal("1000")),
        make_event("s2", "salary", EventDirection.CREDIT, date(2026, 2, 15), Decimal("1000")),
    ]
    message = MessageEvidenceExtractor.parse_single_message(
        message_id="arrears",
        user_id="user_rec_test",
        message_text=(
            "Your regular salary for the next payroll is INR 1000. The same payroll "
            "includes a one-time arrears adjustment of INR 450."
        ),
    )
    expanded = expand_events(
        user_id="user_rec_test",
        home_currency="INR",
        start_date=date(2026, 3, 1),
        end_date=date(2026, 4, 30),
        patterns=detect_recurrence_patterns(events, [message]),
        existing_events=events,
    )

    assert message.evidence_type == EvidenceType.SALARY_ARREARS_ADJUSTMENT
    assert message.amount == Decimal("1000")
    assert message.additional_amount == Decimal("450")
    assert [event.amount_home_currency for event in expanded] == [
        Decimal("1450"),
        Decimal("1000"),
    ]


def test_one_cycle_salary_override_reverts_to_supported_regular_amount() -> None:
    events = [
        make_event("s1", "salary", EventDirection.CREDIT, date(2025, 10, 15), Decimal("1000")),
        make_event("s2", "salary", EventDirection.CREDIT, date(2025, 11, 15), Decimal("1000")),
        make_event("s3", "salary", EventDirection.CREDIT, date(2025, 12, 15), Decimal("600")),
    ]
    message = MessageEvidence(
        message_id="temporary_next_cycle",
        user_id="user_rec_test",
        request_id=None,
        related_event_id=None,
        sent_at=None,
        source_type="employer",
        evidence_type=EvidenceType.TEMPORARY_SALARY,
        amount=Decimal("800"),
        currency="INR",
        effective_date=date(2026, 1, 15),
        raw_text="Temporary monthly pay is INR 800 for the next payroll.",
    )
    expanded = expand_events(
        user_id="user_rec_test",
        home_currency="INR",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 2, 28),
        patterns=detect_recurrence_patterns(events, [message]),
        existing_events=events,
    )

    assert [event.amount_home_currency for event in expanded] == [
        Decimal("800"),
        Decimal("1000"),
    ]


def test_variable_spending_merchant_names_do_not_create_separate_streams() -> None:
    descriptions = [
        "Supermarket basket",
        "Neighbourhood grocer",
        "Supermarket basket",
        "Local market purchase",
        "Neighbourhood grocer",
        "Fresh food shop",
    ]
    events = [
        make_event(
            f"g{index}",
            "groceries",
            EventDirection.DEBIT,
            date(2026, 1, 1) + timedelta(days=(index - 1) * 10),
            Decimal(str(90 + index)),
            description=description,
        )
        for index, description in enumerate(descriptions, start=1)
    ]
    patterns = detect_recurrence_patterns(events)

    assert len(patterns) == 1
    assert patterns[0].stream_id == "category"
    assert patterns[0].frequency_days == 10
    assert patterns[0].source_event_ids == tuple(f"g{index}" for index in range(1, 7))
