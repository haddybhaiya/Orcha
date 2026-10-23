"""Session-local imports and truthful, engine-derived dashboard data."""

import hashlib
import io
import json
import re
import tempfile
import threading
import zipfile
from collections import OrderedDict
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from orcha.assistant.contracts import ExtractionResponse, InterpretationContext
from orcha.evidence.provider import StructuredEvidenceProvider
from orcha.loaders import REQUIRED_DATASET_FILES
from orcha.repository import DatasetRepository
from orcha.simulation.capacity import calculate_amount_safe_to_pay
from orcha.simulation.engine import BaselineEngine
from orcha.simulation.forecast import simulate
from orcha.simulation.timeline import get_forecast_window

DEMO_DATE = date(2026, 10, 21)
DEMO_DIR = Path(__file__).resolve().parents[3] / "demo" / "dataset"


class UploadedCSV(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)
    content: str = Field(max_length=6_000_000)


class ImportBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")
    files: list[UploadedCSV] = Field(min_length=8, max_length=8)


class SessionProvider:
    """Bounded in-memory extraction cache; facts are revalidated on every run."""

    def __init__(self, provider: StructuredEvidenceProvider, identity: str) -> None:
        self.provider = provider
        self.identity = identity
        self.cache: OrderedDict[str, ExtractionResponse] = OrderedDict()

    def interpret(self, context: InterpretationContext) -> ExtractionResponse:
        key = hashlib.sha256((self.identity + context.model_dump_json()).encode()).hexdigest()
        if key in self.cache:
            result = self.cache[key]
            self.cache.move_to_end(key)
            usage = result.usage.model_copy(
                update={
                    "cached": True,
                    "api_calls": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "total_tokens": 0,
                }
            )
            return result.model_copy(update={"usage": usage})
        result = self.provider.interpret(context)
        self.cache[key] = result
        if len(self.cache) > 32:
            self.cache.popitem(last=False)
        return result


def validate_repository(repository: DatasetRepository) -> None:
    """Reject non-finite amounts and dangling ownership before rendering a workspace."""
    if not repository.all_profiles or len(repository.all_profiles) > 500:
        raise ValueError("Import between 1 and 500 profiles")
    for key, profile in repository.all_profiles.items():
        if not key or len(key) > 128 or not re.fullmatch(r"[A-Z]{3}", profile.home_currency):
            raise ValueError("Invalid profile")
        for amount in [profile.current_available_balance, profile.minimum_balance_to_keep]:
            if not amount.is_finite() or abs(amount) > Decimal("1000000000000"):
                raise ValueError("Invalid profile amount")
        if profile.minimum_balance_to_keep < 0:
            raise ValueError("Minimum balance must be non-negative")
    if len(repository.all_events) > 50_000:
        raise ValueError("Import at most 50,000 financial events")
    for event in repository.all_events:
        if event.user_id not in repository.all_profiles:
            raise ValueError("Event owner does not exist")
        for event_amount in [
            event.amount,
            event.amount_home_currency,
            event.minimum_allowed_amount,
        ]:
            if event_amount is not None and (
                not event_amount.is_finite() or abs(event_amount) > Decimal("1000000000000")
            ):
                raise ValueError("Invalid event amount")


