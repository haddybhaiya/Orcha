"""Authenticated, bounded Laya inference; no financial data, tools, or cloud credentials."""

import hmac
import importlib.metadata
import json
import math
import os
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

try:
    from .policy import (
        ADAPTER_SHA256,
        CRITERIA,
        INSTRUCTIONS,
        POLICY_VERSION,
        apply_adapter,
        model_state,
    )
except ImportError:  # Direct container entry point.
    from policy import (  # type: ignore[import-not-found, no-redef]
        ADAPTER_SHA256,
        CRITERIA,
        INSTRUCTIONS,
        POLICY_VERSION,
        apply_adapter,
        model_state,
    )

MODEL = "convaiinnovations/laya-multilingual"
REVISION = "e4e9ddf21a7b1903b7acffd8814ad4307bf63a67"
FIELDS = {"interpreted", "evidence_valid", "result_verified", "issues_count", "document_count"}


def validate_payload(payload: object) -> dict[str, Any]:
    if not isinstance(payload, dict) or set(payload) != {"schema_version", "state"}:
        raise ValueError("Invalid routing request")
    state = payload["state"]
    if payload["schema_version"] != "1" or not isinstance(state, dict) or set(state) != FIELDS:
        raise ValueError("Invalid routing state")
    for key in ["interpreted", "evidence_valid", "result_verified"]:
        if type(state[key]) is not bool:
            raise ValueError("Invalid routing flag")
    for key, limit in [("issues_count", 100), ("document_count", 8)]:
        if type(state[key]) is not int or not 0 <= state[key] <= limit:
            raise ValueError("Invalid routing count")
    if state["result_verified"] and not state["evidence_valid"]:
        raise ValueError("Result verification needs valid evidence")
    if state["evidence_valid"] and not state["interpreted"]:
        raise ValueError("Evidence validation needs interpretation")
    progress = (state["interpreted"], state["evidence_valid"], state["result_verified"])
    if progress not in {(False, False, False), (True, True, False), (True, True, True)}:
        raise ValueError("Unsupported workflow phase")
    if state["issues_count"] and any(progress):
        raise ValueError("Clarification uses a blocked workflow state")
    return state


class ModelRuntime:
    def __init__(self) -> None:
        self.agent: Any = None
        self.error = False
        self.startup_ms = 0.0
        self.lock = threading.Lock()

    def load(self) -> None:
        started = time.perf_counter()
        try:
            import torch

            laya = importlib.import_module("laya")
            torch.set_num_threads(4)
            agent = laya.load(os.environ.get("LAYA_MODEL_DIR", "/opt/laya-model"), device="cpu")
            apply_adapter(agent, Path(__file__).with_name("workflow-scorer.safetensors"))
            self.agent = agent
            self.startup_ms = round((time.perf_counter() - started) * 1000, 2)
            print(json.dumps({"event": "model_ready", **self.metadata()}), flush=True)
        except Exception as error:
            self.error = True
            print(
                json.dumps({"event": "model_load_failed", "error_type": type(error).__name__}),
                flush=True,
            )

    def metadata(self) -> dict[str, Any]:
        versions = {}
        for name in ["laya", "torch", "transformers"]:
            try:
                versions[name] = importlib.metadata.version(name)
            except importlib.metadata.PackageNotFoundError:
                versions[name] = "not_installed"
        return {
            "model": MODEL,
            "revision": REVISION,
            "versions": versions,
            "device": "cpu",
            "startup_ms": self.startup_ms,
            "policy_version": POLICY_VERSION,
            "adapter_sha256": ADAPTER_SHA256,
        }

    def predict(self, state: dict[str, Any]) -> dict[str, Any]:
        if self.agent is None:
            raise RuntimeError("Model is not ready")
        # Bound concurrent CPU work instead of allowing requests to multiply model memory.
        if not self.lock.acquire(blocking=False):
            raise RuntimeError("Model is busy")
        started = time.perf_counter()
        try:
            result = self.agent.predict(
                model_state(state),
                {
                    "next_action": {
                        "type": "choice",
                        "instructions": INSTRUCTIONS,
                        "criteria": CRITERIA,
                    }
                },
                max_len=512,
            )
            answer = result["answers"]["next_action"]
            confidence = answer["answer_confidence"]
            if isinstance(confidence, bool) or not isinstance(confidence, (float, int)):
                raise ValueError("Invalid model confidence")
            if not math.isfinite(confidence) or not 0 <= confidence <= 1:
                raise ValueError("Invalid model confidence")
            if answer.get("action") == "escalate":
                confidence = 0.0
            action = answer["choice"]
            if action not in CRITERIA:
                raise ValueError("Invalid model action")
            return {
                "schema_version": "1",
                "action": action,
                "confidence": confidence,
                "model": MODEL,
                "revision": REVISION,
                "inference_ms": round((time.perf_counter() - started) * 1000, 2),
                "policy_version": POLICY_VERSION,
            }
        finally:
            self.lock.release()


def make_handler(runtime: ModelRuntime, token: str) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def setup(self) -> None:
            super().setup()
            self.connection.settimeout(10)

        def log_message(self, format: str, *args: Any) -> None:
            pass  # Never log request bodies, headers, or tokens.

        def respond(self, status: int, value: dict[str, Any]) -> None:
            body = json.dumps(value, allow_nan=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            if self.path == "/health":
                self.respond(
                    503 if runtime.error else 200,
                    {"status": "failed" if runtime.error else "alive"},
                )
            elif self.path == "/ready":
                ready = runtime.agent is not None
                self.respond(
                    200 if ready else 503,
                    {
                        "status": "ready" if ready else "failed" if runtime.error else "loading",
                        **runtime.metadata(),
                    },
                )
            else:
                self.respond(404, {"error": "not_found"})

        def do_POST(self) -> None:
            supplied = self.headers.get("Authorization", "")
            if not hmac.compare_digest(supplied.encode(), ("Bearer " + token).encode()):
                self.respond(401, {"error": "unauthorized"})
                return
            if self.path != "/v1/route":
                self.respond(404, {"error": "not_found"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 4096 or self.headers.get("Transfer-Encoding"):
                    self.respond(413, {"error": "request_too_large"})
                    return
                state = validate_payload(json.loads(self.rfile.read(length)))
            except (ValueError, OSError):
                self.respond(400, {"error": "invalid_request"})
                return
            try:
                self.respond(200, runtime.predict(state))
            except Exception:
                self.respond(503, {"error": "model_unavailable"})

    return Handler


class DualStackServer(ThreadingHTTPServer):
    address_family = socket.AF_INET6
    daemon_threads = True

    def server_bind(self) -> None:
        self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        super().server_bind()


def load_or_exit(runtime: ModelRuntime) -> None:
    """A failed checkpoint must restart the process, not remain healthy forever."""
    runtime.load()
    if runtime.error:
        os._exit(1)


if __name__ == "__main__":
    secret = os.environ.get("LAYA_API_TOKEN", "")
    if len(secret) < 16:
        raise SystemExit("Set LAYA_API_TOKEN to a strong service token")
    model = ModelRuntime()
    server = DualStackServer(
        ("::", int(os.environ.get("PORT", "8080"))), make_handler(model, secret)
    )
    threading.Thread(target=load_or_exit, args=(model,), daemon=True).start()
    server.serve_forever()
