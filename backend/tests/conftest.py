from pathlib import Path
from uuid import uuid4
from shutil import copyfile

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app, run_migrations


RUNTIME_DIR = Path(__file__).parent / ".runtime"

@pytest.fixture(scope="session")
def migrated_database():
    RUNTIME_DIR.mkdir(exist_ok=True)
    database_path = RUNTIME_DIR / "template.db"
    run_migrations(f"sqlite:///{database_path.as_posix()}")
    return database_path

@pytest.fixture
def client(migrated_database):
    database_path = RUNTIME_DIR / f"test_{uuid4().hex}.db"
    copyfile(migrated_database, database_path)
    settings = Settings(database_url=f"sqlite:///{database_path.as_posix()}", run_migrations_on_startup=False)
    application = create_app(settings)
    with TestClient(application) as test_client:
        yield test_client
