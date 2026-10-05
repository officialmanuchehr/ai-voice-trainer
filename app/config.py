from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# libpq/psycopg-style query params that platforms (Neon, Supabase, Heroku)
# append to DATABASE_URL but asyncpg's connect() rejects as unknown kwargs.
# SSL is re-established in app/database.py connect_args instead.
_LIBPQ_ONLY_PARAMS = {
    "sslmode",
    "channel_binding",
    "sslrootcert",
    "sslcert",
    "sslkey",
    "gssencmode",
    "options",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "sqlite+aiosqlite:///./data/app.db"

    stt_provider: str = "stub"
    dialog_provider: str = "stub"
    scoring_provider: str = "stub"
    tts_provider: str = "stub"

    deepgram_api_key: str = ""
    deepseek_api_key: str = ""
    deepseek_model: str = "deepseek-chat"
    anthropic_api_key: str = ""
    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = ""

    # Railway / Neon / Supabase / Heroku inject Postgres connection strings as
    # "postgres://..." or "postgresql://...", which SQLAlchemy's async engine
    # can't use directly — it needs the "+asyncpg" driver suffix — and they
    # tack on libpq-only query params (sslmode, channel_binding, ...) that
    # asyncpg.connect() rejects. Normalising both here means the raw
    # platform-provided DATABASE_URL can be pasted in as-is.
    @field_validator("database_url")
    @classmethod
    def _use_asyncpg_driver(cls, v: str) -> str:
        for prefix in ("postgres://", "postgresql://"):
            if v.startswith(prefix):
                v = "postgresql+asyncpg://" + v[len(prefix) :]
                break
        else:
            return v

        parts = urlsplit(v)
        kept = [(k, val) for k, val in parse_qsl(parts.query) if k not in _LIBPQ_ONLY_PARAMS]
        return urlunsplit(parts._replace(query=urlencode(kept)))

    # Internal-tool access gate (HTTP Basic Auth, see app/auth.py). Leave both
    # empty for local dev (auth disabled); MUST be set in Railway.
    basic_auth_username: str = ""
    basic_auth_password: str = ""

    # Run schema-create + seed load on app startup (lifespan). Fine for local
    # dev and single-instance containers. Set false on serverless (Vercel),
    # where many cold starts would race on CREATE TABLE / seed inserts — there
    # you run scripts/init_db.py once instead.
    auto_init_db: bool = True

    # Signs the login cookie (app/security.py). MUST be a long random string
    # outside local SQLite dev — the app refuses to issue cookies without it
    # when running on Postgres.
    secret_key: str = ""
    session_ttl_hours: int = 12

    # Created by init_db if no user with this username exists yet — the way
    # to get the first admin into a fresh database.
    initial_admin_username: str = ""
    initial_admin_password: str = ""

    # Local dev only: creates a demo team and one user per role, all with
    # DEMO_USERS_PASSWORD. Never enable on a real deployment.
    seed_demo_users: bool = False
    demo_users_password: str = "demo12345"

    # Login throttling: after this many failed logins for the same username
    # from the same client IP within the window, further attempts get 429.
    login_max_failures: int = 5
    login_window_minutes: int = 15

    # Request header holding the real client IP, set by a trusted proxy that
    # overwrites any client-supplied value. On Vercel: "x-real-ip" (Vercel
    # overwrites x-forwarded-for/x-real-ip to prevent spoofing). Empty = use
    # the direct TCP peer address; never set this behind a proxy that passes
    # client-supplied headers through.
    client_ip_header: str = ""

    # /docs, /redoc, /openapi.json. Unset = on for local SQLite development,
    # off everywhere else (production); set API_DOCS=true/false to force.
    api_docs: bool | None = None

    @property
    def api_docs_enabled(self) -> bool:
        return self.api_docs if self.api_docs is not None else self.database_url.startswith("sqlite")


settings = Settings()
