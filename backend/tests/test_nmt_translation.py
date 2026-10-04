from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock
import sys

import pytest

from yomiscan.translation.nmt import NMTTranslationEngine, NMT_MODELS
from yomiscan.translation.base import TranslationError, TranslationInitializationError
from yomiscan.translation.factory import create_translation_engine
from yomiscan.translation.benchmark import evaluate_engine, EvaluationCase


class Batch(dict):
    def to(self, device):
        return self


class Row:
    def __init__(self, text, eos=True):
        self.text, self.eos = text, eos

    def __getitem__(self, key):
        return SimpleNamespace(tolist=lambda: [0, 2] if self.eos else [42])


@pytest.fixture
def upstream(monkeypatch):
    tokenizer = Mock()
    tokenizer.src_lang = "jpn_Jpan"
    tokenizer.unk_token_id = 3
    tokenizer.convert_tokens_to_ids.return_value = 256047
    tokenizer.side_effect = lambda texts, **kw: Batch(input_ids=SimpleNamespace(shape=(len(texts), 8)), texts=texts)
    tokenizer.batch_decode.side_effect = lambda rows, **kw: [r.text for r in rows]
    model = Mock()
    model.config.max_position_embeddings = 1024
    model.config.eos_token_id = 2
    model.generate.side_effect = lambda **kw: [Row("EN " + text) for text in kw["texts"]]
    token_factory, model_factory = Mock(), Mock()
    token_factory.from_pretrained.return_value = tokenizer
    model_factory.from_pretrained.return_value = model
    torch = SimpleNamespace(cuda=Mock(), inference_mode=Mock(side_effect=nullcontext), float32="float32")
    torch.cuda.is_available.return_value = False
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setitem(sys.modules, "transformers", SimpleNamespace(AutoTokenizer=token_factory, AutoModelForSeq2SeqLM=model_factory))
    return SimpleNamespace(tokenizer=tokenizer, model=model, token_factory=token_factory, model_factory=model_factory, torch=torch)


@pytest.mark.parametrize("name", ["fugumt", "nllb-600m"])
def test_lazy_factory_batches_once_and_preserves_order(upstream, name):
    engine = create_translation_engine(name, device="cpu")
    upstream.model_factory.from_pretrained.assert_not_called()
    assert engine.translate_many([]) == []
    with pytest.raises(ValueError): engine.translate_many(["猫", ""])
    with pytest.raises(TypeError): engine.translate_many("猫")
    upstream.model_factory.from_pretrained.assert_not_called()
    engine.batch_size = 2
    sources = ["猫", "でも\n大丈夫", "犬"]
    results = engine.translate_many(sources)
    assert [r.source_text for r in results] == sources
    assert [r.translated_text for r in results] == ["EN 猫", "EN でも 大丈夫", "EN 犬"]
    assert [r.metadata["batch_size"] for r in results] == [2, 2, 1]
    assert len(upstream.model.generate.call_args_list) == 2
    engine.translate("猫")
    upstream.model_factory.from_pretrained.assert_called_once()
    upstream.token_factory.from_pretrained.assert_called_once()
    assert upstream.model_factory.from_pretrained.call_args.args == (NMT_MODELS[name].model,)
    assert results[0].metadata["revision"] == NMT_MODELS[name].revision
    assert results[0].metadata["license"] == NMT_MODELS[name].license
    assert all(call.kwargs["do_sample"] is False and call.kwargs["num_beams"] == (1 if name == "fugumt" else 4)
               for call in upstream.model.generate.call_args_list)
    engine.close()
    assert engine._model is None and engine._tokenizer is None


def test_nllb_source_and_forced_target_are_explicit(upstream):
    engine = NMTTranslationEngine("nllb-600m", local_files_only=True)
    engine.translate_many(["一", "二"])
    options = upstream.token_factory.from_pretrained.call_args.kwargs
    assert options["src_lang"] == "jpn_Jpan" and options["tgt_lang"] == "eng_Latn"
    assert options["local_files_only"] is True
    assert upstream.model_factory.from_pretrained.call_args.kwargs["local_files_only"] is True
    upstream.tokenizer.convert_tokens_to_ids.assert_called_once_with("eng_Latn")
    assert upstream.model.generate.call_args.kwargs["forced_bos_token_id"] == 256047


