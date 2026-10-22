"""Batch and single-request baseline affordability evaluation engine."""

from __future__ import annotations

from datetime import date

from orcha.evidence.images import ImageEvidenceExtractor
from orcha.evidence.messages import MessageEvidenceExtractor
from orcha.ledger.models import ResolvedFinancialEvent
from orcha.ledger.resolve import resolve_canonical_ledger
from orcha.models import BaselineAffordability, FinancialRequest
from orcha.repository import DatasetRepository
from orcha.simulation.capacity import (
    calculate_amount_safe_to_pay,
    calculate_earliest_date_for_full_payment,
)
from orcha.simulation.forecast import simulate
from orcha.simulation.timeline import get_forecast_window


class BaselineEngine:
    """Deterministic financial authority for baseline affordability."""

    def __init__(
        self,
        repository: DatasetRepository,
        image_extractor: ImageEvidenceExtractor | None = None,
        message_extractor: MessageEvidenceExtractor | None = None,
    ) -> None:
        self.repository = repository
        self.image_extractor = image_extractor or ImageEvidenceExtractor()
        self.message_extractor = message_extractor or MessageEvidenceExtractor()
        self._ledger_cache: dict[tuple[str, date, str | None], list[ResolvedFinancialEvent]] = {}

    def get_or_resolve_ledger(
        self, user_id: str, request_date: date, request_id: str | None = None
    ) -> list[ResolvedFinancialEvent]:
        """Resolve and cache canonical ledger for a user relative to a request date."""
        key = (user_id, request_date, request_id)
        if key not in self._ledger_cache:
            self._ledger_cache[key] = resolve_canonical_ledger(
                repository=self.repository,
                user_id=user_id,
                request_date=request_date,
                request_id=request_id,
                forecast_horizon_days=90,
                image_extractor=self.image_extractor,
                message_extractor=self.message_extractor,
            )
        return self._ledger_cache[key]

    def evaluate(self, request_id: str) -> BaselineAffordability:
        """Evaluate baseline affordability for one production request."""
        return self.evaluate_financial_request(self.repository.get_request(request_id))

    def evaluate_sample(self, request_id: str) -> BaselineAffordability:
        """Evaluate one public example for an explicit oracle check only."""
        return self.evaluate_financial_request(self.repository.get_sample_request(request_id))

    def evaluate_financial_request(self, req: FinancialRequest) -> BaselineAffordability:
        """Evaluate a supplied typed request without consulting sample labels."""
        prof = self.repository.get_profile(req.user_id)
        start_date, end_date = get_forecast_window(req.request_date, horizon_days=90)

        resolved_events = self.get_or_resolve_ledger(req.user_id, req.request_date, req.request_id)

        # Baseline projection (no hypothetical payments, no spending changes)
        baseline = simulate(
            profile=prof,
            resolved_events=resolved_events,
            start_date=start_date,
            end_date=end_date,
            hypothetical_payments=(),
        )

        amount_safe = calculate_amount_safe_to_pay(
            profile=prof,
            requested_amount=req.requested_amount,
            request_date=start_date,
            end_date=end_date,
            baseline_result=baseline,
            resolved_events=resolved_events,
        )

        earliest_date = calculate_earliest_date_for_full_payment(
            profile=prof,
            requested_amount=req.requested_amount,
            request_date=start_date,
            end_date=end_date,
            baseline_result=baseline,
            resolved_events=resolved_events,
        )

        return BaselineAffordability(
            request_id=req.request_id,
            amount_safe_to_pay=amount_safe,
            earliest_date_for_full_payment=earliest_date,
            minimum_baseline_balance=baseline.min_balance_projected,
            minimum_baseline_balance_date=baseline.min_balance_date,
            baseline_simulation=baseline,
        )

    def evaluate_all(
        self, request_ids: list[str] | None = None
    ) -> dict[str, BaselineAffordability]:
        """Evaluate baseline affordability for all or specified request IDs."""
        if request_ids is None:
            request_ids = [r.request_id for r in self.repository.all_requests]
        results: dict[str, BaselineAffordability] = {}
        for rid in request_ids:
            results[rid] = self.evaluate(rid)
        return results
