"""Stage 5b increment 1: Torch-free vision readers and the shared pinned model store (no weights)."""

import hashlib
import io
import json
from pathlib import Path

import numpy as np
from PIL import Image
import pytest

from yomiscan import engine_models
from yomiscan.detection.pinned import PinnedComicTextDetector, detector_pixels, post_process
from yomiscan.ocr.pinned import PinnedMangaOCREngine, decode_tokens, ocr_pixels
from yomiscan.onnx_runtime import onnx_device

ROOT = Path(__file__).resolve().parents[2]


def test_local_pins_share_the_browser_commit_and_files():
    extension = ROOT / "extension" / "src" / "engine"
    assert engine_models.default_host() == json.loads((extension / "artifact-host.json").read_text(encoding="utf-8"))
    assert engine_models.default_source().startswith("https://huggingface.co/")
    browser = engine_models.load_bundle(extension / "artifact-manifest.json")
    local = engine_models.load_bundle()
    assert sorted(local.components) == ["detector-fp32", "ocr-int8", "translation-opus-ja-en-fp32"]
    assert local.components["ocr-int8"] == browser.components["ocr-int8"]
    assert {f.path for f in local.components["detector-fp32"].files} == {"detector-fp32/detector.onnx"}


def _bundle(tmp_path: Path, files: dict[str, bytes]) -> engine_models.Bundle:
    manifest = {"schema": 1, "bundle": "test-bundle", "components": [{
        "id": "detector", "kind": "detector", "variant": "fp16", "license": "Apache-2.0", "source": "test",
        "files": [{"path": p, "bytes": len(b), "sha256": hashlib.sha256(b).hexdigest()} for p, b in files.items()]}]}
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return engine_models.load_bundle(path)


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def test_download_verifies_keeps_finished_files_and_never_keeps_bad_bytes(tmp_path):
    files = {"detector/a.onnx": b"alpha", "detector/b.onnx": b"bravo"}
    bundle = _bundle(tmp_path, files)
    served, requested = dict(files), []

    def opener(request, timeout):
        requested.append(request.full_url)
        return _Response(served[request.full_url.removeprefix("https://host/")])

    root = tmp_path / "models"
    with pytest.raises(FileNotFoundError, match="yomiscan-prepare-engine detector"):
        engine_models.component_directory("detector", bundle=bundle, root=root)
    folder = engine_models.download_components(["detector"], source="https://host", bundle=bundle, root=root, opener=opener)
    assert folder == root / "test-bundle" and (folder / "detector" / "b.onnx").read_bytes() == b"bravo"
    assert engine_models.component_directory("detector", bundle=bundle, root=root) == folder
    requested.clear()
    engine_models.download_components(["detector"], source="https://host/", bundle=bundle, root=root, opener=opener)
    assert requested == []  # verified files are skipped

    (folder / "detector" / "b.onnx").write_bytes(b"BRAVO")  # damaged: same size, wrong hash
    with pytest.raises(FileNotFoundError):
        engine_models.component_directory("detector", bundle=bundle, root=root)
    served["detector/b.onnx"] = b"bravX"
    with pytest.raises(ValueError, match="does not match"):
        engine_models.download_components(["detector"], source="https://host/", bundle=bundle, root=root, opener=opener)
    assert not (folder / "detector" / "b.onnx.part").exists()
    assert requested == ["https://host/detector/b.onnx"]


def test_download_failure_keeps_the_cause(tmp_path):
    bundle = _bundle(tmp_path, {"detector/a.onnx": b"alpha"})

    def opener(request, timeout):
        raise OSError("connection reset")

    with pytest.raises(RuntimeError, match="Could not download detector/a.onnx") as caught:
        engine_models.download_components(["detector"], source="https://host/", bundle=bundle, root=tmp_path, opener=opener)
    assert isinstance(caught.value.__cause__, OSError)


