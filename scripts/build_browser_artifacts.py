"""Package browser-engine model artifacts and pin them in the extension (Stage 5a).

Copies the ONNX exports made by research/stage-2 (see its README for the export commands)
into one servable folder and writes two manifests with each file's size and SHA-256:

- <output>/manifest.json, served next to the files;
- extension/src/engine/artifact-manifest.json, committed, so the extension accepts only these bytes;
- <output>/local-manifest.json and backend/yomiscan/resources/engine/local-manifest.json for the
  Torch-free local engine (Stage 5b): the fp32 detector plus the browser bundle's int8 OCR files.

Weights stay out of Git. Serve the output folder with scripts/serve_browser_artifacts.py
for local development; scripts/publish_browser_artifacts.py uploads it unchanged to Hugging
Face. The folder also gets a model card and license texts from packaging/browser-models/.
"""

import argparse
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import shutil
from string import Template
import sys

ROOT = Path(__file__).resolve().parents[1]
PINNED = ROOT / "extension" / "src" / "engine" / "artifact-manifest.json"
LOCAL_PINNED = ROOT / "backend" / "yomiscan" / "resources" / "engine" / "local-manifest.json"
LOCAL_BUNDLE = "yomiscan-local-2026.11.1"
NOTICES = ROOT / "packaging" / "browser-models"
BUNDLE = "yomiscan-browser-2026.11.1"
MANGA_OCR = "kha-white/manga-ocr-base (Apache-2.0); ONNX export, research/stage-2"
LINDERA = "lindera-wasm-unidic@2.1.0 (npm, pinned in extension/package-lock.json)"
LINDERA_WASM = ROOT / "extension" / "node_modules" / "lindera-wasm-unidic" / "lindera_wasm_unidic_bg.wasm"
JMDICT = "JMdict (EDRDG), imported by scripts/import_jmdict.py; attribution required"
OPUS = "Xenova/opus-mt-ja-en: ONNX export of Helsinki-NLP/opus-mt-ja-en (Apache-2.0); fp16 files"
DETECTOR = "ogkalu/comic-text-and-bubble-detector@16e8a622f91fabc6b5b65c96d32d1183f8843546 (Apache-2.0); ONNX export"


@dataclass(frozen=True)
class Component:
    id: str
    kind: str
    variant: str
    license: str
    source: str
    files: tuple[tuple[Path, str], ...]  # (source file, published path)


def components(stage2: Path, dictionary: Path = ROOT / "data" / "jmdict.sqlite3", tokenizer: Path = LINDERA_WASM) -> tuple[Component, ...]:
    ocr = lambda variant: Component(f"ocr-{variant}", "ocr", variant, "Apache-2.0", MANGA_OCR, tuple(
        (stage2 / f"manga-ocr-onnx-{variant}" / name, f"ocr-{variant}/{name}")
        for name in ("encoder.onnx", "decoder.onnx", "vocab.txt", "generation.json")))
    return (
        Component("detector", "detector", "fp16", "Apache-2.0", DETECTOR,
                  ((stage2 / "detector-onnx" / "detector-fp16.onnx", "detector/detector-fp16.onnx"),)),
        ocr("q4"),    # WebGPU (Stage 2: 85 ms median per block)
        ocr("int8"),  # CPU / WASM (Stage 2: 194 ms median per block, 8 threads)
        # The WASM must match the JS glue bundled in the extension: the same pinned npm package.
        Component("tokenizer", "tokenizer", "unidic", "MIT (lindera); UniDic BSD-3-Clause", LINDERA,
                  ((tokenizer, "tokenizer/lindera_wasm_unidic_bg.wasm"),)),
        Component("dictionary", "dictionary", "jmdict-schema2", "CC-BY-SA-4.0 (EDRDG)", JMDICT,
                  ((dictionary, "dictionary/jmdict.sqlite3"),)),
        # Stage 2: fp16 + beam search on WASM reproduces the Python backend on 99/100 lines.
        Component("translation-opus-ja-en", "translation", "fp16", "Apache-2.0 (Helsinki-NLP OPUS-MT)", OPUS, tuple(
            (stage2 / "hf" / "Xenova" / "opus-mt-ja-en" / source, f"translation-opus-ja-en/{Path(source).name}") for source in (
                "onnx/encoder_model_fp16.onnx", "onnx/decoder_model_merged_fp16.onnx", "tokenizer.json", "tokenizer_config.json",
                "config.json", "generation_config.json"))),
    )


