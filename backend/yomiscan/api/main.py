"""Run with uvicorn yomiscan.api.main:app --host 127.0.0.1 --port 8765."""

import asyncio
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import AbstractContextManager, asynccontextmanager
import logging
import json
import os
from io import BytesIO
from pathlib import Path
from time import perf_counter
from typing import Annotated, cast

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from yomiscan.service import ImageAnalysisService, open_local_service
from yomiscan.translation.base import Device
from yomiscan.detection import DetectionInitializationError
from .images import decode_image, MAX_FILE_BYTES
from .models import ImageAnalysisResponse, PageAnalysisResponse
from .security import EXTENSION_ORIGIN, LocalRequestGuard

logger = logging.getLogger(__name__)
ServiceFactory = Callable[[], AbstractContextManager[ImageAnalysisService]]


def default_service() -> AbstractContextManager[ImageAnalysisService]:
    device = os.getenv("YOMISCAN_DEVICE", "auto")
    if device not in ("auto", "cpu", "cuda"):
        raise ValueError("YOMISCAN_DEVICE must be auto, cpu, or cuda")
    return open_local_service(
        Path(os.getenv("YOMISCAN_DICTIONARY", "data/jmdict.sqlite3")), device=cast(Device, device),
    )


def analyze_upload(service: ImageAnalysisService, data: bytes, page: bool = False,
                   render: bool = False) -> ImageAnalysisResponse | PageAnalysisResponse | Response:
    start = perf_counter()
    try:
        image = decode_image(data)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    with image:
        if page:
            try:
                if render:
                    result = service.translate_and_render_page(image)
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
        context = None

        def initialize():
            nonlocal context
            context = service_factory()
            return context.__enter__()

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
        expose_headers=["X-YomiScan-Blocks-Rendered", "X-YomiScan-Blocks-Skipped", "X-YomiScan-Processing-Ms", "X-YomiScan-Coverage"],
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "[::1]"])

    @app.get("/health")
    async def health(request: Request) -> dict[str, str]:
        if request.app.state.service is None:
            raise HTTPException(503, "Analysis resources unavailable. Check server logs and restart after setup.")
        return {"status": "ok"}

    @app.post("/api/v1/analyze-image", response_model=ImageAnalysisResponse)
    async def analyze(request: Request, file: Annotated[UploadFile, File()]) -> ImageAnalysisResponse:
        return await handle_upload(request, file, page=False)

    @app.post("/api/v1/analyze-page", response_model=PageAnalysisResponse)
    async def analyze_page(request: Request, file: Annotated[UploadFile, File()]) -> PageAnalysisResponse:
        return await handle_upload(request, file, page=True)

    @app.post("/api/v1/render-page", response_class=Response,
              responses={200: {"content": {"image/png": {}}}})
    async def render_page(request: Request, file: Annotated[UploadFile, File()]) -> Response:
        return await handle_upload(request, file, page=True, render=True)

    async def handle_upload(request: Request, file: UploadFile, *, page: bool,
                            render: bool = False) -> ImageAnalysisResponse | PageAnalysisResponse | Response:
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
        future = asyncio.get_running_loop().run_in_executor(
            state.executor, analyze_upload, state.service, data, page, render,
        )

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
