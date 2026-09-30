from unittest.mock import Mock

from PIL import Image

from yomiscan import analysis_cli
from yomiscan.ocr import OCRResult
from yomiscan.translation import TranslationResult, TranslationError, TranslationInitializationError
import pytest


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
    translator = Mock()
    translator.return_value.translate.return_value = TranslationResult("猫", "A cat.", "fake", "fake", 1)
    monkeypatch.setattr(analysis_cli, "MarianTranslationEngine", translator)
    args = [str(path), "--dictionary", str(dictionary_path), "--cpu"]
    assert analysis_cli.main(args, image_mode=True) == 2
    factory.assert_not_called()
    translator.assert_not_called()
    with Image.new("RGB", (8, 8)) as image:
        image.save(path)
    assert analysis_cli.main(args, image_mode=True) == 0
    factory.assert_called_once_with(force_cpu=True)
    translator.assert_called_once_with(device="cpu")
    translator.return_value.translate.assert_called_once_with("猫")
    output = capsys.readouterr().out
    assert "A cat." in output
    assert "Translation: 1 ms" in output


def test_text_translation_opt_in_and_lexical_preserved(dictionary_path, monkeypatch, capsys):
    factory = Mock()
    factory.return_value.translate.return_value = TranslationResult("猫", "A cat.", "fake", "fake", 1)
    monkeypatch.setattr(analysis_cli, "MarianTranslationEngine", factory)
    args = ["猫", "--dictionary", str(dictionary_path)]
    assert analysis_cli.main(args) == 0
    factory.assert_not_called()
    assert analysis_cli.main(args + ["--translate"]) == 0
    assert "Translation:\nA cat." in capsys.readouterr().out


def test_image_lexical_only_does_not_load_translation(dictionary_path, tmp_path, monkeypatch):
    path = tmp_path / "image.png"
    with Image.new("RGB", (8, 8)) as image:
        image.save(path)
    ocr = Mock()
    ocr.return_value.recognize.return_value = OCRResult("猫", "fake", 1)
    translator = Mock()
    monkeypatch.setattr(analysis_cli, "MangaOCREngine", ocr)
    monkeypatch.setattr(analysis_cli, "MarianTranslationEngine", translator)
    assert analysis_cli.main(
        [str(path), "--dictionary", str(dictionary_path), "--no-translation"], image_mode=True,
    ) == 0
    translator.assert_not_called()


def test_blank_combined_text_preserves_empty_result(dictionary_path, monkeypatch, capsys):
    translator = Mock()
    monkeypatch.setattr(analysis_cli, "MarianTranslationEngine", translator)
    assert analysis_cli.main([" \n", "--translate", "--dictionary", str(dictionary_path)]) == 0
    translator.assert_not_called()
    assert "(none)" in capsys.readouterr().out


@pytest.mark.parametrize("initialize,code", [(True, 3), (False, 4)])
def test_translation_failure(dictionary_path, monkeypatch, capsys, initialize, code):
    factory = Mock()
    if initialize:
        factory.side_effect = TranslationInitializationError("cache missing")
    else:
        factory.return_value.translate.side_effect = TranslationError("inference failed")
    monkeypatch.setattr(analysis_cli, "MarianTranslationEngine", factory)
    assert analysis_cli.main(["猫", "--translate", "--dictionary", str(dictionary_path)]) == code
    assert "Error:" in capsys.readouterr().err
