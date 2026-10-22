"""Routing and service boundaries: no real model, cloud account, or API key needed."""

import io
import json
from dataclasses import dataclass, field
from http.client import HTTPMessage
from pathlib import Path
from typing import Any

import pytest

from orcha.assistant.contracts import (
    AssistantInput,
    Extraction,
    ExtractionResponse,
    InterpretationContext,
    ModelUsage,
)
from orcha.assistant.controller import run_assistant
from orcha.assistant.routing import RemoteLayaRouter, RoutingSession, RoutingState
from orcha.repository import DatasetRepository
from services.laya.service import MODEL, REVISION, ModelRuntime, make_handler, validate_payload


def proposal(action: str = "run_forecast", confidence: object = 0.99) -> dict[str, Any]:
    return {
        "schema_version": "1",
        "action": action,
        "confidence": confidence,
        "model": MODEL,
        "revision": REVISION,
        "inference_ms": 10.0,
    }


@dataclass
class StubRouter:
    response: object
    states: list[RoutingState] = field(default_factory=list)

    def propose(self, state: RoutingState) -> object:
        self.states.append(state)
        return self.response


@pytest.mark.parametrize(
    "response,reason",
    [
        (proposal(), "accepted"),
        (proposal(confidence=0.1), "low_confidence"),
        (proposal("explain_result"), "ineligible_action"),
        (proposal(confidence=True), "invalid_response"),
        (proposal(confidence=float("nan")), "invalid_response"),
        (proposal(confidence="1"), "invalid_response"),
        (proposal("execute_code"), "invalid_response"),
        ([], "invalid_response"),
        (None, "invalid_response"),
    ],
)
def test_every_proposal_is_validated_and_can_only_select_the_eligible_action(
    response: object, reason: str
) -> None:
    session = RoutingSession(StubRouter(response), document_count=1)
    assert session.choose("run_forecast") == "run_forecast"
    assert session.decisions[0].reason == reason
    assert session.decisions[0].source == ("laya" if reason == "accepted" else "deterministic")


def test_unavailable_service_is_called_once_and_does_not_leak_error_contents() -> None:
    class Down:
        calls = 0

        def propose(self, state: RoutingState) -> object:
            self.calls += 1
            raise TimeoutError("do-not-log-this-secret")

    router = Down()
    session = RoutingSession(router, 0)
    assert session.choose("interpret_request") == "interpret_request"
    assert session.choose("run_forecast") == "run_forecast"
    assert session.choose("explain_result") == "explain_result"
    assert router.calls == 1
    assert all(d.reason == "unavailable" for d in session.decisions)
    assert "do-not-log" not in str(session.decisions)


def test_no_service_configuration_preserves_the_existing_workflow() -> None:
    session = RoutingSession(None, 0)
    assert session.choose("interpret_request") == "interpret_request"
    assert session.decisions[0].reason == "not_configured"


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com",
        "https://example.com/path",
        "https://user:pass@example.com",
        "https://example.com?key=secret",
        "https://example.com#fragment",
    ],
)
def test_endpoint_configuration_cannot_put_tokens_in_urls_or_use_plain_http(url: str) -> None:
    with pytest.raises(ValueError):
        RemoteLayaRouter(url, "fake-service-token-at-least-16")


def test_remote_client_sends_only_state_and_uses_header_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorded: list[Any] = []

    class Response(io.BytesIO):
        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *args: Any) -> None:
            self.close()

    class Opener:
        def open(self, request: Any, timeout: float) -> Response:
            recorded.append(request)
            return Response(json.dumps(proposal()).encode())

    monkeypatch.setattr(
        "orcha.assistant.routing.urllib.request.build_opener", lambda *args: Opener()
    )
    state = RoutingState(
        interpreted=True,
        evidence_valid=True,
        result_verified=False,
        issues_count=0,
        document_count=1,
    )
    client = RemoteLayaRouter("https://example.com", "fake-service-token-at-least-16")
    client.propose(state)
    payload = json.loads(recorded[0].data)
    assert set(payload) == {"schema_version", "state"}
    assert set(payload["state"]) == {
        "interpreted",
        "evidence_valid",
        "result_verified",
        "issues_count",
        "document_count",
    }
    assert recorded[0].get_header("Authorization") == "Bearer fake-service-token-at-least-16"
    assert "fake-service-token" not in repr(client)
    assert "fake-service-token" not in recorded[0].full_url


