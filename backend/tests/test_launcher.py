"""Stage 5b increment 4: native-messaging launcher, engine token and idle shutdown (no models)."""

from contextlib import contextmanager
import io
import json
import struct
from unittest.mock import MagicMock, Mock

from fastapi.testclient import TestClient
import pytest

from yomiscan.api.main import create_app
from yomiscan.engine_main import ActivityTracker, main as engine_main, watch_idle
from yomiscan import launcher as launcher_module
from yomiscan.launcher import (HOST_NAME, Launcher, extension_id_for_path, handle, host_main, host_manifest, read_message,
                               register, unregister, write_message)

ID = "a" * 32


def framed(message) -> io.BytesIO:
    body = json.dumps(message).encode()
    return io.BytesIO(struct.pack("=I", len(body)) + body)


def test_framing_round_trip_and_limits():
    out = io.BytesIO()
    write_message(out, {"ok": True, "port": 50001})
    assert read_message(io.BytesIO(out.getvalue())) == {"ok": True, "port": 50001}
    assert read_message(io.BytesIO(b"")) is None
    with pytest.raises(ValueError, match="exceeds"):
        read_message(io.BytesIO(struct.pack("=I", 10**6)))
    with pytest.raises(ValueError, match="Truncated"):
        read_message(io.BytesIO(struct.pack("=I", 10) + b"{}"))
    with pytest.raises(ValueError, match="JSON object"):
        read_message(framed([1, 2]))


def test_extension_id_is_chrome_shaped_and_stable(tmp_path):
    first = extension_id_for_path(tmp_path / "dist")
    assert first == extension_id_for_path(tmp_path / "dist") and len(first) == 32 and set(first) <= set("abcdefghijklmnop")
    assert first != extension_id_for_path(tmp_path / "other")


def test_registration_writes_manifest_and_hkcu_key(tmp_path):
    registry = MagicMock(HKEY_CURRENT_USER="HKCU", REG_SZ=1)
    key = registry.CreateKey.return_value.__enter__.return_value
    path = register(tmp_path / "yomiscan-engine.exe", [ID, ID], tmp_path / "host", registry)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    assert manifest == {"name": HOST_NAME, "description": "YomiScan local engine", "path": str(tmp_path / "yomiscan-engine.exe"),
                        "type": "stdio", "allowed_origins": [f"chrome-extension://{ID}/"]}
    registry.CreateKey.assert_called_once_with("HKCU", r"Software\Google\Chrome\NativeMessagingHosts\com.yomiscan.engine")
    registry.SetValueEx.assert_called_once_with(key, "", 0, 1, str(path))
    registry.DeleteKey.side_effect = FileNotFoundError
    unregister(tmp_path / "host", registry)
    assert not path.exists()
    with pytest.raises(ValueError):
        host_manifest(tmp_path / "x.exe", ["not-an-id"])


class FakeProcess:
    def __init__(self, pid, exits=False):
        self.pid, self.exits, self.killed = pid, exits, False

    def poll(self):
        return 1 if self.exits or self.killed else None

    def kill(self):
        self.killed = True


def make_launcher(tmp_path, serving, processes, ports=(50001, 50002, 50003)):
    clock = {"now": 0.0}
    spawned = []

    def spawn(port, token):
        spawned.append((port, token))
        return processes.pop(0)

    def sleep(seconds):
        clock["now"] += seconds
    ports = list(ports)
    launcher = Launcher(tmp_path, "0.1.0", spawn=spawn, probe=lambda port, token: (port, token) in serving,
                        port=lambda: ports.pop(0), clock=lambda: clock["now"], sleep=sleep)
    return launcher, spawned


def test_start_spawns_once_then_reuses_the_running_engine(tmp_path):
    serving = set()
    launcher, spawned = make_launcher(tmp_path, serving, [FakeProcess(11)])
    original = launcher.spawn

    def spawn(port, token):
        process = original(port, token)
        serving.add((port, token))  # becomes ready
        return process
    launcher.spawn = spawn
    state = launcher.start()
    assert (state.pid, state.port) == (11, 50001) and len(state.token) >= 40
    assert launcher.start() == state and len(spawned) == 1  # reused through engine-state.json
    assert not (tmp_path / "engine-start.lock").exists()
    serving.clear()  # the engine exited (idle): the next start launches a new one
    launcher.spawn = lambda port, token: (serving.add((port, token)), FakeProcess(12))[1]
    assert launcher.start().pid == 12


