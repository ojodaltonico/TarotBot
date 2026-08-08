"""Manual, sanitized Gemini connectivity diagnostic; never run in tests."""
import os
import re
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
VENV_PYTHON = ROOT_DIR / "backend" / ".venv" / "Scripts" / "python.exe"
if sys.prefix == sys.base_prefix and VENV_PYTHON.exists():
    os.execv(str(VENV_PYTHON), [str(VENV_PYTHON), str(Path(__file__).resolve())])

sys.path.insert(0, str(ROOT_DIR / "backend"))

from app.core.config import get_settings


def sanitize_message(value: object) -> str:
    text = str(value)
    text = re.sub(r"([?&](?:key|api_key)=)[^&\s]+", r"\1[REDACTED]", text, flags=re.I)
    text = re.sub(r"(authorization\s*[:=]\s*)\S+", r"\1[REDACTED]", text, flags=re.I)
    text = re.sub(r"AIza[\w-]+|AQ\.[\w.-]+", "[REDACTED]", text)
    return text[:1200]


def value_from(error: Exception, *names: str):
    for name in names:
        value = getattr(error, name, None)
        if value is not None:
            return value
    return None


settings = get_settings()
if settings.ai_provider != "gemini":
    raise SystemExit("AI_PROVIDER must be gemini for this check.")
if not settings.gemini_api_key:
    raise SystemExit("GEMINI_API_KEY is not configured locally.")

try:
    from google import genai

    client = genai.Client(api_key=settings.gemini_api_key)
    response = client.models.generate_content(
        model=settings.ai_chat_model,
        contents="Reply exactly: connection correct",
        config={"http_options": {"timeout": settings.ai_timeout_seconds * 1000}},
    )
except Exception as error:
    response = getattr(error, "response", None)
    status = value_from(error, "status_code", "code") or value_from(response, "status_code", "status")
    request_id = value_from(error, "request_id") or value_from(response, "request_id", "response_id")
    message = sanitize_message(value_from(error, "message") or error)
    google_status = re.search(r"\b(INVALID_ARGUMENT|UNAUTHENTICATED|PERMISSION_DENIED|NOT_FOUND|RESOURCE_EXHAUSTED)\b", message)
    print(f"Provider: gemini\nModel: {settings.ai_chat_model}\nCategory: provider_error\nHTTP status: {status or '-'}\nGoogle status: {google_status.group(1) if google_status else '-'}\nSDK exception: {type(error).__name__}\nRequest ID: {request_id or '-'}\nGoogle message: {message}")
    raise SystemExit(1)

print(f"Provider: gemini\nModel: {settings.ai_chat_model}\nResult: connection accepted\nRequest ID: {getattr(response, 'response_id', None) or '-'}")
