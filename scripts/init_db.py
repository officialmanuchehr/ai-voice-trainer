"""One-time (re-runnable) database setup for deployments that don't initialise
on startup — i.e. serverless, where AUTO_INIT_DB=false so that dozens of cold
starts don't race on CREATE TABLE / seed inserts.

Creates tables, applies the additive column migrations, loads seed data. Run it
against the production database once after the first deploy, and again whenever
the schema or seed/*.json changes:

    DATABASE_URL='postgresql://USER:PASS@HOST/DB' python scripts/init_db.py
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.main import init_db  # noqa: E402


def main() -> None:
    asyncio.run(init_db())
    print("init_db: tables created, migrations applied, seed loaded.")


if __name__ == "__main__":
    main()
