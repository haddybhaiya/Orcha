"""Hosted demo boundaries and expiring background results, without model calls."""

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from orcha.assistant.contracts import AssistantResult
from orcha.web.app import create_app
from orcha.web.cloud import create_cloud_app
from orcha.web.demo_jobs import DemoJobs

ORIGIN = "https://demo.example"


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("GEMMA_API_KEY", "fake-private-key")
    monkeypatch.setattr(
        "orcha.web.app.run_assistant",
        lambda *args, **kwargs: AssistantResult(
            status="needs_clarification", brief="More information is needed.", questions=["Amount?"]
        ),
    )
    # Simulate a gateway terminating HTTPS and forwarding HTTP to the container.
    return TestClient(create_app(public_origin=ORIGIN), base_url="http://demo.example")


def token(client: TestClient) -> dict[str, str]:
    return {"X-Orcha-Token": client.get("/api/workspace").json()["csrf_token"], "Origin": ORIGIN}


def payload() -> dict[str, Any]:
    return json.loads(Path("demo/assistant_request.json").read_text())  # type: ignore[no-any-return]


def test_public_workspace_is_synthetic_and_cannot_be_replaced(client: TestClient) -> None:
    workspace = client.get("/api/workspace").json()
    assert workspace["public_demo"] is True and workspace["is_demo"] is True
    assert "fake-private-key" not in json.dumps(workspace)
    for path in ["/api/import", "/api/reset"]:
        assert client.post(path, json={}, headers=token(client)).status_code == 403
    assert client.get("/api/workspace").json()["summary"] == workspace["summary"]
    assert client.get("/health").json() == {"status": "ready"}


def test_public_assist_returns_job_and_then_result(client: TestClient) -> None:
    response = client.post("/api/assist", json=payload(), headers=token(client))
    assert response.status_code == 202
    job = response.json()
    assert job["status"] == "pending" and len(job["job_id"]) >= 40
    result = client.get("/api/jobs/" + job["job_id"])
    assert result.status_code == 200
    assert result.headers["cache-control"] == "no-store"
    assert result.json()["status"] == "done"
    assert result.json()["result"]["status"] == "needs_clarification"
    assert client.get("/api/jobs/unknown-token").status_code == 404


def test_job_failure_does_not_expose_private_exception(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("private-financial-content")

    monkeypatch.setattr("orcha.web.app.run_assistant", fail)
    job = client.post("/api/assist", json=payload(), headers=token(client)).json()
    result = client.get("/api/jobs/" + job["job_id"])
    assert result.json()["status"] == "failed"
    assert "private-financial-content" not in result.text


def test_public_host_origin_and_workspace_token_are_enforced(client: TestClient) -> None:
    assert client.get("/", headers={"Host": "attacker.example"}).status_code == 400
    assert client.post("/api/assist", json=payload()).status_code == 403
    assert (
        client.post(
            "/api/assist",
            json=payload(),
            headers={**token(client), "Origin": "https://attacker.example"},
        ).status_code
        == 403
    )
    assert client.get("/api/jobs").status_code == 404


@pytest.mark.parametrize(
    "origin",
    [
        "http://demo.example",
        "https://user:pass@demo.example",
        "https://demo.example/path",
        "https://demo.example?key=x",
    ],
)
def test_public_origin_requires_exact_https_origin(origin: str) -> None:
    with pytest.raises(ValueError, match="HTTPS origin"):
        create_app(public_origin=origin)


def test_public_mode_cannot_load_arbitrary_dataset(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="synthetic dataset"):
        create_app(tmp_path, public_origin=ORIGIN)


def test_cloud_entry_requires_explicit_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ORCHA_PUBLIC_ORIGIN", raising=False)
    with pytest.raises(ValueError, match="ORCHA_PUBLIC_ORIGIN"):
        create_cloud_app()


def test_demo_jobs_allow_one_active_request_and_expire_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("orcha.web.demo_jobs.time.monotonic", lambda: 0)
    jobs = DemoJobs()
    first = jobs.submit()
    assert jobs.get(first) == {"status": "pending"}
    with pytest.raises(HTTPException) as busy:
        jobs.submit()
    assert busy.value.status_code == 409
    jobs.finish(first, {"status": "done", "result": {}})
    monkeypatch.setattr("orcha.web.demo_jobs.time.monotonic", lambda: 601)
    with pytest.raises(HTTPException) as expired:
        jobs.get(first)
    assert expired.value.status_code == 404


def test_demo_jobs_are_bounded_and_hourly_limit_recovers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("orcha.web.demo_jobs.time.monotonic", lambda: 0)
    jobs = DemoJobs()
    identifiers = []
    for _ in range(60):
        identifier = jobs.submit()
        identifiers.append(identifier)
        jobs.finish(identifier, {"status": "done"})
    assert len(jobs.results) == 16
    with pytest.raises(HTTPException):
        jobs.get(identifiers[0])
    with pytest.raises(HTTPException) as limited:
        jobs.submit()
    assert limited.value.status_code == 429
    assert limited.value.headers == {"Retry-After": "3600"}
    monkeypatch.setattr("orcha.web.demo_jobs.time.monotonic", lambda: 3601)
    assert jobs.get(jobs.submit()) == {"status": "pending"}
