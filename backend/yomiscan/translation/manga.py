"""Optional local manga engines. No runtime/model is loaded on import or construction.

GGUF engines own one loopback llama.cpp server; Qwen2.5 adds a converted PEFT adapter.
Neither transport calls an external translation service.
"""

from collections.abc import Sequence
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import tempfile
import logging
from typing import TYPE_CHECKING
from time import monotonic, perf_counter, sleep
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from threading import Event, Thread

from .base import Device, TranslationContext, TranslationError, TranslationInitializationError, TranslationResult, validate_text
from .options import TranslationCapabilities
if TYPE_CHECKING:
    from .structured import PageTranslationRequest

HY_MODEL = "fumetodev/Hy-MT2-1.8B-JP-Manga-Finetune-v5-GGUF"
HY_REVISION = "e17bc6a8dd92ddf930bd7858ceb916117ee5f916"
VNTL_MODEL = "0xBrandon/Qwen3.5-4B-VNTL-V1"
VNTL_REVISION = "bf7b11333a9ef958ed4646dcc18dea9f757a6e08"
Q25_MODEL = "NaelShichida/qwen2.5-7b-manga-translator-full"
Q25_REVISION = "4267f42e98fcc2daa36096cea8524a926cbb84d1"
Q25_BASE = "Qwen/Qwen2.5-7B-Instruct"
Q25_BASE_REVISION = "a09a35458c702b33eeacc393d103063234e8bc28"


def messages_for(engine: str, texts: Sequence[str], context: TranslationContext | None = None) -> list[dict[str, str]]:
    """Keep each fine-tune's documented training prompt isolated here."""
    context = context or TranslationContext()
    glossary = "\n".join(f"{ja} translates to {en}" for ja, en in context.glossary.items())
    if engine == "hy-mt2-manga":
        if len(texts) != 1 or context.previous or context.following:
            raise ValueError("Hy-MT2 manga v5 supports independent lines, not dialogue context")
        hints = glossary or "部室 translates to clubroom\nついたー translates to I'm here!"
        prompt = (f"Reference the following manga translations:\n{hints}\n"
                  "Translate the following text from Japanese into English as natural, concise manga dialogue. "
                  "Preserve specific nouns, exact meaning, speaker intent, tone, punctuation, and sound effects. "
                  "Output only the translated result without any explanation:\n\n" + texts[0])
        return [{"role": "user", "content": prompt}]
    if engine == "qwen35-vntl":
        source = "\n".join((*context.previous, *texts, *context.following))
        metadata = "[Metadata]\nLanguage: Japanese"
        if glossary:
            metadata += "\nGlossary:\n" + glossary
        return [{"role": "system", "content": "You are a manga translator. Translate the following text to English."},
                {"role": "user", "content": metadata + "\n\n[Source]\n" + source}]
    if engine == "qwen25-manga":
        if len(texts) != 1:
            raise ValueError("Qwen2.5 manga adapter translates one current line per prompt")
        hints = context.tone
        if context.previous:
            hints += "\nPrevious dialogue: " + " / ".join(context.previous)
        if context.following:
            hints += "\nFollowing dialogue: " + " / ".join(context.following)
        if glossary:
            hints += "\nGlossary:\n" + glossary
        return [{"role": "user", "content": f"Translate this manga dialogue into English. Context: {hints}\n\nInput: {texts[0]}"}]
    raise ValueError(f"Unknown manga engine: {engine}")


def parse_lines(output: str, count: int) -> list[str]:
    lines = output.strip().splitlines()
    if len(lines) != count or any(not line.strip() for line in lines):
        raise TranslationError(f"Model returned {len(lines)} lines for {count} sources; refusing to assign translations to the wrong bubbles")
    if any(line.lstrip().startswith(("```", "[Source]", "[Translation]")) for line in lines):
        raise TranslationError("Model returned unexpected markup instead of aligned translation lines")
    return [line.strip() for line in lines]