def test_manifest_rejects_paths_outside_the_bundle(tmp_path):
    with pytest.raises(ValueError, match="unsafe path"):
        _bundle(tmp_path, {"../escape.onnx": b"x"})


def test_models_root_and_readiness_view(tmp_path):
    assert engine_models.models_root({"YOMISCAN_ENGINE_MODELS": str(tmp_path)}) == tmp_path
    assert engine_models.models_root({"LOCALAPPDATA": str(tmp_path)}) == tmp_path / "YomiScan" / "models"
    bundle = _bundle(tmp_path, {"detector/a.onnx": b"alpha"})
    environment = {"YOMISCAN_ENGINE_MODELS": str(tmp_path / "m")}
    assert engine_models.installed_files("detector", environment, bundle) == ([], False)
    target = tmp_path / "m" / "test-bundle" / "detector" / "a.onnx"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"alpha")
    assert engine_models.installed_files("detector", environment, bundle) == ([target], True)


def test_readiness_selects_and_inspects_pinned_engines(tmp_path):
    from yomiscan.readiness import local_artifacts, model_catalog, selected_models
    assert selected_models({"YOMISCAN_OCR": "pinned", "YOMISCAN_DETECTOR": "pinned"}) == {
        "ocr": "ocr-pinned", "detection": "detector-pinned", "translation": "current"}
    catalog = {spec.id: spec for spec in model_catalog()}
    spec = catalog["ocr-pinned"]
    assert spec.kind == "ocr" and spec.setup_command == "yomiscan-prepare-engine ocr-int8"
    assert catalog["detector-pinned"].setup_command == "yomiscan-prepare-engine detector-fp32"
    assert spec.model == engine_models.default_host()["repository"]
    assert local_artifacts(spec, {"YOMISCAN_ENGINE_MODELS": str(tmp_path)}) == ([], False)


def test_onnx_device_mapping():
    assert onnx_device("cpu", {"YOMISCAN_ONNX_DEVICE": "directml"}) == "cpu"
    assert onnx_device("auto", {}) == "cpu"
    assert onnx_device("auto", {"YOMISCAN_ONNX_DEVICE": "directml"}) == "directml"
    with pytest.raises(ValueError, match="no CUDA path"):
        onnx_device("cuda", {})
    with pytest.raises(ValueError):
        onnx_device("auto", {"YOMISCAN_ONNX_DEVICE": "tpu"})


def test_detector_matches_transformers_preprocessing_and_post_processing():
    torch = pytest.importorskip("torch")
    transformers = pytest.importorskip("transformers")
    processor = transformers.RTDetrImageProcessorPil()  # configuration only, no weights
    rng = np.random.default_rng(7)
    image = Image.fromarray(rng.integers(0, 256, (333, 517, 3), dtype=np.uint8))
    expected = processor(images=image, return_tensors="np")["pixel_values"]
    assert np.array_equal(detector_pixels(image), expected.astype(np.float32))

    logits = rng.normal(-2, 2, (1, 300, 3)).astype(np.float32)
    boxes = rng.uniform(.05, .6, (1, 300, 4)).astype(np.float32)

    class Outputs:
        pass
    outputs = Outputs()
    outputs.logits, outputs.pred_boxes = torch.from_numpy(logits), torch.from_numpy(boxes)
    reference = processor.post_process_object_detection(outputs, threshold=.5, target_sizes=[(image.height, image.width)])[0]
    found_boxes, found_scores, found_labels = post_process(logits, boxes, image.size, .5)
    assert found_labels == reference["labels"].tolist()
    # Torch's vectorized sigmoid differs from NumPy by up to 2 float32 ulps; only scores within
    # about 1e-7 of the threshold could change a decision.
    assert found_scores == pytest.approx(reference["scores"].tolist(), rel=1e-6, abs=0)
    assert found_boxes == reference["boxes"].tolist()


class _Input:
    def __init__(self, name):
        self.name = name


