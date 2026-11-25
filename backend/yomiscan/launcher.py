"""Native-messaging launcher for the packaged local engine (Stage 5b increment 4).

Chrome starts `yomiscan-engine.exe chrome-extension://<id>/` as a native-messaging host for each
`chrome.runtime.sendNativeMessage` call. The host reads one message, answers it and exits:

- `status`: version, whether the default models and dictionary are installed, and whether an
  engine is running.
- `start`: reuse the running engine, or start one detached on a free loopback port with a fresh
  per-launch token (passed through the environment, never the command line). Answers
  `{port, token}` once the engine serves readiness. The engine exits by itself after an idle
  period; the next `start` launches it again.
- `stop`: end the running engine.

The engine's port, token and process id are kept in `engine-state.json` in the per-user data
folder; only this user can read it. Registration writes the host manifest and one HKCU key, so
no administrator rights are needed.
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import secrets
import socket
import struct
import subprocess
import sys
import time
from typing import Any, BinaryIO
from urllib.error import URLError
from urllib.request import Request, urlopen

HOST_NAME = "com.yomiscan.engine"
REGISTRY_KEY = r"Software\Google\Chrome\NativeMessagingHosts" + "\\" + HOST_NAME
IDLE_SECONDS = 15 * 60
MAX_MESSAGE = 64 * 1024
READY_TIMEOUT = 45.0


# ---- native messaging framing ------------------------------------------------------------------

def read_message(stream: BinaryIO) -> dict[str, Any] | None:
    """One message: 4-byte native-order length, then UTF-8 JSON. None at end of input."""
    header = stream.read(4)
    if not header:
        return None
    if len(header) != 4:
        raise ValueError("Truncated native message header")
    (length,) = struct.unpack("=I", header)
    if length > MAX_MESSAGE:
        raise ValueError(f"Native message of {length} bytes exceeds {MAX_MESSAGE}")
    body = stream.read(length)
    if len(body) != length:
        raise ValueError("Truncated native message")
    message = json.loads(body.decode("utf-8"))
    if not isinstance(message, dict):
        raise ValueError("A native message must be a JSON object")
    return message


def write_message(stream: BinaryIO, message: dict[str, Any]) -> None:
    body = json.dumps(message, separators=(",", ":")).encode("utf-8")
    stream.write(struct.pack("=I", len(body)) + body)
    stream.flush()


# ---- Chrome registration ---------------------------------------------------------------------

def extension_id_for_path(path: Path) -> str:
    """The ID Chrome gives an unpacked extension without a manifest key (crx_file::id_util).

    SHA-256 of the absolute path (UTF-16-LE on Windows, drive letter upper-cased), first 16
    bytes in hex, each digit 0-f mapped to a-p.
    """
    value = str(path.resolve())
    if os.name == "nt":
        if len(value) > 1 and value[1] == ":":
            value = value[0].upper() + value[1:]
        data = value.encode("utf-16-le")
    else:
        data = value.encode("utf-8")
    return "".join(chr(ord("a") + int(digit, 16)) for digit in hashlib.sha256(data).hexdigest()[:32])


def host_manifest(executable: Path, extension_ids: Iterable[str]) -> dict[str, Any]:
    ids = sorted(set(extension_ids))
    if not ids or any(len(i) != 32 or not set(i) <= set("abcdefghijklmnop") for i in ids):
        raise ValueError("Give at least one Chrome extension ID (32 letters a-p)")
    return {"name": HOST_NAME, "description": "YomiScan local engine", "path": str(executable),
            "type": "stdio", "allowed_origins": [f"chrome-extension://{i}/" for i in ids]}


def register(executable: Path, extension_ids: Iterable[str], folder: Path, registry: Any = None) -> Path:
    """Write the host manifest into `folder` and point Chrome's HKCU key at it."""
    manifest = host_manifest(executable, extension_ids)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{HOST_NAME}.json"
    path.write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
    registry = registry or _winreg()
    try:
        with registry.CreateKey(registry.HKEY_CURRENT_USER, REGISTRY_KEY) as key:
            registry.SetValueEx(key, "", 0, registry.REG_SZ, str(path))
    except OSError as error:
        raise RuntimeError(f"Could not register the native-messaging host in HKCU\\{REGISTRY_KEY}") from error
    return path


def unregister(folder: Path, registry: Any = None) -> None:
    registry = registry or _winreg()
    try:
        registry.DeleteKey(registry.HKEY_CURRENT_USER, REGISTRY_KEY)
    except FileNotFoundError:
        pass
    (folder / f"{HOST_NAME}.json").unlink(missing_ok=True)


def _winreg() -> Any:
    if os.name != "nt":
        raise RuntimeError("Native-messaging registration is implemented for Windows only")
    import winreg
    return winreg


# ---- engine lifecycle ------------------------------------------------------------------------

@dataclass(frozen=True)
class EngineState:
    pid: int
    port: int
    token: str
    version: str


def engine_command() -> list[str]:
    """The packaged executable, or this Python running the engine module during development."""
    if getattr(sys, "frozen", False):
        return [sys.executable]
    return [sys.executable, "-m", "yomiscan.engine_main"]


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def serving(port: int, token: str, timeout: float = 2.0) -> bool:
    """The engine answers readiness with this token (any initialization state)."""
    request = Request(f"http://127.0.0.1:{port}/api/v1/readiness",
                      headers={"X-YomiScan-Client": "study-extension-v1", "X-YomiScan-Token": token})
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.status == 200
    except (URLError, OSError, ValueError):
        return False


