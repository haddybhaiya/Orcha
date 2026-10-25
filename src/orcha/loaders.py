"""Data loaders for Orcha financial datasets."""

import csv
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from orcha.models import (
    EventDirection,
    EventFlexibility,
    EventStatus,
    EventType,
    ExchangeRate,
    FinancialEvent,
    FinancialProfile,
    FinancialRequest,
    ImageRecord,
    MessageRecord,
    MessageSourceType,
    PaymentOption,
    PaymentOptionMethod,
    RecommendedPaymentMethod,
    RequestType,
)

REQUIRED_DATASET_FILES = [
    "requests.csv",
    "financial_profiles.csv",
    "financial_events.csv",
    "exchange_rates.csv",
    "request_payment_options.csv",
    "messages.csv",
    "images.csv",
    "output.csv",
]


def _clean_str(val: str | None) -> str | None:
    if val is None:
        return None
    s = val.strip()
    return s if s else None


def _clean_decimal(val: str | None) -> Decimal | None:
    s = _clean_str(val)
    if s is None:
        return None
    return Decimal(s)


def _clean_date(val: str | None) -> date | None:
    s = _clean_str(val)
    if s is None:
        return None
    return date.fromisoformat(s)


def _clean_pipe_list(val: str | None) -> list[str]:
    s = _clean_str(val)
    if not s:
        return []
    return [item.strip() for item in s.split("|") if item.strip()]


def load_requests(file_path: Path) -> list[FinancialRequest]:
    """Load evaluation requests from CSV, preserving exact IDs and amounts as Decimal."""
    if not file_path.is_file():
        raise FileNotFoundError(f"Requests file not found: {file_path}")

    requests: list[FinancialRequest] = []
    with file_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row_idx, row in enumerate(reader, start=2):
            try:
                raw_allows_partial = (_clean_str(row.get("allows_partial_payment")) or "").lower()
                allows_partial = raw_allows_partial in ("true", "1", "yes")

                req = FinancialRequest(
                    request_id=row["request_id"].strip(),
                    user_id=row["user_id"].strip(),
                    request_date=date.fromisoformat(row["request_date"].strip()),
                    request_type=RequestType(row["request_type"].strip()),
                    requested_amount=Decimal(row["requested_amount"].strip()),
                    desired_completion_date=date.fromisoformat(
                        row["desired_completion_date"].strip()
                    ),
                    allows_partial_payment=allows_partial,
                    request_text=row.get("request_text", "").strip(),
                )
                requests.append(req)
            except Exception as e:
                raise ValueError(f"Failed to parse request at {file_path}:{row_idx}: {e}") from e

    return requests


def load_profiles(file_path: Path) -> dict[str, FinancialProfile]:
    """Load user financial profiles keyed by user_id."""
    if not file_path.is_file():
        raise FileNotFoundError(f"Financial profiles file not found: {file_path}")

    profiles: dict[str, FinancialProfile] = {}
    with file_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row_idx, row in enumerate(reader, start=2):
            try:
                user_id = row["user_id"].strip()
                if user_id in profiles:
                    raise ValueError(f"Duplicate profile ID: {user_id}")
                methods_raw = _clean_pipe_list(row.get("payment_methods_user_will_consider"))
                methods = [RecommendedPaymentMethod(m) for m in methods_raw]

                max_inst_raw = _clean_str(row.get("max_installment_months"))
                max_inst = int(max_inst_raw) if max_inst_raw is not None else None

                profile = FinancialProfile(
                    user_id=user_id,
                    home_currency=row["home_currency"].strip(),
                    current_available_balance=Decimal(row["current_available_balance"].strip()),
                    minimum_balance_to_keep=Decimal(row["minimum_balance_to_keep"].strip()),
                    financial_priorities=_clean_pipe_list(row.get("financial_priorities")),
                    expense_categories_to_protect=_clean_pipe_list(
                        row.get("expense_categories_to_protect")
                    ),
                    expense_categories_user_is_willing_to_reduce=_clean_pipe_list(
                        row.get("expense_categories_user_is_willing_to_reduce")
                    ),
                    expense_categories_user_is_willing_to_stop=_clean_pipe_list(
                        row.get("expense_categories_user_is_willing_to_stop")
                    ),
                    payment_methods_user_will_consider=methods,
                    max_installment_months=max_inst,
                )
                profiles[user_id] = profile
            except Exception as e:
                raise ValueError(f"Failed to parse profile at {file_path}:{row_idx}: {e}") from e

    return profiles


