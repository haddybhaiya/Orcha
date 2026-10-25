"""Authenticated remote Laya proposals, constrained by Python workflow dependencies."""

import json
import math
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

from orcha.environment import settings

Action = Literal["interpret_request", "ask_clarification", "run_forecast", "explain_result"]


class RoutingState(BaseModel):
    """Only these flags/counts leave the laptop; never financial text or amounts."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    interpreted: bool
    evidence_valid: bool
    result_verified: bool
    issues_count: int = Field(ge=0, le=100)
    document_count: int = Field(ge=0, le=8)


class Proposal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["1"]
    action: Action
    confidence: float = Field(ge=0, le=1)
    model: str = Field(min_length=1, max_length=128)
    revision: str = Field(pattern=r"^[a-f0-9]{40}$")
    inference_ms: float = Field(ge=0)
    policy_version: str | None = Field(default=None, min_length=1, max_length=100)

    @field_validator("confidence", "inference_ms", mode="before")
    @classmethod
    def finite_numbers(cls, value: object) -> object:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("A finite numeric value is required")
        if not math.isfinite(value):
            raise ValueError("A finite numeric value is required")
        return value


class RoutingDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    eligible_action: Action
    selected_action: Action
    proposed_action: Action | None = None
    source: Literal["laya", "deterministic"]
    reason: str
    confidence: float | None = None
    latency_ms: float = 0
    model: str | None = None
    revision: str | None = None
    policy_version: str | None = None


class ActionRouter(Protocol):
    def propose(self, state: RoutingState) -> object: ...


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


@dataclass(frozen=True)
class RemoteLayaRouter:
    url: str
    token: str = field(repr=False)
    timeout_seconds: float = 8
    startup_timeout_seconds: float = 45

    def __post_init__(self) -> None:
        parsed = urlsplit(self.url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path.rstrip("/")
        ):
            raise ValueError("LAYA_API_URL must be an HTTPS origin without credentials or a path")
        if (
            len(self.token) < 16
            or not 1 <= self.timeout_seconds <= 60
            or not 1 <= self.startup_timeout_seconds <= 60
        ):
            raise ValueError("Invalid Laya token or timeout")

    def propose(self, state: RoutingState) -> object:
        deadline = time.monotonic() + self.startup_timeout_seconds
        body = json.dumps({"schema_version": "1", "state": state.model_dump()}).encode()
        request = urllib.request.Request(
            self.url.rstrip("/") + "/v1/route",
            data=body,
            method="POST",
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
        )
        opener = urllib.request.build_opener(_NoRedirect())

        def read_json(response: Any) -> Any:
            with response:
                raw = response.read(16_385)
            if len(raw) > 16_384:
                raise ValueError("Oversized routing response")
            return json.loads(raw)

        def remaining() -> float:
            seconds = deadline - time.monotonic()
            if seconds <= 0:
                raise TimeoutError("Laya startup deadline expired")
            return min(self.timeout_seconds, seconds)

        request_timeout = remaining()
        try:
            return read_json(opener.open(request, timeout=request_timeout))
        except urllib.error.HTTPError as error:
            if error.code not in {502, 503, 504}:
                raise
            error.close()
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            # Infrastructure may time out before the model process can answer.
            pass
        readiness = urllib.request.Request(self.url.rstrip("/") + "/ready")
        while True:
            request_timeout = remaining()
            try:
                response = opener.open(readiness, timeout=request_timeout)
            except urllib.error.HTTPError as error:
                if error.code not in {502, 503, 504}:
                    raise
                response = error
            except (urllib.error.URLError, TimeoutError, ConnectionError):
                time.sleep(min(1, remaining()))
                continue
            try:
                payload = read_json(response)
            except (ValueError, OSError):
                if getattr(response, "code", 200) not in {502, 503, 504}:
                    raise
                time.sleep(min(1, remaining()))
                continue
            status = payload.get("status") if isinstance(payload, dict) else None
            if status == "ready":
                return read_json(opener.open(request, timeout=remaining()))
            if status != "loading":
                if getattr(response, "code", 200) in {502, 503, 504} and status != "failed":
                    time.sleep(min(1, remaining()))
                    continue
                raise ValueError("Laya model initialization failed")
            time.sleep(min(1, remaining()))


def router_from_environment() -> ActionRouter | None:
    """Absent or invalid optional settings must not break the working Gemma flow."""
    values = settings()
    url, token = values.get("LAYA_API_URL"), values.get("LAYA_API_TOKEN")
    if not url or not token:
        return None
    try:
        return RemoteLayaRouter(
            url,
            token,
            float(values.get("LAYA_TIMEOUT_SECONDS", "8")),
            float(values.get("LAYA_STARTUP_TIMEOUT_SECONDS", "45")),
        )
    except ValueError:
        return None


class RoutingSession:
    """One workflow: record proposals and stop calling an unavailable service."""

    def __init__(self, router: ActionRouter | None, document_count: int) -> None:
        self.router = router
        self.document_count = document_count
        self.decisions: list[RoutingDecision] = []
        self.unavailable = False
        try:
            threshold = float(settings().get("LAYA_MIN_CONFIDENCE", "0.8"))
            self.threshold = threshold if math.isfinite(threshold) and 0 <= threshold <= 1 else 0.8
        except ValueError:
            self.threshold = 0.8

    def choose(self, eligible: Action, issues: int = 0) -> Action:
        state = RoutingState(
            interpreted=eligible in {"run_forecast", "explain_result"},
            evidence_valid=eligible in {"run_forecast", "explain_result"},
            result_verified=eligible == "explain_result",
            issues_count=max(1, issues) if eligible == "ask_clarification" else 0,
            document_count=self.document_count,
        )
        proposal: Proposal | None = None
        reason = "not_configured" if self.router is None else "unavailable"
        started = time.perf_counter()
        if self.router is not None and not self.unavailable:
            try:
                raw = self.router.propose(state)
            except Exception:
                # Do not expose network exceptions, request bodies, or authentication headers.
                self.unavailable = True
            else:
                try:
                    proposal = Proposal.model_validate(raw)
                    if proposal.action != eligible:
                        reason = "ineligible_action"
                    elif proposal.confidence < self.threshold:
                        reason = "low_confidence"
                    else:
                        reason = "accepted"
                except ValueError:
                    reason = "invalid_response"
                    self.unavailable = True
        accepted = reason == "accepted"
        self.decisions.append(
            RoutingDecision(
                eligible_action=eligible,
                selected_action=eligible,
                proposed_action=proposal.action if proposal else None,
                source="laya" if accepted else "deterministic",
                reason=reason,
                confidence=proposal.confidence if proposal else None,
                latency_ms=round((time.perf_counter() - started) * 1000, 2),
                model=proposal.model if proposal else None,
                revision=proposal.revision if proposal else None,
                policy_version=proposal.policy_version if proposal else None,
            )
        )
        return eligible
