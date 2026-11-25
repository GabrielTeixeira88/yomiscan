"""Stage 5b increment 2: Torch-free OPUS-MT (no downloaded weights)."""

import json

import numpy as np
import pytest

from yomiscan.translation.base import TranslationError, TranslationInitializationError
from yomiscan.translation.beam import beam_search
from yomiscan.translation.opus_onnx import NUM_BEAMS, PinnedOpusTranslationEngine


@pytest.mark.parametrize("seed", [0, 1, 2, 3, 4, 5])
def test_beam_search_matches_transformers_generate_on_a_tiny_random_marian(seed):
    torch = pytest.importorskip("torch")
    transformers = pytest.importorskip("transformers")
    torch.manual_seed(seed)
    vocab, pad, eos = 40, 39, 0
    config = transformers.MarianConfig(vocab_size=vocab, d_model=16, encoder_layers=1, decoder_layers=1,
                                       encoder_attention_heads=2, decoder_attention_heads=2, encoder_ffn_dim=32,
                                       decoder_ffn_dim=32, max_position_embeddings=64, pad_token_id=pad,
                                       eos_token_id=eos, decoder_start_token_id=pad, forced_eos_token_id=None)
    model = transformers.MarianMTModel(config).eval()  # random weights; nothing is downloaded
    with torch.no_grad():
        # Bias toward eos so some beams finish and the stopping heuristic is exercised.
        model.final_logits_bias[0, eos] = 2.5
    source = torch.randint(1, vocab - 1, (1, 7))
    max_new = 12
    with torch.no_grad():
        expected = model.generate(source, attention_mask=torch.ones_like(source), num_beams=NUM_BEAMS, do_sample=False,
                                  max_new_tokens=max_new, max_length=None, early_stopping=False, length_penalty=1.0,
                                  bad_words_ids=[[pad]], renormalize_logits=True, num_return_sequences=1)[0].tolist()

    def step(running, parents):
        with torch.no_grad():
            out = model(input_ids=source.repeat(len(running), 1), decoder_input_ids=torch.tensor(running))
        return out.logits[:, -1, :].numpy()

    found = beam_search(step, vocab_size=vocab, num_beams=NUM_BEAMS, start_id=pad, eos_id=eos,
                        max_length=1 + max_new, banned=(pad,))
    expected = expected[:len(expected) - next((i for i, t in enumerate(reversed(expected)) if t != pad), 0)]
    assert found.tokens == expected


def test_sentencepiece_tokenizer_matches_marian_tokenizer_when_cached():
    transformers = pytest.importorskip("transformers")
    from huggingface_hub import try_to_load_from_cache
    from yomiscan.translation.marian import DEFAULT_MODEL, MODEL_REVISION
    from yomiscan.translation.marian_sentencepiece import MarianSentencePiece
    files = {name: try_to_load_from_cache(DEFAULT_MODEL, name, revision=MODEL_REVISION)
             for name in ("source.spm", "target.spm", "vocab.json")}
    if not all(isinstance(path, str) for path in files.values()):
        pytest.skip("OPUS-MT tokenizer files are not in the local Hugging Face cache")
    from pathlib import Path
    folder = Path(files["vocab.json"]).parent
    ours = MarianSentencePiece(folder)
    reference = transformers.MarianTokenizer.from_pretrained(DEFAULT_MODEL, revision=MODEL_REVISION, local_files_only=True)
    for text in ("何してんだよ", "なんだその言い方はァ!!!", "ＡＢＣ　です…？", "🙂未知の𠮷"):
        ids = reference(text)["input_ids"]
        assert ours.encode(text) == ids
        assert ours.decode(ids + [ours.pad_id]) == reference.decode(ids, skip_special_tokens=True)


class _Spec:
    def __init__(self, name):
        self.name = name


class _Encoder:
    def run(self, names, feed):
        assert feed["input_ids"].dtype == np.int64 and feed["attention_mask"].shape == feed["input_ids"].shape
        return [np.zeros((1, feed["input_ids"].shape[1], 4), dtype=np.float32)]


PAST = ["past_key_values.0.decoder.key", "past_key_values.0.encoder.key"]


