"""Small installable entry points; serving remains bound to localhost."""

import argparse
from importlib.metadata import version
import os

# Not 8765: that is AnkiConnect's default port, often running beside YomiScan.
DEFAULT_PORT = 47615


def server_main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Serve YomiScan on 127.0.0.1; inspect /api/v1/readiness for setup")
    parser.add_argument("--version", action="version", version=version("yomiscan"))
    parser.add_argument("--port", type=int, default=DEFAULT_PORT,
                        help=f"Loopback port (default {DEFAULT_PORT}; must match the extension's Setup & readiness port)")
    from .engine_models import default_dictionary
    parser.add_argument("--dictionary", default=str(default_dictionary()),
                        help="JMdict SQLite (default: YOMISCAN_DICTIONARY, else data/jmdict.sqlite3 if present, else the downloaded one)")
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default=os.getenv("YOMISCAN_DEVICE", "auto"))
    args = parser.parse_args(argv)
    if not 1024 <= args.port <= 65535:
        parser.error("Port must be between 1024 and 65535")
    os.environ["YOMISCAN_DICTIONARY"], os.environ["YOMISCAN_DEVICE"] = args.dictionary, args.device
    import uvicorn
    uvicorn.run("yomiscan.api.main:app", host="127.0.0.1", port=args.port)


def prepare_defaults(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Explicitly download and verify the default engine models; no inference")
    parser.add_argument("--component", choices=("ocr", "detection", "translation", "dictionary", "all"), default="all")
    parser.add_argument("--reference", action="store_true",
                        help="Prepare the PyTorch reference artifacts instead (needs the `reference` dependency group)")
    args = parser.parse_args(argv)
    if not args.reference:
        from .engine_models import download_components, load_bundle, models_root
        from .readiness import ENGINE_DEFAULTS
        selected = [component for _, kind, component in ENGINE_DEFAULTS if args.component in (kind, "all")]
        selected += ["dictionary"] if args.component in ("dictionary", "all") else []
        bundle = load_bundle()
        print(f"Downloading {sum(bundle.components[c].size for c in selected) / 2**20:.0f} MiB to {models_root() / bundle.name}")
        download_components(selected, bundle=bundle)
        print("Prepared and verified " + ", ".join(selected) + "; licenses remain separate from YomiScan MIT.")
        return 0
    if args.component == "dictionary":
        parser.error("The reference path has no dictionary download; use yomiscan-import-jmdict")
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
