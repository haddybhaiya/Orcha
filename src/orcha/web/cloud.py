"""Public synthetic demo entry point; no accounts or durable user storage."""

import os

from fastapi import FastAPI

from orcha.environment import settings
from orcha.web.app import create_app


def create_cloud_app() -> FastAPI:
    origin = settings().get("ORCHA_PUBLIC_ORIGIN")
    if not origin:
        raise ValueError("Set ORCHA_PUBLIC_ORIGIN before serving the public demo")
    return create_app(public_origin=origin)


def main() -> None:
    import uvicorn

    uvicorn.run(
        create_cloud_app(),
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8080")),
        access_log=False,
        proxy_headers=False,
    )


if __name__ == "__main__":
    main()
