from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    # Railway (and Heroku-style platforms) inject Postgres connection strings
    # as "postgres://..." or "postgresql://...", which SQLAlchemy's async
    # engine can't use directly — it needs a driver suffix. Normalizing here
    # means the raw platform-provided DATABASE_URL can be pasted as-is.
    @field_validator("database_url")
    @classmethod
    def _use_asyncpg_driver(cls, v: str) -> str:
        if v.startswith("postgres://"):
            return "postgresql+asyncpg://" + v[len("postgres://") :]
        if v.startswith("postgresql://"):
            return "postgresql+asyncpg://" + v[len("postgresql://") :]
        return v

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
