# init_db.py  - create/upgrade the database schema with Alembic:  python init_db.py
from pathlib import Path

from alembic import command
from alembic.config import Config

from app.database import check_database

ROOT = Path(__file__).resolve().parent


def init_db() -> None:
    if not check_database():
        raise SystemExit("❌ PostgreSQL is unreachable. Check DATABASE_URL in .env and that the service is running.")
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    print("🗄️  Applying migrations (alembic upgrade head)...")
    command.upgrade(cfg, "head")
    print("✅ Database schema is up to date.")


if __name__ == "__main__":
    init_db()
