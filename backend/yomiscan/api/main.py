"""Run with uvicorn yomiscan.api.main:app --host 127.0.0.1 --port 8765."""

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

from fastapi import FastAPI, File, HTTPException, Request, UploadFile, Query
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from fastapi.responses import Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from yomiscan.service import ImageAnalysisService, open_local_service, PageRefreshError
from yomiscan.cache import Refresh, MiB
from yomiscan.translation.base import Device
from yomiscan.detection import DetectionInitializationError
from .images import decode_image, MAX_FILE_BYTES
from .models import ImageAnalysisResponse, PageAnalysisResponse
from .security import EXTENSION_ORIGIN, LocalRequestGuard

logger = logging.getLogger(__name__)
ServiceFactory = Callable[[], AbstractContextManager[ImageAnalysisService]]


class CacheSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    enabled: StrictBool
    disk_bytes: int | None = Field(default=None, ge=MiB, le=16*1024*MiB)


def default_service() -> AbstractContextManager[ImageAnalysisService]:
    device = os.getenv("YOMISCAN_DEVICE", "auto")
    if device not in ("auto", "cpu", "cuda"):
        raise ValueError("YOMISCAN_DEVICE must be auto, cpu, or cuda")
    return open_local_service(
        Path(os.getenv("YOMISCAN_DICTIONARY", "data/jmdict.sqlite3")), device=cast(Device, device),
    )


def analyze_upload(service: ImageAnalysisService, data: bytes, page: bool = False,
                   render: bool = False, diagnostics: bool = False, refresh: Refresh = "none",
                   configuration: str | None = None) -> ImageAnalysisResponse | PageAnalysisResponse | Response:
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
                        result = service.translate_and_render_page(image, refresh=refresh) if refresh != "none" else service.translate_and_render_page(image)
                    except PageRefreshError as exc:
                        raise HTTPException(502, "Page refresh failed; previous translation retained. See server logs.") from exc
                    if diagnostics:
                        from yomiscan.diagnostics import page_snapshot, render_bundle
                        snapshot = page_snapshot(image, result, input_sha256=sha256(data).hexdigest(),
                                                 models=service.diagnostic_models())
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
                return PageAnalysisResponse.from_result(service.analyze_page(image))
            except DetectionInitializationError as exc:
                logger.exception("Page detector unavailable")
                raise HTTPException(503, "Page detector unavailable. Check server logs and model setup.") from exc
        result = service.analyze_image(image)
    return ImageAnalysisResponse.from_result(result, (perf_counter() - start) * 1000)


def create_app(
    service_factory: ServiceFactory = default_service, *, allowed_origins: list[str] | None = None,
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
        context = None

        def initialize():
            nonlocal context
            context = service_factory()
            service = context.__enter__()
            if isinstance(service, ImageAnalysisService):
                app.state.configuration_id = service.configuration_id()
            return service

        try:
            try:
                app.state.service = await asyncio.wrap_future(executor.submit(initialize))
            except Exception:
                # Startup boundary: expose availability, retain full diagnostics only in logs.
                logger.exception("YomiScan initialization failed; check dictionary, model cache and device. Restart after fixing.")
            yield
        finally:
            try:
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

    @app.post("/api/v1/analyze-image", response_model=ImageAnalysisResponse)
    async def analyze(request: Request, file: Annotated[UploadFile, File()]) -> ImageAnalysisResponse:
        return await handle_upload(request, file, page=False)

    @app.post("/api/v1/analyze-page", response_model=PageAnalysisResponse)
    async def analyze_page(request: Request, file: Annotated[UploadFile, File()]) -> PageAnalysisResponse:
        return await handle_upload(request, file, page=True)

    @app.post("/api/v1/render-page", response_class=Response,
              responses={200: {"content": {"image/png": {}, "application/zip": {}}}})
    async def render_page(request: Request, file: Annotated[UploadFile, File()], diagnostics: bool = False,
                          refresh: Refresh = "none",
                          configuration: Annotated[str | None, Query(pattern=r"^[a-f0-9]{64}$", max_length=64)] = None) -> Response:
        return await handle_upload(request, file, page=True, render=True, diagnostics=diagnostics,
                                   refresh=refresh, configuration=configuration)

    async def cache_operation(request: Request, operation: Callable[[ImageAnalysisService], object]):
        state = request.app.state
        if state.service is None:
            raise HTTPException(503, "Analysis resources unavailable.")
        if state.busy:
            raise HTTPException(429, "Processing is active; try cache controls after the current page finishes.")
        state.busy = True
        future = asyncio.get_running_loop().run_in_executor(state.executor, operation, state.service)
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
                            configuration: str | None = None) -> ImageAnalysisResponse | PageAnalysisResponse | Response:
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
        state.busy = True
        def perform_upload():
            if isinstance(state.service, ImageAnalysisService):
                state.configuration_id = state.service.configuration_id()
            return analyze_upload(state.service, data, page, render, diagnostics, refresh, configuration)
        future = asyncio.get_running_loop().run_in_executor(state.executor, perform_upload)

        def finished(task: asyncio.Future) -> None:
            state.busy = False
            # Retrieve failures even if the HTTP client disconnected while inference ran.
            if not task.cancelled():
                error = task.exception()
                if error is not None and not isinstance(error, HTTPException):
                    logger.error("Image analysis failed", exc_info=(type(error), error, error.__traceback__))

        future.add_done_callback(finished)
        try:
            return await asyncio.shield(future)
        except HTTPException:
            raise
        except Exception as exc:
            # HTTP boundary: do not disclose library errors, paths, or tracebacks to clients.
            if page:
                raise HTTPException(500, "Page analysis failed. See server logs for diagnostics.") from exc
            raise HTTPException(500, "Image analysis failed. Try a smaller clear crop; see server logs.") from exc

    return app


app = create_app()
