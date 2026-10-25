"""Run a single-user, loopback-only Orcha workspace."""

import argparse
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Open Orcha's local financial workspace")
    parser.add_argument("--dataset", type=Path, default=None)
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("Choose a port between 1024 and 65535")
    try:
        import uvicorn

        from orcha.web.app import create_app
        from orcha.web.workspace import DEMO_DIR
    except ImportError:
        parser.exit(1, 'Install web dependencies first: python -m pip install -e ".[web]"\n')
    try:
        app = create_app(args.dataset or DEMO_DIR)
    except (OSError, ValueError, KeyError):
        parser.exit(1, "Could not load the dataset. Check the CSV files and --dataset path.\n")
    print(f"Orcha is ready at http://127.0.0.1:{args.port}")
    uvicorn.run(app, host="127.0.0.1", port=args.port, access_log=False)


if __name__ == "__main__":
    main()
