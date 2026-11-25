from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from io import BytesIO
import json
from pathlib import Path
from threading import Event
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from test_processing_cache import resources, page
from yomiscan.api.main import create_app
from yomiscan.progress import JobRegistry
from yomiscan.readiness import readiness_snapshot, require_local_models, SetupUnavailable, model_catalog, local_artifacts

HEADERS = {"X-YomiScan-Client": "study-extension-v1"}


@pytest.mark.reference
def test_detector_readiness_requires_the_safetensors_artifact_used_by_its_loader(monkeypatch, tmp_path):
    import huggingface_hub
    for name in ("config.json", "preprocessor_config.json", "pytorch_model.bin"):
        (tmp_path/name).write_bytes(b"fixture")
    monkeypatch.setattr(huggingface_hub, "try_to_load_from_cache", lambda model, name, **kw: str(tmp_path/name) if (tmp_path/name).is_file() else None)
    detector = next(spec for spec in model_catalog() if spec.id == "detector-current")
    assert local_artifacts(detector, {})[1] is False
    (tmp_path/"model.safetensors").write_bytes(b"fixture")
    assert local_artifacts(detector, {})[1] is True


def test_registry_is_bounded_expiring_and_distinguishes_cache_from_computation():
    jobs = JobRegistry(capacity=2)
    first, second, third = (str(uuid4()) for _ in range(3))
    update = jobs.start(first)
    update("ocr", "cached", None)
    assert jobs.snapshot(first)["stages"]["ocr"]["state"] == "cached"
    update("ocr", "running", None);update("ocr", "completed", 12);update("ocr", "cached", None)
    assert jobs.snapshot(first)["stages"]["ocr"] == {"state": "completed", "computed": True, "cache_hits": 2, "compute_ms": 12, "failures": 0}
    update("ocr", "failed", None);update("ocr", "cached", None)
    assert jobs.snapshot(first)["stages"]["ocr"]["state"] == "failed"
    jobs.finish(first, "cancelled")
    jobs.start(second);jobs.start(third)
    assert jobs.snapshot(first) is None
    with pytest.raises(ValueError): jobs.start(str(uuid4()))
    jobs.finish(second, "failed");jobs.retention_seconds=0
    assert jobs.snapshot(second) is None
    assert JobRegistry().instance != jobs.instance


@pytest.mark.reference
def test_readiness_uses_only_local_metadata_preserves_paths_and_reports_capabilities(monkeypatch, tmp_path):
    import huggingface_hub
    monkeypatch.setattr(huggingface_hub, "snapshot_download", lambda *a, **k: pytest.fail("readiness must not download"))
    monkeypatch.setattr(huggingface_hub, "hf_hub_download", lambda *a, **k: pytest.fail("readiness must not download"))
    monkeypatch.setattr("yomiscan.readiness.local_artifacts", lambda spec, environment: ([], False))
    environment = {"YOMISCAN_DICTIONARY": str(tmp_path/"private"/"missing.sqlite3"), "YOMISCAN_TRANSLATION_ENGINE": "nllb-600m",
                   "YOMISCAN_DEVICE": "cpu", "YOMISCAN_LLAMA_SERVER": str(tmp_path/"secret"/"missing.exe")}
    result = readiness_snapshot(initialization="failed", busy=False, environment=environment)
    selected = next(m for m in result["models"] if m["id"] == "nllb-600m")
    assert selected["selected"] and not selected["installed"] and not selected["loaded"]
    assert selected["targets"] == ("en", "pt-BR", "es") and selected["license"] == "CC-BY-NC-4.0"
    assert any("Brazilian" in text for text in selected["warnings"])
    assert "secret" not in json.dumps(result) and str(tmp_path) not in json.dumps(result)
    assert not result["dictionary"]["installed"]
    for changes in ({"YOMISCAN_DEVICE": "bogus"}, {"YOMISCAN_TRANSLATION_ENGINE": "private/unknown"},
                    {"YOMISCAN_TRANSLATION_ENGINE": "ocr-current"}, {"YOMISCAN_TRANSLATION_ENGINE": "detector-current"}, {"YOMISCAN_OCR": "missing"}):
        bad = readiness_snapshot(initialization="failed", busy=False, environment=environment|changes)
        assert not bad["configuration_valid"]
        with pytest.raises(SetupUnavailable) as error:
            require_local_models(environment | changes)
        assert error.value.code == "invalid_configuration"
    assert bad["selected"]["ocr"] == "invalid"
    rejected = readiness_snapshot(initialization="failed", busy=False, failure_code="unsupported_device", environment={"YOMISCAN_DEVICE": "cuda"})
    assert not next(m for m in rejected["models"] if m["selected"])["compatible"]
    assert rejected["storage"]["processing_cache"]["persistent_enabled"] is None
    observed = readiness_snapshot(initialization="ready", busy=True, environment=environment,
        loaded={"processing_cache": {"persistent_enabled": False}, "glossary_open": True})
    assert observed["storage"]["processing_cache"]["persistent_enabled"] is False
    assert observed["storage"]["glossary"]["accessibility"] == "open"
    with pytest.raises(SetupUnavailable) as error:
        require_local_models(environment)
    assert error.value.code == "ocr_artifacts_missing"
    cuda = next(m for m in readiness_snapshot(initialization="failed", busy=False, environment={"YOMISCAN_DEVICE": "cuda"})["models"] if m["id"] == "ocr-onnx")
    assert not cuda["compatible"]


