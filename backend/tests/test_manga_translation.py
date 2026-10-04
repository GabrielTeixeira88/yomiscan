import csv
import json
from pathlib import Path

import pytest

from yomiscan.translation.base import TranslationError, TranslationInitializationError, TranslationResult
from yomiscan.translation.factory import create_translation_engine
from yomiscan.translation.manga import LlamaServer, MangaTranslationEngine, TranslationContext, messages_for, parse_lines
from yomiscan.translation.benchmark import EvaluationCase, evaluate_engine, read_dataset, write_ratings, summarize_ratings, format_comparison


class Runtime:
    device = "cpu"
    model = Path("fake.gguf")
    lora = None

    def __init__(self, outputs):
        self.outputs = iter(outputs)
        self.calls = []
        self.loaded = False
        self.closed = False

    def load(self):
        self.loaded = True

    def generate(self, messages, *, max_tokens):
        self.calls.append((messages, max_tokens))
        return next(self.outputs)

    def close(self):
        self.closed = True


def test_lazy_empty_validation_and_reuse():
    runtime = Runtime(["One", "Two"])
    engine = MangaTranslationEngine("hy-mt2-manga", runtime)
    assert not runtime.loaded
    assert engine.translate_many([]) == []
    with pytest.raises(ValueError):
        engine.translate_many(["いい", " "])
    assert not runtime.loaded
    results = engine.translate_many(["一", "二"])
    assert [r.source_text for r in results] == ["一", "二"]
    assert [r.translated_text for r in results] == ["One", "Two"]
    assert results[0].device == "cpu"
    assert results[0].metadata["temperature"] == 0
    assert len(runtime.calls) == 2  # honest sequential reuse, not claimed native batching
    engine.close()
    assert runtime.closed


def test_vntl_page_alignment_and_context_slice():
    runtime = Runtime(["Before\nFirst\nSecond\nAfter"])
    engine = MangaTranslationEngine("qwen35-vntl", runtime)
    results = engine.translate_many(["一\nです", "二"], context=TranslationContext(previous=("前",), following=("後",)))
    assert [r.translated_text for r in results] == ["First", "Second"]
    assert len(runtime.calls) == 1
    assert "[Source]\n前\n一 です\n二\n後" in runtime.calls[0][0][1]["content"]
    assert results[0].processing_time_ms == results[1].processing_time_ms
    with pytest.raises(ValueError, match="single dialogue"):
        engine.translate("はい", context=TranslationContext(previous=("a\nb",)))


@pytest.mark.parametrize("output", ["Only one", "one\n\ntwo", "one\ntwo\nthree", "[Translation]\ntwo", "```\ntwo"])
def test_bad_page_outputs_are_never_assigned(output):
    with pytest.raises(TranslationError):
        parse_lines(output, 2)


def test_model_specific_prompts_and_unsupported_context():
    hints = TranslationContext(glossary={"霊力": "spirit energy"})
    assert "霊力 translates to spirit energy" in messages_for("hy-mt2-manga", ["霊力"], hints)[0]["content"]
    assert "Context:" in messages_for("qwen25-manga", ["はい"], hints)[0]["content"]
    with pytest.raises(ValueError, match="context"):
        MangaTranslationEngine("hy-mt2-manga", Runtime([])).translate("はい", context=TranslationContext(previous=("前",)))


def test_qwen25_rejects_echoed_context_lines():
    engine = MangaTranslationEngine("qwen25-manga", Runtime(["Before\nActual translation\nAfter"]))
    with pytest.raises(TranslationError, match="wrong bubbles"):
        engine.translate("はい", context=TranslationContext(previous=("前",)))


def test_factory_keeps_default_and_requires_real_adapter(monkeypatch):
    import yomiscan.translation.marian as marian
    monkeypatch.delenv("YOMISCAN_TRANSLATION_ENGINE", raising=False)
    sentinel = object()
    monkeypatch.setattr(marian, "MarianTranslationEngine", lambda **kwargs: sentinel)
    assert create_translation_engine() is sentinel
    with pytest.raises(ValueError):
        create_translation_engine("imaginary")
    monkeypatch.setenv("YOMISCAN_LLAMA_SERVER", "server.exe")
    monkeypatch.setenv("YOMISCAN_QWEN25_GGUF", "base.gguf")
    monkeypatch.delenv("YOMISCAN_QWEN25_LORA", raising=False)
    with pytest.raises(TranslationInitializationError, match="Refusing"):
        create_translation_engine("qwen25-manga")
    monkeypatch.delenv("YOMISCAN_QWEN35_GGUF", raising=False)
    with pytest.raises(TranslationInitializationError, match="contains no weights"):
        create_translation_engine("qwen35-vntl").translate("はい")


def test_missing_local_runtime_has_actionable_error(tmp_path):
    runtime = LlamaServer(tmp_path / "missing.gguf", executable=tmp_path / "server.exe")
    with pytest.raises(TranslationInitializationError, match="setup"):
        runtime.load()
    assert runtime.process is None


def test_transport_determinism_and_truncation(monkeypatch):
    import yomiscan.translation.manga as manga
    runtime = LlamaServer(Path("model"), executable=Path("server"))
    runtime.url = "http://127.0.0.1:1234"
    monkeypatch.setattr(runtime, "load", lambda: None)
    sent = []
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self): return json.dumps({"choices": [{"finish_reason": "length", "message": {"content": "partial"}}]}).encode()
    def request(req, timeout):
        sent.append(json.loads(req.data))
        return Response()
    monkeypatch.setattr(manga, "urlopen", request)
    with pytest.raises(TranslationError, match="finish"):
        runtime.generate([{"role": "user", "content": "はい"}], max_tokens=20)
    assert sent[0]["temperature"] == 0 and sent[0]["seed"] == 0


