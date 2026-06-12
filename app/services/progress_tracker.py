from __future__ import annotations

import time
from threading import Lock
from typing import Any


class ProgressStore:
    def __init__(self, max_age_seconds: float = 3600) -> None:
        self.max_age_seconds = max_age_seconds
        self._jobs: dict[str, dict[str, Any]] = {}
        self._lock = Lock()

    def start(self, job_id: str, message: str = "Preparing files...") -> bool:
        now = time.monotonic()
        with self._lock:
            self._prune(now)
            if job_id in self._jobs:
                return False
            self._jobs[job_id] = {
                "status": "processing",
                "percent": 0.0,
                "message": message,
                "eta_seconds": None,
                "started_at": now,
                "updated_at": now,
            }
            return True

    def update(self, job_id: str, percent: float, message: str) -> None:
        now = time.monotonic()
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            normalized = max(float(job["percent"]), min(99.5, float(percent)))
            elapsed = max(0.0, now - float(job["started_at"]))
            eta_seconds = None
            if normalized > 0:
                eta_seconds = max(0, round(elapsed * (100 - normalized) / normalized))
            job.update(
                percent=round(normalized, 1),
                message=message,
                eta_seconds=eta_seconds,
                updated_at=now,
            )

    def finish(self, job_id: str, message: str = "Processing complete.") -> None:
        self._set_terminal(job_id, "completed", message)

    def fail(self, job_id: str, message: str) -> None:
        self._set_terminal(job_id, "failed", message)

    def get(self, job_id: str) -> dict[str, Any] | None:
        now = time.monotonic()
        with self._lock:
            self._prune(now)
            job = self._jobs.get(job_id)
            if job is None:
                return None
            return {
                key: value
                for key, value in job.items()
                if key not in {"started_at", "updated_at"}
            }

    def _set_terminal(self, job_id: str, status: str, message: str) -> None:
        now = time.monotonic()
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            job.update(
                status=status,
                percent=100.0,
                message=message,
                eta_seconds=0,
                updated_at=now,
            )

    def _prune(self, now: float) -> None:
        expired = [
            job_id
            for job_id, job in self._jobs.items()
            if now - float(job["updated_at"]) > self.max_age_seconds
        ]
        for job_id in expired:
            del self._jobs[job_id]
