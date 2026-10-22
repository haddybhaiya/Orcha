"""Evidence provider abstraction and interfaces."""

from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from orcha.evidence.images import ImageEvidenceExtractor
from orcha.evidence.messages import MessageEvidenceExtractor
from orcha.evidence.models import ImageEvidence, MessageEvidence

if TYPE_CHECKING:
    from orcha.assistant.contracts import ExtractionResponse, InterpretationContext


class StructuredEvidenceProvider(Protocol):
    """Interpret new questions/documents without granting financial authority."""

    def interpret(self, context: "InterpretationContext") -> "ExtractionResponse": ...


class EvidenceProvider(Protocol):
    """Protocol for extracting evidence from unstructured artifacts."""

    def extract_image(self, image_path: Path, event_id: str) -> ImageEvidence | None: ...

    def extract_message(
        self, message_text: str, message_id: str, user_id: str
    ) -> MessageEvidence: ...


class LocalEvidenceProvider:
    """Local, offline, cache-first evidence provider ensuring zero external calls."""

    def __init__(
        self,
        image_extractor: ImageEvidenceExtractor | None = None,
        message_extractor: MessageEvidenceExtractor | None = None,
    ) -> None:
        self.images = image_extractor or ImageEvidenceExtractor()
        self.messages = message_extractor or MessageEvidenceExtractor()

    def extract_image(self, image_path: Path, event_id: str) -> ImageEvidence | None:
        evidence = self.images.get_by_event_id(event_id)
        if evidence is None or not image_path.is_file():
            return None
        if image_path.stem != evidence.image_id:
            return None
        return evidence

    def extract_message(self, message_text: str, message_id: str, user_id: str) -> MessageEvidence:
        # Check cache first
        cached = self.messages.get_by_message_id(message_id)
        if cached is not None:
            return cached
        # Fallback to local deterministic parser
        return self.messages.parse_single_message(
            message_id=message_id,
            user_id=user_id,
            message_text=message_text,
        )
