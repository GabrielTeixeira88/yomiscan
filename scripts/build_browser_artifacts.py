"""Package browser-engine model artifacts and pin them in the extension (Stage 5a).

Copies the ONNX exports made by research/stage-2 (see its README for the export commands)
into one servable folder and writes two manifests with each file's size and SHA-256:

- <output>/manifest.json, served next to the files;
- extension/src/engine/artifact-manifest.json, committed, so the extension accepts only these bytes.

Weights stay out of Git. Serve the output folder with scripts/serve_browser_artifacts.py
for local development, or publish it unchanged to the chosen public host.
"""

import argparse
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
PINNED = ROOT / "extension" / "src" / "engine" / "artifact-manifest.json"
BUNDLE = "yomiscan-browser-2026.11.1"
MANGA_OCR = "kha-white/manga-ocr-base (Apache-2.0); ONNX export, research/stage-2"
DETECTOR = "ogkalu/comic-text-and-bubble-detector@16e8a622f91fabc6b5b65c96d32d1183f8843546 (Apache-2.0); ONNX export"


@dataclass(frozen=True)
class Component:
    id: str
    kind: str
    variant: str
    license: str
    source: str
    files: tuple[tuple[str, str], ...]  # (path inside the stage-2 cache, published path)


def components(stage2: Path) -> tuple[Component, ...]:
    ocr = lambda variant: Component(f"ocr-{variant}", "ocr", variant, "Apache-2.0", MANGA_OCR, tuple(
        (f"manga-ocr-onnx-{variant}/{name}", f"ocr-{variant}/{name}")
        for name in ("encoder.onnx", "decoder.onnx", "vocab.txt", "generation.json")))
    return (
        Component("detector", "detector", "fp16", "Apache-2.0", DETECTOR,
                  (("detector-onnx/detector-fp16.onnx", "detector/detector-fp16.onnx"),)),
        ocr("q4"),    # WebGPU (Stage 2: 85 ms median per block)
        ocr("int8"),  # CPU / WASM (Stage 2: 194 ms median per block, 8 threads)
    )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build(stage2: Path, output: Path, pinned: Path = PINNED) -> dict:
    manifest: dict = {"schema": 1, "bundle": BUNDLE, "components": []}
    missing = [stage2 / source for c in components(stage2) for source, _ in c.files if not (stage2 / source).is_file()]
    if missing:
        raise FileNotFoundError("Missing Stage 2 exports (run the research/stage-2 export commands first): "
                                + ", ".join(str(p) for p in missing))
    for component in components(stage2):
        files = []
        for source, published in component.files:
            target = output / published
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(stage2 / source, target)
            files.append({"path": published, "bytes": target.stat().st_size, "sha256": sha256(target)})
        manifest["components"].append({"id": component.id, "kind": component.kind, "variant": component.variant,
                                       "license": component.license, "source": component.source, "files": files})
    text = json.dumps(manifest, indent=1, ensure_ascii=False) + "\n"
    (output / "manifest.json").write_text(text, encoding="utf-8")
    pinned.write_text(text, encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--stage2", type=Path, default=ROOT / ".cache" / "stage2", help="Stage 2 export folder")
    parser.add_argument("--output", type=Path, default=ROOT / ".cache" / "browser-artifacts", help="Servable artifact folder")
    arguments = parser.parse_args(argv)
    try:
        manifest = build(arguments.stage2, arguments.output)
    except FileNotFoundError as error:
        print(error, file=sys.stderr)
        return 2
    for component in manifest["components"]:
        size = sum(f["bytes"] for f in component["files"]) / 2**20
        print(f"{component['id']:<10} {size:7.1f} MiB  {len(component['files'])} files")
    print(f"Wrote {arguments.output / 'manifest.json'} and {PINNED.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
