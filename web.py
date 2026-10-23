"""Launch the local Orcha interface directly from a source checkout."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from orcha.web.__main__ import main  # noqa: E402

if __name__ == "__main__":
    main()
