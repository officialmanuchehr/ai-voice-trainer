"""Per-request ID and security headers, as one plain ASGI middleware.

The request ID is generated server-side (never taken from the client), put
in the X-Request-ID response header, exposed to handlers via
`request_id_var` / `request.state.request_id`, and included in server logs,
so a user-reported error can be matched to its log line.
"""

import json
import uuid
from contextvars import ContextVar

from starlette.datastructures import MutableHeaders

from app.limits import MAX_REQUEST_BYTES

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

# Strict for the current static frontend: all scripts and styles are files
# under /static (no inline <script>, style attributes, event handlers or
# javascript: URLs — Phase 4A), client audio as data: URLs, same-origin API
# calls only, no third-party resources. Dynamic sizes are set via CSSOM
# (element.style.x = …), which style-src 'self' allows.
CONTENT_SECURITY_POLICY = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self'",
        "img-src 'self' data:",
        "media-src 'self' data: blob:",
        "connect-src 'self'",
        "font-src 'self'",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    ]
)

SECURITY_HEADERS = {
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
    # Microphone stays available to this origin (voice training); the rest is off.
    "Permissions-Policy": "microphone=(self), camera=(), geolocation=(), payment=(), usb=(), interest-cohort=()",
}

# Dev-only API docs load Swagger/ReDoc assets from a CDN; they're disabled in
# production, so the CSP is relaxed only on these paths.
_NO_CSP_PATHS = {"/docs", "/redoc"}


def security_headers(path: str) -> dict[str, str]:
    if path in _NO_CSP_PATHS:
        return {k: v for k, v in SECURITY_HEADERS.items() if k != "Content-Security-Policy"}
    return SECURITY_HEADERS


class RequestContextMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        request_id = uuid.uuid4().hex
        # Left set (not reset) so the unhandled-error handler, which runs
        # outside this middleware, still sees it.
        request_id_var.set(request_id)
        scope.setdefault("state", {})["request_id"] = request_id
        headers_to_add = {**security_headers(scope["path"]), "X-Request-ID": request_id}

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in headers_to_add.items():
                    headers[name] = value
            await send(message)

        # A2-2: refuse oversized bodies up front (declared length); a body
        # without Content-Length is still bounded per field by app/limits.py.
        declared = dict(scope.get("headers") or []).get(b"content-length")
        if declared and declared.isdigit() and int(declared) > MAX_REQUEST_BYTES:
            body = json.dumps({"code": "too_large", "detail": "Запрос слишком большой.", "request_id": request_id}, ensure_ascii=False).encode()
            await send_with_headers({"type": "http.response.start", "status": 413, "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
            await send({"type": "http.response.body", "body": body})
            return

        await self.app(scope, receive, send_with_headers)
