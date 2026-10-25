"""Keep the public offline suite runnable without the optional original dataset."""

import os
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_local_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    # Tests supply explicit fake settings; never discover a developer's API keys.
    monkeypatch.setattr("orcha.environment.dotenv_values", lambda path: {})
    for key in list(os.environ):
        if key.startswith(("GEMMA_", "LAYA_")):
            monkeypatch.delenv(key)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    available = any(
        (path / "financial_events.csv").is_file() for path in [Path("dataset"), Path("../dataset")]
    )
    if not available:
        marker = pytest.mark.skip(reason="Optional original dataset is not installed")
        for item in items:
            if item.get_closest_marker("private_data") or "dataset_dir" in getattr(
                item, "fixturenames", []
            ):
                item.add_marker(marker)
