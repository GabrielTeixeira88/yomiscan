"""Run with uvicorn yomiscan.api.main:app --host 127.0.0.1 --port 47615 (the default port of yomiscan-server)."""

import asyncio
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import AbstractContextManager, asynccontextmanager
import logging
import json
import os
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from time import perf_counter
from typing import Annotated, cast

from fastapi import FastAPI, File, HTTPException, Request, UploadFile, Query, Form, Path as PathParameter
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from pydantic import TypeAdapter, ValidationError
from dataclasses import fields
from threading import Event
import sqlite3
from fastapi.responses import Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from yomiscan.service import ImageAnalysisService, open_local_service, PageRefreshError, TranslationConfigurationChanged
from yomiscan.cache import Refresh, MiB
from yomiscan.translation.options import TranslationOptions, TargetLanguage
from yomiscan.translation.base import Device
from yomiscan.detection import DetectionInitializationError
from .images import decode_image, MAX_FILE_BYTES
from .models import ImageAnalysisResponse, PageAnalysisResponse
from .security import EXTENSION_ORIGIN, LocalRequestGuard
from ..rendering.settings import RenderSettings
from ..progress import JobRegistry, Progress
from ..readiness import SetupUnavailable

logger = logging.getLogger(__name__)
ServiceFactory = Callable[[], AbstractContextManager[ImageAnalysisService]]


class TextAnalysisRequest(BaseModel):
    """OCR text the user corrected in the Study popup."""
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=1000)


class EngineSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    engine: str = Field(min_length=1, max_length=32, pattern=r"^[a-z0-9-]+$")


class CacheSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    enabled: StrictBool
    disk_bytes: int | None = Field(default=None, ge=MiB, le=16*1024*MiB)


class SeriesCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    label: str = Field(min_length=1, max_length=100)


