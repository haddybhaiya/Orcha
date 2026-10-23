"""The specialized model must only receive the finite workflow it was adapted for."""

import hashlib
import json
from pathlib import Path

import pytest

from services.laya.policy import ADAPTER_SHA256, apply_adapter, model_state
from services.laya.service import validate_payload


def test_all_supported_count_variations_preserve_exactly_four_model_states() -> None:
    groups: dict[str, set[str]] = {}
    count = 0
    for documents in range(9):
        for interpreted, valid, verified, issues, expected in [
            (False, False, False, 0, "interpret_request"),
            (True, True, False, 0, "run_forecast"),
            (True, True, True, 0, "explain_result"),
            *[(False, False, False, i, "ask_clarification") for i in range(1, 101)],
        ]:
            state = validate_payload(
                {
                    "schema_version": "1",
                    "state": {
                        "interpreted": interpreted,
                        "evidence_valid": valid,
                        "result_verified": verified,
                        "issues_count": issues,
                        "document_count": documents,
                    },
                }
            )
            encoded = model_state(state)
            assert expected not in encoded
            assert "document_count" not in encoded
            assert isinstance(json.loads(encoded)["issues_count"], int)
            groups.setdefault(encoded, set()).add(expected)
            count += 1
    assert count == 927
    assert len(groups) == 4
    assert all(len(labels) == 1 for labels in groups.values())


@pytest.mark.parametrize(
    "progress,issues",
    [((True, False, False), 0), ((True, True, False), 1), ((True, True, True), 2)],
)
def test_service_rejects_states_outside_the_adapted_workflow(
    progress: tuple[bool, bool, bool], issues: int
) -> None:
    with pytest.raises(ValueError):
        validate_payload(
            {
                "schema_version": "1",
                "state": {
                    "interpreted": progress[0],
                    "evidence_valid": progress[1],
                    "result_verified": progress[2],
                    "issues_count": issues,
                    "document_count": 1,
                },
            }
        )


def test_adapter_is_the_verified_training_artifact() -> None:
    artifact = Path("services/laya/workflow-scorer.safetensors").read_bytes()
    assert len(artifact) == 3152
    assert hashlib.sha256(artifact).hexdigest() == ADAPTER_SHA256


def test_corrupted_adapter_fails_before_model_dependencies_are_needed(tmp_path: Path) -> None:
    artifact = tmp_path / "bad.safetensors"
    artifact.write_bytes(b"corrupted")
    with pytest.raises(ValueError, match="checksum"):
        apply_adapter(None, artifact)
