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


settings = Settings()