class LlamaServer:
    """A single owned, local-only subprocess, reused until close()."""

    def __init__(self, model: Path, *, executable: Path, device: Device = "auto", lora: Path | None = None,
                 context_size: int = 4096, timeout: float = 300) -> None:
        self.model, self.executable, self.requested_device, self.lora = model, executable, device, lora
        self.context_size, self.timeout = context_size, timeout
        self.device = "unloaded"
        self.process: subprocess.Popen | None = None
        self._log = None
        self.url = ""
        self._key = secrets.token_urlsafe(32)
        self.record_debug = False  # Explicit benchmark-only opt-in; never enabled by reader requests.
        self.debug_responses: list[dict[str, object]] = []

    def _record_response(self, payload: dict[str, object]) -> None:
        if self.record_debug and len(self.debug_responses) < 32 and len(json.dumps(payload).encode()) <= 128*1024:
            self.debug_responses.append(payload)

    def load(self) -> None:
        if self.process is not None:
            if self.process.poll() is not None:
                raise TranslationError("The local llama.cpp server exited unexpectedly")
            return
        if self.requested_device not in ("auto", "cpu", "cuda"):
            raise ValueError("device must be auto, cpu, or cuda")
        for path in (self.executable, self.model, self.lora):
            if path is not None and not path.is_file():
                raise TranslationInitializationError(f"Local runtime/model file not found: {path}. See docs/translation-benchmark.md for setup.")
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        try:
            probe = subprocess.run([str(self.executable), "--list-devices"], capture_output=True, text=True,
                                   errors="replace", timeout=30, creationflags=flags)
            cuda = "CUDA" in probe.stdout
            if self.requested_device == "cuda" and not cuda:
                raise TranslationInitializationError("CUDA requested, but this llama.cpp runtime reports no CUDA device. Install its CUDA runtime bundle or select cpu.")
            self.device = "cuda" if self.requested_device != "cpu" and cuda else "cpu"
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            self.url = f"http://127.0.0.1:{port}"
            args = [str(self.executable), "--model", str(self.model), "--host", "127.0.0.1", "--port", str(port),
                    "--ctx-size", str(self.context_size), "--parallel", "1", "--n-gpu-layers",
                    "99" if self.device == "cuda" else "0", "--alias", "yomiscan", "--no-webui", "--no-context-shift"]
            if self.lora:
                args += ["--lora", str(self.lora)]
            self._log = tempfile.TemporaryFile(mode="w+b")
            self.process = subprocess.Popen(args, stdout=self._log, stderr=self._log, creationflags=flags,
                                            env={**os.environ, "LLAMA_API_KEY": self._key})
            deadline = monotonic() + self.timeout
            while monotonic() < deadline:
                if self.process.poll() is not None:
                    self._log.seek(0)
                    detail = self._log.read().decode("utf-8", errors="replace")[-3000:]
                    raise TranslationInitializationError(f"llama.cpp initialization failed: {detail}")
                try:
                    with urlopen(self.url + "/health", timeout=2) as response:
                        if response.status == 200:
                            return
                except (URLError, TimeoutError):
                    sleep(.1)
            raise TranslationInitializationError("Timed out waiting for the local llama.cpp model to load")
        except (OSError, subprocess.SubprocessError) as exc:
            self.close()
            raise TranslationInitializationError(f"Could not start llama.cpp: {exc}") from exc
        except TranslationInitializationError:
            self.close()
            raise

    def generate(self, messages: list[dict[str, str]], *, max_tokens: int) -> str:
        self.load()
        body = {"model": "yomiscan", "messages": messages, "temperature": 0, "seed": 0,
                "max_tokens": max_tokens, "stream": False, "repeat_penalty": 1.0, "cache_prompt": False}
        request = Request(self.url + "/v1/chat/completions", data=json.dumps(body).encode(),
                          headers={"Content-Type": "application/json", "Authorization": "Bearer " + self._key})
        try:
            with urlopen(request, timeout=self.timeout) as response:
                payload = json.load(response)
            self._record_response(payload)
            choice = payload["choices"][0]
            if choice["finish_reason"] != "stop":
                raise TranslationError(f"Local model output did not finish normally: {choice['finish_reason']}")
            output = choice["message"]["content"]
            if not isinstance(output, str) or not output.strip():
                raise TranslationError("Local model returned an empty translation")
            return output.strip()
        except HTTPError as exc:
            detail = exc.read(2000).decode("utf-8", errors="replace")
            raise TranslationError(f"Local inference HTTP {exc.code}: {detail}") from exc
        except (URLError, TimeoutError, ValueError, KeyError, IndexError, TypeError) as exc:
            raise TranslationError(f"Invalid/failed local inference response: {exc}") from exc

    def generate_json(self, messages: list[dict[str, str]], schema: dict[str, object], *,
                      max_tokens: int, cancel: Event | None = None) -> tuple[str, dict[str, object]]:
        """Pinned server JSON-schema interface, exact prompt-token preflight, bounded response.

        Cancellation terminates only this transport's owned inference subprocess. It
        may require reloading next time; it cannot leave a partial page as success.
        """
        from .structured import StructuredTranslationError
        if cancel is not None and cancel.is_set():
            raise StructuredTranslationError("cancelled", "Structured page translation cancelled")
        done = Event()
        def watch() -> None:
            while not done.wait(.05):
                if cancel is not None and cancel.is_set() and self.process is not None:
                    process = self.process
                    if process.poll() is None:
                        try:
                            process.terminate()
                            process.wait(timeout=1)
                        except subprocess.TimeoutExpired:
                            process.kill()
                        except OSError:
                            logging.getLogger(__name__).warning("Owned runtime cancellation raced with process exit", exc_info=True)
                    return
        watcher = Thread(target=watch, daemon=True) if cancel is not None else None
        if watcher is not None:
            watcher.start()
        def post(endpoint: str, body: dict[str, object]) -> dict:
            request = Request(self.url+endpoint, data=json.dumps(body).encode(), headers={
                "Content-Type": "application/json", "Authorization": "Bearer "+self._key})
            with urlopen(request, timeout=self.timeout) as response:
                encoded = response.read(1024*1024+1)
            if len(encoded) > 1024*1024:
                raise StructuredTranslationError("output_limit", "Local structured response exceeds 1 MiB")
            result = json.loads(encoded)
            if not isinstance(result, dict):
                raise ValueError("Expected a JSON response object")
            return result
        try:
            self.load()
            template = post("/apply-template", {"messages": messages})["prompt"]
            if not isinstance(template, str) or len(template.encode()) > 64*1024:
                raise StructuredTranslationError("input_limit", "Chat template exceeds the input byte budget")
            tokens = post("/tokenize", {"content": template, "add_special": True, "parse_special": True})["tokens"]
            if not isinstance(tokens, list) or any(type(t) is not int for t in tokens):
                raise ValueError("Runtime returned invalid token IDs")
            if not 1 <= max_tokens <= 2048 or len(tokens)+max_tokens+64 > self.context_size:
                raise StructuredTranslationError("context_limit", "Complete prompt plus output/reserve exceeds the runtime context; nothing was truncated")
            payload = post("/v1/chat/completions", {"model": "yomiscan", "messages": messages, "temperature": 0, "seed": 0,
                "max_tokens": max_tokens, "stream": False, "repeat_penalty": 1.0, "cache_prompt": False,
                "response_format": {"type": "json_schema", "json_schema": {"name": "page_translations", "schema": schema}}})
            self._record_response(payload)
            if cancel is not None and cancel.is_set():
                raise StructuredTranslationError("cancelled", "Structured page translation cancelled")
            choice = payload["choices"][0]
            if choice["finish_reason"] != "stop":
                raise StructuredTranslationError("incomplete_termination", "Structured generation did not terminate normally")
            output = choice["message"]["content"]
            if not isinstance(output, str) or not output.strip():
                raise StructuredTranslationError("invalid_format", "Structured generation returned no content")
            usage = payload.get("usage", {})
            return output, {"input_tokens": len(tokens), "output_tokens": usage.get("completion_tokens"),
                            "token_budget": max_tokens, "context_tokens": self.context_size, "termination": "stop"}
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, KeyError, IndexError, TypeError) as exc:
            if cancel is not None and cancel.is_set():
                raise StructuredTranslationError("cancelled", "Structured translation cancelled; owned runtime stopped") from exc
            code = "timeout" if isinstance(exc, TimeoutError) or isinstance(getattr(exc, "reason", None), TimeoutError) else "runtime_error"
            raise StructuredTranslationError(code, "Local structured translation failed; verify the pinned runtime and server logs") from exc
        finally:
            done.set()
            if watcher is not None:
                watcher.join(timeout=2)
            if cancel is not None and cancel.is_set():
                self.close()
                self.device = "unloaded"

    def close(self) -> None:
        if self.process is not None:
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait()
            self.process = None
        if self._log is not None:
            self._log.close()
            self._log = None


