"""Explicit CLI entry point for sending selected text to hosted Gemma."""

import json
import os
from pathlib import Path

from pydantic import ValidationError

from orcha.assistant.contracts import AssistantInput
from orcha.assistant.controller import run_assistant
from orcha.assistant.routing import router_from_environment
from orcha.evidence.gemma import GemmaConfig, GoogleGemmaProvider
from orcha.repository import DatasetRepository


def run_assistant_command(input_path: Path, dataset: Path | None, as_json: bool) -> int:
    """Only this opt-in command loads .env and makes model requests."""
    try:
        if input_path.stat().st_size > 64_000:
            raise ValueError("Assistant input exceeds 64 KB")
        request = AssistantInput.model_validate_json(input_path.read_text(encoding="utf-8"))
        config = GemmaConfig.from_environment()
        dataset_path = dataset or Path(os.getenv("DATASET_DIR", "dataset"))
        repository = DatasetRepository.load_from_dir(dataset_path)
    except ValidationError:
        print("[ERROR] Invalid assistant input. Check its fields and unique source IDs.")
        return 2
    except (OSError, ValueError, KeyError):
        # File/schema/config exceptions may contain raw input. Never dump them to the CLI.
        print(
            "[ERROR] Could not load assistant input, dataset, or Gemma settings. "
            "Check their configuration."
        )
        return 2
    if not as_json:
        print(f"[GEMMA] Sending the selected question and text updates to Google ({config.model}).")
    result = run_assistant(
        request, repository, GoogleGemmaProvider(config), router=router_from_environment()
    )
    if as_json:
        print(result.model_dump_json(indent=2))
    else:
        print(result.brief)
        for question in result.questions:
            print(f"Clarification: {question}")
        if result.evidence:
            print("Supporting facts:")
            for fact in result.evidence:
                print(f"  [{fact.source_id}] {fact.field}: {fact.value}")
        print("Actions: " + " -> ".join(result.actions))
        for decision in result.routing:
            print(f"Routing: {decision.selected_action} via {decision.source} ({decision.reason})")
        if result.usage:
            print("Model usage: " + json.dumps(result.usage.model_dump()))
    return {"complete": 0, "needs_clarification": 2, "unavailable": 3}[result.status]
