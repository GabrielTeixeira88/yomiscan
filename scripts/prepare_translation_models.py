"""Explicit opt-in, pinned model downloads; never called during application startup."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from huggingface_hub import hf_hub_download, snapshot_download
from yomiscan.translation.manga import HY_MODEL, HY_REVISION, Q25_MODEL, Q25_REVISION, Q25_BASE, Q25_BASE_REVISION
from yomiscan.translation.nmt import NMT_MODELS


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", required=True, choices=("hy-mt2-manga", "qwen25-manga", *NMT_MODELS))
    parser.add_argument("--llama-source", type=Path, help="For Qwen: official llama.cpp b11380 checkout (converter plus gguf-py)")
    parser.add_argument("--output-dir", type=Path, default=Path("models/manga"))
    args = parser.parse_args()
    if args.engine in NMT_MODELS:
        spec = NMT_MODELS[args.engine]
        print(f"Preparing {spec.model} ({spec.license}); model license is separate from YomiScan MIT.")
        path = snapshot_download(spec.model, revision=spec.revision,
                                 allow_patterns=["*.json", "*.spm", "*.model", "pytorch_model.bin", "README.md"])
        print(f"Cached {spec.revision} at {path}. Select --engine {args.engine}; no llama.cpp runtime needed.")
        return
    args.output_dir.mkdir(parents=True, exist_ok=True)
    if args.engine == "hy-mt2-manga":
        path = Path(hf_hub_download(HY_MODEL, "manga-v5-Q4_K_M.gguf", revision=HY_REVISION))
        with path.open("rb") as stream:
            checksum = hashlib.file_digest(stream, "sha256").hexdigest()
        if checksum != "e4ed3cf8535c4e99e4b9f3d930ecc6f93bc3b3e0b4b5edca872c4cff5a112abe":
            raise RuntimeError("Hy-MT2 artifact checksum mismatch")
        settings = {"YOMISCAN_HY_MT2_GGUF": str(path)}
    else:
        if args.llama_source is None or not (args.llama_source / "convert_lora_to_gguf.py").is_file():
            parser.error("Qwen requires --llama-source pointing to an official b11380 checkout")
        revision = subprocess.check_output(["git", "-C", str(args.llama_source), "rev-parse", "HEAD"], text=True).strip()
        if revision != "eec18f5d32099fb15d4ba15003a231bcc72757d5":
            parser.error("Use the documented llama.cpp b11380 commit for reproducible conversion")
        base_repo, base_revision = "Qwen/Qwen2.5-7B-Instruct-GGUF", "bb5d59e06d9551d752d08b292a50eb208b07ab1f"
        paths = [hf_hub_download(base_repo, f"qwen2.5-7b-instruct-q4_k_m-0000{i}-of-00002.gguf", revision=base_revision) for i in (1, 2)]
        adapter = snapshot_download(Q25_MODEL, revision=Q25_REVISION)
        config = Path(hf_hub_download(Q25_BASE, "config.json", revision=Q25_BASE_REVISION)).parent
        output = args.output_dir.resolve() / "qwen25-manga-lora-f16.gguf"
        subprocess.run([sys.executable, str(args.llama_source / "convert_lora_to_gguf.py"), adapter,
                        "--base", str(config), "--outtype", "f16", "--outfile", str(output)], check=True)
        settings = {"YOMISCAN_QWEN25_GGUF": paths[0], "YOMISCAN_QWEN25_LORA": str(output)}
    path = args.output_dir / (args.engine + "-paths.json")
    path.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    print(json.dumps(settings, indent=2))
    print(f"Saved paths to {path}; set these environment variables plus YOMISCAN_LLAMA_SERVER.")


if __name__ == "__main__":
    main()
