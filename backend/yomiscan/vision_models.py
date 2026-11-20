"""Pinned experimental artifacts. Downloads require an explicit setup command."""

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from .detection.rtdetr import MODEL_ID, MODEL_REVISION


@dataclass(frozen=True)
class ModelFiles:
    repository: str
    revision: str
    files: tuple[str, ...]
    hashes: dict[str, str]
    license: str = "Apache-2.0"


TOKENIZER_FILES = ("config.json", "preprocessor_config.json", "tokenizer_config.json", "special_tokens_map.json", "vocab.txt")
MODELS = {
    "detector": ModelFiles(MODEL_ID, MODEL_REVISION, ("detector-v4-s_int8.onnx", "README.md"), {
        "detector-v4-s_int8.onnx": "5fe9e4f576e49d4e7e8b0e029d6d3cdc252abd4694113e1cae120e62c931ea79"}),
    "ocr-original": ModelFiles("kha-white/manga-ocr-base", "aa6573bd10b0d446cbf622e29c3e084914df9741",
        (*TOKENIZER_FILES, "pytorch_model.bin"), {
            "pytorch_model.bin": "c63e0bb5b3ff798c5991de18a8e0956c7ee6d1563aca6729029815eda6f5c2eb"}),
    "ocr-2025": ModelFiles("jzhang533/manga-ocr-base-2025", "1e64d5beb41ee6bee72c200838ddb93ad541482a",
        (*TOKENIZER_FILES, "generation_config.json", "model.safetensors", "LICENSE", "README.md"), {
            "model.safetensors": "6152295c6d796ff92ed024b3ed5a0246a7865568e36d73c64b4bed2a71e4acb0"}),
    "ocr-onnx": ModelFiles("artsaraiva/manga-ocr-2025-onnx-past", "151898756903f03a2682fa6be4507dfeff71fb7e",
        ("encoder_model.onnx", "decoder_model_merged.onnx", "vocab.txt", "config.json", "generation_config.json", "preprocessor_config.json", "README.md"), {
            "encoder_model.onnx": "2398ca8799bcc30a6240f2f309b3f9a1b697b5192afa9231338d2f69c3f866ef",
            "decoder_model_merged.onnx": "ac0ac6f48fa89bbfff1ab8d53ffcaa76839a72b145fe20a70923dc59b0b9349e",
            "vocab.txt": "344fbb6b8bf18c57839e924e2c9365434697e0227fac00b88bb4899b78aa594d"}),
}


def file_hash(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def model_directory(name: str, *, download: bool = False) -> Path:
    """Reuse the standard HF cache, including the already installed original models."""
    from huggingface_hub import snapshot_download
    model = MODELS[name]
    folder = Path(snapshot_download(model.repository, revision=model.revision,
                    allow_patterns=list(model.files), local_files_only=not download))
    for filename in model.files:
        path = folder / filename
        if not path.is_file():
            raise FileNotFoundError(f"{name} is incomplete; run scripts/setup_vision_models.py {name}")
        if filename in model.hashes and file_hash(path) != model.hashes[filename]:
            raise ValueError(f"{name}/{filename} SHA-256 mismatch; do not use this artifact")
    return folder


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Explicitly download and verify optional vision models; no inference")
    parser.add_argument("models", nargs="+", choices=tuple(MODELS))
    args = parser.parse_args()
    for name in args.models:
        model_directory(name, download=True)
        model = MODELS[name]
        print(f"Verified {name}: {model.repository}@{model.revision} ({model.license})")
    return 0
