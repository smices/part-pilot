"""Small local job registry for long-running CAD work."""

from __future__ import annotations

import hashlib
import json
import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class LocalJob:
    job_id: str
    fingerprint: str
    status: str = "queued"
    result: dict[str, Any] | None = None
    error: str | None = None
    future: Future | None = field(default=None, repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {"job_id": self.job_id, "status": self.status, "result": self.result, "error": self.error}


class LocalJobManager:
    """Serialize CAD jobs and make queued cancellation/deduplication explicit."""

    def __init__(self) -> None:
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="partpilot")
        self._jobs: dict[str, LocalJob] = {}
        self._lock = threading.Lock()

    @staticmethod
    def fingerprint(payload: dict[str, Any]) -> str:
        return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    def submit(self, payload: dict[str, Any], work: Callable[[], dict[str, Any]]) -> LocalJob:
        fingerprint = self.fingerprint(payload)
        with self._lock:
            for job in self._jobs.values():
                if job.fingerprint == fingerprint and job.status in {"queued", "running", "cancel_requested"}:
                    return job
            job = LocalJob(uuid.uuid4().hex, fingerprint)
            self._jobs[job.job_id] = job
            job.future = self._executor.submit(self._run, job, work)
            return job

    def _run(self, job: LocalJob, work: Callable[[], dict[str, Any]]) -> None:
        with self._lock:
            if job.status == "cancelled":
                return
            job.status = "running"
        try:
            result = work()
        except Exception as exc:
            with self._lock:
                job.status = "failed"
                job.error = f"{type(exc).__name__}: {exc}"
        else:
            with self._lock:
                if job.status == "cancel_requested":
                    job.status = "cancelled"
                else:
                    job.status = "succeeded"
                    job.result = result

    def get(self, job_id: str) -> LocalJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def cancel(self, job_id: str) -> LocalJob | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.status in {"succeeded", "failed", "cancelled"}:
                return job
            if job.future and job.future.cancel():
                job.status = "cancelled"
            else:
                job.status = "cancel_requested"
            return job
