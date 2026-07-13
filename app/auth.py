import base64
import secrets

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.config import settings

# Paths Railway's own platform healthcheck must be able to reach without
# credentials. Deliberately narrow — everything else (including the API and
# the static HTML page) requires auth.
_UNPROTECTED_PATHS = {"/health"}


class BasicAuthMiddleware(BaseHTTPMiddleware):
    """Gates the entire app behind HTTP Basic Auth.

    This is an internal banking tool and must never be reachable by the open
    internet without credentials. If BASIC_AUTH_USERNAME/PASSWORD are unset
    (local dev default), auth is skipped — but Railway deployments MUST set
    both, or the app is wide open.
    """

    async def dispatch(self, request: Request, call_next):
        if not settings.basic_auth_username or not settings.basic_auth_password:
            return await call_next(request)

        if request.url.path in _UNPROTECTED_PATHS:
            return await call_next(request)

        auth_header = request.headers.get("Authorization")
        if auth_header and self._is_valid(auth_header):
            return await call_next(request)

        return Response(
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="AI Voice Trainer"'},
        )

    @staticmethod
    def _is_valid(auth_header: str) -> bool:
        try:
            scheme, _, credentials = auth_header.partition(" ")
            if scheme.lower() != "basic":
                return False
            decoded = base64.b64decode(credentials).decode("utf-8")
            username, _, password = decoded.partition(":")
        except Exception:
            return False

        return secrets.compare_digest(username, settings.basic_auth_username) and secrets.compare_digest(
            password, settings.basic_auth_password
        )
