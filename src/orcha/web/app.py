"""Loopback-only HTTP boundary. Financial content and API secrets stay server-side."""

import hashlib
import hmac
import json
import secrets
from collections.abc import Awaitable, Callable
from datetime import date
from pathlib import Path
from typing import Any, TypeVar

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.middleware.trustedhost import TrustedHostMiddleware

from orcha.assistant.contracts import AssistantInput
from orcha.assistant.controller import run_assistant
from orcha.assistant.routing import router_from_environment
from orcha.evidence.gemma import PROMPT_VERSION, GemmaConfig, GoogleGemmaProvider
from orcha.web.workspace import DEMO_DIR, ImportBundle, SessionProvider, Workspace, demo_archive

STATIC = Path(__file__).with_name("static")
Model = TypeVar("Model", bound=BaseModel)


async def read_payload(request: Request, contract: type[Model], limit: int) -> Model:
    if request.headers.get("content-type", "").split(";")[0] != "application/json":
        raise HTTPException(415, "Send application/json")
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > limit:
            raise HTTPException(413, "The upload is too large. Use a smaller file bundle.")
    try:
        return contract.model_validate_json(bytes(body))
    except ValidationError:
        # Pydantic's default errors include raw input; do not echo financial text.
        raise HTTPException(
            422, "Check the input fields, dates, file count, and text limits."
        ) from None


def create_app(dataset: Path = DEMO_DIR) -> FastAPI:
    workspace = Workspace(dataset)
    token = secrets.token_urlsafe(32)
    app = FastAPI(title="Orcha", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.workspace = workspace
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"]
    )

    def configure_provider() -> None:
        try:
            config = GemmaConfig.from_environment()
        except ValueError:
            workspace.provider = None
            return
        identity = json.dumps(
            {
                "prompt": PROMPT_VERSION,
                "model": config.model,
                "output_tokens": config.max_output_tokens,
                "credential": hashlib.sha256(config.api_key.encode()).hexdigest(),
                "timeout": config.timeout_seconds,
                "cache_dir": str(config.cache_dir),
            },
            sort_keys=True,
        )
        if workspace.provider is None or workspace.provider.identity != identity:
            workspace.provider = SessionProvider(GoogleGemmaProvider(config), identity)

    def view(user_id: str | None = None, as_of: date | None = None) -> dict[str, Any]:
        configure_provider()
        data = workspace.view(user_id, as_of)
        data["csrf_token"] = token
        data["providers"] = {
            "gemma_configured": workspace.provider is not None,
            "laya_configured": router_from_environment() is not None,
        }
        return data

    @app.middleware("http")
    async def local_boundary(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        origin = request.headers.get("origin")
        expected_origin = str(request.base_url).rstrip("/")
        if origin and origin != expected_origin:
            return JSONResponse({"detail": "Open Orcha from its local address."}, status_code=403)
        if request.method not in {"GET", "HEAD"}:
            supplied = request.headers.get("x-orcha-token", "")
            if not hmac.compare_digest(supplied.encode(), token.encode()):
                return JSONResponse(
                    {"detail": "Reload the workspace and try again."}, status_code=403
                )
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "font-src 'self'; img-src 'self' data:; connect-src 'self'; "
            "frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        )
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, error: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            {"detail": "Check the selected profile and reference date."}, status_code=422
        )

    def locked(operation: Callable[[], Any]) -> Any:
        if not workspace.lock.acquire(blocking=False):
            raise HTTPException(409, "A request is already running. Wait for it to finish.")
        try:
            return operation()
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(
                422,
                "This financial data could not be verified. Check the CSV format, "
                "profile, currencies, and required evidence. Your previous workspace is preserved.",
            ) from None
        finally:
            workspace.lock.release()

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC / "index.html", media_type="text/html")

    @app.get("/api/workspace")
    def get_workspace(user_id: str | None = None, as_of: date | None = None) -> Any:
        return locked(lambda: view(user_id, as_of))

    @app.post("/api/import")
    async def import_data(request: Request) -> Any:
        bundle = await read_payload(request, ImportBundle, 8_000_000)

        def perform() -> dict[str, Any]:
            previous = workspace.repository, workspace.is_demo, workspace.provider
            try:
                workspace.import_bundle(bundle)
                return view()
            except Exception:
                workspace.repository, workspace.is_demo, workspace.provider = previous
                raise

        return await run_in_threadpool(locked, perform)

    @app.post("/api/reset")
    def reset() -> Any:
        def perform() -> dict[str, Any]:
            workspace.reset()
            return view()

        return locked(perform)

    @app.get("/api/template")
    def template() -> Response:
        return Response(
            demo_archive(),
            media_type="application/zip",
            headers={"Content-Disposition": 'attachment; filename="orcha-demo-csvs.zip"'},
        )

    @app.post("/api/assist")
    async def assist(request: Request) -> Any:
        payload = await read_payload(request, AssistantInput, 70_000)

        def perform() -> dict[str, Any]:
            configure_provider()
            if workspace.provider is None:
                raise HTTPException(503, "Add GEMMA_API_KEY to your local .env, then try again.")
            result = run_assistant(
                payload,
                workspace.repository,
                workspace.provider,
                router=router_from_environment(),
                include_timeline=True,
            )
            response = result.model_dump(mode="json")
            response["forecast_label"] = "With your updates · before this purchase"
            return response

        return await run_in_threadpool(locked, perform)

    app.mount("/static", StaticFiles(directory=STATIC, check_dir=False), name="static")
    return app
