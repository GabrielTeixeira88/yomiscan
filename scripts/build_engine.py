"""Freeze the Torch-free local engine with PyInstaller (Stage 5b increment 3).

    uv run python scripts/build_engine.py            # -> .cache/engine-build/dist/yomiscan-engine/

The build uses its own environment with only the package's dependencies and PyInstaller
(`uv sync --no-default-groups --group freeze --no-editable`), so the PyTorch `reference` group
cannot leak into the bundle. PyInstaller follows imports inside functions too; the Torch
adapters' lazy imports are excluded explicitly and the build fails if any of them got in.
Models are not bundled: `yomiscan-engine --prepare` downloads them explicitly.
"""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / ".cache" / "engine-build"
NAME = "yomiscan-engine"
SPEC = ROOT / "packaging" / "engine" / "yomiscan-engine.spec"
EXCLUDED = ("torch", "torchvision", "transformers", "manga_ocr", "huggingface_hub", "sacremoses", "tokenizers",
            "safetensors", "tkinter", "matplotlib", "IPython", "pytest")


def environment_python(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def sync(venv: Path) -> Path:
    environment = {**os.environ, "UV_PROJECT_ENVIRONMENT": str(venv)}
    environment.pop("VIRTUAL_ENV", None)
    # --reinstall-package: uv keys its cache of a local project on pyproject.toml only, so a
    # non-editable install would otherwise keep stale YomiScan sources.
    subprocess.run(["uv", "sync", "--frozen", "--no-default-groups", "--group", "freeze", "--no-editable",
                    "--reinstall-package", "yomiscan"],
                   cwd=ROOT, env=environment, check=True)
    return environment_python(venv)


def folder_size(path: Path) -> int:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def build(python: Path, output: Path) -> Path:
    entry = BUILD / "entry.py"
    entry.parent.mkdir(parents=True, exist_ok=True)
    entry.write_text("\n".join(("from yomiscan.engine_main import main", "raise SystemExit(main())", "")), encoding="utf-8")
    arguments = [str(python), "-m", "PyInstaller", "--noconfirm", "--clean", "--distpath", str(output),
                 "--workpath", str(BUILD / "work"), str(SPEC)]
    environment = {**os.environ, "YOMISCAN_ENGINE_ENTRY": str(entry), "YOMISCAN_ENGINE_EXCLUDED": ",".join(EXCLUDED)}
    subprocess.run(arguments, cwd=ROOT, env=environment, check=True)
    bundle = output / NAME
    # OpenCV's video I/O plugin (FFmpeg, about 30 MB) is loaded only for video; YomiScan reads images.
    for plugin in (bundle / "_internal" / "cv2").glob("opencv_videoio_ffmpeg*.dll"):
        plugin.unlink()
    return bundle


# Lists every installed distribution's license files (dist-info metadata), run with the build venv.
LICENSE_LISTER = """
import importlib.metadata as m, json, re
rows = []
for d in m.distributions():
    files = [str(d.locate_file(f)) for f in (d.files or []) if re.search(r"(^|/)(licen[cs]e|copying|notice|authors)[^/]*$", str(f), re.I)]
    rows.append({"name": d.metadata["Name"], "version": d.version, "license": d.metadata.get("License-Expression") or d.metadata.get("License") or "",
                 "files": files})
print(json.dumps(rows))
"""


def collect_licenses(python: Path, bundle: Path) -> int:
    """Copy each bundled package's license texts into licenses/<package>/ and write an index."""
    rows = json.loads(subprocess.run([str(python), "-c", LICENSE_LISTER], capture_output=True, text=True, check=True).stdout)
    target = bundle / "licenses"
    lines = ["Third-party software in the YomiScan local engine", "",
             "YomiScan itself is MIT-licensed (LICENSE). The packages below keep their own licenses; their texts are",
             "in the folder of the same name. The reading models and the dictionary are downloaded separately and",
             "keep theirs (see the model card on Hugging Face): JMdict (EDRDG, CC BY-SA 4.0), UniDic, OPUS-MT,",
             "manga-ocr and the comic text detector (Apache-2.0).", ""]
    for row in sorted(rows, key=lambda r: r["name"].lower()):
        if row["name"] in ("pyinstaller", "pyinstaller-hooks-contrib", "altgraph", "pefile", "pywin32-ctypes", "packaging", "setuptools"):
            continue  # build tools, not shipped
        folder = target / row["name"]
        for source in map(Path, row["files"]):
            if source.is_file():
                folder.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, folder / source.name)
        summary = (row["license"].splitlines() or [""])[0][:100]
        lines.append(f"{row['name']} {row['version']}: {summary or 'see its folder'}")
    shutil.copyfile(ROOT / "LICENSE", bundle / "LICENSE.txt")
    (target / "THIRD-PARTY-NOTICES.txt").parent.mkdir(parents=True, exist_ok=True)
    (target / "THIRD-PARTY-NOTICES.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(rows)


def inspect(bundle: Path) -> dict:
    internal = bundle / "_internal"
    leaked = sorted({p.name for p in internal.iterdir() if p.name.split(".")[0] in EXCLUDED}) if internal.is_dir() else []
    if leaked:
        raise RuntimeError(f"Excluded packages reached the bundle: {leaked}")
    package = ROOT / "backend" / "yomiscan"
    stale = [str(path.relative_to(package)) for path in package.rglob("*.py") if "__pycache__" not in path.parts and
             (not (internal / "yomiscan" / path.relative_to(package)).is_file() or
              (internal / "yomiscan" / path.relative_to(package)).read_bytes() != path.read_bytes())]
    if stale:
        raise RuntimeError(f"The bundle holds stale or missing YomiScan sources: {stale[:5]}")
    largest = sorted(((folder_size(p) if p.is_dir() else p.stat().st_size, p.name) for p in internal.iterdir()), reverse=True)[:8]
    return {"bundle": str(bundle.relative_to(ROOT)), "bytes": folder_size(bundle),
            "files": sum(1 for p in bundle.rglob("*") if p.is_file()),
            "largest": [{"name": name, "mib": round(size / 2**20, 1)} for size, name in largest]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", type=Path, default=BUILD / "dist")
    arguments = parser.parse_args(argv)
    if (arguments.output / NAME).exists():
        shutil.rmtree(arguments.output / NAME)
    python = sync(BUILD / "venv")
    bundle = build(python, arguments.output)
    packages = collect_licenses(python, bundle)
    report = {**inspect(bundle), "license_packages": packages}
    print(json.dumps({**report, "mib": round(report["bytes"] / 2**20, 1)}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
