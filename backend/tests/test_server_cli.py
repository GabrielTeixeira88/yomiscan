"""yomiscan-server argument handling; uvicorn is replaced, so nothing is served."""

import sys
from types import SimpleNamespace

import pytest

from yomiscan import cli


@pytest.fixture
def served(monkeypatch):
    calls = []
    # server_main exports these for the app; monkeypatch restores them afterwards.
    monkeypatch.delenv("YOMISCAN_DICTIONARY", raising=False)
    monkeypatch.delenv("YOMISCAN_DEVICE", raising=False)
    monkeypatch.setitem(sys.modules, "uvicorn", SimpleNamespace(run=lambda app, **options: calls.append((app, options))))
    monkeypatch.setattr(cli, "version", lambda name: "0.0-test")
    return calls


def test_default_port_avoids_ankiconnect(served):
    cli.server_main([])
    assert cli.DEFAULT_PORT == 47615 != 8765
    assert served == [("yomiscan.api.main:app", {"host": "127.0.0.1", "port": 47615})]


def test_explicit_port_is_used(served):
    cli.server_main(["--port", "8790"])
    assert served[0][1]["port"] == 8790


@pytest.mark.parametrize("port", ["80", "1023", "65536"])
def test_privileged_or_invalid_ports_are_rejected(served, port):
    with pytest.raises(SystemExit):
        cli.server_main(["--port", port])
    assert served == []
