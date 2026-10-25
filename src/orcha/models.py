"""Core typed data models for Orcha financial decision agent."""

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

# StrEnum is imported from enum


class AffordabilityStatus(StrEnum):
    AFFORDABLE_NOW = "affordable_now"
    AFFORDABLE_WITH_PLAN = "affordable_with_plan"
    AFFORDABLE_LATER = "affordable_later"
    NOT_AFFORDABLE = "not_affordable"


class RecommendedPaymentMethod(StrEnum):
    FULL_PAYMENT = "full_payment"
    PARTIAL_PAYMENT = "partial_payment"
    INSTALLMENTS = "installments"
    WAIT = "wait"
    NOT_RECOMMENDED = "not_recommended"


class RequestType(StrEnum):
    PURCHASE = "purchase"
    TRAVEL = "travel"
    EDUCATION = "education"
    FAMILY_TRANSFER = "family_transfer"
    DEBT_REPAYMENT = "debt_repayment"
    INVESTMENT = "investment"
    HOUSING = "housing"
    EMERGENCY_EXPENSE = "emergency_expense"
    OTHER = "other"


class EventType(StrEnum):
    EXPENSE = "expense"
    DEBT_PAYMENT = "debt_payment"
    SUBSCRIPTION = "subscription"
    INCOME = "income"
    REFUND = "refund"
    INVESTMENT_PURCHASE = "investment_purchase"
    INVESTMENT_VALUATION = "investment_valuation"
    INVESTMENT_SALE = "investment_sale"


class EventDirection(StrEnum):
    DEBIT = "debit"
    CREDIT = "credit"
    NON_CASH = "non_cash"


class EventStatus(StrEnum):
    SETTLED = "settled"
    CANCELLED = "cancelled"
    PENDING = "pending"
    SCHEDULED = "scheduled"
    FAILED = "failed"
    UNREALIZED = "unrealized"


class EventFlexibility(StrEnum):
    FIXED = "fixed"
    STOPPABLE = "stoppable"
    REDUCIBLE = "reducible"
    REDUCIBLE_OR_STOPPABLE = "reducible_or_stoppable"


# Alias for compatibility
FlexibilityType = EventFlexibility


class PaymentOptionMethod(StrEnum):
    FULL_PAYMENT = "full_payment"
    INSTALLMENTS = "installments"


class MessageSourceType(StrEnum):
    EMPLOYER = "employer"
    SERVICE_PROVIDER = "service_provider"
    BANK = "bank"
    MERCHANT = "merchant"
    FINANCIAL_SERVICE = "financial_service"


class SpendingChangeAction(StrEnum):
    STOP = "stop"
    REDUCE_TO = "reduce_to"


class PlanPayment(BaseModel):
    """A scheduled payment in a candidate or recommended payment plan."""

    model_config = ConfigDict(frozen=True)

    payment_date: date
    amount: Decimal

    def to_str(self) -> str:
        # Format Decimal without trailing zeroes if integer, or preserving decimal places
        amt_str = (
            f"{self.amount:f}".rstrip("0").rstrip(".")
            if "." in f"{self.amount:f}"
            else f"{self.amount:f}"
        )
        return f"{self.payment_date.isoformat()}:{amt_str}"

    @classmethod
    def from_str(cls, s: str) -> "PlanPayment":
        parts = s.split(":")
        if len(parts) != 2:
            raise ValueError(f"Invalid PlanPayment string: '{s}', expected 'YYYY-MM-DD:amount'")
        return cls(payment_date=date.fromisoformat(parts[0]), amount=Decimal(parts[1]))


