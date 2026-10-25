"""Image evidence extraction and indexing."""

import hashlib
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from orcha.evidence.models import ImageEvidence


class ImageEvidenceExtractor:
    """Extracts and resolves structured evidence from image files."""

    def __init__(self, cache_path: Path | None = None) -> None:
        self._cache_path = self._resolve_cache_path(cache_path)
        self._by_image_id: dict[str, ImageEvidence] = {}
        self._by_event_id: dict[str, ImageEvidence] = {}
        self._load_cache()

    @staticmethod
    def _resolve_cache_path(custom_path: Path | None) -> Path:
        if custom_path is not None:
            return custom_path
        candidates = [
            Path("code/cache/image_evidence.json"),
            Path("cache/image_evidence.json"),
            Path("../code/cache/image_evidence.json"),
        ]
        for c in candidates:
            if c.is_file():
                return c
        return Path("code/cache/image_evidence.json")

    def _load_cache(self) -> None:
        if not self._cache_path.is_file():
            return
        with open(self._cache_path, encoding="utf-8") as f:
            records = json.load(f)

        for r in records:
            doc_date = date.fromisoformat(r["document_date"]) if r.get("document_date") else None
            evidence = ImageEvidence(
                image_id=r["image_id"],
                user_id=r["user_id"],
                request_id=r.get("request_id"),
                related_event_id=r["related_event_id"],
                amount=Decimal(str(r["amount"])),
                currency=r["currency"],
                document_date=doc_date,
                document_type=r.get("document_type", "receipt"),
                description=r.get("description", ""),
                confidence=float(r.get("confidence", 1.0)),
                source_sha256=r.get("source_sha256"),
            )
            self._by_image_id[evidence.image_id] = evidence
            self._by_event_id[evidence.related_event_id] = evidence

    @property
    def total_resolved(self) -> int:
        return len(self._by_image_id)

    def get_by_image_id(self, image_id: str) -> ImageEvidence | None:
        return self._by_image_id.get(image_id)

    def get_by_event_id(self, event_id: str) -> ImageEvidence | None:
        return self._by_event_id.get(event_id)

    @staticmethod
    def matches_source(evidence: ImageEvidence, path: Path) -> bool:
        """Cached facts are valid only for the exact reviewed image bytes."""
        if (
            path.stem != evidence.image_id
            or evidence.source_sha256 is None
            or not evidence.amount.is_finite()
            or evidence.amount < 0
        ):
            return False
        try:
            with path.open("rb") as source:
                return hashlib.file_digest(source, "sha256").hexdigest() == evidence.source_sha256
        except OSError:
            return False

    def all_records(self) -> list[ImageEvidence]:
        return list(self._by_image_id.values())