class _Decoder:
    """Scripted next tokens; checks the cache contract (empty first, encoder cache reused, decoder cache gathered)."""

    def __init__(self, script, vocab=6):
        self.script, self.vocab, self.steps = script, vocab, 0

    def get_inputs(self):
        return [_Spec("input_ids"), _Spec("encoder_hidden_states"), *map(_Spec, PAST), _Spec("use_cache_branch")]

    def get_outputs(self):
        return [_Spec("logits"), *(_Spec(n.replace("past_key_values.", "present.")) for n in PAST)]

    def run(self, names, feed):
        first = not bool(feed["use_cache_branch"][0])
        assert feed["input_ids"].shape == (NUM_BEAMS, 1)
        if first:
            assert all(feed[n].shape[2] == 0 for n in PAST)
        else:
            assert feed["past_key_values.0.encoder.key"].shape[2] == 3  # reused from step one
            assert feed["past_key_values.0.decoder.key"].shape[2] == self.steps
        logits = np.full((NUM_BEAMS, 1, self.vocab), -5.0, dtype=np.float32)
        logits[:, 0, self.script[min(self.steps, len(self.script) - 1)]] = 5
        self.steps += 1
        return [logits, np.zeros((NUM_BEAMS, 2, self.steps, 2), np.float32), np.zeros((NUM_BEAMS, 2, 3, 2), np.float32)]


class _Tokenizer:
    pad_id = 5

    def __init__(self, length=3):
        self.length = length

    def encode(self, text):
        return [1] * (self.length - 1) + [0]

    def decode(self, ids):
        return " ".join({2: "hello", 3: "there"}[i] for i in ids if i in (2, 3))


CONFIG = {"vocab_size": 6, "decoder_attention_heads": 2, "d_model": 4, "max_position_embeddings": 8,
          "decoder_start_token_id": 5, "eos_token_id": 0}


def _engine(script, tokenizer=None, config=CONFIG):
    return PinnedOpusTranslationEngine(tokenizer=tokenizer or _Tokenizer(), encoder=_Encoder(), decoder=_Decoder(script),
                                       config=config)


def test_engine_translates_with_the_backend_contract():
    engine = _engine([2, 3, 0])
    result = engine.translate("  何して   んだ ")
    assert result.translated_text == "hello there" and result.source_text == "  何して   んだ "
    assert result.engine == "marian-mt" and result.metadata["runtime"] == "onnxruntime"
    assert engine.diagnostic_metadata()["engine"] == "opus-pinned" and engine.capabilities().targets == ("en",)


def test_engine_refuses_long_input_unfinished_and_empty_output():
    with pytest.raises(TranslationError, match="exceeds 8 model tokens"):
        _engine([0], tokenizer=_Tokenizer(length=9)).translate("x")
    with pytest.raises(TranslationError, match="generation limit"):
        _engine([2]).translate("x")
    with pytest.raises(TranslationError, match="empty translation"):
        _engine([4, 0]).translate("x")
    with pytest.raises(ValueError):
        _engine([0]).translate("   ")
    with pytest.raises(TranslationInitializationError, match="yomiscan-prepare-engine translation-opus-ja-en-fp32"):
        PinnedOpusTranslationEngine(encoder=_Encoder(), decoder=_Decoder([0]), config=CONFIG)


def test_readiness_and_factory_offer_the_torch_free_translator(tmp_path):
    from yomiscan.engine_models import load_bundle
    from yomiscan.readiness import local_artifacts, model_catalog
    from yomiscan.translation.factory import ENGINE_NAMES, create_translation_engine
    assert "opus-pinned" in ENGINE_NAMES
    spec = {s.id: s for s in model_catalog()}["opus-pinned"]
    assert spec.kind == "translation" and spec.targets == ("en",)
    assert spec.setup_command == "yomiscan-prepare-engine translation-opus-ja-en-fp32"
    assert local_artifacts(spec, {"YOMISCAN_ENGINE_MODELS": str(tmp_path)}) == ([], False)
    files = {f.path.rsplit("/", 1)[1] for f in load_bundle().components["translation-opus-ja-en-fp32"].files}
    assert {"encoder_model.onnx", "decoder_model_merged.onnx", "source.spm", "target.spm", "vocab.json", "config.json"} <= files
    with pytest.raises(TranslationInitializationError, match="no CUDA path"):
        create_translation_engine("opus-pinned", device="cuda")
    assert json.loads(json.dumps(spec.targets)) == ["en"]
