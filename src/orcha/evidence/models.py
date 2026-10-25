"""Models for unstructured evidence extracted from messages and images."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum


class EvidenceType(StrEnum):
    """Semantic category of evidence extracted from unstructured sources."""

    # Salary and compensation
    FIRST_SALARY_CONFIRMED = "first_salary_confirmed"
    SALARY_INCREASE = "salary_increase"
    TEMPORARY_SALARY = "temporary_salary"
    UNPAID_LEAVE_REDUCTION = "unpaid_leave_reduction"
    SALARY_DATE_CHANGE = "salary_date_change"
    SALARY_RESUMED = "salary_resumed"
    SALARY_ARREARS_ADJUSTMENT = "salary_arrears_adjustment"
    EMPLOYMENT_ENDED_SALARY_REDUCTION = "employment_ended_salary_reduction"
    CONTRACT_ENDED = "contract_ended"
    PENDING_BONUS_OR_COMMISSION = "pending_bonus_or_commission"

    # Housing and obligations
    RENT_INCREASE = "rent_increase"

    # Account and transactions
    INTERNAL_TRANSFER = "internal_transfer"
    PENDING_REFUND = "pending_refund"
    FOREIGN_REFUND_PROCESSING = "foreign_refund_processing"
    PENDING_PAYOUT = "pending_payout"
    PENDING_PRIZE = "pending_prize"
    PRIZE_SETTLED = "prize_settled"
    INVOICE_APPROVED = "invoice_approved"
    PAYMENT_RECEIPT_CONFIRMED = "payment_receipt_confirmed"
    UNREALIZED_PORTFOLIO = "unrealized_portfolio"

    # Generic / Document
    INVOICE_DOCUMENT = "invoice_document"
    RECEIPT_DOCUMENT = "receipt_document"
    BILL_DOCUMENT = "bill_document"
    PAYSLIP_DOCUMENT = "payslip_document"
    GENERAL_NOTIFICATION = "general_notification"


@dataclass(frozen=True)
class ImageEvidence:
    """Structured financial evidence extracted from an image file."""

    image_id: str
    user_id: str
    request_id: str | None
    related_event_id: str
    amount: Decimal
    currency: str
    document_date: date | None
    document_type: str
    description: str
    confidence: float = 1.0
    source_sha256: str | None = None


@dataclass(frozen=True)
class MessageEvidence:
    """Structured financial evidence extracted from a user notification message."""

    message_id: str
    user_id: str
    request_id: str | None
    related_event_id: str | None
    sent_at: datetime | None
    source_type: str
    evidence_type: EvidenceType
    amount: Decimal | None = None
    additional_amount: Decimal | None = None
    currency: str | None = None
    effective_date: date | None = None
    status: str = "confirmed"
    notes: str = ""
    raw_text: str = ""
    confidence: float = 1.0