def test_status_is_available_during_slow_initialization_without_loading_optional_models(monkeypatch):
    entered, release = Event(), Event()
    monkeypatch.setattr("yomiscan.readiness.local_artifacts", lambda *a: ([], False))
    @contextmanager
    def factory():
        entered.set();assert release.wait(3)
        raise RuntimeError("private-C:/secret-configuration")
        yield
    with TestClient(create_app(factory, background_initialization=True), base_url="http://localhost") as client:
        try:
            assert entered.wait(1)
            assert client.get("/api/v1/readiness").status_code == 403
            response = client.get("/api/v1/readiness", headers=HEADERS)
            assert response.json()["initialization"] == "initializing"
            assert client.get("/health").status_code == 503
        finally: release.set()


def test_readiness_tracks_cache_changes_and_glossary_open_without_an_image_job(tmp_path, monkeypatch):
    monkeypatch.setattr("yomiscan.readiness.local_artifacts", lambda *a: ([], False))
    monkeypatch.setenv("YOMISCAN_GLOSSARY_DATABASE", str(tmp_path/"user-glossaries.sqlite3"))
    @contextmanager
    def factory():
        service, *_ = resources(tmp_path/"processing", enabled=False)
        try: yield service
        finally: service.close()
    with TestClient(create_app(factory), base_url="http://localhost") as client:
        status = lambda: client.get("/api/v1/readiness", headers=HEADERS).json()["storage"]
        assert status()["processing_cache"]["persistent_enabled"] is False
        for enabled in (True, False):
            assert client.post("/api/v1/cache/settings", headers=HEADERS, json={"enabled": enabled}).status_code == 200
            assert status()["processing_cache"]["persistent_enabled"] is enabled
        assert status()["glossary"]["accessibility"] == "not_open"
        assert client.get("/api/v1/translation-profile", headers=HEADERS).status_code == 200
        assert status()["glossary"]["accessibility"] == "open"


def test_real_stage_callbacks_status_busy_and_cached_job_isolation(tmp_path, monkeypatch):
    entered, release = Event(), Event()
    monkeypatch.setattr("yomiscan.readiness.local_artifacts", lambda *a: ([], False))
    @contextmanager
    def factory():
        service, counts, detector, *_ = resources(tmp_path)
        native = detector.detect
        def detect(image):
            entered.set();assert release.wait(3);return native(image)
        detector.detect = detect
        try: yield service
        finally: service.close()
    image = BytesIO();page().save(image, "PNG")
    files = {"file": ("page.png", image.getvalue(), "image/png")}
    job, other = str(uuid4()), str(uuid4())
    with TestClient(create_app(factory), base_url="http://localhost") as client, ThreadPoolExecutor(1) as worker:
        pending = worker.submit(client.post, "/api/v1/render-page", params={"job_id": job}, headers=HEADERS, files=files)
        try:
            assert entered.wait(1)
            status = client.get("/api/v1/jobs/"+job, headers=HEADERS).json()
            assert status["job_id"] == job and status["current"] == "detection"
            assert client.get("/api/v1/readiness", headers=HEADERS).json()["busy"]
            assert client.get("/api/v1/jobs/"+other, headers=HEADERS).status_code == 404
            assert client.get("/api/v1/jobs/"+job).status_code == 403
            assert "猫" not in json.dumps(status) and "page.png" not in json.dumps(status)
        finally: release.set()
        assert pending.result().status_code == 200
        done = client.get("/api/v1/jobs/"+job, headers=HEADERS).json()
        assert done["state"] == "completed" and done["version"] > status["version"]
        assert client.post("/api/v1/render-page", params={"job_id": other}, headers=HEADERS, files=files).status_code == 200
        restored = client.get("/api/v1/jobs/"+other, headers=HEADERS).json()
        assert all(s["state"] == "cached" for s in restored["stages"].values())


def test_reading_analysis_reports_progress_and_a_later_render_reuses_its_stages(tmp_path, monkeypatch):
    """Reading mode analyzes first; toggling English for that page must not repeat OCR or translation."""
    monkeypatch.setattr("yomiscan.readiness.local_artifacts", lambda *a: ([], False))
    @contextmanager
    def factory():
        service, *_ = resources(tmp_path)
        try: yield service
        finally: service.close()
    image = BytesIO();page().save(image, "PNG")
    files = {"file": ("page.png", image.getvalue(), "image/png")}
    reading, english = str(uuid4()), str(uuid4())
    with TestClient(create_app(factory), base_url="http://localhost") as client:
        configuration = client.get("/health").headers["X-YomiScan-Configuration"]
        stale = client.post("/api/v1/analyze-page", params={"configuration": "0"*64}, headers=HEADERS, files=files)
        assert stale.status_code == 409
        analyzed = client.post("/api/v1/analyze-page", params={"job_id": reading, "configuration": configuration},
                               headers=HEADERS, files=files)
        assert analyzed.status_code == 200
        blocks = analyzed.json()["text_blocks"]
        assert blocks and all("provenance" in block and "analysis_origin" not in block["provenance"] for block in blocks)
        status = client.get("/api/v1/jobs/"+reading, headers=HEADERS).json()
        assert status["state"] == "completed" and status["stages"]["ocr"]["computed"]
        assert client.post("/api/v1/render-page", params={"job_id": english}, headers=HEADERS, files=files).status_code == 200
        stages = client.get("/api/v1/jobs/"+english, headers=HEADERS).json()["stages"]
        assert {"detection", "ocr", "translation"} <= stages.keys()
        assert all(stages[name]["state"] == "cached" for name in ("detection", "ocr", "translation"))
