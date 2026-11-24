"""The browser-engine artifact builder pins exact sizes and hashes (no model weights needed)."""
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("build_browser_artifacts", ROOT / "scripts" / "build_browser_artifacts.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


def fake_inputs(root: Path) -> dict[str, Path]:
    """Every input lives under the test folder; real exports, node_modules and data/ are never touched."""
    paths = {"stage2": root / "stage2", "dictionary": root / "jmdict.sqlite3", "tokenizer": root / "lindera.wasm"}
    for component in builder.components(paths["stage2"], paths["dictionary"], paths["tokenizer"]):
        for source, _ in component.files:
            assert root in source.parents
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_bytes(f"fake {source.name} {component.id}".encode())
    return paths


def test_builder_copies_exports_and_pins_size_and_sha256(tmp_path):
    paths, output, pinned = fake_inputs(tmp_path), tmp_path / "out", tmp_path / "pinned.json"
    manifest = builder.build(paths["stage2"], output, pinned, paths["dictionary"], paths["tokenizer"])
    assert json.loads(pinned.read_text(encoding="utf-8")) == manifest == json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert [c["id"] for c in manifest["components"]] == ["detector", "ocr-q4", "ocr-int8", "tokenizer", "dictionary"]
    for component in manifest["components"]:
        for entry in component["files"]:
            data = (output / entry["path"]).read_bytes()
            assert entry["bytes"] == len(data) and entry["sha256"] == hashlib.sha256(data).hexdigest()


def test_builder_refuses_missing_exports_without_writing_a_manifest(tmp_path):
    with pytest.raises(FileNotFoundError, match="research/stage-2"):
        builder.build(tmp_path / "missing", tmp_path / "out", tmp_path / "pinned.json", tmp_path / "none.sqlite3", tmp_path / "none.wasm")
    assert not (tmp_path / "pinned.json").exists()


def test_committed_manifest_matches_the_extension_contract():
    manifest = json.loads(builder.PINNED.read_text(encoding="utf-8"))
    assert manifest["schema"] == 1
    for component in manifest["components"]:
        assert component["files"] and all(len(f["sha256"]) == 64 and f["bytes"] > 0 and ".." not in f["path"] for f in component["files"])
