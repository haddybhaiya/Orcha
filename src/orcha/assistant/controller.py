"""Validate grounded evidence, construct an isolated request, and verify its result."""

import hashlib
import re
from datetime import date, datetime, timedelta
from decimal import Decimal

from orcha.assistant.contracts import (
    AssistantInput,
    AssistantResult,
    DateQuote,
    EvidenceFact,
    InterpretationContext,
    ModelUsage,
    MoneyQuote,
    TextSource,
)
from orcha.assistant.routing import ActionRouter, RoutingSession
from orcha.evaluation import validate_final_rows
from orcha.evidence.gemma import GemmaUnavailable
from orcha.evidence.provider import StructuredEvidenceProvider
from orcha.models import (
    EventDirection,
    EventFlexibility,
    EventStatus,
    EventType,
    FinancialRequest,
    NormalizedFinancialEvent,
    PaymentOption,
    PaymentOptionMethod,
    RequestType,
)
from orcha.money import ExchangeRateError, quantize_money
from orcha.planning.engine import DecisionEngine
from orcha.repository import DatasetRepository

_INSTRUCTIONS = re.compile(
    r"ignore\s+(?:all\s+)?(?:previous\s+)?instructions?|system\s*prompt|"
    r"bypass\s+rules?|you\s+are\s+now|mark\s+the\s+user\s+rich|"
    r"(?:ignore|disable|override)\s+(?:the\s+)?(?:minimum|balance|rules)",
    re.I,
)
_UNCERTAIN_BILL = re.compile(
    r"\b(?:cancelled|canceled|paid|settled|refund|refunded|estimate|estimated|"
    r"tentative|perhaps|might|maybe|not\s+(?:due|owed|payable|confirmed)|"
    r"do\s+not\s+(?:owe|pay)|not\s+a\s+bill)\b",
    re.I,
)


def _currency_amounts(text: str) -> set[tuple[str, Decimal]]:
    code = r"[A-Z]{3}"
    number = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
    matches = re.findall(rf"\b({code})\s*({number})(?!\w|\.\d|,\d)", text)
    matches += [
        (currency, value)
        for value, currency in re.findall(rf"(?<![\w.,])({number})\s*({code})\b", text)
    ]
    return {(currency, Decimal(value.replace(",", ""))) for currency, value in matches}


def _money_grounded(fact: MoneyQuote, source: TextSource) -> bool:
    return (
        fact.source_id == source.source_id
        and fact.quote in source.text
        and (fact.currency, fact.amount) in _currency_amounts(fact.quote)
    )


def _multiple_amounts(source: TextSource) -> bool:
    """A short text update must identify one payable amount, not competing totals."""
    return len(_currency_amounts(source.text)) > 1


def _date_grounded(fact: DateQuote, source: TextSource) -> bool:
    if fact.source_id != source.source_id or fact.quote not in source.text:
        return False
    if re.search(rf"(?<!\d){fact.value.isoformat()}(?!\d)", fact.quote):
        return True
    for pattern, formats in [
        (r"\b\d{1,2}\s+[A-Za-z]+\s+\d{4}\b", ["%d %B %Y", "%d %b %Y"]),
        (r"\b[A-Za-z]+\s+\d{1,2},?\s+\d{4}\b", ["%B %d %Y", "%b %d %Y"]),
    ]:
        for candidate in re.findall(pattern, fact.quote):
            for fmt in formats:
                try:
                    if datetime.strptime(candidate.replace(",", ""), fmt).date() == fact.value:
                        return True
                except ValueError:
                    continue
    return False


def _clarify(questions: list[str], actions: list[str], usage: ModelUsage | None) -> AssistantResult:
    return AssistantResult(
        status="needs_clarification",
        brief="More information is needed before calculating a recommendation.",
        questions=list(dict.fromkeys(questions)),
        actions=[*actions, "ask_clarification"],
        usage=usage,
    )


