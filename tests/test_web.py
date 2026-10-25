"""Verify the local HTTP boundary, real financial result, and import isolation offline."""

import io
import json
import zipfile
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from orcha.assistant.contracts import (
    Extraction,
    ExtractionResponse,
    InterpretationContext,
    ModelUsage,
)
from orcha.evidence.gemma import GemmaConfig
from orcha.web.app import create_app
from orcha.web.workspace import DEMO_DIR


class Provider:
    calls = 0

    def interpret(self, context: InterpretationContext) -> ExtractionResponse:
        self.calls += 1
        return ExtractionResponse(
            extraction=Extraction.model_validate(
                {
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
                    "bills": [
                        {
                            "source_id": "repair_notice",
                            "operation": "new_bill",
                            "reference": "DEMO-REPAIR-01",
                            "money": {
                                "amount": "12000.00",
                                "currency": "INR",
                                "source_id": "repair_notice",
                                "quote": "INR 12000.00",
                            },
                            "due_date": {
                                "value": "2026-10-23",
                                "source_id": "repair_notice",
                                "quote": "2026-10-23",
                            },
                        }
                    ],
                    "unresolved": [],
                }
            ),
            usage=ModelUsage(model="fake", api_calls=1),
        )


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(
        "orcha.web.app.GemmaConfig.from_environment",
        lambda: GemmaConfig(api_key="fake-private-key"),
    )
    provider = Provider()
    monkeypatch.setattr("orcha.web.app.GoogleGemmaProvider", lambda config: provider)
    monkeypatch.setattr("orcha.web.app.router_from_environment", lambda: None)
    return TestClient(create_app())


def headers(client: TestClient) -> dict[str, str]:
    return {"X-Orcha-Token": client.get("/api/workspace").json()["csrf_token"]}