class Workspace:
    def __init__(self, dataset: Path) -> None:
        self.repository = DatasetRepository.load_from_dir(dataset)
        validate_repository(self.repository)
        self.is_demo = dataset.resolve() == DEMO_DIR.resolve()
        self.lock = threading.Lock()
        self.provider: SessionProvider | None = None

    def import_bundle(self, bundle: ImportBundle) -> None:
        names = [f.name for f in bundle.files]
        if set(names) != set(REQUIRED_DATASET_FILES) or len(set(names)) != len(names):
            raise ValueError("Select exactly the eight required CSV files")
        # No archive extraction, user-chosen paths, or persistent financial uploads.
        with tempfile.TemporaryDirectory(prefix="orcha-import-") as directory:
            target = Path(directory)
            for item in bundle.files:
                if "\x00" in item.content:
                    raise ValueError("CSV files must contain UTF-8 text")
                (target / item.name).write_text(item.content, encoding="utf-8")
            candidate = DatasetRepository.load_from_dir(target)
            validate_repository(candidate)
            if candidate.all_images:
                raise ValueError("Image evidence requires a local configured dataset")
            candidate.dataset_dir = None
        self.repository = candidate
        self.is_demo = False
        self.provider = None

    def reset(self) -> None:
        candidate = DatasetRepository.load_from_dir(DEMO_DIR)
        validate_repository(candidate)
        self.repository = candidate
        self.is_demo = True
        self.provider = None

    def view(self, user_id: str | None = None, as_of: date | None = None) -> dict[str, Any]:
        repository = self.repository
        selected = user_id or (
            "demo_before" if self.is_demo else next(iter(repository.all_profiles))
        )
        if selected not in repository.all_profiles:
            raise ValueError("Select a profile from this workspace")
        reference = as_of or (DEMO_DATE if self.is_demo else date.today())
        if not date(2000, 1, 1) <= reference <= date(2100, 1, 1):
            raise ValueError("Choose a reference date between 2000 and 2100")
        profile = repository.get_profile(selected)
        engine = BaselineEngine(repository)
        ledger = engine.get_or_resolve_ledger(selected, reference)
        start, end = get_forecast_window(reference)
        simulation = simulate(profile, ledger, start, end)
        safe = calculate_amount_safe_to_pay(
            profile,
            max(Decimal("0"), profile.current_available_balance),
            start,
            end,
            simulation,
            ledger,
        )
        upcoming = [
            r for r in simulation.daily_records if r.record_date < start + timedelta(days=30)
        ]
        events = [
            {
                "id": e.canonical_event_id,
                "label": e.description,
                "date": max(e.settlement_date, start).isoformat(),
                "amount": str(e.amount_home_currency),
                "direction": e.direction.value,
                "status": e.resolved_status.value,
            }
            for e in sorted(ledger, key=lambda e: (e.settlement_date, e.canonical_event_id))
            if e.canonical_event_id in simulation.included_event_ids
        ]
        examples: list[dict[str, Any]] = []
        if self.is_demo:
            for filename, title in [
                ("assistant_request", "A laptop & a new bill"),
                ("assistant_missing_amount", "A bill with missing details"),
                ("assistant_amendment", "An updated repair bill"),
            ]:
                example = json.loads((DEMO_DIR.parent / f"{filename}.json").read_text())
                examples.append({"id": filename, "title": title, **example})
        return {
            "workspace_name": "Demo workspace" if self.is_demo else "Your workspace",
            "is_demo": self.is_demo,
            "profiles": [p.model_dump(mode="json") for p in repository.all_profiles.values()],
            "selected_user_id": selected,
            "as_of": reference.isoformat(),
            "summary": {
                "balance": str(profile.current_available_balance),
                "minimum_balance": str(profile.minimum_balance_to_keep),
                "safe_to_spend": str(safe),
                "currency": profile.home_currency,
                "upcoming_income": str(sum((r.cash_inflows for r in upcoming), Decimal("0"))),
                "upcoming_expenses": str(sum((r.cash_outflows for r in upcoming), Decimal("0"))),
            },
            "timeline": [
                {
                    "date": r.record_date.isoformat(),
                    "balance": str(r.closing_balance),
                    "income": str(r.cash_inflows),
                    "expenses": str(r.cash_outflows),
                }
                for r in simulation.daily_records
            ],
            "events": events,
            "amendable_events": [
                {
                    "id": e.event_id,
                    "label": e.description,
                    "date": (e.settlement_date or e.event_date).isoformat(),
                    "amount": str(e.amount_home_currency),
                }
                for e in repository.get_events_for_user(selected)
                if e.direction.value == "debit" and e.status.value == "scheduled"
            ],
            "examples": examples,
            "import_files": REQUIRED_DATASET_FILES,
            "forecast_label": "Imported cash flow · before new updates",
        }


def demo_archive() -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in REQUIRED_DATASET_FILES:
            archive.write(DEMO_DIR / name, name)
    return stream.getvalue()