def test_benchmark_serialization_ratings_and_cleanup(tmp_path):
    class Fake:
        closed = False
        def translate(self, text): return TranslationResult(text, "Yes", "fake", "fake", 1)
        def translate_many(self, texts): return [self.translate(text) for text in texts]
        def close(self): self.closed = True
    fake = Fake()
    report = evaluate_engine("current", [EvaluationCase("a", "polite", ("はい",), ("Yes",))], factory=lambda *a, **k: fake)
    assert fake.closed
    assert report["summary"]["cases_ok"] == 1
    assert json.loads(json.dumps(report))["rows"][0]["runs"][0][0]["translated_text"] == "Yes"
    path = tmp_path / "ratings.csv"
    write_ratings(path, [report])
    row = next(csv.DictReader(path.open(encoding="utf-8-sig")))
    assert row["accuracy_1_5"] == "" and row["major_meaning_error"] == ""
    assert row["source"] == "はい"
    assert summarize_ratings(path) == {}
    row.update(accuracy_1_5="6")
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=row.keys())
        writer.writeheader()
        writer.writerow(row)
    with pytest.raises(ValueError, match="1–5"):
        summarize_ratings(path)


def test_dataset_and_unavailable_model(tmp_path):
    assert len(read_dataset(Path("benchmarks/manga-dialogue.jsonl"))) >= 40
    path = tmp_path / "bad.jsonl"
    path.write_text('{"id":"a","category":"x","texts":["x","y"],"references":["x"]}', encoding="utf-8")
    with pytest.raises(ValueError, match="align"):
        read_dataset(path)
    def unavailable(*args, **kwargs):
        raise TranslationInitializationError("not installed")
    report = evaluate_engine("qwen25-manga", [], factory=unavailable)
    assert report["status"] == "unavailable" and "not installed" in report["error"]


def test_comparison_keeps_source_order_timings_and_failures_visible():
    cases = [EvaluationCase("scene", "page", ("一", "二"))]
    row = {"id": "scene", "status": "ok", "run_ms": [30], "translate_many_ms": 20,
           "runs": [[{"translated_text": "One", "processing_time_ms": 10, "metadata": {"timing_scope": "page"}},
                     {"translated_text": "Two", "processing_time_ms": 10, "metadata": {"timing_scope": "page"}}]]}
    reports = [{"engine": "current", "status": "completed", "rows": [row]},
               {"engine": "qwen35-vntl", "status": "unavailable", "error": "no weights", "rows": []},
               {"engine": "qwen25-manga", "status": "completed_with_errors", "rows": [
                   {"id": "scene", "status": "error", "error": "output count mismatch"}]}]
    text = format_comparison(cases, reports)
    assert text.index("One") < text.index("Two")
    assert "10.0 ms (page)" in text and "20.0 ms for 2 line(s)" in text
    assert "qwen35-vntl: unavailable — no weights" in text
    assert "qwen25-manga: error — output count mismatch" in text


def test_application_closes_optional_engine_even_if_ocr_initialization_fails(monkeypatch):
    from contextlib import nullcontext
    import yomiscan.service as service
    runtime = Runtime([])
    engine = MangaTranslationEngine("hy-mt2-manga", runtime)
    monkeypatch.setattr(service, "SQLiteDictionary", lambda path: nullcontext(object()))
    monkeypatch.setattr(service, "FugashiTokenizer", lambda: object())
    monkeypatch.setattr(service, "create_translation_engine", lambda **kwargs: engine)
    def unavailable(**kwargs):
        raise RuntimeError("OCR setup failed")
    monkeypatch.setattr(service, "MangaOCREngine", unavailable)
    with pytest.raises(RuntimeError, match="OCR setup"):
        with service.open_local_service():
            pass
    assert runtime.closed


def test_unsupported_context_is_reported_without_silent_baseline_fallback():
    class Fake:
        def translate(self, text):
            raise AssertionError("must not translate with an unsupported context")
        def translate_many(self, texts):
            raise AssertionError("must not silently drop context")
    report = evaluate_engine("current", [EvaluationCase("a", "context", ("はい",))], mode="page", factory=lambda *a, **k: Fake())
    assert report["status"] == "unsupported"
    assert report["summary"]["cases_ok"] == 0


def test_llama_load_reuses_process_and_cuda_selection(monkeypatch, tmp_path):
    import yomiscan.translation.manga as manga
    model, exe = tmp_path / "m.gguf", tmp_path / "llama-server.exe"
    model.touch(); exe.touch()
    starts = []
    class Process:
        stopped = False
        def poll(self): return 0 if self.stopped else None
        def terminate(self): self.stopped = True
        def wait(self, timeout=None): return 0
    process = Process()
    def spawn(args, **kwargs):
        starts.append(args)
        assert kwargs["env"]["LLAMA_API_KEY"]
        return process
    class Probe:
        stdout = "CUDA0: fake GPU"
    class Response:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *args): pass
    monkeypatch.setattr(manga.subprocess, "run", lambda *a, **k: Probe())
    monkeypatch.setattr(manga.subprocess, "Popen", spawn)
    monkeypatch.setattr(manga, "urlopen", lambda *a, **k: Response())
    runtime = LlamaServer(model, executable=exe, device="auto")
    runtime.load(); runtime.load()
    assert runtime.device == "cuda" and len(starts) == 1
    assert starts[0][starts[0].index("--host")+1] == "127.0.0.1"
    runtime.close()
    assert process.stopped and runtime.process is None