def test_provider_refreshes_when_credentials_or_timeout_change(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    client.get("/api/workspace")
    old = client.app.state.workspace.provider  # type: ignore[attr-defined]
    monkeypatch.setattr(
        "orcha.web.app.GemmaConfig.from_environment",
        lambda: GemmaConfig(api_key="changed-private-key", timeout_seconds=12),
    )
    client.get("/api/workspace")
    new = client.app.state.workspace.provider  # type: ignore[attr-defined]
    assert old is not new
    assert "changed-private-key" not in new.identity


def request_data() -> dict[str, Any]:
    return json.loads(Path("demo/assistant_request.json").read_text())  # type: ignore[no-any-return]


def bundle() -> dict[str, Any]:
    return {"files": [{"name": p.name, "content": p.read_text()} for p in DEMO_DIR.glob("*.csv")]}


def test_dashboard_is_derived_from_real_ledger_and_does_not_expose_keys(client: TestClient) -> None:
    response = client.get("/api/workspace")
    assert response.status_code == 200
    data = response.json()
    assert data["summary"]["safe_to_spend"] == "30000.00"
    assert len(data["timeline"]) == 90
    assert data["events"][0]["direction"] == "credit"
    assert data["providers"] == {"gemma_configured": True, "laya_configured": False}
    assert "fake-private-key" not in response.text
    assert response.headers["cache-control"] == "no-store"


def test_browser_forecast_uses_new_bill_and_verified_payment_date(client: TestClient) -> None:
    original = client.get("/api/workspace").json()
    response = client.post("/api/assist", json=request_data(), headers=headers(client))
    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "complete"
    assert result["decision"]["amount_safe_to_pay"] == "18000.00"
    assert result["decision"]["payment_plan"] == "2026-10-25:25000"
    assert result["timeline"][2]["balance"] == "28000.00"
    assert result["timeline"][2]["expenses"] == "12000.00"
    assert len(result["routing"]) == 3
    assert result["actions"][-2:] == ["verify_result", "explain_result"]
    assert client.get("/api/workspace").json()["timeline"] == original["timeline"]


def test_content_cache_reuses_identical_input_but_not_changed_evidence(client: TestClient) -> None:
    auth = headers(client)
    first = client.post("/api/assist", json=request_data(), headers=auth).json()
    second = client.post("/api/assist", json=request_data(), headers=auth).json()
    assert first["usage"]["api_calls"] == 1
    assert second["usage"]["cached"] is True
    assert second["usage"]["api_calls"] == 0
    modified = request_data()
    modified["documents"][0]["text"] = modified["documents"][0]["text"].replace("12000", "15000")
    third = client.post("/api/assist", json=modified, headers=auth).json()
    assert third["usage"]["cached"] is False
    assert third["status"] == "needs_clarification"  # stale provider quote is not trusted


def test_negation_clarifies_without_calling_model(client: TestClient) -> None:
    data = request_data()
    data["documents"][0]["text"] = "This bill is cancelled. Do not pay."
    result = client.post("/api/assist", json=data, headers=headers(client)).json()
    assert result["status"] == "needs_clarification"
    assert result["decision"] is None and result["timeline"] == []
    assert result["usage"] is None


@pytest.mark.parametrize("path", ["/api/assist", "/api/import", "/api/reset"])
def test_mutations_require_workspace_token(client: TestClient, path: str) -> None:
    assert client.post(path, json={}).status_code == 403


def test_cross_origin_and_host_rebinding_are_blocked(client: TestClient) -> None:
    assert client.get("/api/workspace", headers={"Host": "evil.example"}).status_code == 400
    assert (
        client.post(
            "/api/reset", json={}, headers={**headers(client), "Origin": "https://evil.example"}
        ).status_code
        == 403
    )


def test_validation_errors_never_echo_input(client: TestClient) -> None:
    response = client.post(
        "/api/assist", json={"private": "secret-financial-content"}, headers=headers(client)
    )
    assert response.status_code == 422
    assert "secret-financial-content" not in response.text
    assert (
        client.post(
            "/api/assist",
            content="x" * 70_001,
            headers={**headers(client), "Content-Type": "application/json"},
        ).status_code
        == 413
    )


def test_successful_import_and_reset_are_session_local(client: TestClient) -> None:
    original = (DEMO_DIR / "financial_profiles.csv").read_bytes()
    data = bundle()
    for item in data["files"]:
        if item["name"] == "financial_profiles.csv":
            item["content"] = item["content"].replace("40000.00", "45000.00")
    response = client.post("/api/import", json=data, headers=headers(client))
    assert response.status_code == 200
    assert response.json()["is_demo"] is False
    assert response.json()["summary"]["balance"] == "45000.00"
    assert (DEMO_DIR / "financial_profiles.csv").read_bytes() == original
    restored = client.post("/api/reset", json={}, headers=headers(client)).json()
    assert restored["is_demo"] is True and restored["summary"]["balance"] == "40000.00"


@pytest.mark.parametrize("failure", ["path", "duplicate", "invalid", "nonfinite"])
def test_bad_import_cannot_replace_previous_workspace(client: TestClient, failure: str) -> None:
    original = client.get("/api/workspace").json()
    data = bundle()
    if failure == "path":
        data["files"][0]["name"] = "../financial_profiles.csv"
    elif failure == "duplicate":
        data["files"][0]["name"] = data["files"][1]["name"]
    else:
        for item in data["files"]:
            if item["name"] == "financial_profiles.csv":
                item["content"] = (
                    "not-a-csv"
                    if failure == "invalid"
                    else item["content"].replace("40000.00", "NaN")
                )
    response = client.post("/api/import", json=data, headers=headers(client))
    assert response.status_code == 422
    assert client.get("/api/workspace").json()["summary"] == original["summary"]


def test_template_download_contains_only_synthetic_csvs(client: TestClient) -> None:
    response = client.get("/api/template")
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert len(archive.namelist()) == 8
        assert all(name.endswith(".csv") and "/" not in name for name in archive.namelist())
        assert b"demo_before" in archive.read("financial_profiles.csv")
