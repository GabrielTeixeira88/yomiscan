from unittest.mock import Mock

import pytest

from yomiscan.translation import TranslationError, TranslationInitializationError, TranslationResult
from yomiscan.translation import cli


def test_cli_batch(monkeypatch, capsys):
    factory = Mock()
    factory.return_value.device = "cpu"
    factory.return_value.translate_many.return_value = [
        TranslationResult("猫", "Cat", "fake", "fake-model", 3),
        TranslationResult("犬", "Dog", "fake", "fake-model", 3),
    ]
    monkeypatch.setattr(cli, "MarianTranslationEngine", factory)
    assert cli.main(["猫", "犬", "--device", "cpu"]) == 0
    factory.assert_called_once_with(device="cpu")
    factory.return_value.translate_many.assert_called_once_with(["猫", "犬"])
    output = capsys.readouterr().out
    assert output.index("Cat") < output.index("Dog")
    assert "Device: cpu" in output


def test_empty_cli_does_not_load_model(monkeypatch, capsys):
    factory = Mock()
    monkeypatch.setattr(cli, "MarianTranslationEngine", factory)
    assert cli.main(["  "]) == 2
    factory.assert_not_called()
    assert "empty" in capsys.readouterr().err


@pytest.mark.parametrize("initialize,code", [(True, 3), (False, 4)])
def test_cli_failure(monkeypatch, capsys, initialize, code):
    factory = Mock()
    if initialize:
        factory.side_effect = TranslationInitializationError("download failed")
    else:
        factory.return_value.translate_many.side_effect = TranslationError("inference failed")
    monkeypatch.setattr(cli, "MarianTranslationEngine", factory)
    assert cli.main(["猫"]) == code
    assert "failed" in capsys.readouterr().err