class SeriesDelete(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    scope: str = Field(min_length=1, max_length=36)


class GlossaryTerm(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    scope: str = Field(min_length=1, max_length=36)
    target_language: TargetLanguage
    source: str = Field(min_length=1, max_length=120)
    preferred: str = Field(min_length=1, max_length=200)
    entry_id: str | None = Field(default=None, min_length=36, max_length=36)


class GlossaryDelete(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    scope: str = Field(min_length=1, max_length=36)
    target_language: TargetLanguage
    entry_id: str = Field(min_length=36, max_length=36)


def parse_options(encoded: str | None) -> TranslationOptions | None:
    if encoded is None:
        return None
    try:
        data = json.loads(encoded)
        if not isinstance(data, dict) or set(data)-{f.name for f in fields(TranslationOptions)}:
            raise ValueError("Unknown translation option")
        return TypeAdapter(TranslationOptions).validate_json(encoded, strict=True)
    except (ValueError, TypeError, ValidationError) as exc:
        raise HTTPException(422, "Invalid bounded translation options") from exc


def default_service() -> AbstractContextManager[ImageAnalysisService]:
    device = os.getenv("YOMISCAN_DEVICE", "auto")
    if device not in ("auto", "cpu", "cuda"):
        raise ValueError("YOMISCAN_DEVICE must be auto, cpu, or cuda")
    return open_local_service(
        Path(os.getenv("YOMISCAN_DICTIONARY", "data/jmdict.sqlite3")), device=cast(Device, device),
    )


def analyze_upload(service: ImageAnalysisService, data: bytes, page: bool = False,
                   render: bool = False, diagnostics: bool = False, refresh: Refresh = "none",
                   configuration: str | None = None, options: TranslationOptions | None = None,
                   cancel: Event | None = None, font_scale: float = 1.0,
                   progress: Progress | None = None) -> ImageAnalysisResponse | PageAnalysisResponse | Response:
    start = perf_counter()
    try:
        image = decode_image(data)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    with image:
        if configuration is not None and service.configuration_id() != configuration:
            raise HTTPException(409, "Processing settings changed. Start the chapter again to invalidate session results.")
        if page:
            try:
                if render:
                    try:
                        keywords = {}
                        if refresh != "none": keywords["refresh"] = refresh
                        if options is not None: keywords["options"] = options
                        if cancel is not None: keywords["cancel"] = cancel
                        if font_scale != 1.0: keywords["render_settings"] = RenderSettings(font_scale)
                        if progress is not None: keywords["progress"] = progress
                        result = service.translate_and_render_page(image, **keywords)
                    except PageRefreshError as exc:
                        raise HTTPException(502, "Page refresh failed; previous translation retained. See server logs.") from exc
                    if diagnostics:
                        if progress: progress("finalizing", "running", None)
                        from yomiscan.diagnostics import page_snapshot, render_bundle
                        models = service.diagnostic_models()
                        models.setdefault("settings", {}).update(result.diagnostics.get("translation_settings", {}))
                        snapshot = page_snapshot(image, result, input_sha256=sha256(data).hexdigest(), models=models)
                        snapshot["timings"]["backend_before_pack_ms"] = (perf_counter() - start) * 1000
                        try:
                            bundle = render_bundle(result.rendered_image, snapshot)
                        except ValueError as exc:
                            raise HTTPException(413, str(exc)) from exc
                        return Response(bundle, media_type="application/zip", headers={"Cache-Control": "no-store"})
                    buffer = BytesIO()
                    result.rendered_image.save(buffer, format="PNG")
                    return Response(buffer.getvalue(), media_type="image/png", headers={
                        "X-YomiScan-Blocks-Rendered": str(result.blocks_rendered),
                        "X-YomiScan-Blocks-Skipped": str(result.blocks_skipped),
                        "X-YomiScan-Coverage": json.dumps(result.diagnostics.get("coverage", {}), separators=(",", ":")),
                        "X-YomiScan-Processing-Ms": f"{result.analysis_processing.get('pipeline_total_ms', 0):.1f}",
                        "Cache-Control": "no-store",
                    })
                return PageAnalysisResponse.from_result(service.analyze_page(image, options=options, cancel=cancel) if options is not None else service.analyze_page(image))
            except TranslationConfigurationChanged as exc:
                raise HTTPException(409, "Glossary changed. Reload translation settings and start the chapter again.") from exc
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
            except DetectionInitializationError as exc:
                logger.exception("Page detector unavailable")
                raise HTTPException(503, "Page detector unavailable. Check server logs and model setup.") from exc
            except SetupUnavailable as exc:
                raise HTTPException(503, "Selected model artifacts are unavailable. Open Setup & readiness, prepare them explicitly, then restart.") from exc
        result = service.analyze_image(image)
    return ImageAnalysisResponse.from_result(result, (perf_counter() - start) * 1000)


def create_app(
    service_factory: ServiceFactory = default_service, *, allowed_origins: list[str] | None = None,
    background_initialization: bool | None = None,
) -> FastAPI:
    origins = allowed_origins if allowed_origins is not None else [
        value.strip() for value in os.getenv("YOMISCAN_EXTENSION_ORIGINS", "").split(",") if value.strip()
    ]

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # SQLite creation/use/close and model inference all share one owning thread.
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="yomiscan-analysis")
        app.state.executor = executor
        app.state.service = None
        app.state.busy = False
        app.state.configuration_id = None
        app.state.jobs = JobRegistry()
        app.state.initialization = "initializing"
        app.state.failure_code = None
        app.state.runtime_state = {}
        app.state.readiness_environment = dict(os.environ)
        context = None

        def initialize():
            nonlocal context
            context = service_factory()
            service = context.__enter__()
            if isinstance(service, ImageAnalysisService):
                app.state.configuration_id = service.configuration_id()
            return service

        async def initialize_resources():
            try:
                app.state.service = await asyncio.wrap_future(executor.submit(initialize))
                app.state.runtime_state = await asyncio.wrap_future(executor.submit(app.state.service.runtime_state)) if isinstance(app.state.service, ImageAnalysisService) else {}
                app.state.initialization = "ready"
            except Exception as exc:
                # Startup boundary: expose availability, retain full diagnostics only in logs.
                logger.exception("YomiScan initialization failed; check dictionary, model cache and device. Restart after fixing.")
                app.state.initialization = "failed"
                from ..translation.base import TranslationInitializationError
                from ..ocr import OCRInitializationError
                from ..dictionary.models import DictionaryError
                from ..readiness import SetupUnavailable
                app.state.failure_code = exc.code if isinstance(exc, SetupUnavailable) else "dictionary_unavailable" if isinstance(exc, DictionaryError) else "translation_unavailable" if isinstance(exc, TranslationInitializationError) else "ocr_unavailable" if isinstance(exc, OCRInitializationError) else "initialization_failed"
        initialization_task = asyncio.create_task(initialize_resources())
        try:
            if not (background_initialization if background_initialization is not None else service_factory is default_service):
                await initialization_task
            yield
        finally:
            try:
                await initialization_task
                if app.state.service is not None and context is not None:
                    await asyncio.wrap_future(executor.submit(context.__exit__, None, None, None))
            finally:
                executor.shutdown(wait=True, cancel_futures=True)

    app = FastAPI(title="YomiScan local study API", version="1.0", lifespan=lifespan)
    app.add_middleware(LocalRequestGuard, origins=origins)
    app.add_middleware(
        CORSMiddleware, allow_origins=origins,
        allow_origin_regex=None if origins else EXTENSION_ORIGIN,
        allow_methods=["GET", "POST"], allow_headers=["Content-Type", "X-YomiScan-Client"],
        expose_headers=["X-YomiScan-Blocks-Rendered", "X-YomiScan-Blocks-Skipped", "X-YomiScan-Processing-Ms", "X-YomiScan-Coverage", "X-YomiScan-Configuration"],
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "[::1]"])

    @app.get("/health")
    async def health(request: Request, response: Response) -> dict[str, str]:
        if request.app.state.service is None:
            raise HTTPException(503, "Analysis resources unavailable. Check server logs and restart after setup.")
        # Immutable string published by the worker: responsive even during inference.
        if request.app.state.configuration_id is not None:
            response.headers["X-YomiScan-Configuration"] = request.app.state.configuration_id
        response.headers["Cache-Control"] = "no-store"
        return {"status": "ok"}

    @app.get("/api/v1/readiness")
    async def readiness(request: Request):
        from ..readiness import readiness_snapshot
        state = request.app.state
        return readiness_snapshot(initialization=state.initialization, busy=state.busy,
            failure_code=state.failure_code, loaded=state.runtime_state, environment=state.readiness_environment)

    @app.get("/api/v1/jobs/{job_id}")
    async def job_status(request: Request, job_id: Annotated[str, PathParameter(pattern=r"^[a-f0-9-]{36}$", max_length=36)]):
        result = request.app.state.jobs.snapshot(job_id)
        if result is None:
            raise HTTPException(404, "Job status unavailable or expired")
        return result

    @app.post("/api/v1/analyze-image", response_model=ImageAnalysisResponse)
    async def analyze(request: Request, file: Annotated[UploadFile, File()]) -> ImageAnalysisResponse:
        return await handle_upload(request, file, page=False)

    @app.post("/api/v1/analyze-text", response_model=ImageAnalysisResponse)
    async def analyze_text(request: Request, body: TextAnalysisRequest) -> ImageAnalysisResponse:
        """Re-analyze corrected OCR text: no image, no OCR; same single worker as images."""
        text = body.text.strip()
        if not text:
            raise HTTPException(422, "Enter some Japanese text to analyze.")
        state = request.app.state
        if state.service is None:
            raise HTTPException(503, "Analysis resources unavailable. Check server logs and restart after setup.")
        if state.busy:
            raise HTTPException(429, "YomiScan is processing another crop. Please try again shortly.")
        state.busy = True
        start = perf_counter()

        def perform() -> ImageAnalysisResponse:
            analysis = state.service.analyze_text(text)
            return ImageAnalysisResponse.from_analysis(analysis, total_ms=(perf_counter() - start) * 1000, origin="edited")
        future = asyncio.get_running_loop().run_in_executor(state.executor, perform)

        def finished(task: asyncio.Future) -> None:
            state.busy = False
            if not task.cancelled() and (error := task.exception()) is not None and not isinstance(error, HTTPException):
                logger.error("Text analysis failed", exc_info=(type(error), error, error.__traceback__))
        future.add_done_callback(finished)
        try:
            return await asyncio.shield(future)
        except HTTPException:
            raise
        except Exception as exc:
            # HTTP boundary: do not disclose library errors, paths, or tracebacks to clients.
            raise HTTPException(500, "Text analysis failed. See server logs.") from exc

    @app.post("/api/v1/analyze-page", response_model=PageAnalysisResponse)
    async def analyze_page(request: Request, file: Annotated[UploadFile, File()],
                           options_json: Annotated[str | None, Form(max_length=2048)] = None) -> PageAnalysisResponse:
        return await handle_upload(request, file, page=True, options=parse_options(options_json))

    @app.post("/api/v1/render-page", response_class=Response,
              responses={200: {"content": {"image/png": {}, "application/zip": {}}}})
    async def render_page(request: Request, file: Annotated[UploadFile, File()], diagnostics: bool = False,
                          refresh: Refresh = "none",
                          font_scale: Annotated[float, Query(ge=.75, le=1.5)] = 1.0,
                          job_id: Annotated[str | None, Query(pattern=r"^[a-f0-9-]{36}$", max_length=36)] = None,
                          options_json: Annotated[str | None, Form(max_length=2048)] = None,
                          configuration: Annotated[str | None, Query(pattern=r"^[a-f0-9]{64}$", max_length=64)] = None) -> Response:
        return await handle_upload(request, file, page=True, render=True, diagnostics=diagnostics,
                                   refresh=refresh, configuration=configuration, options=parse_options(options_json), font_scale=font_scale, job_id=job_id)

    async def cache_operation(request: Request, operation: Callable[[ImageAnalysisService], object]):
        state = request.app.state
        if state.service is None:
            raise HTTPException(503, "Analysis resources unavailable.")
        if state.busy:
            raise HTTPException(429, "Processing is active; try cache controls after the current page finishes.")
        state.busy = True
        def perform_operation():
            try:
                return operation(state.service)
            finally:
                if isinstance(state.service, ImageAnalysisService):
                    state.runtime_state = state.service.runtime_state()
        future = asyncio.get_running_loop().run_in_executor(state.executor, perform_operation)
        def finished(task: asyncio.Future) -> None:
            state.busy = False
            if not task.cancelled():
                task.exception()
        future.add_done_callback(finished)
        try:
            return await asyncio.shield(future)
        except OSError as exc:
            logger.exception("Cache administration failed")
            raise HTTPException(503, "Local cache storage is unavailable. Check permissions and server logs.") from exc
        except sqlite3.Error as exc:
            logger.exception("Local user-data operation failed")
            raise HTTPException(503, "Local glossary data unavailable. Preserve its database and check server logs.") from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.post("/api/v1/translation-engine")
    async def translation_engine(request: Request, body: EngineSelection) -> dict[str, str]:
        """Switch the sentence translator to another installed engine until the backend restarts."""
        from ..readiness import local_artifacts, model_catalog
        spec = next((item for item in model_catalog() if item.id == body.engine and item.kind == "translation"), None)
        if spec is None:
            raise HTTPException(422, "Unknown translation engine.")
        state = request.app.state
        if state.service is None:
            raise HTTPException(503, "Analysis resources unavailable. Check server logs and restart after setup.")
        if state.busy:
            raise HTTPException(429, "Processing is active; switch engines after the current request finishes.")
        environment = dict(state.readiness_environment or os.environ)
        state.busy = True

        def perform() -> None:
            if not local_artifacts(spec, environment)[1]:
                raise HTTPException(409, f"{spec.id} is not installed. Setup: {spec.setup_command}")
            state.service.select_translation_engine(spec.id)
            if isinstance(state.service, ImageAnalysisService):
                state.configuration_id = state.service.configuration_id()
                state.runtime_state = state.service.runtime_state()
        future = asyncio.get_running_loop().run_in_executor(state.executor, perform)

        def finished(task: asyncio.Future) -> None:
            state.busy = False
            if not task.cancelled() and (error := task.exception()) is not None and not isinstance(error, HTTPException):
                logger.error("Translation engine switch failed", exc_info=(type(error), error, error.__traceback__))
        future.add_done_callback(finished)
        try:
            await asyncio.shield(future)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(503, "The engine could not be loaded; the previous engine is still active. See server logs.") from exc
        if state.readiness_environment is not None:
            state.readiness_environment["YOMISCAN_TRANSLATION_ENGINE"] = spec.id
        return {"selected": spec.id}

    @app.get("/api/v1/translation-profile")
    async def translation_profile(request: Request, scope: Annotated[str, Query(max_length=36)] = "global",
                                  target: TargetLanguage | None = None):
        return await cache_operation(request, lambda service: service.translation_profile(scope, target))

    @app.post("/api/v1/glossaries/series")
    async def glossary_series(request: Request, item: SeriesCreate):
        return await cache_operation(request, lambda service: {"id": service.glossaries.create_series(item.label)})

    @app.post("/api/v1/glossaries/delete-series")
    async def glossary_delete_series(request: Request, item: SeriesDelete):
        def perform(service: ImageAnalysisService):
            service.glossaries.delete_series(item.scope)
            return {"ok": True}
        return await cache_operation(request, perform)

    @app.post("/api/v1/glossaries/term")
    async def glossary_term(request: Request, item: GlossaryTerm):
        return await cache_operation(request, lambda service: {"id": service.glossaries.save_entry(
            item.scope, item.target_language, item.source, item.preferred, entry_id=item.entry_id)})

    @app.post("/api/v1/glossaries/delete-term")
    async def glossary_delete_term(request: Request, item: GlossaryDelete):
        def perform(service: ImageAnalysisService):
            service.glossaries.delete_entry(item.scope, item.target_language, item.entry_id)
            return {"ok": True}
        return await cache_operation(request, perform)

    @app.get("/api/v1/cache")
    async def cache_status(request: Request):
        return await cache_operation(request, lambda service: {
            **service.cache.stats(), "configuration_id": service.configuration_id()})

    @app.post("/api/v1/cache/settings")
    async def cache_settings(request: Request, settings: CacheSettings):
        return await cache_operation(request, lambda service: service.cache.configure(settings.enabled, settings.disk_bytes))

    @app.post("/api/v1/cache/clear")
    async def cache_clear(request: Request):
        return await cache_operation(request, lambda service: service.cache.clear())

    async def handle_upload(request: Request, file: UploadFile, *, page: bool,
                            render: bool = False, diagnostics: bool = False, refresh: Refresh = "none",
                            configuration: str | None = None, options: TranslationOptions | None = None,
                            font_scale: float = 1.0, job_id: str | None = None) -> ImageAnalysisResponse | PageAnalysisResponse | Response:
        try:
            data = await file.read(MAX_FILE_BYTES + 1)
        finally:
            await file.close()
        if len(data) > MAX_FILE_BYTES:
            raise HTTPException(413, "Image exceeds 10 MiB.")
        if not data:
            raise HTTPException(400, "The uploaded image is empty.")
        state = request.app.state
        if state.service is None:
            raise HTTPException(503, "Analysis resources unavailable. Check server logs and restart after setup.")
        if state.busy:
            raise HTTPException(429, "YomiScan is processing another crop. Please try again shortly.")
        progress = None
        if job_id is not None:
            try: progress = state.jobs.start(job_id)
            except ValueError as exc: raise HTTPException(409, "Use a new job identifier") from exc
        state.busy = True
        cancel = Event() if job_id is not None or (options is not None and options.mode != "sentences") else None
        def perform_upload():
            if isinstance(state.service, ImageAnalysisService):
                state.configuration_id = state.service.configuration_id()
            try:
                return analyze_upload(state.service, data, page, render, diagnostics, refresh, configuration, options, cancel, font_scale, progress)
            finally:
                if isinstance(state.service, ImageAnalysisService): state.runtime_state = state.service.runtime_state()
        future = asyncio.get_running_loop().run_in_executor(state.executor, perform_upload)

        def finished(task: asyncio.Future) -> None:
            state.busy = False
            # Retrieve failures even if the HTTP client disconnected while inference ran.
            if not task.cancelled():
                error = task.exception()
                if job_id is not None: state.jobs.finish(job_id, "cancelled" if cancel is not None and cancel.is_set() else "failed" if error is not None else "completed")
                if error is not None and not isinstance(error, HTTPException):
                    logger.error("Image analysis failed", exc_info=(type(error), error, error.__traceback__))

        future.add_done_callback(finished)
        async def watch_disconnect():
            while not future.done():
                if await request.is_disconnected():
                    cancel.set()
                    return
                await asyncio.sleep(.1)
        monitor = asyncio.create_task(watch_disconnect()) if cancel is not None else None
        try:
            return await asyncio.shield(future)
        except asyncio.CancelledError:
            if cancel is not None: cancel.set()
            raise
        except HTTPException:
            raise
        except Exception as exc:
            # HTTP boundary: do not disclose library errors, paths, or tracebacks to clients.
            if page:
                raise HTTPException(500, "Page analysis failed. See server logs for diagnostics.") from exc
            raise HTTPException(500, "Image analysis failed. Try a smaller clear crop; see server logs.") from exc
        finally:
            if monitor is not None:
                monitor.cancel()

    return app


app = create_app()
