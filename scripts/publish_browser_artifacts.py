"""Publish the browser-engine artifacts to Hugging Face and pin the revision in the extension (Stage 5a).

    uv run hf auth login                     # once, with a write token
    uv run python scripts/build_browser_artifacts.py
    uv run python scripts/publish_browser_artifacts.py --repo <user>/yomiscan-browser-models

Uploads .cache/browser-artifacts unchanged (files, manifest.json, model card, license texts),
then downloads every pinned file back through the public URL and checks its size and SHA-256.
Only then does it write extension/src/engine/artifact-host.json, so the extension's default
source is an immutable commit URL whose bytes are known to match the pinned manifest. The same
commit also serves the Torch-free local engine (Stage 5b): local-manifest.json is checked the
same way and backend/yomiscan/resources/engine/local-host.json gets the same pin.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
PINNED = ROOT / "extension" / "src" / "engine" / "artifact-manifest.json"
HOST = ROOT / "extension" / "src" / "engine" / "artifact-host.json"
LOCAL_PINNED = ROOT / "backend" / "yomiscan" / "resources" / "engine" / "local-manifest.json"
LOCAL_HOST = ROOT / "backend" / "yomiscan" / "resources" / "engine" / "local-host.json"
REPOSITORY = re.compile(r"^[\w.-]+/[\w.-]+$")
REVISION = re.compile(r"^[a-f0-9]{40}$")


def host_record(repository: str, revision: str) -> dict:
    if not REPOSITORY.match(repository) or not REVISION.match(revision):
        raise ValueError(f"Expected owner/name and a 40-character commit, got {repository!r} @ {revision!r}")
    return {"repository": repository, "revision": revision,
            "base": f"https://huggingface.co/{repository}/resolve/{revision}/"}


def check_folder(folder: Path, pinned: Path = PINNED, served_name: str = "manifest.json") -> dict:
    """The folder must hold exactly the manifest that is pinned in the repository."""
    served = folder / served_name
    if not served.is_file():
        raise FileNotFoundError(f"{served} is missing; run scripts/build_browser_artifacts.py first")
    manifest = json.loads(served.read_text(encoding="utf-8"))
    if manifest != json.loads(pinned.read_text(encoding="utf-8")):
        raise ValueError(f"{served} differs from {pinned}; rebuild the artifacts before publishing")
    for component in manifest["components"]:
        for file in component["files"]:
            path = folder / file["path"]
            if not path.is_file() or path.stat().st_size != file["bytes"]:
                raise ValueError(f"{path} is missing or not {file['bytes']} bytes; rebuild the artifacts")
    return manifest


def verify_remote(manifest: dict, base: str, opener=urlopen) -> int:
    """Download each pinned file from `base` and check size and SHA-256. Returns the bytes read."""
    total = 0
    for component in manifest["components"]:
        for file in component["files"]:
            digest, size = hashlib.sha256(), 0
            request = Request(base + file["path"], headers={"User-Agent": "yomiscan-artifact-check"})
            try:
                with opener(request, timeout=60) as response:
                    for chunk in iter(lambda: response.read(1 << 20), b""):
                        digest.update(chunk)
                        size += len(chunk)
            except OSError as error:
                raise RuntimeError(f"Could not download {file['path']} from {base}") from error
            if size != file["bytes"] or digest.hexdigest() != file["sha256"]:
                raise ValueError(f"{file['path']} at {base} does not match the pinned size/SHA-256")
            total += size
            print(f"  verified {file['path']} ({size / 2**20:.1f} MiB)")
    return total


def combined(*manifests: dict) -> dict:
    """One manifest with every distinct file, so shared files are downloaded and checked once."""
    seen: dict[str, dict] = {}
    for manifest in manifests:
        for component in manifest["components"]:
            for file in component["files"]:
                if seen.setdefault(file["path"], file) != file:
                    raise ValueError(f"{file['path']} has different pins in the browser and local manifests")
    return {"components": [{"id": "all", "files": list(seen.values())}]}


def publish(folder: Path, repository: str, private: bool) -> str:
    from huggingface_hub import HfApi
    from huggingface_hub.errors import HfHubHTTPError

    api = HfApi()
    manifest = check_folder(folder)
    try:
        api.create_repo(repository, repo_type="model", private=private, exist_ok=True)
        commit = api.upload_folder(repo_id=repository, repo_type="model", folder_path=folder,
                                   commit_message=f"Publish {manifest['bundle']}")
    except HfHubHTTPError as error:
        raise RuntimeError(f"Hugging Face upload to {repository} failed; check `uv run hf auth whoami` and the token's write access") from error
    revision = commit.oid
    if not revision or not REVISION.match(revision):
        # An upload with no changes returns no new commit; pin the repository's current head.
        revision = api.model_info(repository).sha
    return revision


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", required=True, help="Hugging Face model repository, owner/name")
    parser.add_argument("--folder", type=Path, default=ROOT / ".cache" / "browser-artifacts")
    parser.add_argument("--revision", help="Skip the upload and only verify and pin this existing commit")
    parser.add_argument("--private", action="store_true", help="Create the repository private (the extension cannot download it)")
    arguments = parser.parse_args(argv)
    if not REPOSITORY.match(arguments.repo):
        parser.error("--repo must look like owner/name")
    manifest = check_folder(arguments.folder)
    local = check_folder(arguments.folder, LOCAL_PINNED, "local-manifest.json")
    revision = arguments.revision or publish(arguments.folder, arguments.repo, arguments.private)
    record = host_record(arguments.repo, revision)
    print(f"Checking every pinned file at {record['base']}")
    total = verify_remote(combined(manifest, local), record["base"])
    for path in (HOST, LOCAL_HOST):
        path.write_text(json.dumps(record, indent=1) + "\n", encoding="utf-8")
    print(f"All {total / 2**20:.0f} MiB match. Wrote {HOST.relative_to(ROOT)} and {LOCAL_HOST.relative_to(ROOT)}; "
          "rebuild the extension.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