def local_components(stage2: Path) -> tuple[Component, ...]:
    """Files only the local engine uses (Stage 5b): the fp32 detector reproduces the PyTorch boxes
    (226/226 on DirectML); fp32 OPUS with the ported beam search reproduces the backend on 153/153 lines."""
    opus = stage2 / "hf" / "Xenova" / "opus-mt-ja-en"
    return (Component("detector-fp32", "detector", "fp32", "Apache-2.0", DETECTOR,
                      ((stage2 / "detector-onnx" / "detector.onnx", "detector-fp32/detector.onnx"),)),
            Component("translation-opus-ja-en-fp32", "translation", "fp32", "Apache-2.0 (Helsinki-NLP OPUS-MT)",
                      OPUS.replace("fp16 files", "fp32 files, Marian SentencePiece vocabularies"), tuple(
                          (opus / source, f"translation-opus-ja-en-fp32/{Path(source).name}") for source in (
                              "onnx/encoder_model.onnx", "onnx/decoder_model_merged.onnx", "source.spm", "target.spm",
                              "vocab.json", "config.json", "generation_config.json"))))


# Browser-bundle components the local engine reuses unchanged (same paths and hashes).
LOCAL_SHARED = ("ocr-int8", "dictionary")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def copy_component(component: Component, output: Path) -> dict:
    files = []
    for source, published in component.files:
        target = output / published
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        files.append({"path": published, "bytes": target.stat().st_size, "sha256": sha256(target)})
    return {"id": component.id, "kind": component.kind, "variant": component.variant,
            "license": component.license, "source": component.source, "files": files}


def build(stage2: Path, output: Path, pinned: Path = PINNED, dictionary: Path = ROOT / "data" / "jmdict.sqlite3",
          tokenizer: Path = LINDERA_WASM, local_pinned: Path | None = None) -> dict:
    """Writes both manifests; local_pinned defaults to local-manifest.json next to `pinned`."""
    manifest: dict = {"schema": 1, "bundle": BUNDLE, "components": []}
    everything = (*components(stage2, dictionary, tokenizer), *local_components(stage2))
    missing = [source for c in everything for source, _ in c.files if not source.is_file()]
    if missing:
        raise FileNotFoundError("Missing inputs (research/stage-2 exports, npm ci in extension/, scripts/import_jmdict.py): "
                                + ", ".join(str(p) for p in missing))
    for component in components(stage2, dictionary, tokenizer):
        manifest["components"].append(copy_component(component, output))
    local: dict = {"schema": 1, "bundle": LOCAL_BUNDLE, "components": [
        *(copy_component(c, output) for c in local_components(stage2)),
        *(c for c in manifest["components"] if c["id"] in LOCAL_SHARED)]}
    for name, data, committed in (("manifest.json", manifest, pinned),
                                  ("local-manifest.json", local, local_pinned or pinned.with_name("local-manifest.json"))):
        text = json.dumps(data, indent=1, ensure_ascii=False) + "\n"
        (output / name).write_text(text, encoding="utf-8")
        committed.write_text(text, encoding="utf-8")
    write_notices(manifest, output, local)
    return manifest


def write_notices(manifest: dict, output: Path, local: dict, notices: Path = NOTICES) -> None:
    """The hosted folder's model card (with generated component tables) and license texts."""
    def rows(items) -> str:
        return "\n".join(
            f"| `{c['id']}` ({c['variant']}) | {len(c['files'])} | {sum(f['bytes'] for f in c['files']) / 2**20:.1f} MiB "
            f"| {c['license']} | {c['source']} |" for c in items)
    only_local = [c for c in local["components"] if c["id"] not in LOCAL_SHARED]
    card = Template((notices / "README.md").read_text(encoding="utf-8")).substitute(
        bundle=manifest["bundle"], components=rows(manifest["components"]), local_bundle=local["bundle"],
        local_components=rows(only_local), local_shared=", ".join(f"`{c}`" for c in LOCAL_SHARED))
    (output / "README.md").write_text(card, encoding="utf-8")
    shutil.copytree(notices / "LICENSES", output / "LICENSES", dirs_exist_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--stage2", type=Path, default=ROOT / ".cache" / "stage2", help="Stage 2 export folder")
    parser.add_argument("--output", type=Path, default=ROOT / ".cache" / "browser-artifacts", help="Servable artifact folder")
    arguments = parser.parse_args(argv)
    try:
        manifest = build(arguments.stage2, arguments.output, local_pinned=LOCAL_PINNED)
    except FileNotFoundError as error:
        print(error, file=sys.stderr)
        return 2
    for component in manifest["components"]:
        size = sum(f["bytes"] for f in component["files"]) / 2**20
        print(f"{component['id']:<10} {size:7.1f} MiB  {len(component['files'])} files")
    print(f"Wrote {arguments.output / 'manifest.json'} and {arguments.output / 'local-manifest.json'}, "
          f"{PINNED.relative_to(ROOT)} and {LOCAL_PINNED.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
