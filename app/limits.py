"""Technical input ceilings (A2-2): abuse and stability protection, not bank
policy. Each is far above normal pilot use — a spoken or typed reply, a seed
KB (~6 KB), a scenario (~3 KB) — and bounds prompt size, provider cost and
storage. Checked on the server; the frontend only mirrors some as maxlength.
"""

import json

from fastapi import HTTPException

MAX_REQUEST_BYTES = 6 * 1024 * 1024    # whole request body (Vercel itself stops at ~4.5 MB)
MAX_AUDIO_BYTES = 4 * 1024 * 1024      # one push-to-talk recording (~1 min of Opus is <1 MB)
MAX_TURN_CHARS = 2000                  # one manager reply, typed or recognised
MAX_MANAGER_TURNS = 60                 # per session; bounds the dialog prompt that grows each turn
MAX_DISPUTE_CHARS = 2000
MAX_USERNAME_CHARS = 100
MAX_PASSWORD_CHARS = 256
MAX_NAME_CHARS = 200                   # full name, team name
MAX_NOTES_CHARS = 2000                 # KB version comment
MAX_VERSION_CHARS = 40                 # KB version label
MAX_SCENARIO_BYTES = 100_000           # serialized scenario document
MAX_KB_BYTES = 300_000                 # serialized KB document (sent into AI prompts)


def too_long(detail: str) -> HTTPException:
    return HTTPException(status_code=422, detail=detail)


def check_chars(value: str | None, limit: int, label: str) -> None:
    if value is not None and len(value) > limit:
        raise too_long(f"{label}: не больше {limit} символов")


def check_document(data, limit: int, label: str) -> None:
    size = len(json.dumps(data, ensure_ascii=False).encode("utf-8"))
    if size > limit:
        raise too_long(f"{label}: документ слишком большой ({size // 1024} КБ, максимум {limit // 1024} КБ)")
