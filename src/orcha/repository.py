"""Indexed dataset repository for deterministic, efficient lookups across all financial entities."""

from collections import defaultdict
from pathlib import Path

from orcha.loaders import DatasetLoader, load_requests
from orcha.models import (
    FinancialProfile,
    FinancialRequest,
    ImageRecord,
    MessageRecord,
    NormalizedFinancialEvent,
    PaymentOption,
)
from orcha.money import ExchangeRateResolver


class DatasetRepository:
    """In-memory indexed repository containing all validated, typed, and normalized financial data.

    Constructs lookup indexes at initialization for O(1) retrieval without repeated filtering.
    """

    def __init__(
        self,
        requests: list[FinancialRequest],
        profiles: dict[str, FinancialProfile],
        events: list[NormalizedFinancialEvent],
        payment_options: dict[str, list[PaymentOption]],
        messages: list[MessageRecord],
        images: list[ImageRecord],
        fx_resolver: ExchangeRateResolver,
        sample_requests: list[FinancialRequest] | None = None,
        dataset_dir: Path | None = None,
    ) -> None:
        self.all_requests = requests
        self.sample_requests = sample_requests or []
        self.all_profiles = profiles
        self.all_events = events
        self.all_payment_options = payment_options
        self.all_messages = messages
        self.all_images = images
        self.fx_resolver = fx_resolver
        self.dataset_dir = dataset_dir

        # Keep public examples in a separate namespace.  Production request lookup
        # must never be overwritten by an evaluation-oracle row with a colliding ID.
        self._requests_by_id: dict[str, FinancialRequest] = {r.request_id: r for r in requests}
        self._sample_requests_by_id: dict[str, FinancialRequest] = {
            r.request_id: r for r in self.sample_requests
        }

        self._profiles_by_id: dict[str, FinancialProfile] = dict(profiles)
        self._events_by_id: dict[str, NormalizedFinancialEvent] = {e.event_id: e for e in events}

        self._events_by_user: dict[str, list[NormalizedFinancialEvent]] = defaultdict(list)
        for ev in events:
            self._events_by_user[ev.user_id].append(ev)

        self._options_by_request: dict[str, list[PaymentOption]] = dict(payment_options)

        self._messages_by_user: dict[str, list[MessageRecord]] = defaultdict(list)
        self._messages_by_request: dict[str, list[MessageRecord]] = defaultdict(list)
        self._messages_by_event: dict[str, list[MessageRecord]] = defaultdict(list)
        for msg in messages:
            self._messages_by_user[msg.user_id].append(msg)
            if msg.request_id:
                self._messages_by_request[msg.request_id].append(msg)
            if msg.related_event_id:
                self._messages_by_event[msg.related_event_id].append(msg)

        self._images_by_user: dict[str, list[ImageRecord]] = defaultdict(list)
        self._images_by_request: dict[str, list[ImageRecord]] = defaultdict(list)
        self._image_by_event: dict[str, ImageRecord] = {}
        for img in images:
            self._images_by_user[img.user_id].append(img)
            if img.request_id:
                self._images_by_request[img.request_id].append(img)
            if img.related_event_id:
                self._image_by_event[img.related_event_id] = img

    @classmethod
    def load_from_dir(
        cls, dataset_dir: Path, *, include_samples: bool = False
    ) -> "DatasetRepository":
        """Load production inputs, optionally adding isolated public-oracle requests."""
        loader = DatasetLoader(dataset_dir)
        loader.validate()

        raw_requests = loader.load_all_requests()
        profiles = loader.load_all_profiles()
        raw_options = loader.load_all_payment_options()
        raw_events = loader.load_all_events()
        raw_rates = loader.load_all_rates()
        messages = loader.load_all_messages()
        images = loader.load_all_images()

        sample_path = dataset_dir / "sample_requests.csv"
        raw_samples = (
            load_requests(sample_path) if include_samples and sample_path.is_file() else []
        )

        fx_resolver = ExchangeRateResolver(raw_rates)

        # Normalize financial events to user's home currency
        normalized_events: list[NormalizedFinancialEvent] = []
        for raw in raw_events:
            profile = profiles.get(raw.user_id)
            home_curr = profile.home_currency if profile else raw.currency

            amt_home = None
            rate_used = None
            rate_date = None
            is_foreign = raw.currency != home_curr

            if raw.amount is not None:
                if not is_foreign:
                    amt_home = raw.amount
                    rate_used = None
                else:
                    rate_date = raw.settlement_date or raw.event_date
                    rate_used = fx_resolver.get_rate(raw.currency, home_curr, rate_date)
                    amt_home = raw.amount * rate_used

            minimum_home = raw.minimum_allowed_amount
            if minimum_home is not None and is_foreign:
                if rate_used is None:
                    rate_date = raw.settlement_date or raw.event_date
                    rate_used = fx_resolver.get_rate(raw.currency, home_curr, rate_date)
                minimum_home *= rate_used

            norm_ev = NormalizedFinancialEvent(
                event_id=raw.event_id,
                user_id=raw.user_id,
                event_type=raw.event_type,
                description=raw.description,
                category=raw.category,
                direction=raw.direction,
                amount=raw.amount,
                currency=raw.currency,
                event_date=raw.event_date,
                settlement_date=raw.settlement_date,
                status=raw.status,
                linked_event_id=raw.linked_event_id,
                flexibility=raw.flexibility,
                minimum_allowed_amount=minimum_home,
                amount_home_currency=amt_home,
                home_currency=home_curr,
                conversion_rate_used=rate_used,
                conversion_rate_date=rate_date,
                is_foreign_currency=is_foreign,
                raw_description_or_metadata=raw.description,
            )
            normalized_events.append(norm_ev)

        return cls(
            requests=raw_requests,
            profiles=profiles,
            events=normalized_events,
            payment_options=raw_options,
            messages=messages,
            images=images,
            fx_resolver=fx_resolver,
            sample_requests=raw_samples,
            dataset_dir=dataset_dir,
        )

    def get_profile(self, user_id: str) -> FinancialProfile:
        """Lookup financial profile by user_id."""
        if user_id not in self._profiles_by_id:
            raise KeyError(f"Profile not found for user_id: '{user_id}'")
        return self._profiles_by_id[user_id]

    def get_request(self, request_id: str) -> FinancialRequest:
        """Lookup an evaluation request by request_id."""
        if request_id not in self._requests_by_id:
            raise KeyError(f"Request not found for request_id: '{request_id}'")
        return self._requests_by_id[request_id]

    def get_sample_request(self, request_id: str) -> FinancialRequest:
        """Lookup a public example exclusively for an explicit oracle check."""
        if request_id not in self._sample_requests_by_id:
            raise KeyError(f"Sample request not found for request_id: '{request_id}'")
        return self._sample_requests_by_id[request_id]

    def get_event(self, event_id: str) -> NormalizedFinancialEvent:
        """Lookup normalized financial event by event_id."""
        if event_id not in self._events_by_id:
            raise KeyError(f"Event not found for event_id: '{event_id}'")
        return self._events_by_id[event_id]

    def get_events_for_user(self, user_id: str) -> list[NormalizedFinancialEvent]:
        """Get all financial events belonging to user_id."""
        return list(self._events_by_user.get(user_id, []))

    def get_payment_options(self, request_id: str) -> list[PaymentOption]:
        """Get payment options available for request_id."""
        return list(self._options_by_request.get(request_id, []))

    def get_messages_for_user(self, user_id: str) -> list[MessageRecord]:
        """Get all messages associated with user_id."""
        return list(self._messages_by_user.get(user_id, []))

    def get_messages_for_request(self, request_id: str) -> list[MessageRecord]:
        """Get all messages explicitly linked to request_id."""
        return list(self._messages_by_request.get(request_id, []))

    def get_messages_for_event(self, event_id: str) -> list[MessageRecord]:
        """Get all messages explicitly linked to event_id."""
        return list(self._messages_by_event.get(event_id, []))

    def get_images_for_user(self, user_id: str) -> list[ImageRecord]:
        """Get all images associated with user_id."""
        return list(self._images_by_user.get(user_id, []))

    def get_images_for_request(self, request_id: str) -> list[ImageRecord]:
        """Get all images explicitly linked to request_id."""
        return list(self._images_by_request.get(request_id, []))

    def get_image_for_event(self, event_id: str) -> ImageRecord | None:
        """Get image record linked to event_id, if any."""
        return self._image_by_event.get(event_id)
