"""Cold starts may wait for readiness; authentication and failed loads must fail promptly."""

import io
import json
import urllib.error
from email.message import Message
from typing import Any

import pytest

from orcha.assistant.routing import RemoteLayaRouter, RoutingState


class Response(io.BytesIO):
    def __enter__(self) -> "Response":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()


def state() -> RoutingState:
    return RoutingState(
        interpreted=False,
        evidence_valid=False,
        result_verified=False,
        issues_count=0,
        document_count=1,
    )


def unavailable(body: dict[str, str], status: int = 503) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "https://example.com/v1/route",
        status,
        "Unavailable",
        Message(),
        Response(json.dumps(body).encode()),
    )


def install(monkeypatch: pytest.MonkeyPatch, responses: list[Any]) -> list[str]:
    paths: list[str] = []

    class Opener:
        def open(self, request: Any, timeout: float) -> Any:
            assert 0 < timeout <= 8
            paths.append(request.full_url)
            response = responses.pop(0)
            if isinstance(response, Exception):
                raise response
            return Response(json.dumps(response).encode())

    monkeypatch.setattr(
        "orcha.assistant.routing.urllib.request.build_opener", lambda *args: Opener()
    )
    monkeypatch.setattr("orcha.assistant.routing.time.sleep", lambda seconds: None)
    return paths


def test_model_loading_retries_only_after_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    expected = {"action": "interpret_request"}
    paths = install(
        monkeypatch,
        [
            unavailable({"error": "model_unavailable"}),
            unavailable({"status": "loading"}),
            {"status": "ready"},
            expected,
        ],
    )
    assert (
        RemoteLayaRouter("https://example.com", "fake-token-long-enough").propose(state())
        == expected
    )
    assert paths == [
        "https://example.com/v1/route",
        "https://example.com/ready",
        "https://example.com/ready",
        "https://example.com/v1/route",
    ]


def test_authentication_failure_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    paths = install(monkeypatch, [unavailable({"error": "unauthorized"}, 401)])
    with pytest.raises(urllib.error.HTTPError):
        RemoteLayaRouter("https://example.com", "fake-token-long-enough").propose(state())
    assert len(paths) == 1


def test_failed_checkpoint_does_not_poll_forever(monkeypatch: pytest.MonkeyPatch) -> None:
    paths = install(
        monkeypatch,
        [unavailable({"error": "model_unavailable"}), unavailable({"status": "failed"})],
    )
    with pytest.raises(ValueError, match="initialization failed"):
        RemoteLayaRouter("https://example.com", "fake-token-long-enough").propose(state())
    assert len(paths) == 2


def test_loading_has_a_total_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    paths = install(monkeypatch, [unavailable({"error": "model_unavailable"})])
    ticks = iter([0.0, 0.0, 46.0])
    monkeypatch.setattr("orcha.assistant.routing.time.monotonic", lambda: next(ticks))
    with pytest.raises(TimeoutError):
        RemoteLayaRouter("https://example.com", "fake-token-long-enough").propose(state())
    assert len(paths) == 1


@pytest.mark.parametrize("initial", [TimeoutError("wake timeout"), unavailable({}, 502)])
def test_infrastructure_wake_failure_still_waits_for_ready(
    monkeypatch: pytest.MonkeyPatch, initial: Exception
) -> None:
    expected = {"action": "interpret_request"}
    paths = install(monkeypatch, [initial, unavailable({}, 504), {"status": "ready"}, expected])
    assert (
        RemoteLayaRouter("https://example.com", "fake-token-long-enough").propose(state())
        == expected
    )
    assert len(paths) == 4


def test_failed_model_exits_and_reports_unhealthy(monkeypatch: pytest.MonkeyPatch) -> None:
    from services.laya.service import ModelRuntime, load_or_exit, make_handler

    runtime = ModelRuntime()
    monkeypatch.setattr(runtime, "load", lambda: setattr(runtime, "error", True))
    exits: list[int] = []
    monkeypatch.setattr("services.laya.service.os._exit", exits.append)
    load_or_exit(runtime)
    assert exits == [1]
    handler = object.__new__(make_handler(runtime, "fake-token-long-enough"))
    handler.path = "/health"
    responses: list[tuple[int, dict[str, Any]]] = []
    monkeypatch.setattr(handler, "respond", lambda status, value: responses.append((status, value)))
    handler.do_GET()  # type: ignore[attr-defined]
    assert responses == [(503, {"status": "failed"})]