def test_fugu_has_no_multilingual_language_override(upstream):
    NMTTranslationEngine("fugumt").translate("はい")
    assert "src_lang" not in upstream.token_factory.from_pretrained.call_args.kwargs
    assert "forced_bos_token_id" not in upstream.model.generate.call_args.kwargs


def test_cache_failure_retains_cause_and_never_falls_back(upstream):
    cause = OSError("not in local cache")
    upstream.model_factory.from_pretrained.side_effect = cause
    engine = NMTTranslationEngine("fugumt", local_files_only=True)
    with pytest.raises(TranslationInitializationError, match="cache") as error:
        engine.load()
    assert error.value.__cause__ is cause and engine._model is None


@pytest.mark.parametrize("failure", ["empty", "count", "unfinished", "inference", "too_long"])
def test_bad_inference_is_explicit(upstream, failure):
    if failure == "empty": upstream.tokenizer.batch_decode.side_effect = lambda *a, **k: [""]
    if failure == "count": upstream.tokenizer.batch_decode.side_effect = lambda *a, **k: []
    if failure == "unfinished": upstream.model.generate.side_effect = lambda **kw: [Row("partial", eos=False)]
    if failure == "inference": upstream.model.generate.side_effect = RuntimeError("oom")
    if failure == "too_long": upstream.tokenizer.side_effect = lambda *a, **k: Batch(input_ids=SimpleNamespace(shape=(1, 513)))
    with pytest.raises(TranslationError) as error:
        NMTTranslationEngine("nllb-600m").translate("猫")
    assert error.value.__cause__ is not None


def test_nllb_rejects_missing_language_id(upstream):
    upstream.tokenizer.convert_tokens_to_ids.return_value = 3
    with pytest.raises(TranslationInitializationError, match="eng_Latn"):
        NMTTranslationEngine("nllb-600m").load()
    upstream.model_factory.from_pretrained.assert_not_called()


def test_cuda_and_cleanup(upstream):
    upstream.torch.cuda.is_available.return_value = True
    engine = NMTTranslationEngine("fugumt", device="cuda")
    engine.translate("猫")
    upstream.model.to.assert_called_once_with("cuda")
    upstream.torch.cuda.synchronize.assert_called_once()
    engine.close()
    upstream.torch.cuda.empty_cache.assert_called_once()


@pytest.mark.parametrize("name", ["fugumt", "nllb-600m"])
def test_benchmark_serializes_nmt_results(upstream, name):
    import json
    report = evaluate_engine(name, [EvaluationCase("test", "casual", ("はい", "いい"))])
    restored = json.loads(json.dumps(report))
    assert restored["status"] == "completed"
    assert [r["source_text"] for r in restored["rows"][0]["runs"][0]] == ["はい", "いい"]
    assert restored["rows"][0]["translate_many"][0]["metadata"]["batch_size"] == 2


def test_requested_cuda_unavailable_does_not_load_weights(upstream):
    with pytest.raises(TranslationInitializationError, match="CUDA"):
        NMTTranslationEngine("nllb-600m", device="cuda").load()
    upstream.model_factory.from_pretrained.assert_not_called()


@pytest.mark.parametrize("name", ["fugumt", "nllb-600m"])
@pytest.mark.parametrize("mode,glossary", [("page", False), ("isolated", True)])
def test_benchmark_does_not_claim_context_or_glossary(upstream, name, mode, glossary):
    report = evaluate_engine(name, [EvaluationCase("test", "context", ("はい",))], mode=mode, glossary=glossary)
    assert report["status"] == "unsupported"
    upstream.model.generate.assert_not_called()
