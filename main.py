"""Primary entry point for the Orcha financial assistant."""

import sys
from pathlib import Path

# Ensure src/ is on sys.path when running main.py directly
src_dir = Path(__file__).resolve().parent / "src"
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from orcha.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
