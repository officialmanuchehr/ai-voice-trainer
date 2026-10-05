"""Per-request ID and security headers, as one plain ASGI middleware.

The request ID is generated server-side (never taken from the client), put
in the X-Request-ID response header, exposed to handlers via
`request_id_var` / `request.state.request_id`, and included in server logs,
so a user-reported error can be matched to its log line.
"""

import uuid
from contextvars import ContextVar

from starlette.datastructures import MutableHeaders

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

# Compatible with the current static frontend: one inline <script> per page and
# inline style attributes (hence 'unsafe-inline'), client audio as data: URLs,
# same-origin API calls only, no third-party resources.
CONTENT_SECURITY_POLICY = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self' 'unsafe-inline'",
        "style-src 'self' 'unsafe-inline'",
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

        await self.app(scope, receive, send_with_headers)
