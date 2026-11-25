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
    for component in (*builder.components(paths["stage2"], paths["dictionary"], paths["tokenizer"]),
                      *builder.local_components(paths["stage2"])):
        for source, _ in component.files:
            assert root in source.parents
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_bytes(f"fake {source.name} {component.id}".encode())
    return paths


def test_builder_copies_exports_and_pins_size_and_sha256(tmp_path):
    paths, output, pinned = fake_inputs(tmp_path), tmp_path / "out", tmp_path / "pinned.json"
    manifest = builder.build(paths["stage2"], output, pinned, paths["dictionary"], paths["tokenizer"])
    assert json.loads(pinned.read_text(encoding="utf-8")) == manifest == json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert [c["id"] for c in manifest["components"]] == ["detector", "ocr-q4", "ocr-int8", "tokenizer", "dictionary", "translation-opus-ja-en"]
    for component in manifest["components"]:
        for entry in component["files"]:
            data = (output / entry["path"]).read_bytes()
            assert entry["bytes"] == len(data) and entry["sha256"] == hashlib.sha256(data).hexdigest()
    local = json.loads((tmp_path / "local-manifest.json").read_text(encoding="utf-8"))
    assert local == json.loads((output / "local-manifest.json").read_text(encoding="utf-8"))
    assert local["bundle"] == builder.LOCAL_BUNDLE and [c["id"] for c in local["components"]] == ["detector-fp32", "translation-opus-ja-en-fp32", "ocr-int8"]
    assert local["components"][2] == manifest["components"][2]  # shared files keep identical pins
    assert (output / "detector-fp32" / "detector.onnx").is_file()


def test_builder_refuses_missing_exports_without_writing_a_manifest(tmp_path):
    with pytest.raises(FileNotFoundError, match="research/stage-2"):
        builder.build(tmp_path / "missing", tmp_path / "out", tmp_path / "pinned.json", tmp_path / "none.sqlite3", tmp_path / "none.wasm")
    assert not (tmp_path / "pinned.json").exists()


def test_committed_manifests_match_the_engine_contracts():
    for pinned in (builder.PINNED, builder.LOCAL_PINNED):
        manifest = json.loads(pinned.read_text(encoding="utf-8"))
        assert manifest["schema"] == 1
        for component in manifest["components"]:
            assert component["files"] and all(len(f["sha256"]) == 64 and f["bytes"] > 0 and ".." not in f["path"] for f in component["files"])


def test_builder_writes_the_model_card_and_license_texts(tmp_path):
    paths, output = fake_inputs(tmp_path), tmp_path / "out"
    manifest = builder.build(paths["stage2"], output, tmp_path / "pinned.json", paths["dictionary"], paths["tokenizer"])
    card = (output / "README.md").read_text(encoding="utf-8")
    assert f"# YomiScan browser models ({manifest['bundle']})" in card and "$" not in card
    assert card.count("\n| `") == len(manifest["components"]) + 2  # plus the local engine's fp32 detector and translator
    assert "`detector-fp32` (fp32)" in card and builder.LOCAL_BUNDLE in card
    assert "CC BY-SA 4.0" in card and "UniDic Consortium" in card and "Electronic Dictionary Research" in card
    assert sorted(p.name for p in (output / "LICENSES").iterdir()) == ["Apache-2.0.txt", "UniDic-BSD-3-Clause.txt", "lindera-MIT.txt"]


spec = importlib.util.spec_from_file_location("publish_browser_artifacts", ROOT / "scripts" / "publish_browser_artifacts.py")
publisher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publisher)


def test_published_source_is_an_immutable_commit_url():
    record = publisher.host_record("owner/yomiscan-browser-models", "a" * 40)
    assert record["base"] == f"https://huggingface.co/owner/yomiscan-browser-models/resolve/{'a' * 40}/"
    for repository, revision in (("owner/name", "main"), ("no-owner", "a" * 40), ("owner/name/../x", "a" * 40)):
        with pytest.raises(ValueError):
            publisher.host_record(repository, revision)


def test_publisher_refuses_a_folder_that_differs_from_the_pinned_manifest(tmp_path):
    paths, output, pinned = fake_inputs(tmp_path), tmp_path / "out", tmp_path / "pinned.json"
    builder.build(paths["stage2"], output, pinned, paths["dictionary"], paths["tokenizer"])
    assert publisher.check_folder(output, pinned)["bundle"] == builder.BUNDLE
    local = publisher.check_folder(output, tmp_path / "local-manifest.json", "local-manifest.json")
    assert local["bundle"] == builder.LOCAL_BUNDLE
    files = publisher.combined(json.loads(pinned.read_text(encoding="utf-8")), local)["components"][0]["files"]
    assert len(files) == len({f["path"] for f in files}) and "detector-fp32/detector.onnx" in {f["path"] for f in files}
    (output / "detector" / "detector-fp16.onnx").write_bytes(b"changed size")
    with pytest.raises(ValueError, match="rebuild"):
        publisher.check_folder(output, pinned)
    pinned.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="differs"):
        publisher.check_folder(output, pinned)


def test_remote_check_reads_every_file_and_rejects_swapped_bytes(tmp_path):
    import io
    paths, output, pinned = fake_inputs(tmp_path), tmp_path / "out", tmp_path / "pinned.json"
    manifest = builder.build(paths["stage2"], output, pinned, paths["dictionary"], paths["tokenizer"])
    base, served = "https://host/x/", {}
    opener = lambda request, timeout: io.BytesIO(served.get(request.full_url, (output / request.full_url[len(base):]).read_bytes()))
    expected = sum(f["bytes"] for c in manifest["components"] for f in c["files"])
    assert publisher.verify_remote(manifest, base, opener) == expected
    served[base + "detector/detector-fp16.onnx"] = b"x" * manifest["components"][0]["files"][0]["bytes"]
    with pytest.raises(ValueError, match="detector-fp16.onnx"):
        publisher.verify_remote(manifest, base, opener)
