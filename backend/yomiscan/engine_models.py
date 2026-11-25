"""Pinned models for the Torch-free local engine (Stage 5b).

They live in the same Hugging Face repository and commit as the browser engine's bundle.
`resources/engine/local-manifest.json` pins each file's size and SHA-256 (written by
scripts/build_browser_artifacts.py; files shared with the browser bundle keep identical pins),
and `local-host.json` pins the commit (written by scripts/publish_browser_artifacts.py after it
re-verified every file). Downloads happen only through `download_components` (an explicit setup
command); inference calls `component_directory`, which verifies and never fetches.
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

RESOURCES = Path(__file__).parent / "resources" / "engine"
CHUNK = 1 << 20


@dataclass(frozen=True)
class PinnedFile:
    path: str
    bytes: int
    sha256: str


@dataclass(frozen=True)
class Component:
    id: str
    kind: str
    variant: str
    license: str
    source: str
    files: tuple[PinnedFile, ...]

    @property
    def size(self) -> int:
        return sum(file.bytes for file in self.files)


@dataclass(frozen=True)
class Bundle:
    name: str
    components: dict[str, Component]


def load_bundle(path: Path = RESOURCES / "local-manifest.json") -> Bundle:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("schema") != 1:
        raise ValueError(f"Unsupported engine manifest schema in {path}")
    components = {}
    for raw in manifest["components"]:
        files = tuple(PinnedFile(f["path"], int(f["bytes"]), f["sha256"]) for f in raw["files"])
        if not files or any(Path(f.path).is_absolute() or ".." in Path(f.path).parts for f in files):
            raise ValueError(f"Engine component {raw['id']} has no files or an unsafe path")
        components[raw["id"]] = Component(raw["id"], raw["kind"], raw["variant"], raw["license"], raw["source"], files)
    return Bundle(manifest["bundle"], components)


def default_source(path: Path = RESOURCES / "local-host.json") -> str:
    """The pinned download base (an immutable Hugging Face resolve/<commit>/ URL)."""
    base = default_host(path)["base"]
    if not base:
        raise ValueError(f"{path} has no download base")
    return base


def default_host(path: Path = RESOURCES / "local-host.json") -> dict[str, str | None]:
    return json.loads(path.read_text(encoding="utf-8"))


def installed_files(component_id: str, environment: dict[str, str] | None = None,
                    bundle: Bundle | None = None) -> tuple[list[Path], bool]:
    """Readiness view: present files and whether every one has its pinned size (SHA-256 is checked at load)."""
    bundle = bundle or load_bundle()
    folder = models_root(environment) / bundle.name
    paths = [folder / f.path for f in bundle.components[component_id].files]
    present = [p for p in paths if p.is_file()]
    complete = all(p.is_file() and p.stat().st_size == f.bytes
                   for p, f in zip(paths, bundle.components[component_id].files, strict=True))
    return present, complete


def models_root(environment: dict[str, str] | None = None) -> Path:
    environment = dict(os.environ) if environment is None else environment
    if environment.get("YOMISCAN_ENGINE_MODELS"):
        return Path(environment["YOMISCAN_ENGINE_MODELS"])
    if environment.get("LOCALAPPDATA"):
        return Path(environment["LOCALAPPDATA"]) / "YomiScan" / "models"
    return Path.home() / ".cache" / "yomiscan" / "models"


def file_digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _verified(folder: Path, file: PinnedFile) -> bool:
    path = folder / file.path
    return path.is_file() and path.stat().st_size == file.bytes and file_digest(path) == file.sha256


def component_directory(component_id: str, *, bundle: Bundle | None = None, root: Path | None = None) -> Path:
    """The verified folder holding one installed component; never downloads."""
    bundle = bundle or load_bundle()
    if component_id not in bundle.components:
        raise KeyError(f"Unknown engine component {component_id!r}; choose {sorted(bundle.components)}")
    folder = (root or models_root()) / bundle.name
    for file in bundle.components[component_id].files:
        if not _verified(folder, file):
            raise FileNotFoundError(
                f"Engine model {component_id} is missing or damaged ({file.path} in {folder}). "
                f"Run: uv run yomiscan-prepare-engine {component_id}")
    return folder


Opener = Callable[..., Any]


def download_components(component_ids: Iterable[str], *, source: str | None = None, bundle: Bundle | None = None,
                        root: Path | None = None, opener: Opener = urlopen,
                        progress: Callable[[str, int], None] | None = None) -> Path:
    """Download and verify components. Finished, verified files are kept and skipped."""
    bundle = bundle or load_bundle()
    source = source or default_source()
    if not source.endswith("/"):
        source += "/"
    folder = (root or models_root()) / bundle.name
    for component_id in component_ids:
        if component_id not in bundle.components:
            raise KeyError(f"Unknown engine component {component_id!r}; choose {sorted(bundle.components)}")
        for file in bundle.components[component_id].files:
            if _verified(folder, file):
                continue
            target = folder / file.path
            target.parent.mkdir(parents=True, exist_ok=True)
            partial = target.with_name(target.name + ".part")
            digest, size = hashlib.sha256(), 0
            request = Request(source + file.path, headers={"User-Agent": "yomiscan-engine-setup"})
            try:
                with opener(request, timeout=60) as response, partial.open("wb") as stream:
                    for chunk in iter(lambda: response.read(CHUNK), b""):
                        size += len(chunk)
                        if size > file.bytes:
                            break
                        digest.update(chunk)
                        stream.write(chunk)
                        if progress:
                            progress(file.path, size)
            except OSError as error:
                partial.unlink(missing_ok=True)
                raise RuntimeError(f"Could not download {file.path} from {source}; check the connection and try again") from error
            if size != file.bytes or digest.hexdigest() != file.sha256:
                partial.unlink(missing_ok=True)
                raise ValueError(f"{file.path} from {source} does not match the pinned size/SHA-256; nothing was kept")
            partial.replace(target)
    return folder


def main(argv: list[str] | None = None) -> int:
    import argparse
    bundle = load_bundle()
    parser = argparse.ArgumentParser(description="Explicitly download and verify Torch-free engine models (no inference)")
    parser.add_argument("components", nargs="+", choices=sorted(bundle.components))
    parser.add_argument("--source", help="Download base URL (default: the pinned Hugging Face commit)")
    arguments = parser.parse_args(argv)
    total = sum(bundle.components[c].size for c in arguments.components)
    print(f"Downloading {total / 2**20:.0f} MiB of {bundle.name} to {models_root() / bundle.name}")
    folder = download_components(arguments.components, source=arguments.source, bundle=bundle)
    for component_id in arguments.components:
        component = bundle.components[component_id]
        print(f"Verified {component_id} ({component.variant}, {component.license}) in {folder}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