class MangaTranslationEngine:
    """Adapters share transport, but retain distinct model prompts and batch semantics."""

    def __init__(self, engine: str, runtime: LlamaServer | None, *, model: str | None = None) -> None:
        self.engine = engine
        self.model = model or {"hy-mt2-manga": HY_MODEL, "qwen35-vntl": VNTL_MODEL, "qwen25-manga": Q25_MODEL}[engine]
        self.runtime = runtime

    @property
    def device(self) -> str:
        return self.runtime.device if self.runtime else "unavailable"

    def diagnostic_metadata(self) -> dict[str, object]:
        return {"engine": self.engine, "model": self.model, "device": self.device,
                "context_tokens": self.runtime.context_size if self.runtime else None, "temperature": 0, "seed": 0,
                "base_model": Q25_BASE if self.engine == "qwen25-manga" else None,
                "base_revision": Q25_BASE_REVISION if self.engine == "qwen25-manga" else None,
                "expected_revision": {"hy-mt2-manga": HY_REVISION, "qwen35-vntl": VNTL_REVISION,
                                      "qwen25-manga": Q25_REVISION}[self.engine]}

    def capabilities(self) -> TranslationCapabilities:
        available = self.engine in ("hy-mt2-manga", "qwen25-manga")
        return TranslationCapabilities(glossary_hints=True, structured=available, bounded_context=available)

    def translate_page(self, request: "PageTranslationRequest", *, cancel: Event | None = None) -> list[TranslationResult]:
        from .structured import (CONTRACT_VERSION, request_groups, structured_messages, output_schema,
                                 parse_output, context_for, StructuredTranslationError)
        if not self.capabilities().structured:
            raise StructuredTranslationError("unsupported_engine", "This adapter has no validated structured runtime contract")
        if self.runtime is None:
            raise StructuredTranslationError("runtime_unavailable", "Configure the selected local LLM artifact first")
        results = {}
        # Collect all groups before returning: later panel failure invalidates the whole page.
        for group in request_groups(request):
            if cancel is not None and cancel.is_set():
                raise StructuredTranslationError("cancelled", "Structured translation cancelled")
            start = perf_counter()
            output, usage = self.runtime.generate_json(structured_messages(request, group), output_schema(group),
                max_tokens=min(2048, 128*len(group)+64), cancel=cancel)
            parsed = parse_output(output, group)
            elapsed = (perf_counter()-start)*1000
            for segment in group:
                results[segment.id] = TranslationResult(segment.text, parsed[segment.id], self.engine, self.model, elapsed,
                    {"device": self.device, "runtime": "llama.cpp", "target_language": request.target_language,
                     "prompt_version": 3, "grammar_contract": CONTRACT_VERSION, "translation_mode": request.mode,
                     "block_id": segment.id, "panel_id": segment.panel_id, "context_policy": request.context,
                     "context_ids": [s.id for s in context_for(request, group)], "glossary_terms": len(request.glossary),
                     "glossary_application": "hints" if request.glossary else "none", "fallback": "none",
                     "timing_scope": "structured_group", **usage})
        return [results[segment.id] for segment in request.segments]

    def load(self) -> None:
        if self.runtime is None:
            raise TranslationInitializationError(
                f"{self.model} has no configured local artifact. Qwen3.5 VNTL's published revision "
                f"{VNTL_REVISION} contains no weights; do not substitute the base model. See docs/translation-benchmark.md."
            )
        self.runtime.load()

    def close(self) -> None:
        if self.runtime:
            self.runtime.close()

    def translate(self, text: str, *, context: TranslationContext | None = None) -> TranslationResult:
        return self.translate_many([text], context=context)[0]

    def translate_many(self, texts: Sequence[str], *, context: TranslationContext | None = None) -> list[TranslationResult]:
        texts = list(texts)
        for text in texts:
            validate_text(text)
        if not texts:
            return []
        # Visual OCR line breaks belong to one bubble, not additional VNTL outputs.
        normalized = [" ".join(text.split()) for text in texts]
        context = context or TranslationContext()
        if any("\n" in text or "\r" in text for text in (*context.previous, *context.following)):
            raise ValueError("Context items must be single dialogue lines, without embedded newlines")
        if self.engine == "hy-mt2-manga" and (context.previous or context.following):
            raise ValueError("Hy-MT2 manga v5 does not support dialogue context; use isolated mode")
        self.load()
        assert self.runtime is not None
        if self.engine == "qwen35-vntl":
            start = perf_counter()
            count = len(context.previous) + len(texts) + len(context.following)
            output = self.runtime.generate(messages_for(self.engine, normalized, context), max_tokens=min(2048, 128 * count))
            lines = parse_lines(output, count)[len(context.previous):len(context.previous) + len(texts)]
            elapsed = (perf_counter() - start) * 1000
            return [self._result(source, line, elapsed, "page", len(texts)) for source, line in zip(texts, lines, strict=True)]
        results = []
        for source, normalized_text in zip(texts, normalized, strict=True):
            start = perf_counter()
            output = self.runtime.generate(messages_for(self.engine, [normalized_text], context), max_tokens=512)
            if self.engine == "qwen25-manga":
                # This fine-tune sometimes echoes the surrounding dialogue. Never silently
                # choose the first line and attach another bubble's words to this source.
                output = parse_lines(output, 1)[0]
            results.append(self._result(source, output, (perf_counter() - start) * 1000, "sentence", 1))
        return results

    def _result(self, source: str, output: str, elapsed: float, scope: str, size: int) -> TranslationResult:
        return TranslationResult(source, output, self.engine, self.model, elapsed,
                                 {"device": self.device, "runtime": "llama.cpp", "temperature": 0,
                                  "timing_scope": scope, "batch_size": size,
                                  "prompt_version": 2, "cache_prompt": False,
                                  "artifact": str(self.runtime.model) if self.runtime else None,
                                  "adapter": str(self.runtime.lora) if self.runtime and self.runtime.lora else None,
                                  "expected_revision": {"hy-mt2-manga": HY_REVISION, "qwen35-vntl": VNTL_REVISION,
                                               "qwen25-manga": Q25_REVISION}[self.engine]})
