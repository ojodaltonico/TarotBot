import sqlite3
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config

from app.core.config import ROOT_DIR


def migration_config(database_path: Path) -> Config:
    config = Config(str(ROOT_DIR / "backend" / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT_DIR / "backend" / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path.as_posix()}")
    return config


def tables_in(database_path: Path) -> set[str]:
    with sqlite3.connect(database_path) as connection:
        return {row[0] for row in connection.execute("select name from sqlite_master where type='table'")}


def test_empty_database_migrates_to_head():
    database_path = Path(__file__).parent / f"migration_empty_{uuid4().hex}.db"
    command.upgrade(migration_config(database_path), "head")
    assert {"users", "conversations", "messages", "tarot_readings", "tarot_reading_cards", "tarot_interpretations"}.issubset(tables_in(database_path))


def test_database_at_revision_04_upgrades_to_head():
    database_path = Path(__file__).parent / f"migration_upgrade_{uuid4().hex}.db"
    config = migration_config(database_path)
    command.upgrade(config, "20260807_04")
    assert "tarot_readings" in tables_in(database_path)
    assert "tarot_interpretations" in tables_in(database_path)
    command.upgrade(config, "head")
    assert {"last_intent", "reading_recommended", "suggested_spread"}.issubset({row[1] for row in sqlite3.connect(database_path).execute("pragma table_info(conversations)")})
