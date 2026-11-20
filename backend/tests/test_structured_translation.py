from pathlib import Path
from threading import Event
import json
import pytest

from yomiscan.translation.manga import LlamaServer, MangaTranslationEngine
from yomiscan.translation.structured import (PageTranslationRequest, TranslationSegment, parse_output,
    output_schema, context_for, StructuredTranslationError)


def request(mode="structured-page", context="none"):
    return PageTranslationRequest((TranslationSegment("B001", "何してんだよ", 1), TranslationSegment("B002", "知らねーよ", 1),
                                   TranslationSegment("B003", "待てって！", 2)), mode=mode, context=context)


@pytest.mark.parametrize("output,code", [
    ('{"B001":"One"}', "missing_ids"),
    ('{"B001":"One","B002":"Two","B003":"Three","B004":"invented"}', "extra_ids"),
    ('{"B001":"One","B001":"duplicate","B002":"Two","B003":"Three"}', "duplicate_ids"),
    ('["One","Two","Three"]', "invalid_format"),
    ('```json\n{}\n```', "invalid_format"),
    ('{"B001":', "invalid_format"),
    ('{"B001":null,"B002":"Two","B003":"Three"}', "untranslated_id"),
    ('{"B001":" ","B002":"Two","B003":"Three"}', "untranslated_id"),
])
def test_exact_id_contract_rejects_partial_duplicate_extra_and_malformed_output(output, code):
    with pytest.raises(StructuredTranslationError) as error:
        parse_output(output, request().segments)
    assert error.value.code == code


def test_schema_and_parser_bind_result_to_requested_ids_in_source_order():
    data = request()
    schema = output_schema(data.segments)
    assert schema["required"] == ["B001", "B002", "B003"]
    assert schema["additionalProperties"] is False
    result = parse_output('{"B003":"Wait!","B001":"What are you doing?","B002":"I do not know."}', data.segments)
    assert list(result) == ["B001", "B002", "B003"]
    assert result["B003"] == "Wait!"
    assert context_for(request(context="neighbor"), (data.segments[1],)) == (data.segments[0], data.segments[2])
    assert context_for(request(context="panel"), (data.segments[0],)) == (data.segments[1],)
    assert context_for(data, (data.segments[1],)) == ()
    with pytest.raises(StructuredTranslationError):
        PageTranslationRequest((data.segments[0], data.segments[0]))


class Runtime:
    device = "cpu"
    def __init__(self, outputs):
        self.outputs, self.calls = iter(outputs), []
    def generate_json(self, messages, schema, *, max_tokens, cancel=None):
        self.calls.append((messages, schema))
        return next(self.outputs), {"input_tokens": 100, "output_tokens": 30}


def test_failed_later_panel_never_returns_partial_success_or_silent_line_fallback():
    runtime = Runtime(['{"B001":"One","B002":"Two"}', '{"B999":"wrong"}'])
    engine = MangaTranslationEngine("qwen25-manga", runtime)
    with pytest.raises(StructuredTranslationError, match="invented"):
        engine.translate_page(request("structured-panel"))
    assert len(runtime.calls) == 2


def test_context_is_separate_data_and_raw_source_identity_is_preserved():
    runtime = Runtime(['{"B001":"One"}', '{"B002":"Two"}', '{"B003":"Three"}'])
    engine = MangaTranslationEngine("qwen25-manga", runtime)
    data = request("structured-line", "neighbor")
    results = engine.translate_page(data)
    assert [r.source_text for r in results] == [s.text for s in data.segments]
    assert results[1].metadata["context_ids"] == ["B001", "B003"]
    payload = json.loads(runtime.calls[1][0][1]["content"])
    assert [s["id"] for s in payload["requested"]] == ["B002"]
    assert set(runtime.calls[1][1]["properties"]) == {"B002"}
    assert results[1].metadata["fallback"] == "none"


def test_transport_uses_pinned_schema_api_exact_tokens_and_complete_termination(monkeypatch):
    import yomiscan.translation.manga as manga
    runtime = LlamaServer(Path("fake.gguf"), executable=Path("fake.exe"), context_size=1024)
    runtime.url = "http://127.0.0.1:12345"
    monkeypatch.setattr(runtime, "load", lambda: None)
    bodies = []
    completion = {"choices": [{"finish_reason": "stop", "message": {"content": '{"B001":"One"}'}}], "usage": {"completion_tokens": 8}}
    class Response:
        def __init__(self, data): self.data = data
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, limit): return json.dumps(self.data).encode()
    def post(req, timeout):
        body = json.loads(req.data); bodies.append(body)
        return Response({"prompt": "complete prompt"} if req.full_url.endswith("apply-template") else
                        {"tokens": [1, 2, 3]} if req.full_url.endswith("tokenize") else completion)
    monkeypatch.setattr(manga, "urlopen", post)
    output, usage = runtime.generate_json([], output_schema(request().segments[:1]), max_tokens=128)
    assert output == '{"B001":"One"}' and usage["input_tokens"] == 3
    assert bodies[-1]["response_format"]["json_schema"]["schema"]["required"] == ["B001"]
    assert bodies[-1]["cache_prompt"] is False
    completion["choices"][0]["finish_reason"] = "length"
    with pytest.raises(StructuredTranslationError) as error:
        runtime.generate_json([], {}, max_tokens=128)
    assert error.value.code == "incomplete_termination"
    runtime.context_size = 100
    with pytest.raises(StructuredTranslationError) as error:
        runtime.generate_json([], {}, max_tokens=128)
    assert error.value.code == "context_limit"


def test_cancel_and_timeout_are_errors_not_retry_or_partial_success(monkeypatch):
    import yomiscan.translation.manga as manga
    runtime = LlamaServer(Path("fake.gguf"), executable=Path("fake.exe"))
    cancel = Event(); cancel.set()
    with pytest.raises(StructuredTranslationError) as error:
        runtime.generate_json([], {}, max_tokens=128, cancel=cancel)
    assert error.value.code == "cancelled"
    monkeypatch.setattr(runtime, "load", lambda: None)
    runtime.url = "http://127.0.0.1:12345"
    monkeypatch.setattr(manga, "urlopen", lambda *a, **k: (_ for _ in ()).throw(TimeoutError("fake timeout")))
    with pytest.raises(StructuredTranslationError) as error:
        runtime.generate_json([], {}, max_tokens=128)
    assert error.value.code == "timeout"
