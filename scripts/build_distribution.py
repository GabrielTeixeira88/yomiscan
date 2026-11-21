"""Build unsigned, versioned, checksummed distributions from an identified checkout."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tarfile
from time import gmtime
import tomllib
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]
EXTENSION_FILES = ("manifest.json", "background.js", "content.js", "offscreen.js", "offscreen.html", "image-access.js", "image-access.html")


def run(arguments: list[str], *, cwd: Path = ROOT, environment: dict[str, str] | None = None) -> str:
    return subprocess.check_output(arguments, cwd=cwd, env=environment, text=True, encoding="utf-8", errors="replace").strip()


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def project_environment(environment: dict[str, str]) -> dict:
    """Describe the synchronized project interpreter, never the caller's global packages."""
    code = ("import importlib.metadata as m,json,platform; "
        "print(json.dumps({'python':platform.python_version(),"
        "'package_versions':dict(sorted((d.metadata['Name'],d.version) for d in m.distributions()))}))")
    return json.loads(run(["uv", "run", "--frozen", "python", "-c", code], environment=environment))


def validate_packages(directory: Path) -> None:
    wheel = next(directory.glob("*.whl"))
    with ZipFile(wheel) as archive:
        names = archive.namelist()
        for required in ("yomiscan/api/main.py", "yomiscan/cli.py", "yomiscan/readiness.py",
                         "yomiscan/resources/fonts/NotoSans.ttf", "yomiscan/resources/fonts/OFL.txt"):
            if required not in names:
                raise ValueError("Missing required wheel resource: "+required)
        if not any(name.endswith("/entry_points.txt") for name in names):
            raise ValueError("Wheel has no command entry points")
    source = next(directory.glob("*.tar.gz"))
    with tarfile.open(source) as archive:
        names += archive.getnames()
    if any(any(part in (".cache", "models", "data", "samples", ".env", "node_modules") for part in Path(name).parts) or
           name.endswith((".sqlite3", ".gguf", ".safetensors", ".onnx", ".pyc")) for name in names):
        raise ValueError("Private/generated artifact appeared in Python distribution")
    extension = next(directory.glob("yomiscan-extension-*.zip"))
    with ZipFile(extension) as archive:
        if set(archive.namelist()) != {*EXTENSION_FILES, "LICENSE", "THIRD-PARTY-NOTICES.md"}:
            raise ValueError("Unexpected extension ZIP contents")
        manifest = json.loads(archive.read("manifest.json"))
        if manifest["manifest_version"] != 3 or manifest.get("content_scripts") or manifest["host_permissions"] != ["http://127.0.0.1/*"]:
            raise ValueError("Unexpected extension permission/installation contract")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-dirty", action="store_true", help="Local preview only; manifest explicitly records dirty source")
    parser.add_argument("--skip-tests", action="store_true", help="Use only after the documented external regression gates")
    args = parser.parse_args(argv)
    output = args.output.resolve()
    if output == ROOT or output in ROOT.parents or (output.exists() and any(output.iterdir())):
        parser.error("Choose a new artifact directory separate from source files")
    dirty = bool(run(["git", "status", "--porcelain"]))
    if dirty and not args.allow_dirty:
        parser.error("Commit/review changes first, or use explicitly marked --allow-dirty local preview")
    commit = run(["git", "rev-parse", "HEAD"])
    epoch = run(["git", "show", "-s", "--format=%ct", "HEAD"])
    environment = {**os.environ, "SOURCE_DATE_EPOCH": epoch, "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"}
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    if not npm:
        parser.error("Install Node 22 and npm to build the extension")
    run(["uv", "sync", "--frozen"], environment=environment)
    run([npm, "ci"], cwd=ROOT/"extension", environment=environment)
    if not args.skip_tests:
        run(["uv", "run", "--frozen", "pytest"], environment=environment)
        run([npm, "test"], cwd=ROOT/"extension", environment=environment)
    run([npm, "run", "typecheck"], cwd=ROOT/"extension", environment=environment)
    run(["node", "build.mjs", "--release"], cwd=ROOT/"extension", environment=environment)
    output.mkdir(parents=True, exist_ok=True)
    run(["uv", "build", "--wheel", "--sdist", "--out-dir", str(output)], environment=environment)
    # uv adds this marker to a newly created build directory. It is not a deliverable.
    (output/".gitignore").unlink(missing_ok=True)
    config = tomllib.loads((ROOT/"pyproject.toml").read_text(encoding="utf-8"))
    app_version = config["project"]["version"]
    extension = output/f"yomiscan-extension-{app_version}-{commit[:12]}.zip"
    with ZipFile(extension, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        files = {name: ROOT/"extension"/"dist"/name for name in EXTENSION_FILES}
        files.update({"LICENSE": ROOT/"LICENSE", "THIRD-PARTY-NOTICES.md": ROOT/"docs"/"third-party-licenses.md"})
        for name, path in sorted(files.items()):
            info = ZipInfo(name, gmtime(max(315532800, int(epoch)))[:6])
            info.create_system = 3;info.external_attr = 0o100644 << 16;info.compress_type = ZIP_DEFLATED
            archive.writestr(info, path.read_text(encoding="utf-8").encode("utf-8"))
    for source, destination in ((ROOT/"docs"/"third-party-licenses.md", "THIRD-PARTY-NOTICES.md"),
                                (ROOT/"docs"/"installation.md", "INSTALLATION.md"), (ROOT/"uv.lock", "uv.lock")):
        (output/destination).write_text(source.read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
    validate_packages(output)
    project = project_environment(environment)
    artifacts = [{"name": path.name, "bytes": path.stat().st_size, "sha256": digest(path)} for path in sorted(output.iterdir()) if path.is_file()]
    manifest = {"schema": 1, "commit": commit, "version": app_version, "dirty_source": dirty, "source_date_epoch": int(epoch),
        "unsigned": True, "platform": {"system": platform.system(), "architecture": platform.machine()},
        "python": project["python"], "node": run(["node", "--version"]), "uv": run(["uv", "--version"]),
        "package_versions": project["package_versions"],
        "lockfiles": {name: digest(ROOT/name) for name in ("uv.lock", "extension/package-lock.json")},
        "notices": "THIRD-PARTY-NOTICES.md; font OFL inside backend package", "external_setup": ["JMdict", "local model weights"],
        "tests": "external gates" if args.skip_tests else "executed by build tool", "artifacts": artifacts,
        "platform_note": "Pure Python wheel; dependency compatibility tested separately on Windows/Linux. No cross-OS byte-identity claim."}
    (output/"artifact-manifest.json").write_text(json.dumps(manifest, indent=2)+"\n", encoding="utf-8", newline="\n")
    checksums = [f"{digest(path)}  {path.name}" for path in sorted(output.iterdir()) if path.is_file()]
    (output/"SHA256SUMS").write_text("\n".join(checksums)+"\n", encoding="utf-8", newline="\n")
    print(json.dumps({"commit": commit, "dirty_source": dirty, "artifacts": artifacts}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
