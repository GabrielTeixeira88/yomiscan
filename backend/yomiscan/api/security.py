"""Bound request bodies before multipart parsing; guard browser-origin requests.

With a token (the packaged engine, started by its launcher with a per-launch secret), every
request must carry it in X-YomiScan-Token. Unlike the client header, the token is an
authentication secret: other local programs and web pages cannot read it.
"""

import hmac
import re

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from .images import MAX_FILE_BYTES

EXTENSION_ORIGIN = r"chrome-extension://[a-p]{32}"
CLIENT_HEADER = b"x-yomiscan-client"
CLIENT_VALUE = b"study-extension-v1"
TOKEN_HEADER = b"x-yomiscan-token"
MAX_BODY_BYTES = MAX_FILE_BYTES + 64 * 1024
MAX_TEXT_BODY_BYTES = 8 * 1024  # 1,000 characters of edited OCR text as JSON


class LocalRequestGuard:
    def __init__(self, app: ASGIApp, origins: list[str], token: str | None = None) -> None:
        self.app = app
        self.origins = origins
        self.token = token.encode() if token else None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope["headers"])
        origin = headers.get(b"origin", b"").decode("latin-1")
        allowed = origin in self.origins if self.origins else bool(re.fullmatch(EXTENSION_ORIGIN, origin))
        if origin and not allowed:
            await JSONResponse({"detail": "This browser origin is not allowed."}, 403)(scope, receive, send)
            return
        if self.token is not None and scope["method"] != "OPTIONS" and not hmac.compare_digest(
                headers.get(TOKEN_HEADER, b""), self.token):
            await JSONResponse({"detail": "Missing or wrong YomiScan engine token."}, 401)(scope, receive, send)
            return
        private_read = (scope.get("path") in ("/api/v1/translation-profile", "/api/v1/readiness") or
                        scope.get("path", "").startswith("/api/v1/jobs/")) and scope["method"] == "GET"
        if private_read and headers.get(CLIENT_HEADER) != CLIENT_VALUE:
            await JSONResponse({"detail": "Missing YomiScan client header."}, 403)(scope, receive, send)
            return
        if scope["method"] != "POST":
            await self.app(scope, receive, send)
            return
        # Requires preflight from ordinary webpages; not an authentication secret.
        if headers.get(CLIENT_HEADER) != CLIENT_VALUE:
            await JSONResponse({"detail": "Missing YomiScan client header."}, 403)(scope, receive, send)
            return
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            administration = scope.get("path", "").startswith(("/api/v1/cache", "/api/v1/glossaries", "/api/v1/translation-engine"))
            text = scope.get("path") == "/api/v1/analyze-text"
            limit = (1024 if scope.get("path", "").startswith("/api/v1/cache") else 2048 if administration
                     else MAX_TEXT_BODY_BYTES if text else MAX_BODY_BYTES)
            if len(body) > limit:
                detail = ("Local settings body exceeds its limit." if administration else "Edited text exceeds its limit." if text
                          else "Upload exceeds the 10 MiB image limit.")
                await JSONResponse({"detail": detail}, 413)(scope, receive, send)
                return
            if not message.get("more_body", False):
                break
        sent = False

        async def bounded_receive():
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, bounded_receive, send)
