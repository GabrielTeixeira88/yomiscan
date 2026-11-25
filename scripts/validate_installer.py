"""Install, check and uninstall the YomiScan Engine installer silently (Stage 5b increment 5).

    python scripts/validate_installer.py --installer .cache/engine-build/YomiScan-Engine-Setup-0.1.0.exe

Meant for a clean Windows machine (CI). It refuses to run where a YomiScan native-messaging
registration already exists, so a developer's registration is never replaced by accident
(--allow-replace overrides; the uninstall then removes the registration).
Checks: files; the HKCU native-messaging key, its manifest (path to the windowless host, allowed
extension); the Add/Remove Programs entry; the installed host answering `status` over Chrome's
framing; an invalid extension ID failing the install; and a silent uninstall removing the files,
the registration and the entry while keeping user data. Prints a JSON report.
"""

import argparse
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import time
import winreg

HOST_KEY = r"Software\Google\Chrome\NativeMessagingHosts\com.yomiscan.engine"
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\YomiScanEngine"
EXTENSION_ID = "abcdefghijklmnopabcdefghijklmnop"


def read_key(path: str, name: str = "") -> str | None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
            return str(winreg.QueryValueEx(key, name)[0])
    except FileNotFoundError:
        return None


def ask(host: Path, message: dict) -> dict:
    body = json.dumps(message).encode()
    output = subprocess.run([str(host), f"chrome-extension://{EXTENSION_ID}/", "--parent-window=0"],
                            input=struct.pack("=I", len(body)) + body, capture_output=True, timeout=120, check=True).stdout
    (length,) = struct.unpack("=I", output[:4])
    return json.loads(output[4:4 + length])


def until(check, timeout: float, label: str) -> float:
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        if check():
            return time.monotonic() - start
        time.sleep(.5)
    raise TimeoutError(f"Timed out: {label}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--installer", type=Path, required=True)
    parser.add_argument("--allow-replace", action="store_true")
    arguments = parser.parse_args(argv)
    if read_key(HOST_KEY) is not None and not arguments.allow_replace:
        parser.error("A YomiScan native-messaging registration exists; run this on a clean machine (or pass --allow-replace)")
    report: dict[str, object] = {"installer_mib": round(arguments.installer.stat().st_size / 2**20, 1)}
    with tempfile.TemporaryDirectory() as temporary:
        target = Path(temporary) / "Engine"
        bad = subprocess.run([str(arguments.installer), "/S", "/EXTENSIONID=not-an-extension-id", f"/D={Path(temporary) / 'Bad'}"], timeout=600)
        assert bad.returncode != 0 and read_key(HOST_KEY) is None, "an invalid extension ID must fail the install"
        report["invalid_id"] = f"refused (exit code {bad.returncode}), nothing registered"

        start = time.monotonic()
        result = subprocess.run([str(arguments.installer), "/S", f"/EXTENSIONID={EXTENSION_ID}", f"/D={target}"], timeout=900)
        report["install_s"] = round(time.monotonic() - start, 1)
        assert result.returncode == 0, f"installer exit code {result.returncode}"
        for name in ("yomiscan-engine.exe", "yomiscan-engine-host.exe", "Uninstall.exe", "LICENSE.txt", "licenses/THIRD-PARTY-NOTICES.txt"):
            assert (target / name).is_file(), f"missing {name}"
        report["installed_mib"] = round(sum(p.stat().st_size for p in target.rglob("*") if p.is_file()) / 2**20, 1)

        manifest_path = read_key(HOST_KEY)
        assert manifest_path and Path(manifest_path).is_file(), "native-messaging key or manifest missing"
        manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
        assert Path(manifest["path"]).resolve() == (target / "yomiscan-engine-host.exe").resolve(), manifest["path"]
        assert manifest["allowed_origins"] == [f"chrome-extension://{EXTENSION_ID}/"] and manifest["type"] == "stdio"
        assert read_key(UNINSTALL_KEY, "DisplayName") == "YomiScan Engine"
        assert read_key(UNINSTALL_KEY, "QuietUninstallString") == f'"{target / "Uninstall.exe"}" /S'
        report["registration"] = {"manifest": manifest_path, "host": manifest["path"], "allowed_origins": manifest["allowed_origins"]}

        status = ask(target / "yomiscan-engine-host.exe", {"type": "status"})
        assert status["ok"] and "ready" in status["models"], status
        report["host_status"] = {"version": status["version"], "models_ready": status["models"]["ready"],
                                 "missing_mib": round(status["models"]["bytes"] / 2**20)}

        subprocess.run([str(target / "Uninstall.exe"), "/S"], timeout=120, check=True)
        # The uninstaller copies itself to %TEMP% and returns at once; wait for its work.
        report["uninstall_s"] = round(until(lambda: not target.exists() and read_key(UNINSTALL_KEY, "DisplayName") is None,
                                            120, "uninstall"), 1)
        assert read_key(HOST_KEY) is None and not Path(manifest_path).exists(), "registration left behind"
        report["uninstalled"] = "files, native-messaging registration and Add/Remove Programs entry removed; user data kept"
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
