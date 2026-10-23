"""Versioned model input and tiny task-specific Laya scorer adaptation."""

import hashlib
import json
from pathlib import Path
from typing import Any

POLICY_VERSION = "orcha-workflow-v1"
ADAPTER_SHA256 = "5a19737961a8d1be868010a86dea9a1c574e140a1304a241b5b2d63b195120ab"
INSTRUCTIONS = (
    "Choose the next financial-assistant workflow action from the flags. "
    "Any issues_count above zero requires clarification. Never skip validation."
)
CRITERIA = {
    "interpret_request": "No interpretation yet and no blocking issues: interpret the request.",
    "ask_clarification": "There are blocking issues or unresolved facts: ask for clarification.",
    "run_forecast": (
        "Interpretation and evidence validation are complete, no issues, result not verified."
    ),
    "explain_result": (
        "The financial result is already independently verified and there are no issues."
    ),
}


def model_state(state: dict[str, Any]) -> str:
    """Remove irrelevant magnitudes, without computing or injecting an action label."""
    return json.dumps(
        {
            "interpreted": state["interpreted"],
            "evidence_valid": state["evidence_valid"],
            "result_verified": state["result_verified"],
            "issues_count": int(state["issues_count"] > 0),
        },
        sort_keys=True,
    )


def apply_adapter(agent: Any, path: Path) -> None:
    """Refuse missing, corrupted or incompatible artifacts; never use pickle."""
    if hashlib.sha256(path.read_bytes()).hexdigest() != ADAPTER_SHA256:
        raise ValueError("Workflow adapter checksum mismatch")
    import torch
    from safetensors.torch import load_file

    tensors = load_file(str(path))
    target = agent.model.scorer[-1].weight
    weight = tensors.get("weight")
    if (
        set(tensors) != {"weight"}
        or weight is None
        or tuple(weight.shape) != tuple(target.shape)
        or not torch.isfinite(weight).all()
    ):
        raise ValueError("Incompatible workflow adapter")
    with torch.no_grad():
        target.copy_(weight.to(device=target.device, dtype=target.dtype))
