from unittest.mock import Mock

from PIL import Image
import pytest

from yomiscan.ocr import OCRInitializationError, OCRRecognitionError, OCRResult
from yomiscan.ocr import cli


@pytest.fixture
def image_path(tmp_path):
    path = tmp_path / "crop.png"
    with Image.new("L", (12, 8)) as image:
        image.save(path)
    return path


def test_load_image_decodes_and_closes_source(image_path):
    with cli.load_image(image_path) as image:
        image_path.unlink()
        assert image.mode == "RGB"
        assert image.size == (12, 8)
        assert image.getpixel((0, 0)) == (0, 0, 0)


@pytest.mark.parametrize("kind", ["missing", "directory", "invalid", "truncated"])
def test_bad_input_does_not_initialize_model(kind, tmp_path, image_path, monkeypatch, capsys):
    path = tmp_path / "bad.png"
    if kind == "directory":
        path.mkdir()
    elif kind == "invalid":
        path.write_text("not an image")
    elif kind == "truncated":
        path.write_bytes(image_path.read_bytes()[:40])
    factory = Mock()
    monkeypatch.setattr(cli, "MangaOCREngine", factory)
    assert cli.main([str(path)]) == 2
    factory.assert_not_called()
    assert "Error:" in capsys.readouterr().err


def test_missing_argument():
    with pytest.raises(SystemExit) as caught:
        cli.main([])
    assert caught.value.code == 2


def test_cli_success(image_path, monkeypatch, capsys):
    factory = Mock()
    factory.return_value.recognize.return_value = OCRResult("日本語", "manga-ocr", 12.5)
    monkeypatch.setattr(cli, "MangaOCREngine", factory)
    assert cli.main([str(image_path), "--cpu"]) == 0
    factory.assert_called_once_with(force_cpu=True)
    output = capsys.readouterr().out
    assert "日本語" in output
    assert "Engine: manga-ocr" in output
    assert "Processing time:" in output


@pytest.mark.parametrize("stage,code", [("init", 3), ("recognize", 4)])
def test_cli_engine_errors(image_path, monkeypatch, capsys, stage, code):
    factory = Mock()
    if stage == "init":
        factory.side_effect = OCRInitializationError("test initialization failure")
    else:
        factory.return_value.recognize.side_effect = OCRRecognitionError("test OCR failure")
    monkeypatch.setattr(cli, "MangaOCREngine", factory)
    assert cli.main([str(image_path)]) == code
    assert "failure" in capsys.readouterr().err
