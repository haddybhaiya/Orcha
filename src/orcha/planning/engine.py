"""Main planning and decision engine.

Coordinates candidate generation, verification, ranking, and explanation.
"""

from __future__ import annotations

from decimal import Decimal

from orcha.evidence.images import ImageEvidenceExtractor
from orcha.evidence.messages import MessageEvidenceExtractor
from orcha.models import (
    AffordabilityStatus,
    CandidatePlan,
    DecisionResult,
    FinancialRequest,
    OutputRow,
    RecommendedPaymentMethod,
)
from orcha.planning.candidates import generate_candidate_plans
from orcha.planning.explanations import generate_decision_explanation
from orcha.planning.rank import rank_candidate_plans
from orcha.planning.verify import verify_plan_safety
from orcha.repository import DatasetRepository
from orcha.simulation.engine import BaselineEngine
from orcha.simulation.timeline import get_forecast_window


class DecisionEngine:
    """Full decision planning authority for Orcha."""

    def __init__(
        self,
        repository: DatasetRepository,
        image_extractor: ImageEvidenceExtractor | None = None,
        message_extractor: MessageEvidenceExtractor | None = None,
        baseline_engine: BaselineEngine | None = None,
    ) -> None:
        self.repository = repository
        self.image_extractor = image_extractor or ImageEvidenceExtractor()
        self.message_extractor = message_extractor or MessageEvidenceExtractor()
        self.baseline_engine = baseline_engine or BaselineEngine(
            repository=repository,
            image_extractor=self.image_extractor,
            message_extractor=self.message_extractor,
        )

    def evaluate_request(self, request_id: str) -> DecisionResult:
        """Evaluate one production request."""
        return self.evaluate_financial_request(self.repository.get_request(request_id))

    def evaluate_sample_request(self, request_id: str) -> DecisionResult:
        """Evaluate one public example for an explicit oracle check only."""
        return self.evaluate_financial_request(self.repository.get_sample_request(request_id))

    def evaluate_financial_request(self, request: FinancialRequest) -> DecisionResult:
        """Evaluate a typed request without consulting public sample labels."""
        profile = self.repository.get_profile(request.user_id)
        raw_events = self.repository.get_events_for_user(request.user_id)
        options = self.repository.get_payment_options(request.request_id)

        # 1. Baseline evaluation
        baseline = self.baseline_engine.evaluate_financial_request(request)
        amount_safe_to_pay = baseline.amount_safe_to_pay
        earliest_date_for_full_payment = baseline.earliest_date_for_full_payment

        # 2. Resolved events and forecast window
        resolved_events = self.baseline_engine.get_or_resolve_ledger(
            request.user_id, request.request_date, request.request_id
        )
        _, end_date = get_forecast_window(request.request_date, horizon_days=90)

        # 3. Generate candidate plans
        candidates = generate_candidate_plans(
            request=request,
            profile=profile,
            options=options,
            resolved_events=resolved_events,
            amount_safe_to_pay=amount_safe_to_pay,
            earliest_date_for_full_payment=earliest_date_for_full_payment,
        )

        # 4. Verify candidate plans through 90-day simulation replay
        safe_candidates: list[CandidatePlan] = []
        for candidate in candidates:
            is_safe, _ = verify_plan_safety(
                profile=profile,
                resolved_events=resolved_events,
                plan=candidate,
                request=request,
                payment_options=options,
                forecast_end_date=end_date,
            )
            if is_safe:
                safe_candidates.append(candidate.model_copy(update={"is_safe": True}))

        # 5. Select and rank winning candidate
        winning_plan: CandidatePlan
        affordability_status: AffordabilityStatus

        if safe_candidates:
            ranked_plans = rank_candidate_plans(safe_candidates, request)
            winning_plan = ranked_plans[0]

            # Determine affordability status
            if (
                winning_plan.recommended_payment_method == RecommendedPaymentMethod.FULL_PAYMENT
                and len(winning_plan.spending_changes) == 0
                and winning_plan.completion_date == request.request_date
            ):
                affordability_status = AffordabilityStatus.AFFORDABLE_NOW
            elif winning_plan.recommended_payment_method == RecommendedPaymentMethod.WAIT:
                affordability_status = AffordabilityStatus.AFFORDABLE_LATER
            else:
                # partial_payment, installments, or full_payment with spending changes
                affordability_status = AffordabilityStatus.AFFORDABLE_WITH_PLAN
        else:
            affordability_status = AffordabilityStatus.NOT_AFFORDABLE
            winning_plan = CandidatePlan(
                plan_id="not_recommended",
                recommended_payment_method=RecommendedPaymentMethod.NOT_RECOMMENDED,
                payment_option_id=None,
                payments=[],
                spending_changes=[],
                total_cost=Decimal("0"),
                is_safe=True,
                completion_date=None,
            )

        # 6. Format payment_plan string
        if winning_plan.payments:
            plan_str = "|".join(p.to_str() for p in winning_plan.payments)
        else:
            plan_str = "none"

        # 7. Format spending_changes_needed string
        if winning_plan.spending_changes:
            spending_str = "|".join(c.to_str() for c in winning_plan.spending_changes)
        else:
            spending_str = "none"

        # 8. Construct decision explanation
        explanation = generate_decision_explanation(
            request=request,
            profile=profile,
            plan=winning_plan,
            affordability_status=affordability_status,
            earliest_date_for_full_payment=earliest_date_for_full_payment,
            amount_safe_to_pay=amount_safe_to_pay,
            raw_events=raw_events,
        )

        return OutputRow(
            request_id=request.request_id,
            amount_safe_to_pay=amount_safe_to_pay,
            affordability_status=affordability_status,
            recommended_payment_method=winning_plan.recommended_payment_method,
            payment_plan=plan_str,
            earliest_date_for_full_payment=earliest_date_for_full_payment,
            spending_changes_needed=spending_str,
            decision_explanation=explanation,
        )
