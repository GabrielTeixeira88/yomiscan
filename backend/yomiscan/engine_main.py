"""Entry point of the packaged local engine (Stage 5b): the Torch-free backend with per-user paths.

The frozen build (scripts/build_engine.py) runs this module. Unlike the developer server, it
never reads the working directory: models and the dictionary live in the per-user model folder
(%LOCALAPPDATA%/YomiScan/models), the processing cache and glossaries in %LOCALAPPDATA%/YomiScan.
Explicit YOMISCAN_* variables still win. Nothing is downloaded here; readiness reports the
setup command (`yomiscan-engine --prepare` in this build) until the models are installed.
"""

import argparse
from importlib.metadata import version
import os

from .cli import DEFAULT_PORT

ENGINE_DEFAULTS = {"YOMISCAN_DETECTOR": "pinned", "YOMISCAN_OCR": "pinned", "YOMISCAN_TRANSLATION_ENGINE": "opus-pinned",
                   "YOMISCAN_PREPARE_COMMAND": "yomiscan-engine --prepare"}


def engine_environment(environment: dict[str, str]) -> dict[str, str]:
    """The variables the packaged engine sets when they are absent."""
    from .engine_models import data_root, load_bundle, models_root
    root = data_root(environment)
    defaults = {**ENGINE_DEFAULTS,
                "YOMISCAN_DICTIONARY": str(models_root(environment) / load_bundle().name / "dictionary" / "jmdict.sqlite3"),
                "YOMISCAN_CACHE_DIRECTORY": str(root / "cache" / "processing"),
                "YOMISCAN_GLOSSARY_DATABASE": str(root / "glossaries.sqlite3")}
    return {key: value for key, value in defaults.items() if not environment.get(key)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="yomiscan-engine", description="YomiScan local engine (Torch-free), on 127.0.0.1")
    parser.add_argument("--version", action="version", version=version("yomiscan"))
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"Loopback port (default {DEFAULT_PORT})")
    parser.add_argument("--device", choices=("auto", "cpu"), default=os.getenv("YOMISCAN_DEVICE", "auto"),
                        help="auto uses a DirectML GPU for detection when available; cpu forces the CPU")
    parser.add_argument("--prepare", action="store_true",
                        help="Download and verify the default models and dictionary (explicit; nothing downloads otherwise)")
    parser.add_argument("--component", choices=("ocr", "detection", "translation", "dictionary", "all"), default="all",
                        help="With --prepare: only this part")
    arguments = parser.parse_args(argv)
    if not 1024 <= arguments.port <= 65535:
        parser.error("Port must be between 1024 and 65535")
    os.environ.update(engine_environment(dict(os.environ)))
    if arguments.prepare:
        from .cli import prepare_defaults
        return prepare_defaults(["--component", arguments.component])
    os.environ["YOMISCAN_DEVICE"] = arguments.device
    import uvicorn
    from .api.main import app
    uvicorn.run(app, host="127.0.0.1", port=arguments.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
