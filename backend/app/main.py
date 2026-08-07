import logging
from contextlib import asynccontextmanager

from alembic import command
from alembic.config import Config
from fastapi import FastAPI

from app.api.routes import router
from app.core.config import ROOT_DIR, Settings, get_settings
from app.db.database import create_session_factory, create_sqlite_engine


def run_migrations(database_url: str) -> None:
    config = Config(str(ROOT_DIR / "backend" / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT_DIR / "backend" / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    database_url = settings.resolved_database_url()
    engine = create_sqlite_engine(database_url)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        run_migrations(database_url)
        yield
        engine.dispose()

    logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
    app = FastAPI(title="TarotBot Backend", version="0.1.0", lifespan=lifespan)
    app.state.engine = engine
    app.state.SessionLocal = create_session_factory(engine)
    app.include_router(router)
    return app


app = create_app()
