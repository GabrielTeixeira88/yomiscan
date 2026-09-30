from contextlib import nullcontext
from dataclasses import FrozenInstanceError
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from yomiscan.translation import (
    MarianTranslationEngine, TranslationError, TranslationInitializationError, TranslationResult,
)
from yomiscan.translation.base import select_device


class Batch(dict):
    def to(self, device):
        self.device = device
        return self


class Row:
    def __init__(self, output, tokens=(2,)):
        self.output = output
        self.tokens = tokens

    def __getitem__(self, key):
        return SimpleNamespace(tolist=lambda: list(self.tokens))


@pytest.fixture
def upstream(monkeypatch):
    tokenizer = Mock()
    tokenizer.side_effect = lambda texts, **kw: Batch(
        input_ids=SimpleNamespace(shape=(len(texts), 12)), texts=texts,
    )
    tokenizer.batch_decode.side_effect = lambda rows, **kw: [r.output for r in rows]
    model = Mock()
    model.config.max_position_embeddings = 512
    model.config.eos_token_id = 2
    model.generate.side_effect = lambda **kw: [Row(f"English: {text}") for text in kw["texts"]]
    model_factory = Mock()
    model_factory.from_pretrained.return_value = model
    tokenizer_factory = Mock()
    tokenizer_factory.from_pretrained.return_value = tokenizer
    torch = SimpleNamespace(cuda=Mock(), inference_mode=Mock(side_effect=nullcontext))
    torch.cuda.is_available.return_value = False
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setitem(sys.modules, "transformers", SimpleNamespace(
        MarianTokenizer=tokenizer_factory, MarianMTModel=model_factory,
    ))
    return SimpleNamespace(model=model, tokenizer=tokenizer, torch=torch,
                           model_factory=model_factory, tokenizer_factory=tokenizer_factory)


def test_result_retains_source_and_independent_metadata():
    first = TranslationResult("  猫\n", "Cat", "fake", "fake-model", 1.25)
    second = TranslationResult("犬", "Dog", "fake", "fake-model", 2)
    first.metadata["device"] = "cpu"
    assert second.metadata == {}
    assert first.source_text == "  猫\n"
    with pytest.raises(FrozenInstanceError):
        first.translated_text = "changed"


@pytest.mark.parametrize("requested,available,expected", [
    ("auto", False, "cpu"), ("auto", True, "cuda"),
    ("cpu", True, "cpu"), ("cpu", False, "cpu"), ("cuda", True, "cuda"),
])
def test_device_selection(requested, available, expected):
    assert select_device(requested, cuda_available=available) == expected


def test_unavailable_and_invalid_device():
    with pytest.raises(TranslationInitializationError, match="CUDA"):
        select_device("cuda", cuda_available=False)
    with pytest.raises(ValueError, match="device"):
        select_device("metal", cuda_available=False)


def test_reuses_model_and_batches_in_order(upstream):
    engine = MarianTranslationEngine(batch_size=2)
    texts = ["猫", "  でも\n大丈夫 ", "犬"]
    results = engine.translate_many(texts)
    assert [r.source_text for r in results] == texts
    assert [r.translated_text for r in results] == [
        "English: 猫", "English: でも 大丈夫", "English: 犬",
    ]
    assert upstream.model.generate.call_count == 2
    assert [r.metadata["batch_size"] for r in results] == [2, 2, 1]
    assert results[0].processing_time_ms == results[1].processing_time_ms
    assert all(r.processing_time_ms >= 0 for r in results)
    assert engine.translate("猫").translated_text == "English: 猫"
    upstream.model_factory.from_pretrained.assert_called_once()
    upstream.tokenizer_factory.from_pretrained.assert_called_once()
    upstream.model.to.assert_called_once_with("cpu")
    upstream.model.eval.assert_called_once()
    assert upstream.torch.inference_mode.call_count == 3


def test_empty_and_invalid_inputs_do_not_generate(upstream):
    engine = MarianTranslationEngine()
    assert engine.translate_many([]) == []
    for text in ("", " \n\t"):
        with pytest.raises(ValueError, match="empty"):
            engine.translate(text)
    with pytest.raises(ValueError):
        engine.translate_many(["猫", ""])
    with pytest.raises(TypeError):
        engine.translate_many("猫")
    with pytest.raises(TypeError):
        engine.translate(None)
    upstream.model.generate.assert_not_called()


def test_invalid_batch_size(upstream):
    with pytest.raises(ValueError, match="batch_size"):
        MarianTranslationEngine(batch_size=0)
    upstream.model_factory.from_pretrained.assert_not_called()


def test_initialization_error_preserves_cause(upstream):
    cause = OSError("cache incomplete")
    upstream.model_factory.from_pretrained.side_effect = cause
    with pytest.raises(TranslationInitializationError, match="uv sync") as caught:
        MarianTranslationEngine()
    assert caught.value.__cause__ is cause


def test_inference_error_preserves_cause(upstream):
    engine = MarianTranslationEngine()
    cause = RuntimeError("out of memory")
    upstream.model.generate.side_effect = cause
    with pytest.raises(TranslationError, match="batch_size") as caught:
        engine.translate("猫")
    assert caught.value.__cause__ is cause


def test_long_input_is_rejected_without_truncation(upstream):
    engine = MarianTranslationEngine()
    upstream.model.config.max_position_embeddings = 5
    with pytest.raises(TranslationError, match="never silently truncates"):
        engine.translate("長い文")
    upstream.model.generate.assert_not_called()
    assert upstream.tokenizer.call_args.kwargs["truncation"] is False


@pytest.mark.parametrize("rows", [[], [Row("")], [Row("partial", tokens=(7, 8))]])
def test_missing_empty_or_unfinished_output_fails(upstream, rows):
    engine = MarianTranslationEngine()
    upstream.model.generate.side_effect = None
    upstream.model.generate.return_value = rows
    with pytest.raises(TranslationError):
        engine.translate("猫")


def test_cuda_moves_model_and_synchronizes_mock_only(upstream):
    upstream.torch.cuda.is_available.return_value = True
    engine = MarianTranslationEngine()
    result = engine.translate("猫")
    upstream.model.to.assert_called_once_with("cuda")
    upstream.torch.cuda.synchronize.assert_called_once()
    assert result.metadata["device"] == "cuda"
