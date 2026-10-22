"""Orcha financial assistant package."""

__version__ = "0.1.0"

from orcha.config import AppConfig
from orcha.evidence import (
    EvidenceProvider,
    EvidenceType,
    ImageEvidence,
    ImageEvidenceExtractor,
    LocalEvidenceProvider,
    MessageEvidence,
    MessageEvidenceExtractor,
)
from orcha.ledger import (
    ForecastBehavior,
    LifecycleResolutionResult,
    RecurrencePattern,
    ResolvedFinancialEvent,
    classify_for_forecast,
    detect_recurrence_patterns,
    expand_events,
    resolve_canonical_ledger,
    resolve_event_lifecycles,
)
from orcha.loaders import DatasetLoader
from orcha.models import (
    AffordabilityStatus,
    CandidatePlan,
    DecisionResult,
    FinancialEvent,
    FinancialProfile,
    FinancialRequest,
    ImageRecord,
    MessageRecord,
    NormalizedFinancialEvent,
    OutputRow,
    PaymentOption,
    PlanPayment,
    RecommendedPaymentMethod,
    SimulationResult,
    SpendingChange,
)
from orcha.money import (
    ExchangeRateError,
    ExchangeRateNotFoundError,
    ExchangeRateResolver,
    format_money,
    quantize_money,
)
from orcha.output import validate_output_rows, write_output_csv
from orcha.repository import DatasetRepository

__all__ = [
    "__version__",
    "AppConfig",
    "DatasetLoader",
    "DatasetRepository",
    "AffordabilityStatus",
    "CandidatePlan",
    "DecisionResult",
    "ExchangeRateError",
    "ExchangeRateNotFoundError",
    "ExchangeRateResolver",
    "FinancialEvent",
    "FinancialProfile",
    "FinancialRequest",
    "ImageRecord",
    "MessageRecord",
    "NormalizedFinancialEvent",
    "OutputRow",
    "PaymentOption",
    "PlanPayment",
    "RecommendedPaymentMethod",
    "SimulationResult",
    "SpendingChange",
    "format_money",
    "quantize_money",
    "validate_output_rows",
    "write_output_csv",
    # Evidence
    "EvidenceProvider",
    "EvidenceType",
    "ImageEvidence",
    "ImageEvidenceExtractor",
    "LocalEvidenceProvider",
    "MessageEvidence",
    "MessageEvidenceExtractor",
    # Ledger
    "ForecastBehavior",
    "LifecycleResolutionResult",
    "RecurrencePattern",
    "ResolvedFinancialEvent",
    "classify_for_forecast",
    "detect_recurrence_patterns",
    "expand_events",
    "resolve_canonical_ledger",
    "resolve_event_lifecycles",
]
