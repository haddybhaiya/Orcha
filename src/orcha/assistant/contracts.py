"""Closed contracts between untrusted interpretation and the financial engine."""

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from orcha.models import OutputRow

SourceId = Annotated[str, Field(pattern=r"^[a-zA-Z][a-zA-Z0-9_-]{0,63}$")]
Money = Annotated[
    Decimal, Field(gt=0, le=Decimal("1000000000000"), max_digits=15, decimal_places=2)
]
Currency = Annotated[str, Field(pattern=r"^[A-Z]{3}$")]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TextSource(Contract):
    source_id: SourceId
    text: str = Field(min_length=1, max_length=8000)
    related_event_id: str | None = Field(default=None, max_length=128)


class AssistantInput(Contract):
    user_id: str = Field(min_length=1, max_length=128)
    as_of: date
    question: TextSource
    documents: list[TextSource] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def unique_sources(self) -> "AssistantInput":
        sources = [self.question, *self.documents]
        if len({source.source_id for source in sources}) != len(sources):
            raise ValueError("Every question/document needs a unique source_id")
        if not self.question.text.strip() or any(not s.text.strip() for s in self.documents):
            raise ValueError("Sources cannot be blank")
        return self


class MoneyQuote(Contract):
    amount: Money
    currency: Currency
    source_id: SourceId
    quote: str = Field(min_length=1, max_length=500)

    @field_validator("amount", mode="before")
    @classmethod
    def no_float_amounts(cls, value: object) -> object:
        if isinstance(value, (float, bool)):
            raise ValueError("Money must be a decimal string or integer")
        return value


class DateQuote(Contract):
    value: date
    source_id: SourceId
    quote: str = Field(min_length=1, max_length=500)


class PurchaseDraft(Contract):
    money: MoneyQuote | None
    deadline: DateQuote | None


class BillDraft(Contract):
    source_id: SourceId
    operation: Literal["new_bill", "amend_bill"]
    money: MoneyQuote | None
    due_date: DateQuote | None
    reference: str | None = Field(default=None, max_length=100)


class UnresolvedSource(Contract):
    source_id: SourceId
    reason: Literal["missing_amount", "missing_date", "conflicting", "unsupported", "uncertain"]


class Extraction(Contract):
    schema_version: Literal["1"] = "1"
    purchase: PurchaseDraft
    bills: list[BillDraft] = Field(default_factory=list, max_length=8)
    unresolved: list[UnresolvedSource] = Field(default_factory=list, max_length=9)


class InterpretationContext(Contract):
    request: AssistantInput
    home_currency: Currency


class ModelUsage(Contract):
    provider: str = "google_ai_studio"
    model: str
    api_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cached: bool = False


class ExtractionResponse(Contract):
    extraction: Extraction
    usage: ModelUsage


class EvidenceFact(Contract):
    source_id: str
    field: str
    value: str
    quote: str
    event_id: str | None = None


class AssistantResult(Contract):
    status: Literal["complete", "needs_clarification", "unavailable"]
    brief: str
    questions: list[str] = Field(default_factory=list)
    decision: OutputRow | None = None
    evidence: list[EvidenceFact] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=list)
    usage: ModelUsage | None = None