def test_start_retries_when_the_engine_exits_and_reports_timeouts(tmp_path):
    launcher, spawned = make_launcher(tmp_path, set(), [FakeProcess(1, exits=True)] * 3)
    with pytest.raises(RuntimeError, match="exited during startup"):
        launcher.start()
    assert [port for port, _ in spawned] == [50001, 50002, 50003]
    hanging = FakeProcess(2)
    launcher, _ = make_launcher(tmp_path, set(), [hanging])
    with pytest.raises(TimeoutError, match="did not answer"):
        launcher.start()
    assert hanging.killed


def test_handle_and_host_main_answer_one_message(tmp_path, monkeypatch):
    serving = set()
    launcher, _ = make_launcher(tmp_path, serving, [FakeProcess(5)])
    original = launcher.spawn
    launcher.spawn = lambda port, token: (serving.add((port, token)), original(port, token))[1]
    environment = {"YOMISCAN_ENGINE_MODELS": str(tmp_path / "models"), "YOMISCAN_DICTIONARY": str(tmp_path / "none.sqlite3")}
    status = handle({"type": "status"}, launcher, environment)
    assert status["ok"] and not status["running"] and not status["models"]["ready"]
    assert set(status["models"]["missing"]) == {"detector-fp32", "ocr-int8", "translation-opus-ja-en-fp32", "dictionary"}
    out = io.BytesIO()
    assert host_main(framed({"type": "start"}), out, launcher, environment) == 0
    reply = read_message(io.BytesIO(out.getvalue()))
    assert reply["ok"] and reply["port"] == 50001 and reply["token"]
    out = io.BytesIO()
    assert host_main(framed({"type": "nonsense"}), out, launcher, environment) == 1
    assert read_message(io.BytesIO(out.getvalue()))["ok"] is False
    monkeypatch.setattr(launcher, "start", Mock(side_effect=TimeoutError("slow")))
    out = io.BytesIO()
    host_main(framed({"type": "start"}), out, launcher, environment)
    assert read_message(io.BytesIO(out.getvalue())) == {"ok": False, "error": "TimeoutError: slow"}


def test_stop_ends_a_serving_engine(tmp_path, monkeypatch):
    killed = []
    monkeypatch.setattr(launcher_module.os, "kill", lambda pid, signal: killed.append(pid))
    launcher, _ = make_launcher(tmp_path, {(50001, "t")}, [])
    assert launcher.stop() is False
    (tmp_path / "engine-state.json").write_text(json.dumps({"pid": 9, "port": 50001, "token": "t", "version": "0.1.0"}))
    assert launcher.stop() is True and killed == [9] and not (tmp_path / "engine-state.json").exists()


def test_token_is_required_on_every_request_when_set():
    @contextmanager
    def fake():
        yield Mock()
    headers = {"X-YomiScan-Client": "study-extension-v1"}
    with TestClient(create_app(fake, token="s3cret"), base_url="http://127.0.0.1", headers=headers) as client:
        assert client.get("/health").status_code == 401
        assert client.get("/api/v1/readiness", headers={"X-YomiScan-Token": "wrong"}).status_code == 401
        assert client.get("/health", headers={"X-YomiScan-Token": "s3cret"}).status_code == 200
        preflight = client.options("/api/v1/analyze-text", headers={
            "Origin": "chrome-extension://" + ID, "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-yomiscan-client,x-yomiscan-token"})
        assert preflight.status_code == 200 and "x-yomiscan-token" in preflight.headers["access-control-allow-headers"].lower()
    with TestClient(create_app(fake), base_url="http://127.0.0.1", headers=headers) as client:
        assert client.get("/health").status_code == 200  # the developer server has no token


def test_idle_watchdog_ignores_requests_in_flight():
    clock = {"now": 0.0}
    tracker = ActivityTracker(app=None, clock=lambda: clock["now"])
    server = Mock(should_exit=False)
    tracker.active = 1  # a long page job is running
    clock["now"] = 10_000

    def sleep(_):
        clock["now"] += 100
        if tracker.active and clock["now"] > 10_500:  # the job finishes once
            tracker.active, tracker.last = 0, clock["now"]
    watch_idle(tracker, server, limit=900, poll=1, sleep=sleep)
    assert server.should_exit and tracker.idle_for() >= 900 and clock["now"] >= 10_600 + 900


def test_chrome_origin_argument_selects_the_native_host(monkeypatch):
    import yomiscan.engine_main as module
    monkeypatch.setattr(module, "native_host", lambda: 7)
    assert engine_main([f"chrome-extension://{ID}/", "--parent-window=0"]) == 7