class Launcher:
    """Start, reuse and stop the detached engine. Dependencies are injectable for tests."""

    def __init__(self, data: Path, version: str, *, spawn: Callable[..., Any] | None = None,
                 probe: Callable[[int, str], bool] = serving, port: Callable[[], int] = free_port,
                 clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep,
                 idle_seconds: int = IDLE_SECONDS) -> None:
        self.data, self.version = data, version
        self.spawn = spawn or self._spawn
        self.probe, self.port, self.clock, self.sleep, self.idle_seconds = probe, port, clock, sleep, idle_seconds
        self.state_path, self.lock_path = data / "engine-state.json", data / "engine-start.lock"

    def state(self) -> EngineState | None:
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
            return EngineState(int(raw["pid"]), int(raw["port"]), str(raw["token"]), str(raw["version"]))
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def running(self) -> EngineState | None:
        state = self.state()
        return state if state is not None and state.version == self.version and self.probe(state.port, state.token) else None

    def start(self) -> EngineState:
        with self._lock():
            if (state := self.running()) is not None:
                return state
            for _ in range(3):  # a port taken between choosing and binding: try another
                port, token = self.port(), secrets.token_urlsafe(32)
                process = self.spawn(port, token)
                deadline = self.clock() + READY_TIMEOUT
                while self.clock() < deadline and process.poll() is None:
                    if self.probe(port, token):
                        state = EngineState(process.pid, port, token, self.version)
                        self.data.mkdir(parents=True, exist_ok=True)
                        self.state_path.write_text(json.dumps(state.__dict__), encoding="utf-8")
                        return state
                    self.sleep(.25)
                if process.poll() is None:
                    process.kill()
                    raise TimeoutError(f"The engine did not answer within {READY_TIMEOUT:.0f} s; see {self.log_path()}")
            raise RuntimeError(f"The engine exited during startup; see {self.log_path()}")

    def stop(self) -> bool:
        state = self.state()
        self.state_path.unlink(missing_ok=True)
        if state is None or not self.probe(state.port, state.token):
            return False
        os.kill(state.pid, 15)  # TerminateProcess on Windows
        return True

    def log_path(self) -> Path:
        return self.data / "logs" / "engine.log"

    def _spawn(self, port: int, token: str) -> subprocess.Popen:
        self.log_path().parent.mkdir(parents=True, exist_ok=True)
        environment = {**os.environ, "YOMISCAN_TOKEN": token}
        command = [*engine_command(), "--port", str(port), "--idle-exit", str(self.idle_seconds)]
        with self.log_path().open("ab") as log:
            if os.name != "nt":
                return subprocess.Popen(command, env=environment, stdin=subprocess.DEVNULL, stdout=log,
                                        stderr=subprocess.STDOUT, start_new_session=True)
            detached = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
            try:
                # Chrome runs native hosts in a job object; leave it so the engine outlives the host.
                return subprocess.Popen(command, env=environment, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                        creationflags=detached | subprocess.CREATE_BREAKAWAY_FROM_JOB)
            except PermissionError:
                return subprocess.Popen(command, env=environment, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                        creationflags=detached)

    def _lock(self):
        launcher = self

        class Lock:
            def __enter__(self):
                launcher.data.mkdir(parents=True, exist_ok=True)
                deadline = launcher.clock() + READY_TIMEOUT + 15
                while True:
                    try:
                        os.close(os.open(launcher.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
                        return self
                    except FileExistsError:
                        try:  # a host that crashed while starting leaves a stale lock
                            if time.time() - launcher.lock_path.stat().st_mtime > READY_TIMEOUT + 15:
                                launcher.lock_path.unlink(missing_ok=True)
                                continue
                        except FileNotFoundError:
                            continue
                        if launcher.clock() > deadline:
                            raise TimeoutError("Another YomiScan launch is still in progress") from None
                        launcher.sleep(.25)

            def __exit__(self, *_):
                launcher.lock_path.unlink(missing_ok=True)
        return Lock()


# ---- host ------------------------------------------------------------------------------------

def models_status(environment: dict[str, str]) -> dict[str, Any]:
    from .engine_models import installed_files
    from .readiness import ENGINE_DEFAULTS
    missing = [component for _, _, component in ENGINE_DEFAULTS if not installed_files(component, environment)[1]]
    dictionary = Path(environment["YOMISCAN_DICTIONARY"])
    if not dictionary.is_file():
        missing.append("dictionary")
    return {"ready": not missing, "missing": missing}


def handle(message: dict[str, Any], launcher: Launcher, environment: dict[str, str]) -> dict[str, Any]:
    kind = message.get("type")
    if kind == "status":
        running = launcher.running()
        return {"ok": True, "version": launcher.version, "models": models_status(environment), "running": running is not None}
    if kind == "start":
        state = launcher.start()
        return {"ok": True, "version": launcher.version, "port": state.port, "token": state.token}
    if kind == "stop":
        return {"ok": True, "stopped": launcher.stop()}
    return {"ok": False, "error": f"Unknown request {kind!r}"}


def host_main(stdin: BinaryIO, stdout: BinaryIO, launcher: Launcher, environment: dict[str, str]) -> int:
    """Answer one message from Chrome; errors become {"ok": false} replies, never a silent exit."""
    try:
        message = read_message(stdin)
        if message is None:
            return 0
        reply = handle(message, launcher, environment)
    except Exception as error:  # the extension shows this text; the log keeps nothing secret
        reply = {"ok": False, "error": f"{type(error).__name__}: {error}"}
    write_message(stdout, reply)
    return 0 if reply.get("ok") else 1
