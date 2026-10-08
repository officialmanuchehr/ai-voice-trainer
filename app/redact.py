"""Deterministic secret redaction for diagnostics that are stored or logged
(e.g. a provider's exception message). Not a DLP system: it removes the
configured secret values themselves plus common credential shapes."""

import logging
import re
from urllib.parse import urlsplit

from app.config import settings

REDACTED = "[REDACTED]"
_MAX_LENGTH = 2000

_PATTERNS = [
    # "Authorization: Bearer xyz", "Token xyz", "Basic xyz"
    (re.compile(r"(?i)\b(bearer|token|basic)\s+[A-Za-z0-9._~+/=-]{6,}"), r"\1 " + REDACTED),
    # header/field style: authorization=…, x-api-key: …, api_key='…', cookie: …
    (re.compile(r"(?i)\b(authorization|proxy-authorization|x-api-key|xi-api-key|api[_-]?key|cookie|set-cookie|password|secret)(['\"]?\s*[:=]\s*['\"]?)[^\s,;'\"}]+"), r"\1\2" + REDACTED),
    # provider key shapes (Anthropic/DeepSeek/OpenAI-style, ElevenLabs, Neon)
    (re.compile(r"\bsk-[A-Za-z0-9_-]{8,}"), REDACTED),
    (re.compile(r"\bsk_[A-Za-z0-9]{16,}"), REDACTED),
    (re.compile(r"\bnpg_[A-Za-z0-9]{6,}"), REDACTED),
    # credentials inside connection URLs
    (re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://[^:/\s@]+:)[^@\s]+@"), r"\1" + REDACTED + "@"),
    # this app's session cookie
    (re.compile(r"avt_session=[^;\s]+"), "avt_session=" + REDACTED),
]


def _configured_secrets() -> list[str]:
    values = [
        settings.anthropic_api_key,
        settings.deepseek_api_key,
        settings.deepgram_api_key,
        settings.elevenlabs_api_key,
        settings.secret_key,
        settings.basic_auth_password,
        settings.initial_admin_password,
        urlsplit(settings.database_url).password or "",
    ]
    return sorted({v for v in values if v and len(v) >= 6}, key=len, reverse=True)


def redact(text: str | None, max_length: int | None = _MAX_LENGTH) -> str:
    """Secrets removed; truncated to max_length (None = keep everything, as
    for log tracebacks whose most useful line is the last one)."""
    if not text:
        return text or ""
    for secret in _configured_secrets():
        text = text.replace(secret, REDACTED)
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text if max_length is None else text[:max_length]


class RedactingFilter(logging.Filter):
    """Redacts the message and traceback of records on the "app" logger."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.getMessage(), max_length=None)
        record.args = None
        if record.exc_info:
            record.exc_text = redact(logging.Formatter().formatException(record.exc_info), max_length=None)
            record.exc_info = None
        return True
