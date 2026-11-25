"""Build the per-user Windows installer for the local engine (Stage 5b increment 5).

    uv run python scripts/build_installer.py [--skip-engine] [--extension-id <id>]

Freezes the engine (scripts/build_engine.py) unless --skip-engine, then compiles
packaging/engine/installer.nsi with NSIS 3 (`makensis` from MAKENSIS, PATH or a standard install
folder) into .cache/engine-build/YomiScan-Engine-Setup-<version>.exe and prints its size and
SHA-256. --extension-id pre-fills the installer's "Connect to Chrome" page (the Chrome Web Store
ID once the extension is published). The installer is unsigned (owner decision).
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / ".cache" / "engine-build"
SCRIPT = ROOT / "packaging" / "engine" / "installer.nsi"


def makensis() -> Path:
    candidates = [os.environ.get("MAKENSIS"), shutil.which("makensis"),
                  r"C:\Program Files (x86)\NSIS\makensis.exe", r"C:\Program Files\NSIS\makensis.exe"]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return Path(candidate)
    raise FileNotFoundError("NSIS 3 is required: install it (https://nsis.sourceforge.io) or set MAKENSIS to makensis.exe")


def license_text(bundle: Path) -> Path:
    """The license page: YomiScan's MIT license and where the third-party notices are."""
    text = (ROOT / "LICENSE").read_text(encoding="utf-8").rstrip() + (
        "\r\n\r\n---\r\n\r\nThe engine includes third-party software under its own licenses; their texts are installed "
        "in the licenses folder (THIRD-PARTY-NOTICES.txt lists them). The reading models and the dictionary are not part "
        "of this installer: they are downloaded later, after you agree in the extension, and keep their own licenses, "
        "including JMdict (EDRDG, CC BY-SA 4.0).\r\n")
    path = BUILD / "installer-license.txt"
    path.write_text(text.replace("\r\n", "\n").replace("\n", "\r\n"), encoding="utf-8-sig")
    if not (bundle / "licenses" / "THIRD-PARTY-NOTICES.txt").is_file():
        raise FileNotFoundError("The engine bundle has no licenses folder; rebuild it with scripts/build_engine.py")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--skip-engine", action="store_true", help="Reuse .cache/engine-build/dist/yomiscan-engine")
    parser.add_argument("--extension-id", default="", help="Pre-fill the installer's extension ID")
    arguments = parser.parse_args(argv)
    if arguments.extension_id and (len(arguments.extension_id) != 32 or not set(arguments.extension_id) <= set("abcdefghijklmnop")):
        parser.error("--extension-id must be 32 letters from a to p")
    compiler = makensis()
    if not arguments.skip_engine:
        subprocess.run([sys.executable, str(ROOT / "scripts" / "build_engine.py")], cwd=ROOT, check=True)
    bundle = BUILD / "dist" / "yomiscan-engine"
    if not (bundle / "yomiscan-engine.exe").is_file() or not (bundle / "yomiscan-engine-host.exe").is_file():
        raise FileNotFoundError(f"{bundle} is incomplete; run scripts/build_engine.py")
    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    output = BUILD / f"YomiScan-Engine-Setup-{version}.exe"
    installed_kb = sum(p.stat().st_size for p in bundle.rglob("*") if p.is_file()) // 1024
    defines = {"VERSION": version, "SOURCE": str(bundle), "OUTFILE": str(output), "LICENSE_FILE": str(license_text(bundle)),
               "INSTALLED_KB": str(installed_kb), "DEFAULT_EXTENSION_ID": arguments.extension_id}
    subprocess.run([str(compiler), "/V2", *(f"/D{key}={value}" for key, value in defines.items()), str(SCRIPT)], cwd=ROOT, check=True)
    with output.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    print(json.dumps({"installer": str(output.relative_to(ROOT)), "mib": round(output.stat().st_size / 2**20, 1),
                      "installed_mib": round(installed_kb / 1024, 1), "sha256": digest}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
