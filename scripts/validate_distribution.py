"""Opt-in clean installed-package smoke. Does not download/load neural weights."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import tomllib
from time import monotonic, sleep
from urllib.error import URLError
from urllib.request import Request, urlopen
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]


def run(arguments: list[str], **kwargs) -> None:
    subprocess.run(arguments, check=True, cwd=ROOT, **kwargs)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--environment", type=Path, required=True)
    args = parser.parse_args(argv)
    artifacts, environment = args.artifacts.resolve(), args.environment.resolve()
    if environment.exists():
        parser.error("Choose a new smoke environment")
    for line in (artifacts/"SHA256SUMS").read_text(encoding="utf-8").splitlines():
        expected, name = line.split("  ", 1)
        if Path(name).name != name:
            parser.error("Unsafe checksum entry")
        if hashlib.sha256((artifacts/name).read_bytes()).hexdigest() != expected:
            raise ValueError("Artifact checksum mismatch: "+name)
    manifest = json.loads((artifacts/"artifact-manifest.json").read_text(encoding="utf-8"))
    normalize = lambda name: name.lower().replace("_", "-").replace(".", "-")
    locked = {(normalize(p["name"]), p["version"]) for p in tomllib.loads((ROOT/"uv.lock").read_text(encoding="utf-8"))["package"]}
    for name, version in manifest["package_versions"].items():
        if (normalize(name), version) not in locked:
            raise ValueError("Manifest includes a package/version outside the project lock: "+name)
    if not {"fastapi", "torch", "transformers"} <= {normalize(name) for name in manifest["package_versions"]}:
        raise ValueError("Manifest omitted locked runtime dependency versions")
    run(["uv", "venv", str(environment), "--python", "3.13"])
    python = environment/("Scripts/python.exe" if os.name == "nt" else "bin/python")
    # Frozen sync can use exact cached lockfile URLs without a cached registry index.
    # pip's requirements resolver may need index metadata that sync never requested.
    # Only the package's own dependencies: the PyTorch `reference` group is not part of the release.
    run(["uv", "sync", "--frozen", "--no-default-groups", "--no-install-project", "--offline"],
        env={**os.environ, "UV_PROJECT_ENVIRONMENT": str(environment)})
    wheel, source = next(artifacts.glob("*.whl")), next(artifacts.glob("*.tar.gz"))
    imports = ("import importlib.metadata,sys; from pathlib import Path; import yomiscan; import yomiscan.api.main; "
        "from yomiscan.rendering.typesetting import LATIN_FONT; assert LATIN_FONT.is_file(); "
        "assert LATIN_FONT.with_name('OFL.txt').is_file(); assert 'torch' not in sys.modules; "
        "print('Installed package imports/version/fonts passed:',importlib.metadata.version('yomiscan'))")
    for package in (wheel, source):
        run(["uv", "pip", "install", "--python", str(python), "--offline", "--no-deps", "--reinstall", str(package)])
        run([str(python), "-I", "-c", imports])
    scripts = environment/("Scripts" if os.name == "nt" else "bin")
    for command in ("yomiscan-server", "yomiscan-engine", "yomiscan-import-jmdict", "yomiscan-prepare-defaults", "yomiscan-prepare-engine",
                    "yomiscan-prepare-vision", "yomiscan-prepare-translation", "yomiscan-translate"):
        run([str(scripts/(command+(".exe" if os.name == "nt" else ""))), "--help"], stdout=subprocess.DEVNULL)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0));port = sock.getsockname()[1]
    env = {**os.environ, "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "HF_HOME": str(environment/"empty-model-cache"),
        "YOMISCAN_DICTIONARY": str(environment/"missing-dictionary.sqlite3"),
        # The default (Torch-free) engines with an empty model folder: no user models are found.
        "YOMISCAN_ENGINE_MODELS": str(environment/"empty-engine-models"), "LOCALAPPDATA": str(environment/"local-app-data")}
    for variable in ("YOMISCAN_TRANSLATION_ENGINE", "YOMISCAN_OCR", "YOMISCAN_DETECTOR", "YOMISCAN_ONNX_DEVICE"):
        env.pop(variable, None)
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    with (environment/"startup.log").open("wb") as log:
        process = subprocess.Popen([str(scripts/("yomiscan-server.exe" if os.name == "nt" else "yomiscan-server")),
            "--port", str(port), "--device", "cpu"], cwd=environment, env=env, stdout=log, stderr=log, creationflags=flags)
        try:
            deadline = monotonic()+20
            status = None
            while monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError("Installed backend exited before readiness")
                try:
                    with urlopen(Request(f"http://127.0.0.1:{port}/api/v1/readiness", headers={"X-YomiScan-Client": "study-extension-v1"}), timeout=2) as response:
                        status = json.load(response)
                    if status["initialization"] == "failed": break
                except (URLError, TimeoutError): pass
                sleep(.1)
            if not status or status["initialization"] != "failed" or status["dictionary"]["installed"]:
                raise RuntimeError("Missing-model/dictionary startup was not reported accurately")
            print("Installed backend serves protected readiness with missing resources and no model downloads.")
        finally:
            if process.poll() is None:
                process.terminate()
                try: process.wait(timeout=10)
                except subprocess.TimeoutExpired: process.kill();process.wait()
    extension = next(artifacts.glob("yomiscan-extension-*.zip"))
    unpacked = environment/"unpacked-extension"
    with ZipFile(extension) as archive:
        for name in archive.namelist():
            parts = name.split("/")
            if name.startswith("/") or "\\" in name or any(part in ("", ".", "..") for part in parts):
                raise ValueError("Unexpected archive path: " + name)
            (unpacked/name).parent.mkdir(parents=True, exist_ok=True)
            (unpacked/name).write_bytes(archive.read(name))
    print(json.dumps({"wheel_and_sdist": "installed", "entry_points": "passed", "checksums": "passed",
                      "browser_smoke_directory": str(unpacked)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