def load_payment_options(file_path: Path) -> dict[str, list[PaymentOption]]:
    """Load payment options grouped by request_id."""
    if not file_path.is_file():
        raise FileNotFoundError(f"Payment options file not found: {file_path}")

    grouped_options: dict[str, list[PaymentOption]] = {}
    with file_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row_idx, row in enumerate(reader, start=2):
            try:
                req_id = row["request_id"].strip()
                freq_raw = _clean_str(row.get("payment_frequency_days"))
                freq = int(freq_raw) if freq_raw is not None else None

                fee_raw = _clean_str(row.get("financing_fee"))
                fee = Decimal(fee_raw) if fee_raw is not None else Decimal("0")

                opt = PaymentOption(
                    payment_option_id=row["payment_option_id"].strip(),
                    request_id=req_id,
                    payment_method=PaymentOptionMethod(row["payment_method"].strip()),
                    payment_amount=Decimal(row["payment_amount"].strip()),
                    number_of_payments=int(row["number_of_payments"].strip()),
                    first_payment_date=date.fromisoformat(row["first_payment_date"].strip()),
                    payment_frequency_days=freq,
                    financing_fee=fee,
                    total_payable_amount=Decimal(row["total_payable_amount"].strip()),
                )
                grouped_options.setdefault(req_id, []).append(opt)
            except Exception as e:
                raise ValueError(
                    f"Failed to parse payment option at {file_path}:{row_idx}: {e}"
                ) from e

    return grouped_options


def load_financial_events(file_path: Path) -> list[FinancialEvent]:
    """Load financial events with raw attributes preserved."""
    if not file_path.is_file():
        raise FileNotFoundError(f"Financial events file not found: {file_path}")

    events: list[FinancialEvent] = []
    with file_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row_idx, row in enumerate(reader, start=2):
            try:
                flex_raw = _clean_str(row.get("flexibility"))
                flex = EventFlexibility(flex_raw) if flex_raw else None

                ev = FinancialEvent(
                    event_id=row["event_id"].strip(),
                    user_id=row["user_id"].strip(),
                    event_type=EventType(row["event_type"].strip()),
                    description=row.get("description", "").strip(),
                    category=row.get("category", "").strip(),
                    direction=EventDirection(row["direction"].strip()),
                    amount=_clean_decimal(row.get("amount")),
                    currency=row["currency"].strip(),
                    event_date=date.fromisoformat(row["event_date"].strip()),
                    settlement_date=_clean_date(row.get("settlement_date")),
                    status=EventStatus(row["status"].strip()),
                    linked_event_id=_clean_str(row.get("linked_event_id")),
                    flexibility=flex,
                    minimum_allowed_amount=_clean_decimal(row.get("minimum_allowed_amount")),
                )
                events.append(ev)
            except Exception as e:
                raise ValueError(
                    f"Failed to parse financial event at {file_path}:{row_idx}: {e}"
                ) from e

    return events


def load_exchange_rates(file_path: Path) -> list[ExchangeRate]:
    """Load dated conversion rates."""
    if not file_path.is_file():
        raise FileNotFoundError(f"Exchange rates file not found: {file_path}")

    rates: list[ExchangeRate] = []
    with file_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row_idx, row in enumerate(reader, start=2):
            try:
                rate = ExchangeRate(
                    rate_date=date.fromisoformat(row["rate_date"].strip()),
                    from_currency=row["from_currency"].strip(),
                    to_currency=row["to_currency"].strip(),
                    rate=Decimal(row["rate"].strip()),
                )
                rates.append(rate)
            except Exception as e:
                raise ValueError(
                    f"Failed to parse exchange rate at {file_path}:{row_idx}: {e}"
                ) from e

    return rates


