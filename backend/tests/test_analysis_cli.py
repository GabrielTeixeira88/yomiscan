from unittest.mock import Mock

from PIL import Image

from yomiscan import analysis_cli
from yomiscan.ocr import OCRResult


def test_text_cli(dictionary_path, capsys):
    assert analysis_cli.main(["でも大丈夫", "--dictionary", str(dictionary_path)]) == 0
    output = capsys.readouterr().out
    assert "だいじょうぶ" in output
    assert "okay" in output
    assert "CC BY-SA" in output


def test_cli_missing_database(tmp_path, capsys):
    assert analysis_cli.main(["猫", "--dictionary", str(tmp_path / "absent")]) == 3
    assert "import_jmdict" in capsys.readouterr().err


def test_image_cli_and_invalid_image(dictionary_path, tmp_path, monkeypatch, capsys):
    path = tmp_path / "image.png"
    factory = Mock()
    factory.return_value.recognize.return_value = OCRResult("猫", "fake", 2.0)
    monkeypatch.setattr(analysis_cli, "MangaOCREngine", factory)
    args = [str(path), "--dictionary", str(dictionary_path), "--cpu"]
    assert analysis_cli.main(args, image_mode=True) == 2
    factory.assert_not_called()
    with Image.new("RGB", (8, 8)) as image:
        image.save(path)
    assert analysis_cli.main(args, image_mode=True) == 0
    factory.assert_called_once_with(force_cpu=True)
    assert "cat" in capsys.readouterr().out
