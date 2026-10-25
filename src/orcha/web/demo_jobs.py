"""Small, expiring result mailbox for one-process public demonstrations."""

import secrets
import threading
import time
from collections import deque
from typing import Any

from fastapi import HTTPException


class DemoJobs:
    """One active forecast, 60 submissions/hour, at most 16 ten-minute results."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.active: str | None = None
        self.submissions: deque[float] = deque()
        self.results: dict[str, tuple[float, dict[str, Any]]] = {}

    def submit(self) -> str:
        with self.lock:
            now = time.monotonic()
            self.results = {
                key: value for key, value in self.results.items() if now - value[0] < 600
            }
            while self.submissions and now - self.submissions[0] >= 3600:
                self.submissions.popleft()
            if self.active:
                raise HTTPException(409, "The demo is checking another request. Try again shortly.")
            if len(self.submissions) >= 60:
                raise HTTPException(
                    429,
                    "The public demo's hourly limit was reached. Try again later.",
                    headers={"Retry-After": str(max(1, int(3600 - (now - self.submissions[0]))))},
                )
            while len(self.results) >= 16:
                del self.results[next(iter(self.results))]
            identifier = secrets.token_urlsafe(32)
            self.results[identifier] = (now, {"status": "pending"})
            self.active = identifier
            self.submissions.append(now)
            return identifier

    def finish(self, identifier: str, value: dict[str, Any]) -> None:
        with self.lock:
            self.results[identifier] = (time.monotonic(), value)
            self.active = None

    def get(self, identifier: str) -> dict[str, Any]:
        with self.lock:
            item = self.results.get(identifier)
            if item is None or time.monotonic() - item[0] >= 600:
                raise HTTPException(404, "This demo result expired. Run the planner again.")
            return item[1]