class _DetectorSession:
    def get_inputs(self):
        return [_Input("pixel_values")]

    def get_outputs(self):
        return [_Input("logits"), _Input("pred_boxes")]

    def run(self, names, feed):
        assert feed["pixel_values"].shape == (1, 3, 640, 640)
        logits = np.full((1, 300, 3), -10, dtype=np.float32)
        boxes = np.full((1, 300, 4), .1, dtype=np.float32)
        logits[0, 0, 0] = 5   # bubble outline (class 0): dropped
        logits[0, 1, 1] = 3    # text bubble
        boxes[0, 1] = [.5, .25, .25, .125]
        logits[0, 2, 2] = -.1  # free text below threshold
        logits[0, 3, 2] = 2    # free text, higher on the page
        boxes[0, 3] = [.25, .125, .125, .125]
        return [logits, boxes]


def test_pinned_detector_returns_ordered_text_regions():
    detector = PinnedComicTextDetector(session=_DetectorSession())
    regions = detector.detect(Image.new("RGB", (200, 400), "white"))
    assert [(r.id, r.metadata["class"], r.bbox.coordinates()) for r in regions] == [
        (1, "text_free", (37, 25, 63, 75)), (2, "text_bubble", (75, 75, 125, 125))]
    assert detector.diagnostic_metadata()["engine"] == "pinned-onnx"


class _Encoder:
    def run(self, names, feed):
        assert feed["pixel_values"].shape == (1, 3, 224, 224)
        return [np.zeros((1, 197, 4), dtype=np.float32)]


class _Decoder:
    def __init__(self, script):
        self.script, self.calls = script, []

    def run(self, names, feed):
        ids = feed["input_ids"]
        self.calls.append(ids.shape[1])
        logits = np.zeros((1, ids.shape[1], 8), dtype=np.float32)
        logits[0, -1, self.script[min(ids.shape[1] - 1, len(self.script) - 1)]] = 1
        return [logits]


VOCABULARY = ["[PAD]", "[UNK]", "[CLS]", "[SEP]", "ク", "##ン", "A", "…"]
GENERATION = {"decoder_start_token_id": 2, "eos_token_id": 3, "max_length": 300}


def test_pinned_ocr_greedy_decoding_and_text_convention():
    decoder = _Decoder([4, 5, 6, 1, 7, 7, 3])
    engine = PinnedMangaOCREngine(encoder=_Encoder(), decoder=decoder, vocabulary=VOCABULARY, generation=GENERATION)
    result = engine.recognize(Image.new("RGB", (40, 90), "white"))
    # ## joins subwords, [UNK] is skipped like skip_special_tokens, ASCII becomes full width, … becomes ...
    assert result.text == "クンＡ．．．．．．" and result.engine == "manga-ocr"
    assert decoder.calls == [1, 2, 3, 4, 5, 6, 7]
    assert decode_tokens([2, 4, 3], VOCABULARY) == "ク"


def test_pinned_ocr_stops_at_max_length():
    decoder = _Decoder([4])
    engine = PinnedMangaOCREngine(encoder=_Encoder(), decoder=decoder, vocabulary=VOCABULARY,
                                  generation={**GENERATION, "max_length": 5})
    assert engine.recognize(Image.new("RGB", (10, 10))).text == "クククク"
    assert decoder.calls == [1, 2, 3, 4]


def test_ocr_pixels_match_vit_processor():
    transformers = pytest.importorskip("transformers")
    processor = transformers.ViTImageProcessorPil(size={"height": 224, "width": 224}, resample=2,
                                                  image_mean=[.5, .5, .5], image_std=[.5, .5, .5])
    image = Image.fromarray(np.random.default_rng(3).integers(0, 256, (61, 143, 3), dtype=np.uint8))
    expected = processor(images=image.convert("L").convert("RGB"), return_tensors="np")["pixel_values"]
    assert np.allclose(ocr_pixels(image), expected, atol=1e-6)