def load_messages(file_path: Path) -> list[MessageRecord]:
    """Load message records (untrusted supporting evidence)."""
    if not file_path.is_file():
        raise FileNotFoundError(f"Messages file not found: {file_path}")

    messages: list[MessageRecord] = []
    with file_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row_idx, row in enumerate(reader, start=2):
            try:
                sent_at_str = row["sent_at"].strip()
                if sent_at_str.endswith("Z"):
                    sent_at = datetime.fromisoformat(sent_at_str.replace("Z", "+00:00"))
                else:
                    sent_at = datetime.fromisoformat(sent_at_str)

                msg = MessageRecord(
                    message_id=row["message_id"].strip(),
                    user_id=row["user_id"].strip(),
                    request_id=_clean_str(row.get("request_id")),
                    related_event_id=_clean_str(row.get("related_event_id")),
                    sent_at=sent_at,
                    source_type=MessageSourceType(row["source_type"].strip()),
                    message_text=row.get("message_text", "").strip(),
                )
                messages.append(msg)
            except Exception as e:
                raise ValueError(f"Failed to parse message at {file_path}:{row_idx}: {e}") from e

    return messages


def load_images(file_path: Path) -> list[ImageRecord]:
    """Load image metadata linking images to requests/events."""
    if not file_path.is_file():
        raise FileNotFoundError(f"Images file not found: {file_path}")

    images: list[ImageRecord] = []
    with file_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row_idx, row in enumerate(reader, start=2):
            try:
                img = ImageRecord(
                    image_id=row["image_id"].strip(),
                    user_id=row["user_id"].strip(),
                    request_id=_clean_str(row.get("request_id")),
                    related_event_id=_clean_str(row.get("related_event_id")),
                )
                images.append(img)
            except Exception as e:
                raise ValueError(
                    f"Failed to parse image record at {file_path}:{row_idx}: {e}"
                ) from e

    return images


class DatasetLoader:
    """Unified dataset loader and validator."""

    def __init__(self, dataset_dir: Path) -> None:
        self.dataset_dir = dataset_dir

    def check_missing_files(self) -> list[str]:
        """Return list of missing required dataset files."""
        missing: list[str] = []
        for filename in REQUIRED_DATASET_FILES:
            if not (self.dataset_dir / filename).is_file():
                missing.append(filename)
        return missing

    def validate(self) -> None:
        """Verify all required dataset files exist."""
        if not self.dataset_dir.is_dir():
            raise FileNotFoundError(f"Dataset directory does not exist: {self.dataset_dir}")
        missing = self.check_missing_files()
        if missing:
            raise FileNotFoundError(
                f"Dataset at '{self.dataset_dir}' is missing required files: {', '.join(missing)}"
            )

    def load_all_requests(self) -> list[FinancialRequest]:
        return load_requests(self.dataset_dir / "requests.csv")

    def load_all_profiles(self) -> dict[str, FinancialProfile]:
        return load_profiles(self.dataset_dir / "financial_profiles.csv")

    def load_all_payment_options(self) -> dict[str, list[PaymentOption]]:
        return load_payment_options(self.dataset_dir / "request_payment_options.csv")

    def load_all_events(self) -> list[FinancialEvent]:
        return load_financial_events(self.dataset_dir / "financial_events.csv")

    def load_all_rates(self) -> list[ExchangeRate]:
        return load_exchange_rates(self.dataset_dir / "exchange_rates.csv")

    def load_all_messages(self) -> list[MessageRecord]:
        return load_messages(self.dataset_dir / "messages.csv")

    def load_all_images(self) -> list[ImageRecord]:
        return load_images(self.dataset_dir / "images.csv")