class SpendingChange(BaseModel):
    """A concrete modification to an existing flexible recurring expense."""

    model_config = ConfigDict(frozen=True)

    action: SpendingChangeAction
    event_id: str
    new_amount: Decimal | None = None

    @field_validator("new_amount")
    @classmethod
    def validate_amount(cls, v: Decimal | None, info: object) -> Decimal | None:
        return v

    def to_str(self) -> str:
        if self.action == SpendingChangeAction.STOP:
            return f"stop:{self.event_id}"
        if self.new_amount is None:
            raise ValueError(f"reduce_to requires new_amount for event {self.event_id}")
        amt_str = (
            f"{self.new_amount:f}".rstrip("0").rstrip(".")
            if "." in f"{self.new_amount:f}"
            else f"{self.new_amount:f}"
        )
        return f"reduce_to:{self.event_id}:{amt_str}"

    @classmethod
    def from_str(cls, s: str) -> "SpendingChange":
        parts = s.split(":")
        if parts[0] == "stop" and len(parts) == 2:
            return cls(action=SpendingChangeAction.STOP, event_id=parts[1])
        if parts[0] == "reduce_to" and len(parts) == 3:
            return cls(
                action=SpendingChangeAction.REDUCE_TO,
                event_id=parts[1],
                new_amount=Decimal(parts[2]),
            )
        raise ValueError(f"Invalid SpendingChange string: '{s}'")


class FinancialRequest(BaseModel):
    """Incoming purchase or payment request to evaluate."""

    model_config = ConfigDict(frozen=True)

    request_id: str
    user_id: str
    request_date: date
    request_type: RequestType
    requested_amount: Decimal = Field(gt=0, le=Decimal("1000000000000"))
    desired_completion_date: date
    allows_partial_payment: bool
    request_text: str


class FinancialProfile(BaseModel):
    """User financial settings, preferences, priorities, and boundaries."""

    model_config = ConfigDict(frozen=True)

    user_id: str
    home_currency: str
    current_available_balance: Decimal
    minimum_balance_to_keep: Decimal = Field(ge=0, le=Decimal("1000000000000"))
    financial_priorities: list[str] = Field(default_factory=list)
    expense_categories_to_protect: list[str] = Field(default_factory=list)
    expense_categories_user_is_willing_to_reduce: list[str] = Field(default_factory=list)
    expense_categories_user_is_willing_to_stop: list[str] = Field(default_factory=list)
    payment_methods_user_will_consider: list[RecommendedPaymentMethod] = Field(default_factory=list)
    max_installment_months: int | None = None


class FinancialEvent(BaseModel):
    """Raw financial event record as parsed from dataset."""

    model_config = ConfigDict(frozen=True)

    event_id: str
    user_id: str
    event_type: EventType
    description: str
    category: str
    direction: EventDirection
    amount: Decimal | None = None
    currency: str
    event_date: date
    settlement_date: date | None = None
    status: EventStatus
    linked_event_id: str | None = None
    flexibility: EventFlexibility | None = None
    minimum_allowed_amount: Decimal | None = None
    # Normalized / enriched fields
    normalized_amount: Decimal | None = None
    is_recurring: bool = False


class NormalizedFinancialEvent(BaseModel):
    """Canonical normalized financial event suitable for lifecycle and simulation processing."""

    model_config = ConfigDict(frozen=True)

    event_id: str
    user_id: str
    event_type: EventType
    description: str
    category: str
    direction: EventDirection
    amount: Decimal | None = None
    currency: str
    event_date: date
    settlement_date: date | None = None
    status: EventStatus
    linked_event_id: str | None = None
    flexibility: EventFlexibility | None = None
    minimum_allowed_amount: Decimal | None = None

    # Normalized fields
    amount_home_currency: Decimal | None = None
    home_currency: str | None = None
    conversion_rate_used: Decimal | None = None
    conversion_rate_date: date | None = None
    is_foreign_currency: bool = False
    raw_description_or_metadata: str = ""


class PaymentOption(BaseModel):
    """Seller / provider financing option for a request."""

    model_config = ConfigDict(frozen=True)

    payment_option_id: str
    request_id: str
    payment_method: PaymentOptionMethod
    payment_amount: Decimal = Field(gt=0, le=Decimal("1000000000000"))
    number_of_payments: int = Field(ge=1, le=120)
    first_payment_date: date
    payment_frequency_days: int | None = Field(default=None, ge=1, le=366)
    financing_fee: Decimal = Field(default=Decimal("0"), ge=0)
    total_payable_amount: Decimal = Field(gt=0, le=Decimal("1000000000000"))


class ExchangeRate(BaseModel):
    """Dated currency exchange rate."""

    model_config = ConfigDict(frozen=True)

    rate_date: date
    from_currency: str
    to_currency: str
    rate: Decimal = Field(gt=0)


