"""Read current local settings without mutating process environment variables."""

import os
from pathlib import Path

from dotenv import dotenv_values


def settings() -> dict[str, str]:
    """Explicit process settings win; edits to .env apply on the next request."""
    local = {
        key: value for key, value in dotenv_values(Path.cwd() / ".env").items() if value is not None
    }
    return {**local, **os.environ}
