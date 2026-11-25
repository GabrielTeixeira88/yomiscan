"""Entry point of the packaged local engine (Stage 5b): the Torch-free backend with per-user paths.

The frozen build (scripts/build_engine.py) runs this module. Unlike the developer server, it
never reads the working directory: models and the dictionary live in the per-user model folder
(%LOCALAPPDATA%/YomiScan/models), the processing cache and glossaries in %LOCALAPPDATA%/YomiScan.
Explicit YOMISCAN_* variables still win. Nothing is downloaded unless `--prepare` is given.

Modes:
- `yomiscan-engine [--port N] [--idle-exit SECONDS]`: serve on 127.0.0.1.
- `yomiscan-engine chrome-extension://<id>/ ...`: Chrome's native-messaging host (launcher.py).
- `yomiscan-engine --register --extension-id <id>` / `--unregister`: Chrome registration (HKCU).
- `yomiscan-engine --prepare [--component ...] [--progress FILE]`: download and verify the models.
- `yomiscan-engine --stop`: end the engine the launcher started (the uninstaller uses it).

The bundle has two executables: `yomiscan-engine.exe` (console, for these commands) and the
windowless `yomiscan-engine-host.exe`, which Chrome starts and which runs the detached engine, so
no console window ever appears.
"""

import argparse
import io
from importlib.metadata import version
import os
from pathlib import Path
import sys
import threading
import time
from typing import Any, Callable

from .cli import DEFAULT_PORT

ENGINE_DEFAULTS = {"YOMISCAN_DETECTOR": "pinned", "YOMISCAN_OCR": "pinned", "YOMISCAN_TRANSLATION_ENGINE": "opus-pinned",
                   "YOMISCAN_PREPARE_COMMAND": "yomiscan-engine --prepare"}


def engine_environment(environment: dict[str, str]) -> dict[str, str]:
    """The variables the packaged engine sets when they are absent."""
    from .engine_models import data_root, load_bundle, models_root
    root = data_root(environment)
    defaults = {**ENGINE_DEFAULTS,
                "YOMISCAN_DICTIONARY": str(models_root(environment) / load_bundle().name / "dictionary" / "jmdict.sqlite3"),
                "YOMISCAN_CACHE_DIRECTORY": str(root / "cache" / "processing"),
                "YOMISCAN_GLOSSARY_DATABASE": str(root / "glossaries.sqlite3")}
    return {key: value for key, value in defaults.items() if not environment.get(key)}


class ActivityTracker:
    """ASGI wrapper recording requests in flight and when the last one finished."""

    def __init__(self, app: Any, clock: Callable[[], float] = time.monotonic) -> None:
        self.app, self.clock = app, clock
        self.active, self.last = 0, clock()

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        self.active += 1
        try:
            await self.app(scope, receive, send)
        finally:
            self.active -= 1
            self.last = self.clock()

    def idle_for(self) -> float:
        return 0.0 if self.active else self.clock() - self.last


def watch_idle(tracker: ActivityTracker, server: Any, limit: float, poll: float = 5.0,
               sleep: Callable[[float], None] = time.sleep) -> None:
    """Ask the server to exit once no request has run for `limit` seconds."""
    while not server.should_exit:
        if tracker.idle_for() >= limit:
            print(f"YomiScan engine: idle for {limit:.0f} s, shutting down", flush=True)
            server.should_exit = True
            return
        sleep(poll)


def serve(port: int, idle_exit: float) -> None:
    import uvicorn
    from .api.main import app
    tracker = ActivityTracker(app)
    server = uvicorn.Server(uvicorn.Config(tracker, host="127.0.0.1", port=port))
    if idle_exit > 0:
        threading.Thread(target=watch_idle, args=(tracker, server, idle_exit), daemon=True, name="idle-exit").start()
    server.run()
    if not server.started:
        raise SystemExit(f"Could not serve on 127.0.0.1:{port}")


