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
    subprocess.run(["uv", "sync", "--frozen", "--no-default-groups", "--group", "freeze", "--no-editable"],
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


def inspect(bundle: Path) -> dict:
    internal = bundle / "_internal"
    leaked = sorted({p.name for p in internal.iterdir() if p.name.split(".")[0] in EXCLUDED}) if internal.is_dir() else []
    if leaked:
        raise RuntimeError(f"Excluded packages reached the bundle: {leaked}")
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
    report = inspect(build(python, arguments.output))
    print(json.dumps({**report, "mib": round(report["bytes"] / 2**20, 1)}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
