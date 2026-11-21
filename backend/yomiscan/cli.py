"""Small installable entry points; serving remains bound to localhost."""

import argparse
from importlib.metadata import version
import os


def server_main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Serve YomiScan on 127.0.0.1; inspect /api/v1/readiness for setup")
    parser.add_argument("--version", action="version", version=version("yomiscan"))
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--dictionary", default=os.getenv("YOMISCAN_DICTIONARY", "data/jmdict.sqlite3"))
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default=os.getenv("YOMISCAN_DEVICE", "auto"))
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("Port must be between 1 and 65535")
    os.environ["YOMISCAN_DICTIONARY"], os.environ["YOMISCAN_DEVICE"] = args.dictionary, args.device
    import uvicorn
    uvicorn.run("yomiscan.api.main:app", host="127.0.0.1", port=args.port)


def prepare_defaults(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Explicitly download selected pinned production artifacts; no inference")
    parser.add_argument("--component", choices=("ocr", "detection", "translation", "all"), default="all")
    args = parser.parse_args(argv)
    from huggingface_hub import snapshot_download
    from .readiness import model_catalog
    from .vision_models import model_directory
    components = ("ocr", "detection", "translation") if args.component == "all" else (args.component,)
    for component in components:
        if component == "ocr":
            model_directory("ocr-original", download=True)
        else:
            spec = next(m for m in model_catalog() if m.id == ("current" if component == "translation" else "detector-current"))
            weight = "pytorch_model.bin" if component == "translation" else "model.safetensors"
            snapshot_download(spec.model, revision=spec.revision,
                allow_patterns=[*spec.files, weight, "generation_config.json", "tokenizer_config.json", "special_tokens_map.json", "README.md", "LICENSE*"])
        print("Prepared pinned "+component+" artifacts; licenses remain separate from YomiScan MIT.")
    return 0
