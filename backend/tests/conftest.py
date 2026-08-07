from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


@pytest.fixture
def client():
    database_path = (Path(__file__).parent / f"test_{uuid4().hex}.db").as_posix()
    settings = Settings(database_url=f"sqlite:///{database_path}")
    application = create_app(settings)
    with TestClient(application) as test_client:
        yield test_client
