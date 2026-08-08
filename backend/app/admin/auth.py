import secrets

from fastapi import HTTPException, Request, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials



security = HTTPBasic(auto_error=False)


def require_admin(request: Request, credentials: HTTPBasicCredentials | None) -> None:
    settings = request.app.state.settings
    if not settings.admin_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    valid = bool(settings.admin_username and settings.admin_password)
    valid = valid and secrets.compare_digest(credentials.username if credentials else "", settings.admin_username)
    valid = valid and secrets.compare_digest(credentials.password if credentials else "", settings.admin_password)
    if not valid:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required", headers={"WWW-Authenticate": "Basic"})