class MessageRecord(BaseModel):
    """User or transaction-related message (untrusted supporting evidence)."""

    model_config = ConfigDict(frozen=True)

    message_id: str
    user_id: str
    request_id: str | None = None
    related_event_id: str | None = None
    sent_at: datetime
    source_type: MessageSourceType
    message_text: str


class ImageRecord(BaseModel):
    """User or transaction-related image link (untrusted supporting evidence)."""

    model_config = ConfigDict(frozen=True)

    image_id: str
    user_id: str
    request_id: str | None = None
    related_event_id: str | None = None


class CandidatePlan(BaseModel):
    """Evaluated candidate payment plan."""

    plan_id: str
    recommended_payment_method: RecommendedPaymentMethod
    payment_option_id: str | None = None
    payments: list[PlanPayment] = Field(default_factory=list)
    spending_changes: list[SpendingChange] = Field(default_factory=list)
    total_cost: Decimal = Decimal("0")
    is_safe: bool = False
    completion_date: date | None = None
    explanation_notes: list[str] = Field(default_factory=list)


class DailyBalanceRecord(BaseModel):
    """Day-by-day cash flow and balance state."""

    model_config = ConfigDict(frozen=True)

    record_date: date
    opening_balance: Decimal
    cash_inflows: Decimal
    cash_outflows: Decimal
    hypothetical_payments: Decimal
    closing_balance: Decimal
    headroom: Decimal


class SimulationResult(BaseModel):
    """Outcome of a 90-day cash-flow simulation run."""

    is_safe: bool
    min_balance_projected: Decimal
    min_balance_date: date | None = None
    starting_balance: Decimal = Decimal("0")
    ending_balance: Decimal = Decimal("0")
    minimum_balance_to_keep: Decimal = Decimal("0")
    min_headroom_projected: Decimal = Decimal("0")
    min_headroom_date: date | None = None
    failed_date: date | None = None
    failure_reason: str | None = None
    daily_balances: dict[date, Decimal] = Field(default_factory=dict)
    daily_headroom: dict[date, Decimal] = Field(default_factory=dict)
    daily_records: list[DailyBalanceRecord] = Field(default_factory=list)
    included_event_ids: tuple[str, ...] = ()
    ignored_event_ids: tuple[str, ...] = ()
    hypothetical_payments: tuple[tuple[date, Decimal], ...] = ()
    breach_dates: tuple[date, ...] = ()


class BaselineAffordability(BaseModel):
    """Baseline capacity and earliest date without spending changes."""

    model_config = ConfigDict(frozen=True)

    request_id: str
    amount_safe_to_pay: Decimal
    earliest_date_for_full_payment: date | None = None
    minimum_baseline_balance: Decimal
    minimum_baseline_balance_date: date | None = None
    baseline_simulation: SimulationResult | None = None


class OutputRow(BaseModel):
    """One prediction row matching the exact financial output schema."""

    model_config = ConfigDict(frozen=True)

    request_id: str
    amount_safe_to_pay: Decimal
    affordability_status: AffordabilityStatus
    recommended_payment_method: RecommendedPaymentMethod
    payment_plan: str
    earliest_date_for_full_payment: date | None = None
    spending_changes_needed: str
    decision_explanation: str

    def to_csv_dict(self) -> dict[str, str]:
        amt_str = (
            f"{self.amount_safe_to_pay:f}".rstrip("0").rstrip(".")
            if "." in f"{self.amount_safe_to_pay:f}"
            else f"{self.amount_safe_to_pay:f}"
        )
        earliest_str = (
            self.earliest_date_for_full_payment.isoformat()
            if self.earliest_date_for_full_payment
            else ""
        )
        return {
            "request_id": self.request_id,
            "amount_safe_to_pay": amt_str,
            "affordability_status": str(self.affordability_status.value),
            "recommended_payment_method": str(self.recommended_payment_method.value),
            "payment_plan": self.payment_plan,
            "earliest_date_for_full_payment": earliest_str,
            "spending_changes_needed": self.spending_changes_needed,
            "decision_explanation": self.decision_explanation,
        }


# DecisionResult is an alias for OutputRow
DecisionResult = OutputRow
