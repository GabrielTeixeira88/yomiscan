"""Small optional measurement helpers. RSS sampling is explicitly a lower bound."""

from importlib.metadata import PackageNotFoundError, version
import os
import platform
from threading import Event, Thread
from typing import Any


def environment() -> dict[str, Any]:
    versions = {}
    for name in ("yomiscan", "torch", "transformers", "manga-ocr", "onnxruntime", "numpy", "Pillow", "psutil"):
        try:
            versions[name] = version(name)
        except PackageNotFoundError:
            versions[name] = None
    return {"python": platform.python_version(), "platform": platform.platform(), "processor": platform.processor(),
            "logical_cpus": os.cpu_count(), "versions": versions}


class MemoryMeasurement:
    def __init__(self) -> None:
        try:
            import psutil
        except ImportError:
            self.process = None
        else:
            self.process = psutil.Process()
        self.peak: int | None = None
        self.stop = Event()
        self.worker = Thread(target=self.sample, daemon=True)

    def sample(self) -> None:
        while not self.stop.wait(.01):
            if self.process is not None:
                self.peak = max(self.peak or 0, self.process.memory_info().rss)

    def start(self) -> None:
        self.worker.start()

    def snapshot(self) -> dict[str, Any]:
        info = self.process.memory_info() if self.process is not None else None
        return {"rss_bytes": info.rss if info is not None else None,
                "sampled_peak_rss_bytes": self.peak,
                "os_process_lifetime_peak_bytes": getattr(info, "peak_wset", None),
                "scope": "whole current process; sampled peak at 10 ms is a lower bound; OS peak is lifetime, not incremental model RAM"}

    def close(self) -> None:
        self.stop.set(); self.worker.join()
