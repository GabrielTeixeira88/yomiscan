"""Run the frozen local engine (Stage 5b increment 3) and check it end to end.

    uv run python scripts/validate_engine_build.py                         # no models: setup is reported
    uv run --extra benchmark python scripts/validate_engine_build.py --models <folder> --page samples/vision/008.jpg

Without --models, the engine starts with an empty per-user folder and must answer readiness with
the missing default models and their `yomiscan-engine --prepare` command. With --models (a
YOMISCAN_ENGINE_MODELS folder holding the default components and the dictionary), it must become
ready, analyze text and, with --page, a page; startup time, request times and the process's
memory (psutil, from the `benchmark` extra) are reported. Prints a JSON report; exits non-zero
on any failed check.
"""

import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
from time import monotonic, sleep
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
EXE = ROOT / ".cache" / "engine-build" / "dist" / "yomiscan-engine" / ("yomiscan-engine.exe" if os.name == "nt" else "yomiscan-engine")
HEADER = {"X-YomiScan-Client": "study-extension-v1"}


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def call(port: int, path: str, data: bytes | None = None, content_type: str | None = None, timeout: float = 120) -> tuple[int, dict]:
    headers = {**HEADER, **({"Content-Type": content_type} if content_type else {})}
    try:
        with urlopen(Request(f"http://127.0.0.1:{port}{path}", data=data, headers=headers), timeout=timeout) as response:
            return response.status, json.loads(response.read() or b"{}")
    except HTTPError as error:
        return error.code, json.loads(error.read() or b"{}")


def wait(port: int, ready, timeout: float) -> float:
    start = monotonic()
    while monotonic() - start < timeout:
        try:
            if ready(call(port, "/api/v1/readiness", timeout=5)[1]):
                return monotonic() - start
        except (URLError, ConnectionError, TimeoutError):
            pass
        sleep(.2)
    raise TimeoutError(f"The engine did not reach the expected state within {timeout:.0f} s")


def multipart(path: Path) -> tuple[bytes, str]:
    boundary = "yomiscan-validate"
    head = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
            f'Content-Type: {"image/png" if path.suffix == ".png" else "image/jpeg"}\r\n\r\n').encode()
    return head + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode(), f"multipart/form-data; boundary={boundary}"


def memory_mib(pid: int) -> dict[str, int] | None:
    """Private bytes and working set of the engine process (Windows names; rss elsewhere)."""
    try:
        import psutil
    except ImportError:
        return None
    info = psutil.Process(pid).memory_info()
    return {"private": round(getattr(info, "private", info.rss) / 2**20), "working_set": round(info.rss / 2**20),
            "peak_working_set": round(getattr(info, "peak_wset", info.rss) / 2**20)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--exe", type=Path, default=EXE)
    parser.add_argument("--models", type=Path, help="YOMISCAN_ENGINE_MODELS folder with the default components")
    parser.add_argument("--page", type=Path, help="A page image to analyze (needs --models)")
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--device", choices=("auto", "cpu"), default="auto", help="Passed to the engine")
    arguments = parser.parse_args(argv)
    report: dict[str, object] = {"exe": str(arguments.exe), "device": arguments.device}
    version = subprocess.run([str(arguments.exe), "--version"], capture_output=True, text=True, check=True)
    report["version"] = version.stdout.strip()
    with tempfile.TemporaryDirectory() as data:
        environment = {key: value for key, value in os.environ.items() if not key.startswith("YOMISCAN_")}
        environment["LOCALAPPDATA"] = data  # a fresh per-user folder: cache, glossaries, (no) models
        if arguments.models:
            environment["YOMISCAN_ENGINE_MODELS"] = str(arguments.models.resolve())
        port = free_port()
        log = Path(data) / "engine.log"
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        with log.open("wb") as output:
            started = monotonic()
            process = subprocess.Popen([str(arguments.exe), "--port", str(port), "--device", arguments.device], env=environment, stdout=output,
                                       stderr=subprocess.STDOUT, creationflags=flags)
            try:
                if not arguments.models:
                    wait(port, lambda r: r["initialization"] == "failed", arguments.timeout)
                    readiness = call(port, "/api/v1/readiness")[1]
                    defaults = {m["id"]: m for m in readiness["models"] if m["selected"]}
                    assert set(defaults) == {"detector-pinned", "ocr-pinned", "opus-pinned"}, defaults.keys()
                    assert not any(m["installed"] for m in defaults.values())
                    assert all(m["setup_command"].startswith("yomiscan-engine --prepare") for m in defaults.values())
                    assert readiness["dictionary"]["setup_command"] == "yomiscan-engine --prepare --component dictionary"
                    report["missing_models"] = {"failure_code": readiness["failure_code"],
                                                "setup": sorted(m["setup_command"] for m in defaults.values())}
                    report["readiness_s"] = round(monotonic() - started, 2)
                else:
                    report["ready_s"] = round(wait(port, lambda r: r["initialization"] in ("ready", "failed"), arguments.timeout), 2)
                    readiness = call(port, "/api/v1/readiness")[1]
                    assert readiness["initialization"] == "ready", (readiness["failure_code"], log.read_text(errors="replace")[-2000:])
                    assert call(port, "/health")[0] == 200
                    report["memory_ready_mib"] = memory_mib(process.pid)
                    start = monotonic()
                    status, text = call(port, "/api/v1/analyze-text", json.dumps({"text": "猫が好きです"}).encode(), "application/json")
                    assert status == 200 and text["translation"] and text["tokens"], (status, text)
                    report["analyze_text_ms"] = round((monotonic() - start) * 1000)
                    if arguments.page:
                        body, content_type = multipart(arguments.page)
                        start = monotonic()
                        status, page = call(port, "/api/v1/analyze-page", body, content_type, timeout=300)
                        assert status == 200 and page["text_blocks"], (status, str(page)[:500])
                        report["analyze_page_ms"] = round((monotonic() - start) * 1000)
                        report["page_blocks"] = len(page["text_blocks"])
                        report["translated_blocks"] = sum(bool(b["translation"]) for b in page["text_blocks"])
                        report["memory_after_page_mib"] = memory_mib(process.pid)
            except AssertionError:
                process.terminate()
                process.wait(timeout=30)
                for line in log.read_text(encoding="utf-8", errors="replace").splitlines()[-40:]:
                    print(line, file=sys.stderr)
                raise
            finally:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=30)
        report["log_tail"] = log.read_text(encoding="utf-8", errors="replace").splitlines()[-3:]
    print(json.dumps(report, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
