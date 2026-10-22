import re
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from orcha.evidence.models import EvidenceType, MessageEvidence
from orcha.models import EventDirection, EventStatus, NormalizedFinancialEvent


class LifecycleResolutionResult:
    """Outcome of resolving linked events and message amendments."""

    def __init__(self) -> None:
        self.superceded_event_ids: set[str] = set()
        self.neutralized_internal_transfer_ids: set[str] = set()
        self.resolution_reasons: dict[str, str] = {}
        self.amended_attributes: dict[str, dict[str, object]] = {}


def _cash_date(event: NormalizedFinancialEvent) -> date:
    return event.settlement_date or event.event_date


def _message_date(message: MessageEvidence) -> date:
    if message.sent_at is not None:
        return message.sent_at.date()
    return message.effective_date or date.min


def _rent_multiplier(message: MessageEvidence) -> Decimal | None:
    match = re.search(r"(\d+(?:\.\d+)?)\s*%", f"{message.notes} {message.raw_text}")
    if match is None:
        return None
    return Decimal("1") + Decimal(match.group(1)) / Decimal("100")


def resolve_event_lifecycles(
    events: list[NormalizedFinancialEvent],
    user_messages: list[MessageEvidence] | None = None,
) -> LifecycleResolutionResult:
    """Deterministically resolve linked events and message evidence across a user's ledger."""
    result = LifecycleResolutionResult()
    user_messages = user_messages or []

    # Map events by ID
    event_by_id = {e.event_id: e for e in events}

    # 1. Resolve linked event pairs (58 pairs in dataset)
    for e2 in events:
        if not e2.linked_event_id:
            continue
        e1 = event_by_id.get(e2.linked_event_id)
        if e1 is None:
            continue

        # Case A: Failed debit retry (e.g. debt_payment failed -> debt_payment scheduled retry)
        if e1.status == EventStatus.FAILED and e2.status == EventStatus.SCHEDULED:
            result.superceded_event_ids.add(e1.event_id)
            result.resolution_reasons[e1.event_id] = (
                f"Failed obligation superceded by retry {e2.event_id}"
            )
            result.resolution_reasons[e2.event_id] = (
                f"Scheduled retry for earlier failed event {e1.event_id}"
            )

        # Case B: Cancelled debit followed by settled purchase
        elif e1.status == EventStatus.CANCELLED and e2.status == EventStatus.SETTLED:
            result.superceded_event_ids.add(e1.event_id)
            result.resolution_reasons[e1.event_id] = (
                f"Cancelled purchase superceded by settled event {e2.event_id}"
            )
            result.resolution_reasons[e2.event_id] = (
                f"Settled purchase replacing cancelled event {e1.event_id}"
            )

        # Case C: Settled debit with pending merchant refund
        elif (
            e1.status == EventStatus.SETTLED
            and e1.direction == EventDirection.DEBIT
            and e2.event_type == "refund"
            and e2.status == EventStatus.PENDING
        ):
            result.resolution_reasons[e1.event_id] = "Original settled debit"
            result.resolution_reasons[e2.event_id] = (
                f"Pending merchant refund linked to {e1.event_id} "
                "(not spendable cash until settled)"
            )

        # Case D: Settled debit with duplicate card charge investigation (pending debit)
        elif (
            e1.status == EventStatus.SETTLED
            and e2.status == EventStatus.PENDING
            and e2.direction == EventDirection.DEBIT
        ):
            result.resolution_reasons[e1.event_id] = "Original settled transaction"
            result.resolution_reasons[e2.event_id] = (
                f"Pending duplicate charge linked to {e1.event_id} (reserved conservatively)"
            )

        # Case E: Settled debit with settled reversal / reimbursement
        elif (
            e1.status == EventStatus.SETTLED
            and e2.status == EventStatus.SETTLED
            and e2.direction == EventDirection.CREDIT
        ):
            result.resolution_reasons[e1.event_id] = "Original settled debit"
            result.resolution_reasons[e2.event_id] = (
                f"Settled credit/reversal linked to {e1.event_id}"
            )

        # Case F: Unrealized portfolio valuation linked to settled investment purchase
        elif (
            e2.status == EventStatus.UNREALIZED
            or e2.direction == EventDirection.NON_CASH
            or e2.event_type == "investment_valuation"
        ):
            result.resolution_reasons[e2.event_id] = (
                f"Unrealized valuation linked to {e1.event_id} "
                "(non-cash, excluded from liquid balance)"
            )

    # 2. Check for message-supported internal transfers
    internal_transfer_msgs = sorted(
        (m for m in user_messages if m.evidence_type == EvidenceType.INTERNAL_TRANSFER),
        key=lambda message: (_message_date(message), message.message_id),
    )
    for message in internal_transfer_msgs:
        # Unlinked evidence without an amount cannot safely identify a particular pair.
        if message.related_event_id is None and message.amount is None:
            continue
        candidates: list[tuple[NormalizedFinancialEvent, NormalizedFinancialEvent]] = []
        for debit in events:
            if debit.direction != EventDirection.DEBIT or debit.status not in (
                EventStatus.SETTLED,
                EventStatus.SCHEDULED,
            ):
                continue
            for credit in events:
                if credit.direction != EventDirection.CREDIT or credit.status != debit.status:
                    continue
                if message.related_event_id not in (None, debit.event_id, credit.event_id):
                    continue
                debit_amount = debit.amount_home_currency
                credit_amount = credit.amount_home_currency
                if debit_amount is None or credit_amount is None or debit_amount != credit_amount:
                    continue
                if message.amount is not None:
                    raw_match = debit.amount == message.amount and credit.amount == message.amount
                    home_match = debit_amount == message.amount and credit_amount == message.amount
                    if not (raw_match or home_match):
                        continue
                if abs((_cash_date(debit) - _cash_date(credit)).days) > 2:
                    continue
                if message.sent_at is not None:
                    sent_date = message.sent_at.date()
                    newest_event = max(_cash_date(debit), _cash_date(credit))
                    if not sent_date - timedelta(days=14) <= newest_event <= sent_date:
                        continue
                candidates.append((debit, credit))

        # Ambiguous evidence is not financial authority; only a unique pair is neutralized.
        if len(candidates) != 1:
            continue
        debit, credit = candidates[0]
        result.neutralized_internal_transfer_ids.update((debit.event_id, credit.event_id))
        reason = f"Internal transfer pair identified by message {message.message_id}"
        result.resolution_reasons[debit.event_id] = reason
        result.resolution_reasons[credit.event_id] = reason

    # 3. Apply direct message amendments to related events
    direct_messages: dict[str, list[MessageEvidence]] = defaultdict(list)
    for message in user_messages:
        if message.related_event_id and message.related_event_id in event_by_id:
            direct_messages[message.related_event_id].append(message)

    for eid, event_messages in direct_messages.items():
        ev = event_by_id[eid]
        current_amount = ev.amount_home_currency
        for m in sorted(
            event_messages, key=lambda message: (_message_date(message), message.message_id)
        ):
            amendments: dict[str, object] = {}

            if m.evidence_type == EvidenceType.RENT_INCREASE:
                if current_amount is not None:
                    multiplier = _rent_multiplier(m)
                    if m.amount is not None and m.currency in (None, "", ev.home_currency):
                        amendments["amount_home_currency"] = m.amount
                    elif multiplier is not None:
                        amendments["amount_home_currency"] = current_amount * multiplier
                    if "amount_home_currency" in amendments:
                        result.resolution_reasons[eid] = (
                            f"Rent amount amended per message {m.message_id}"
                        )

            elif m.evidence_type in (
                EvidenceType.SALARY_INCREASE,
                EvidenceType.TEMPORARY_SALARY,
                EvidenceType.UNPAID_LEAVE_REDUCTION,
                EvidenceType.EMPLOYMENT_ENDED_SALARY_REDUCTION,
                EvidenceType.SALARY_RESUMED,
            ):
                if m.amount is not None and m.currency in (None, "", ev.home_currency):
                    amendments["amount_home_currency"] = m.amount
                    curr_str = f" {m.currency}" if m.currency else ""
                    result.resolution_reasons[eid] = (
                        f"Salary amended to {m.amount}{curr_str} per message {m.message_id}"
                    )

            elif m.evidence_type == EvidenceType.SALARY_DATE_CHANGE:
                if m.effective_date is not None:
                    amendments["settlement_date"] = m.effective_date
                    amendments["event_date"] = m.effective_date
                    result.resolution_reasons[eid] = (
                        f"Salary date amended to {m.effective_date} per message {m.message_id}"
                    )

            if amendments:
                result.amended_attributes.setdefault(eid, {}).update(amendments)
                amended_amount = amendments.get("amount_home_currency")
                if amended_amount is not None:
                    current_amount = Decimal(str(amended_amount))

    return result