def run_assistant(
    request: AssistantInput,
    repository: DatasetRepository,
    provider: StructuredEvidenceProvider,
    router: ActionRouter | None = None,
) -> AssistantResult:
    """Use model facts only after grounding and domain checks; never edit imported data."""
    actions: list[str] = []
    routing = RoutingSession(router, len(request.documents))

    def clarify(
        questions: list[str], actions: list[str], usage: ModelUsage | None
    ) -> AssistantResult:
        routing.choose("ask_clarification", issues=len(questions))
        return _clarify(questions, actions, usage).model_copy(update={"routing": routing.decisions})

    if request.user_id not in repository.all_profiles:
        return clarify(["Import a financial profile for this user first."], actions, None)
    profile = repository.get_profile(request.user_id)
    if (
        not re.fullmatch(r"[A-Z]{3}", profile.home_currency)
        or not profile.current_available_balance.is_finite()
        or not profile.minimum_balance_to_keep.is_finite()
        or profile.minimum_balance_to_keep < 0
    ):
        return clarify(
            ["Import a valid profile currency, balance, and minimum balance."], actions, None
        )
    sources = [request.question, *request.documents]
    if any(_INSTRUCTIONS.search(source.text) for source in sources):
        return clarify(
            [
                "A source contains instructions aimed at the assistant. Supply the financial facts "
                "without those instructions."
            ],
            actions,
            None,
        )
    ambiguous = [
        source.source_id for source in request.documents if _UNCERTAIN_BILL.search(source.text)
    ]
    if ambiguous:
        return clarify(
            [
                f"Confirm whether {source_id} is an unpaid, confirmed bill and provide its current "
                "amount and due date."
                for source_id in ambiguous
            ],
            actions,
            None,
        )
    if len({source.text.strip() for source in request.documents}) != len(request.documents):
        return clarify(
            ["The same document was supplied twice. Confirm which bills are distinct."],
            actions,
            None,
        )
    if any(_multiple_amounts(source) for source in sources):
        return clarify(
            [
                "A source contains multiple monetary amounts. Supply one confirmed purchase "
                "price or payable bill total per source, or reconcile the conflicting amounts."
            ],
            actions,
            None,
        )
    actions.append(routing.choose("interpret_request"))
    try:
        interpreted = provider.interpret(
            InterpretationContext(request=request, home_currency=profile.home_currency)
        )
    except GemmaUnavailable as error:
        return AssistantResult(
            status="unavailable", brief=str(error), actions=actions, routing=routing.decisions
        )
    extraction, usage = interpreted.extraction, interpreted.usage
    actions.append("validate_evidence")
    questions: list[str] = []
    facts: list[EvidenceFact] = []
    money, deadline = extraction.purchase.money, extraction.purchase.deadline
    if money is None or not _money_grounded(money, request.question):
        questions.append(
            "State the purchase amount and its three-letter currency explicitly in the question."
        )
    elif money.currency != profile.home_currency:
        questions.append(
            f"State the purchase amount in the profile's currency, {profile.home_currency}."
        )
    if deadline is None or not _date_grounded(deadline, request.question):
        questions.append(
            "State the purchase completion deadline with an explicit year, month, and day."
        )
    elif not request.as_of <= deadline.value <= request.as_of + timedelta(days=89):
        questions.append("Choose a purchase deadline within the 90-day forecast window.")

    documents = {source.source_id: source for source in request.documents}
    accounted = [bill.source_id for bill in extraction.bills] + [
        item.source_id for item in extraction.unresolved
    ]
    if sorted(accounted) != sorted(documents):
        questions.append(
            "Every supplied update must be interpreted exactly once. "
            "Clarify any missing or duplicated updates."
        )
    if extraction.unresolved:
        questions.extend(
            f"Clarify {item.source_id}: {item.reason.replace('_', ' ')}. Supply a confirmed bill "
            "amount, currency, and due date, or import the unsupported financial change first."
            for item in extraction.unresolved
        )

    events = list(repository.get_events_for_user(request.user_id))
    by_id = {event.event_id: event for event in events}
    event_updates: dict[str, NormalizedFinancialEvent] = {}
    new_events: list[NormalizedFinancialEvent] = []
    seen_references: set[str] = set()
    seen_bills: set[tuple[Decimal, str, date]] = set()
    for bill in extraction.bills:
        source = documents.get(bill.source_id)
        if source is None:
            continue
        amount, due = bill.money, bill.due_date
        if amount is None or not _money_grounded(amount, source):
            questions.append(f"Confirm the amount and currency printed in {source.source_id}.")
            continue
        if due is None or not _date_grounded(due, source):
            questions.append(f"Confirm the explicit payment due date in {source.source_id}.")
            continue
        if not request.as_of <= due.value <= request.as_of + timedelta(days=89):
            questions.append(
                f"Resolve the bill date in {source.source_id}; it is outside this forecast window."
            )
            continue
        if bill.reference is not None:
            if (
                not bill.reference.strip()
                or bill.reference not in source.text
                or bill.reference in seen_references
            ):
                questions.append(
                    f"Confirm the bill reference in {source.source_id}; "
                    "it is unsupported or duplicated."
                )
            seen_references.add(bill.reference)
        bill_key = (amount.amount, amount.currency, due.value)
        if bill_key in seen_bills:
            questions.append(
                "Two updates have the same amount and due date. "
                "Confirm whether they are the same bill."
            )
        seen_bills.add(bill_key)
        if bill.operation == "amend_bill":
            target = by_id.get(source.related_event_id or "")
            if (
                target is None
                or target.status != EventStatus.SCHEDULED
                or target.direction != EventDirection.DEBIT
            ):
                questions.append(
                    f"Link {source.source_id} to this user's scheduled debit event "
                    "before amending it."
                )
                continue
            if (target.settlement_date or target.event_date) < request.as_of:
                questions.append(
                    f"Reconcile the overdue event linked to {source.source_id} before amending it."
                )
                continue
            event_id = target.event_id
            if event_id in event_updates:
                questions.append(
                    f"Multiple updates amend {event_id}; provide one confirmed current bill."
                )
                continue
        else:
            if source.related_event_id is not None:
                questions.append(
                    f"Confirm whether {source.source_id} amends the linked bill "
                    "rather than adding another bill."
                )
                continue
            if any(
                e.amount == amount.amount
                and e.currency == amount.currency
                and (e.settlement_date or e.event_date) == due.value
                and e.direction == EventDirection.DEBIT
                and e.status in {EventStatus.SCHEDULED, EventStatus.PENDING}
                for e in events
            ):
                questions.append(
                    f"The bill in {source.source_id} may already be imported. "
                    "Link the existing event to amend it."
                )
                continue
            event_id = (
                "assistant_bill_"
                + hashlib.sha256(source.model_dump_json().encode()).hexdigest()[:20]
            )
        try:
            home_amount = quantize_money(
                repository.fx_resolver.convert(
                    amount.amount, amount.currency, profile.home_currency, due.value
                )
            )
        except (ExchangeRateError, ValueError, KeyError):
            questions.append(
                f"Import a dated {amount.currency}/{profile.home_currency} FX rate for {due.value}."
            )
            continue
        update = NormalizedFinancialEvent(
            event_id=event_id,
            user_id=request.user_id,
            event_type=EventType.EXPENSE,
            description=f"Documented bill {source.source_id}",
            category=f"documented_bill_{source.source_id}",
            direction=EventDirection.DEBIT,
            amount=amount.amount,
            currency=amount.currency,
            amount_home_currency=home_amount,
            home_currency=profile.home_currency,
            event_date=due.value,
            settlement_date=due.value,
            status=EventStatus.SCHEDULED,
            flexibility=EventFlexibility.FIXED,
            is_foreign_currency=amount.currency != profile.home_currency,
        )
        if bill.operation == "amend_bill":
            # Preserve the original obligation's category, identity, and other constraints.
            event_updates[event_id] = by_id[event_id].model_copy(
                update={
                    "amount": update.amount,
                    "currency": update.currency,
                    "amount_home_currency": update.amount_home_currency,
                    "event_date": update.event_date,
                    "settlement_date": update.settlement_date,
                    "is_foreign_currency": update.is_foreign_currency,
                }
            )
        else:
            new_events.append(update)
        facts.extend(
            [
                EvidenceFact(
                    source_id=source.source_id,
                    field="bill_amount",
                    value=f"{amount.currency} {amount.amount:f}",
                    quote=amount.quote,
                    event_id=event_id,
                ),
                EvidenceFact(
                    source_id=source.source_id,
                    field="bill_due_date",
                    value=due.value.isoformat(),
                    quote=due.quote,
                    event_id=event_id,
                ),
            ]
        )
    if questions:
        return clarify(questions, actions, usage)
    assert money is not None and deadline is not None
    request_id = "assistant_" + hashlib.sha256(request.model_dump_json().encode()).hexdigest()[:20]
    financial_request = FinancialRequest(
        request_id=request_id,
        user_id=request.user_id,
        request_date=request.as_of,
        request_type=RequestType.PURCHASE,
        requested_amount=money.amount,
        desired_completion_date=deadline.value,
        allows_partial_payment=False,
        request_text=request.question.text,
    )
    option = PaymentOption(
        payment_option_id=f"{request_id}_full",
        request_id=request_id,
        payment_method=PaymentOptionMethod.FULL_PAYMENT,
        payment_amount=money.amount,
        number_of_payments=1,
        first_payment_date=request.as_of,
        financing_fee=Decimal("0"),
        total_payable_amount=money.amount,
    )
    isolated = DatasetRepository(
        requests=[financial_request],
        profiles={request.user_id: profile},
        events=[event_updates.get(event.event_id, event) for event in events] + new_events,
        payment_options={request_id: [option]},
        messages=repository.get_messages_for_user(request.user_id),
        images=[image for image in repository.all_images if image.user_id == request.user_id],
        fx_resolver=repository.fx_resolver,
        dataset_dir=repository.dataset_dir,
    )
    actions.append(routing.choose("run_forecast"))
    try:
        decision = DecisionEngine(isolated).evaluate_request(request_id)
        actions.append("verify_result")
        validate_final_rows([decision], isolated)
    except (ExchangeRateError, ValueError, KeyError, ArithmeticError):
        return clarify(
            [
                "The imported financial evidence could not be fully verified. "
                "Reconcile it before proceeding."
            ],
            actions,
            usage,
        )
    facts.extend(
        [
            EvidenceFact(
                source_id=request.question.source_id,
                field="purchase_amount",
                value=f"{money.currency} {money.amount:f}",
                quote=money.quote,
            ),
            EvidenceFact(
                source_id=request.question.source_id,
                field="purchase_deadline",
                value=deadline.value.isoformat(),
                quote=deadline.quote,
            ),
            EvidenceFact(
                source_id=f"profile:{request.user_id}",
                field="minimum_balance_to_keep",
                value=f"{profile.home_currency} {profile.minimum_balance_to_keep:f}",
                quote="Imported financial profile",
            ),
        ]
    )
    actions.append(routing.choose("explain_result"))
    # The model never writes financial conclusions: use only independently verified output.
    brief = (
        f"{decision.decision_explanation}\n"
        f"Safe to pay today: {profile.home_currency} {decision.amount_safe_to_pay:,.2f}.\n"
        f"Minimum balance target: {profile.home_currency} "
        f"{profile.minimum_balance_to_keep:,.2f}."
    )
    return AssistantResult(
        status="complete",
        brief=brief,
        decision=decision,
        evidence=facts,
        actions=actions,
        usage=usage,
        routing=routing.decisions,
    )