def attach_std_streams() -> None:
    """A windowless (GUI) process may start without sys.std* even when Windows passed it handles:
    Chrome's pipes for the native host, the log file for the detached engine. Attach those."""
    if os.name != "nt" or all(stream is not None for stream in (sys.stdin, sys.stdout, sys.stderr)):
        return
    import ctypes
    import msvcrt
    kernel32 = ctypes.windll.kernel32
    kernel32.GetStdHandle.restype = ctypes.c_void_p
    for name, handle_id, mode in (("stdin", -10, "rb"), ("stdout", -11, "wb"), ("stderr", -12, "wb")):
        if getattr(sys, name) is not None:
            continue
        handle = kernel32.GetStdHandle(handle_id)
        if handle in (None, 0, ctypes.c_void_p(-1).value):
            continue
        try:
            raw = os.fdopen(msvcrt.open_osfhandle(handle, os.O_BINARY | (os.O_RDONLY if mode == "rb" else 0)), mode, buffering=0)
        except OSError:
            continue  # not a usable handle: the stream stays absent, as before
        buffered = io.BufferedReader(raw) if mode == "rb" else io.BufferedWriter(raw)
        setattr(sys, name, io.TextIOWrapper(buffered, encoding="utf-8", errors="replace", line_buffering=True))


def native_host() -> int:
    from .engine_models import data_root
    from .launcher import IDLE_SECONDS, Launcher, host_main
    os.environ.update(engine_environment(dict(os.environ)))
    # YOMISCAN_IDLE_SECONDS shortens the idle exit for tests; Chrome passes its own environment on.
    idle = int(os.environ.get("YOMISCAN_IDLE_SECONDS", IDLE_SECONDS))
    launcher = Launcher(data_root(), version("yomiscan"), idle_seconds=idle)
    return host_main(sys.stdin.buffer, sys.stdout.buffer, launcher, dict(os.environ))


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    attach_std_streams()
    if any(argument.startswith("chrome-extension://") for argument in argv):
        return native_host()  # Chrome passes the caller's origin (and --parent-window on Windows)
    parser = argparse.ArgumentParser(prog="yomiscan-engine", description="YomiScan local engine (Torch-free), on 127.0.0.1")
    parser.add_argument("--version", action="version", version=version("yomiscan"))
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"Loopback port (default {DEFAULT_PORT})")
    parser.add_argument("--device", choices=("auto", "cpu"), default=os.getenv("YOMISCAN_DEVICE", "auto"),
                        help="auto uses a DirectML GPU for detection when available; cpu forces the CPU")
    parser.add_argument("--idle-exit", type=float, default=0, metavar="SECONDS",
                        help="Exit after this many seconds without requests (the launcher uses 900; 0 never)")
    parser.add_argument("--prepare", action="store_true",
                        help="Download and verify the default models and dictionary (explicit; nothing downloads otherwise)")
    parser.add_argument("--component", choices=("ocr", "detection", "translation", "dictionary", "all"), default="all",
                        help="With --prepare: only this part")
    parser.add_argument("--progress", type=Path, help="With --prepare: write progress as JSON to this file")
    parser.add_argument("--stop", action="store_true", help="End the engine the launcher started, if it runs")
    parser.add_argument("--register", action="store_true", help="Register this engine as Chrome's native-messaging host")
    parser.add_argument("--unregister", action="store_true", help="Remove the Chrome registration")
    parser.add_argument("--extension-id", action="append", default=[], help="With --register: an allowed extension (repeatable)")
    parser.add_argument("--extension-path", type=Path, action="append", default=[],
                        help="With --register: an unpacked extension folder; its ID is computed as Chrome does")
    arguments = parser.parse_args(argv)
    if not 1024 <= arguments.port <= 65535:
        parser.error("Port must be between 1024 and 65535")
    os.environ.update(engine_environment(dict(os.environ)))
    if arguments.register or arguments.unregister:
        from .engine_models import data_root
        from .launcher import engine_command, extension_id_for_path, register, unregister
        folder = data_root() / "native-host"
        if arguments.unregister:
            unregister(folder)
            print("Removed the YomiScan native-messaging registration")
            return 0
        if not getattr(sys, "frozen", False):
            parser.error("--register needs the packaged engine (scripts/build_engine.py); Chrome cannot start a Python module")
        ids = [*arguments.extension_id, *(extension_id_for_path(path) for path in arguments.extension_path)]
        path = register(Path(engine_command()[0]), ids, folder)
        print(f"Registered {path} for extension(s) {', '.join(sorted(set(ids)))}")
        return 0
    if arguments.stop:
        from .engine_models import data_root
        from .launcher import Launcher
        print("Stopped the YomiScan engine" if Launcher(data_root(), version("yomiscan")).stop() else "No YomiScan engine was running")
        return 0
    if arguments.prepare:
        from .cli import prepare_defaults
        return prepare_defaults(["--component", arguments.component,
                                 *(["--progress", str(arguments.progress)] if arguments.progress else [])])
    os.environ["YOMISCAN_DEVICE"] = arguments.device
    serve(arguments.port, arguments.idle_exit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
