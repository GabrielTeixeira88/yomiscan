from concurrent.futures import ThreadPoolExecutor
import asyncio
from contextlib import contextmanager
from io import BytesIO
from threading import Event, get_ident
from unittest.mock import Mock

from fastapi.testclient import TestClient
from PIL import Image
import pytest
import httpx

from yomiscan.analysis import TextAnalyzer
from yomiscan.api.images import MAX_FILE_BYTES, decode_image
from yomiscan.api.main import create_app
from yomiscan.dictionary import SQLiteDictionary
from yomiscan.nlp import FugashiTokenizer
from yomiscan.ocr import OCRResult
from yomiscan.service import ImageAnalysisService
from yomiscan.translation import TranslationError, TranslationResult

HEADERS = {"X-YomiScan-Client": "study-extension-v1"}
ORIGIN = "chrome-extension://" + "a" * 32


def image_bytes(format="PNG"):
    buffer = BytesIO()
    with Image.new("RGB", (16, 12), "white") as image:
        image.save(buffer, format=format)
    return buffer.getvalue()


@pytest.fixture
def api(dictionary_path):
    ocr = Mock()
    translator = Mock()
    ocr.recognize.return_value = OCRResult("食べました。猫", "fake", 2)
    translator.translate.return_value = TranslationResult("食べました。猫", "I ate. Cat", "fake", "fake", 3)
    threads = []

    @contextmanager
    def factory():
        threads.append(get_ident())
        with SQLiteDictionary(dictionary_path) as dictionary:
            service = ImageAnalysisService(ocr, TextAnalyzer(FugashiTokenizer(), dictionary, translator))
            original = service.analyze_image

            def analyze(image):
                threads.append(get_ident())
                return original(image)

            service.analyze_image = analyze
            yield service
        threads.append(get_ident())

    app = create_app(factory)
    with TestClient(app, base_url="http://127.0.0.1", headers=HEADERS) as client:
        yield client, ocr, translator, threads
    assert len(set(threads)) == 1


def test_health_and_repeated_analysis_reuses_service(api):
    client, ocr, translator, threads = api
    assert client.get("/health").json() == {"status": "ok"}
    for _ in range(2):
        response = client.post("/api/v1/analyze-image", files={"file": ("crop.png", image_bytes(), "image/png")})
        assert response.status_code == 200
        data = response.json()
        assert data["original_text"] == "食べました。猫"
        assert data["translation"] == "I ate. Cat"
        assert data["processing"]["ocr_ms"] == 2
        assert data["processing"]["translation_ms"] == 3
        token = data["tokens"][0]
        assert token["dictionary_form"] == "食べる"
        assert token["reading"] == "たべ"
        assert token["conjugation_form"]
        assert token["meanings"][0]["glosses"] == ["to eat"]
    assert ocr.recognize.call_count == translator.translate.call_count == 2
    assert len(threads) == 3  # one initialization, two requests


@pytest.mark.parametrize("format", ["PNG", "JPEG", "WEBP"])
def test_image_formats(api, format):
    client, *_ = api
    # Actual decoded format matters, not the filename or untrusted MIME header.
    response = client.post("/api/v1/analyze-image", files={"file": ("anything.dat", image_bytes(format), "application/octet-stream")})
    assert response.status_code == 200


@pytest.mark.parametrize("payload", [b"", b"not an image", image_bytes("GIF"), image_bytes()[:30]])
def test_invalid_upload(api, payload):
    client, ocr, *_ = api
    response = client.post("/api/v1/analyze-image", files={"file": ("bad.png", payload)})
    assert response.status_code == 400
    ocr.recognize.assert_not_called()


def test_upload_limits_and_missing_file(api):
    client, ocr, *_ = api
    assert client.post("/api/v1/analyze-image").status_code == 422
    response = client.post("/api/v1/analyze-image", files={"file": ("large.png", b"x" * (MAX_FILE_BYTES + 1))})
    assert response.status_code == 413
    response = client.post("/api/v1/analyze-image", content=b"x" * (MAX_FILE_BYTES + 100_000))
    assert response.status_code == 413
    ocr.recognize.assert_not_called()


def test_pixel_limit(monkeypatch):
    monkeypatch.setattr("yomiscan.api.images.MAX_PIXELS", 100)
    with pytest.raises(ValueError, match="megapixels"):
        decode_image(image_bytes())


def test_animated_png_rejected(api):
    buffer = BytesIO()
    with Image.new("RGB", (16, 12), "white") as first, Image.new("RGB", (16, 12), "black") as second:
        first.save(buffer, format="PNG", save_all=True, append_images=[second], duration=100, loop=0)
    client, ocr, *_ = api
    assert client.post("/api/v1/analyze-image", files={"file": ("animated.png", buffer.getvalue())}).status_code == 400
    ocr.recognize.assert_not_called()


