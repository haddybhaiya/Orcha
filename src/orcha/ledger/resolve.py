"""Master canonical financial ledger resolver."""

from datetime import date, timedelta

from orcha.evidence.images import ImageEvidenceExtractor
from orcha.evidence.messages import MessageEvidenceExtractor
from orcha.ledger.classify import classify_for_forecast
from orcha.ledger.lifecycle import resolve_event_lifecycles
from orcha.ledger.models import ForecastBehavior, ResolvedFinancialEvent
from orcha.ledger.recurrence import detect_recurrence_patterns, expand_events
from orcha.models import (
    EventStatus,
    FlexibilityType,
    NormalizedFinancialEvent,
)
from orcha.money import quantize_money
from orcha.repository import DatasetRepository


class UnresolvedFinancialEvidenceError(ValueError):
    """Raised when a cash event cannot be resolved without inventing an amount."""


def resolve_canonical_ledger(
    repository: DatasetRepository,
    user_id: str,
    request_date: date,
    request_id: str | None = None,
    forecast_horizon_days: int = 90,
    image_extractor: ImageEvidenceExtractor | None = None,
    message_extractor: MessageEvidenceExtractor | None = None,
) -> list[ResolvedFinancialEvent]:
    """Resolve financial history, pending state, and future obligations into a ledger."""
    profile = repository.get_profile(user_id)
    home_currency = profile.home_currency
    raw_events = repository.get_events_for_user(user_id)

    images = image_extractor or ImageEvidenceExtractor()
    messages = message_extractor or MessageEvidenceExtractor()

    # Parse the current financial records themselves.  Cached extraction is an
    # optimization artifact, never an independent source of financial facts.
    user_messages = []
    for record in repository.get_messages_for_user(user_id):
        if record.sent_at.date() > request_date:
            continue
        if record.request_id is not None and record.request_id != request_id:
            continue
        user_messages.append(
            messages.parse_single_message(
                message_id=record.message_id,
                user_id=record.user_id,
                message_text=record.message_text,
                request_id=record.request_id,
                related_event_id=record.related_event_id,
                sent_at=record.sent_at,
                source_type=record.source_type.value,
            )
        )

    # 1. First pass: Resolve blank amounts using image evidence
    normalized_events: list[NormalizedFinancialEvent] = []
    amount_sources: dict[str, str] = {}
    image_evidence_map: dict[str, tuple[str, ...]] = {}

    for ev in raw_events:
        if ev.amount is None:
            img_evidence = images.get_by_event_id(ev.event_id)
            image_record = repository.get_image_for_event(ev.event_id)
            image_file_exists = (
                repository.dataset_dir is None
                or image_record is None
                or (
                    repository.dataset_dir / "media" / "images" / f"{image_record.image_id}.png"
                ).is_file()
            )
            cache_matches_source = (
                img_evidence is not None
                and image_record is not None
                and img_evidence.image_id == image_record.image_id
                and img_evidence.user_id == ev.user_id
                and img_evidence.related_event_id == ev.event_id
                and image_file_exists
            )
            if cache_matches_source and img_evidence is not None:
                img_amt = img_evidence.amount
                img_curr = img_evidence.currency
                # Convert to home currency if foreign
                if img_curr == home_currency:
                    amt_home = img_amt
                else:
                    rate_date = ev.settlement_date or ev.event_date
                    amt_home = repository.fx_resolver.convert(
                        amount=img_amt,
                        from_currency=img_curr,
                        to_currency=home_currency,
                        rate_date=rate_date,
                    )
                    amt_home = quantize_money(amt_home)
                ev = NormalizedFinancialEvent(
                    event_id=ev.event_id,
                    user_id=ev.user_id,
                    event_type=ev.event_type,
                    description=ev.description,
                    category=ev.category,
                    direction=ev.direction,
                    amount=img_amt,
                    currency=img_curr,
                    amount_home_currency=amt_home,
                    home_currency=home_currency,
                    event_date=ev.event_date,
                    settlement_date=ev.settlement_date,
                    status=ev.status,
                    linked_event_id=ev.linked_event_id,
                    flexibility=ev.flexibility,
                    minimum_allowed_amount=ev.minimum_allowed_amount,
                )
                amount_sources[ev.event_id] = f"image:{img_evidence.image_id}"
                image_evidence_map[ev.event_id] = (img_evidence.image_id,)
            else:
                raise UnresolvedFinancialEvidenceError(
                    f"Event '{ev.event_id}' has no amount and lacks matching image evidence"
                )
        else:
            amount_sources[ev.event_id] = "event"
            image_evidence_map[ev.event_id] = ()

        normalized_events.append(ev)

    # 2. Lifecycle and message conflict resolution
    lifecycle_res = resolve_event_lifecycles(normalized_events, user_messages)

    amended_events: list[NormalizedFinancialEvent] = []
    for event in normalized_events:
        amendments = lifecycle_res.amended_attributes.get(event.event_id, {})
        update: dict[str, object] = {}
        if "amount_home_currency" in amendments:
            update["amount_home_currency"] = amendments["amount_home_currency"]
        if "settlement_date" in amendments:
            update["settlement_date"] = date.fromisoformat(str(amendments["settlement_date"]))
        if "event_date" in amendments:
            update["event_date"] = date.fromisoformat(str(amendments["event_date"]))
        amended_events.append(event.model_copy(update=update))

    # Recurrence is inferred only after newer amendments have been applied.
    patterns = detect_recurrence_patterns(amended_events, user_messages)
    recurring_sources = {event_id for pattern in patterns for event_id in pattern.source_event_ids}

    # 3. Build canonical resolved events for existing records
    resolved_list: list[ResolvedFinancialEvent] = []

    message_ids_by_event: dict[str, list[str]] = {}
    for message in user_messages:
        if message.related_event_id:
            message_ids_by_event.setdefault(message.related_event_id, []).append(message.message_id)

    for ev in amended_events:
        eid = ev.event_id
        if ev.amount_home_currency is None:
            raise UnresolvedFinancialEvidenceError(
                f"Event '{ev.event_id}' has no normalized home-currency amount"
            )
        amt_home = ev.amount_home_currency
        direction = ev.direction
        status = ev.status
        settlement_date: date = ev.settlement_date or ev.event_date
        event_date = ev.event_date
        reason = lifecycle_res.resolution_reasons.get(eid, "")

        # Check for internal transfer neutralization
        if eid in lifecycle_res.neutralized_internal_transfer_ids:
            forecast_behavior = ForecastBehavior.IGNORED_NON_CASH
        elif eid in lifecycle_res.superceded_event_ids:
            if status == EventStatus.FAILED:
                forecast_behavior = ForecastBehavior.IGNORED_FAILED
            elif status == EventStatus.CANCELLED:
                forecast_behavior = ForecastBehavior.IGNORED_CANCELLED
            else:
                forecast_behavior = ForecastBehavior.IGNORED_NON_CASH
        else:
            # Standard forecast classification relative to request_date
            forecast_behavior = classify_for_forecast(
                status=status,
                direction=direction,
                settlement_date=settlement_date,
                request_date=request_date,
            )

        # Map related messages
        msg_ids = tuple(message_ids_by_event.get(eid, ()))

        res_ev = ResolvedFinancialEvent(
            canonical_event_id=eid,
            user_id=user_id,
            event_type=ev.event_type,
            description=ev.description,
            category=ev.category,
            direction=direction,
            amount_home_currency=amt_home,
            home_currency=home_currency,
            original_amount=ev.amount,
            original_currency=ev.currency,
            event_date=event_date,
            settlement_date=settlement_date,
            resolved_status=status,
            forecast_behavior=forecast_behavior,
            flexibility=ev.flexibility or FlexibilityType.FIXED,
            minimum_allowed_amount=ev.minimum_allowed_amount,
            is_recurring=eid in recurring_sources,
            recurrence_pattern=None,
            source_event_ids=(eid,),
            message_evidence_ids=msg_ids,
            image_evidence_ids=image_evidence_map.get(eid, ()),
            resolution_reason=reason,
            amount_source=amount_sources.get(eid, "event"),
        )
        resolved_list.append(res_ev)

    # 4. Recurrence detection and forecast window expansion
    forecast_end_date = request_date + timedelta(days=forecast_horizon_days)

    projected_recurring = expand_events(
        user_id=user_id,
        home_currency=home_currency,
        start_date=request_date,
        end_date=forecast_end_date,
        patterns=patterns,
        existing_events=amended_events,
    )
    resolved_list.extend(projected_recurring)

    # 5. Chronological sort
    resolved_list.sort(key=lambda x: (x.settlement_date, x.event_date, x.canonical_event_id))
    return resolved_list
