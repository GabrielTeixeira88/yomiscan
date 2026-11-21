"""Bounded text-free job observations; one existing worker still performs inference."""

from collections import OrderedDict
from copy import deepcopy
from threading import RLock
from time import monotonic, perf_counter
from typing import Callable
from uuid import uuid4

Progress = Callable[[str, str, float | None], None]
STAGES = ("initializing", "detection", "ocr", "ordering", "lexical", "translation", "render", "finalizing")


class JobRegistry:
    def __init__(self, *, capacity: int = 16, retention_seconds: float = 30) -> None:
        self.instance = uuid4().hex
        self._jobs: OrderedDict[str, dict] = OrderedDict()
        self._lock = RLock()
        self.capacity, self.retention_seconds = capacity, retention_seconds

    def _expire(self) -> None:
        now = monotonic()
        for key in list(self._jobs):
            end = self._jobs[key].get("ended")
            if end is not None and now-end > self.retention_seconds:
                del self._jobs[key]

    def start(self, identifier: str) -> Progress:
        with self._lock:
            self._expire()
            if identifier in self._jobs:
                raise ValueError("Job identifier is already in use")
            while len(self._jobs) >= self.capacity:
                old = next((key for key, value in self._jobs.items() if value.get("ended") is not None), None)
                if old is None:
                    raise ValueError("Too many retained active jobs")
                del self._jobs[old]
            self._jobs[identifier] = {"instance": self.instance, "job_id": identifier, "version": 1,
                "state": "processing", "current": "processing", "stages": {}, "started": perf_counter()}
        return lambda stage, state, elapsed=None: self.update(identifier, stage, state, elapsed)

    def update(self, identifier: str, stage: str, state: str, elapsed: float | None = None) -> None:
        if stage not in STAGES or state not in ("running", "cached", "completed", "failed"):
            raise ValueError("Unknown processing observation")
        with self._lock:
            job = self._jobs.get(identifier)
            if job is None or job["state"] != "processing":
                return
            stages = job["stages"]
            previous = job["current"]
            if previous != stage and previous in stages and stages[previous]["state"] == "running":
                stages[previous]["state"] = "completed"
            entry = stages.setdefault(stage, {"state": "pending", "computed": False, "cache_hits": 0, "failures": 0})
            if state == "cached":
                entry["cache_hits"] += 1
                entry["state"] = "failed" if entry["failures"] else "completed" if entry["computed"] else "cached"
            else:
                if state == "failed": entry["failures"] += 1
                entry["state"] = "failed" if state == "completed" and entry["failures"] else state
                if state in ("running", "completed"):
                    entry["computed"] = True
            if elapsed is not None:
                entry["compute_ms"] = round(max(0, elapsed), 2)
            job["current"] = stage
            job["version"] += 1

    def finish(self, identifier: str, state: str) -> None:
        if state not in ("completed", "failed", "cancelled"):
            raise ValueError("Unknown terminal job state")
        with self._lock:
            job = self._jobs.get(identifier)
            if job is None:
                return
            for entry in job["stages"].values():
                if entry["state"] == "running":
                    entry["state"] = "failed" if entry["failures"] else state
            job.update(state=state, current=state, ended=monotonic(), elapsed_ms=round((perf_counter()-job["started"])*1000, 2))
            job["version"] += 1

    def snapshot(self, identifier: str) -> dict | None:
        with self._lock:
            self._expire()
            job = self._jobs.get(identifier)
            return deepcopy({k: v for k, v in job.items() if k not in ("started", "ended")}) if job else None