def test_exif_orientation_normalized():
    buffer = BytesIO()
    with Image.new("RGB", (16, 12)) as image:
        exif = image.getexif()
        exif[274] = 6
        image.save(buffer, format="JPEG", exif=exif)
    with decode_image(buffer.getvalue()) as image:
        assert image.size == (12, 16)
        assert image.mode == "RGB"


def test_body_limit_without_content_length(api, monkeypatch):
    monkeypatch.setattr("yomiscan.api.security.MAX_BODY_BYTES", 128)
    client, ocr, *_ = api
    response = client.post("/api/v1/analyze-image", content=iter([b"x" * 100, b"y" * 100]))
    assert response.status_code == 413
    ocr.recognize.assert_not_called()


def test_failure_is_logged_but_not_leaked(api, caplog):
    client, _, translator, _ = api
    translator.translate.side_effect = TranslationError("private/path/model exploded")
    response = client.post("/api/v1/analyze-image", files={"file": ("crop.png", image_bytes())})
    assert response.status_code == 500
    assert "private/path" not in response.text
    assert "private/path/model exploded" in caplog.text
    translator.translate.side_effect = None
    assert client.post("/api/v1/analyze-image", files={"file": ("crop.png", image_bytes())}).status_code == 200


def test_initialization_unavailable(caplog):
    @contextmanager
    def failed():
        raise RuntimeError("dictionary missing")
        yield

    with TestClient(create_app(failed), base_url="http://localhost", headers=HEADERS) as client:
        assert client.get("/health").status_code == 503
        assert client.post("/api/v1/analyze-image", files={"file": ("crop.png", image_bytes())}).status_code == 503
    assert "dictionary missing" in caplog.text


def test_origins_client_header_and_host(api):
    client, *_ = api
    preflight = {"Origin": ORIGIN, "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "X-YomiScan-Client"}
    response = client.options("/api/v1/analyze-image", headers=preflight)
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ORIGIN
    preflight["Origin"] = "https://manga.example"
    assert client.options("/api/v1/analyze-image", headers=preflight).status_code == 400
    assert client.post("/api/v1/analyze-image", headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.post("/api/v1/analyze-image", headers={"X-YomiScan-Client": ""}).status_code == 403
    assert client.get("/health", headers={"Host": "attacker.example"}).status_code == 400


def test_explicit_origin_allowlist():
    @contextmanager
    def fake():
        yield Mock()
    with TestClient(create_app(fake, allowed_origins=[ORIGIN]), base_url="http://localhost") as client:
        assert client.get("/health", headers={"Origin": ORIGIN}).status_code == 200
        assert client.get("/health", headers={"Origin": "chrome-extension://" + "b" * 32}).status_code == 403


def test_health_responsive_and_busy_request_rejected(api):
    client, ocr, *_ = api
    started, release = Event(), Event()

    def recognize(image):
        started.set()
        assert release.wait(5)
        return OCRResult("猫", "fake", 1)

    ocr.recognize.side_effect = recognize
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(client.post, "/api/v1/analyze-image", files={"file": ("crop.png", image_bytes())})
        try:
            assert started.wait(5)
            assert client.get("/health").status_code == 200
            assert client.post("/api/v1/analyze-image", files={"file": ("crop.png", image_bytes())}).status_code == 429
        finally:
            release.set()
        assert future.result().status_code == 200


def test_cancelled_client_does_not_release_running_model():
    # Run a separate ASGI lifespan so cancellation reaches the async route directly.
    started, release = Event(), Event()
    @contextmanager
    def factory():
        service = Mock()
        def analyze(image):
            started.set()
            assert release.wait(5)
            raise TranslationError("test failure after client cancellation")
        service.analyze_image.side_effect = analyze
        yield service

    app = create_app(factory)

    async def run():
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://localhost", headers=HEADERS) as http:
                task = asyncio.create_task(http.post("/api/v1/analyze-image", files={"file": ("crop.png", image_bytes())}))
                try:
                    assert await asyncio.to_thread(started.wait, 5)
                    task.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await task
                    assert (await http.post("/api/v1/analyze-image", files={"file": ("crop.png", image_bytes())})).status_code == 429
                finally:
                    release.set()
                async with asyncio.timeout(5):
                    while app.state.busy:
                        await asyncio.sleep(0.01)
                assert (await http.get("/health")).json() == {"status": "ok"}

    asyncio.run(run())