def test_model_cannot_override_a_required_clarification() -> None:
    request = AssistantInput.model_validate_json(Path("demo/assistant_request.json").read_text())
    source = request.documents[0].model_copy(update={"text": "Do not pay: this bill is cancelled."})
    request = request.model_copy(update={"documents": [source]})

    class NeverInterpret:
        def interpret(self, context: InterpretationContext) -> ExtractionResponse:
            raise AssertionError("Gemma must not run for a blocked request")

    result = run_assistant(
        request,
        DatasetRepository.load_from_dir(Path("demo/dataset")),
        NeverInterpret(),
        router=StubRouter(proposal("run_forecast")),
    )
    assert result.status == "needs_clarification"
    assert result.decision is None
    assert result.actions == ["ask_clarification"]
    assert result.routing[0].reason == "ineligible_action"
    assert result.routing[0].selected_action == "ask_clarification"


def test_complete_workflow_retains_all_checks_under_hostile_routing() -> None:
    request = AssistantInput.model_validate_json(Path("demo/assistant_request.json").read_text())
    request = request.model_copy(update={"documents": []})
    data = {
        "purchase": {
            "money": {
                "amount": "25000.00",
                "currency": "INR",
                "source_id": "purchase_question",
                "quote": "INR 25000.00",
            },
            "deadline": {
                "value": "2026-10-30",
                "source_id": "purchase_question",
                "quote": "2026-10-30",
            },
        },
        "bills": [],
        "unresolved": [],
    }

    class Provider:
        def interpret(self, context: InterpretationContext) -> ExtractionResponse:
            return ExtractionResponse(
                extraction=Extraction.model_validate(data), usage=ModelUsage(model="fake")
            )

    router = StubRouter(proposal("ask_clarification"))
    result = run_assistant(
        request, DatasetRepository.load_from_dir(Path("demo/dataset")), Provider(), router
    )
    assert result.status == "complete"
    assert result.actions == [
        "interpret_request",
        "validate_evidence",
        "run_forecast",
        "verify_result",
        "explain_result",
    ]
    assert len(result.routing) == 3
    assert all(d.reason == "ineligible_action" for d in result.routing)
    assert all(
        set(s.model_dump())
        == {"interpreted", "evidence_valid", "result_verified", "issues_count", "document_count"}
        for s in router.states
    )


def payload() -> dict[str, Any]:
    return {
        "schema_version": "1",
        "state": {
            "interpreted": True,
            "evidence_valid": True,
            "result_verified": False,
            "issues_count": 0,
            "document_count": 1,
        },
    }


@pytest.mark.parametrize(
    "change", ["extra_text", "boolean_count", "impossible_state", "wrong_version"]
)
def test_cloud_service_rejects_unexpected_or_inconsistent_state(change: str) -> None:
    body = payload()
    if change == "extra_text":
        body["state"]["financial_text"] = "must never be sent"
    elif change == "boolean_count":
        body["state"]["document_count"] = True
    elif change == "impossible_state":
        body["state"]["interpreted"] = False
    else:
        body["schema_version"] = "2"
    with pytest.raises(ValueError):
        validate_payload(body)


@pytest.mark.parametrize("authenticated,expected", [(False, 401), (True, 200)])
def test_cloud_endpoint_requires_token_before_model_inference(
    authenticated: bool, expected: int
) -> None:
    runtime = ModelRuntime()

    class Agent:
        def predict(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            return {
                "answers": {"next_action": {"choice": "run_forecast", "answer_confidence": 0.99}}
            }

    runtime.agent = Agent()
    base = make_handler(runtime, "fake-service-token-at-least-16")

    class Handler(base):  # type: ignore[valid-type, misc]
        def __init__(self) -> None:
            self.headers = HTTPMessage()
            raw = json.dumps(payload()).encode()
            self.headers["Content-Length"] = str(len(raw))
            if authenticated:
                self.headers["Authorization"] = "Bearer fake-service-token-at-least-16"
            self.path = "/v1/route"
            self.rfile = io.BytesIO(raw)
            self.responses: list[tuple[int, dict[str, Any]]] = []

        def respond(self, status: int, value: dict[str, Any]) -> None:
            self.responses.append((status, value))

    handler = Handler()
    handler.do_POST()
    assert handler.responses[0][0] == expected
    if authenticated:
        assert handler.responses[0][1]["action"] == "run_forecast"
