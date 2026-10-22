"""Canonical models for the resolved financial ledger."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum

from orcha.models import EventDirection, EventStatus, FlexibilityType


class ForecastBehavior(StrEnum):
    """How a resolved financial event behaves in future cash-flow projections."""

    HISTORICAL_ALREADY_IN_BALANCE = "historical_already_in_balance"
    FUTURE_CONFIRMED_CREDIT = "future_confirmed_credit"
    FUTURE_CONFIRMED_DEBIT = "future_confirmed_debit"
    FUTURE_PENDING_DEBIT = "future_pending_debit"
    IGNORED_PENDING_CREDIT = "ignored_pending_credit"
    IGNORED_CANCELLED = "ignored_cancelled"
    IGNORED_FAILED = "ignored_failed"
    IGNORED_UNREALIZED = "ignored_unrealized"
    IGNORED_NON_CASH = "ignored_non_cash"


@dataclass(frozen=True)
class RecurrencePattern:
    """Detected or confirmed recurring cash flow pattern."""

    category: str
    frequency_days: int
    anchor_date: date
    amount_home_currency: Decimal
    direction: EventDirection
    source_event_ids: tuple[str, ...]
    confidence: float = 1.0
    end_date: date | None = None
    description: str = ""
    calendar_monthly: bool = False
    calendar_day: int | None = None
    flexibility: FlexibilityType = FlexibilityType.FIXED
    minimum_allowed_amount: Decimal | None = None
    amount_adjustments: tuple[tuple[date, Decimal], ...] = ()
    single_occurrence_amounts: tuple[tuple[date, Decimal], ...] = ()
    message_evidence_ids: tuple[str, ...] = ()
    home_currency: str | None = None
    stream_id: str = "category"


@dataclass(frozen=True)
class ResolvedFinancialEvent:
    """Fully resolved canonical financial event ready for simulation and planning."""

    canonical_event_id: str
    user_id: str
    event_type: str
    description: str
    category: str
    direction: EventDirection
    amount_home_currency: Decimal
    home_currency: str
    original_amount: Decimal | None
    original_currency: str
    event_date: date
    settlement_date: date
    resolved_status: EventStatus
    forecast_behavior: ForecastBehavior
    flexibility: FlexibilityType
    minimum_allowed_amount: Decimal | None = None
    is_recurring: bool = False
    recurrence_pattern: RecurrencePattern | None = None
    source_event_ids: tuple[str, ...] = ()
    message_evidence_ids: tuple[str, ...] = ()
    image_evidence_ids: tuple[str, ...] = ()
    resolution_reason: str = ""
    amount_source: str = "event"

    @property
    def is_future_cash_inflow(self) -> bool:
        return self.forecast_behavior == ForecastBehavior.FUTURE_CONFIRMED_CREDIT

    @property
    def is_future_cash_outflow(self) -> bool:
        return self.forecast_behavior in (
            ForecastBehavior.FUTURE_CONFIRMED_DEBIT,
            ForecastBehavior.FUTURE_PENDING_DEBIT,
        )

    @property
    def is_ignored(self) -> bool:
        return self.forecast_behavior in (
            ForecastBehavior.HISTORICAL_ALREADY_IN_BALANCE,
            ForecastBehavior.IGNORED_PENDING_CREDIT,
            ForecastBehavior.IGNORED_CANCELLED,
            ForecastBehavior.IGNORED_FAILED,
            ForecastBehavior.IGNORED_UNREALIZED,
            ForecastBehavior.IGNORED_NON_CASH,
        )
