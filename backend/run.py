import uvicorn

from app.core.config import get_settings


if __name__ == "__main__":
    settings = get_settings()
    uvicorn.run("app.main:app", host=settings.backend_host, port=settings.backend_port)