def test_progress_file_is_atomic_throttled_and_reports_failure(tmp_path):
    from yomiscan.engine_models import PinnedFile, ProgressFile
    clock = {"now": 0.0}
    path = tmp_path / "progress.json"
    progress = ProgressFile(path, [PinnedFile("a", 100, "x"), PinnedFile("b", 50, "y")], clock=lambda: clock["now"])
    assert json.loads(path.read_text())["state"] == "running" and json.loads(path.read_text())["total"] == 150
    progress.update("a", 40)
    progress.update("a", 60)  # within half a second: not written
    assert json.loads(path.read_text())["loaded"] == 40
    clock["now"] = 1.0
    progress.update("b", 10)
    assert json.loads(path.read_text())["loaded"] == 70
    progress.fail(ValueError("bad hash"))
    assert json.loads(path.read_text()) | {"pid": 0} == {"pid": 0, "total": 150, "state": "failed", "loaded": 70,
                                                         "error": "ValueError: bad hash"}
    progress.finish()
    assert json.loads(path.read_text())["state"] == "done" and json.loads(path.read_text())["loaded"] == 150
    assert not (tmp_path / "progress.json.tmp").exists()


def test_prepare_starts_one_download_and_status_reports_it(tmp_path, monkeypatch):
    launched = []
    launcher, _ = make_launcher(tmp_path, set(), [])
    assert launcher.prepare(launch=lambda command: (launched.append(command), Mock(pid=31))[1]) == {"state": "starting", "pid": 31}
    assert launched[0][-3:] == ["--prepare", "--progress", str(tmp_path / "prepare-progress.json")]
    monkeypatch.setattr(launcher_module, "_alive", lambda pid: False)
    failed = launcher.progress()  # the download process died before writing progress
    assert failed["state"] == "failed" and "prepare.log" in failed["error"]
    (tmp_path / "prepare-progress.json").write_text(json.dumps({"state": "running", "pid": 4242, "loaded": 1, "total": 9}))
    monkeypatch.setattr(launcher_module, "_alive", lambda pid: pid == 4242)
    assert launcher.prepare(launch=launched.append)["pid"] == 4242 and len(launched) == 1  # not started twice
    environment = {"YOMISCAN_ENGINE_MODELS": str(tmp_path / "models"), "YOMISCAN_DICTIONARY": str(tmp_path / "none.sqlite3")}
    status = handle({"type": "status"}, launcher, environment)
    assert status["prepare"]["state"] == "running" and status["models"]["bytes"] > 700 * 2**20
    assert status["models"]["source"].startswith("huggingface.co/")
    monkeypatch.setattr(launcher_module, "_alive", lambda pid: False)  # a crashed download is started again
    assert handle({"type": "prepare"}, launcher, environment)["ok"]


def test_data_root_override_and_stop_command(tmp_path, monkeypatch, capsys):
    from yomiscan.engine_models import data_root
    assert data_root({"YOMISCAN_DATA": str(tmp_path), "LOCALAPPDATA": "elsewhere"}) == tmp_path
    monkeypatch.setenv("YOMISCAN_DATA", str(tmp_path))
    # main() fills in the engine's defaults. setenv records each key (even an absent one) so the
    # test removes them again; delenv alone records nothing for an absent key.
    for key in ("YOMISCAN_DETECTOR", "YOMISCAN_OCR", "YOMISCAN_TRANSLATION_ENGINE", "YOMISCAN_PREPARE_COMMAND",
                "YOMISCAN_DICTIONARY", "YOMISCAN_CACHE_DIRECTORY", "YOMISCAN_GLOSSARY_DATABASE"):
        monkeypatch.setenv(key, "")
        monkeypatch.delenv(key)
    assert engine_main(["--stop"]) == 0
    assert "No YomiScan engine was running" in capsys.readouterr().out


def test_prepare_defaults_writes_progress_and_failures(tmp_path, monkeypatch):
    import yomiscan.engine_models as models
    from yomiscan.cli import prepare_defaults
    monkeypatch.setenv("YOMISCAN_ENGINE_MODELS", str(tmp_path / "models"))
    calls = []

    def download(selected, *, bundle, progress):
        calls.append(selected)
        progress(bundle.components[selected[0]].files[0].path, 10)
        return tmp_path
    monkeypatch.setattr(models, "download_components", download)
    assert prepare_defaults(["--component", "dictionary", "--progress", str(tmp_path / "p.json")]) == 0
    assert calls == [["dictionary"]] and json.loads((tmp_path / "p.json").read_text())["state"] == "done"

    def broken(selected, *, bundle, progress):
        raise RuntimeError("Could not download dictionary/jmdict.sqlite3")
    monkeypatch.setattr(models, "download_components", broken)
    with pytest.raises(RuntimeError):
        prepare_defaults(["--component", "dictionary", "--progress", str(tmp_path / "p.json")])
    record = json.loads((tmp_path / "p.json").read_text())
    assert record["state"] == "failed" and "Could not download" in record["error"]
