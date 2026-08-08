"""One explicit, sanitized Groq connectivity check; never run from tests."""

from __future__ import annotations

import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
VENV_PYTHON = BACKEND / ".venv" / "Scripts" / "python.exe"


def _use_project_venv() -> None:
    if sys.prefix == sys.base_prefix and VENV_PYTHON.exists():
        os.execv(str(VENV_PYTHON), [str(VENV_PYTHON), str(Path(__file__).resolve())])


_use_project_venv()
sys.path.insert(0, str(BACKEND))

from app.ai.groq_provider import GroqProvider  # noqa: E402
from app.ai.provider import AIMessage, AIProviderError  # noqa: E402
from app.core.config import get_settings  # noqa: E402


def _show_failure(error: AIProviderError, model: str) -> None:
    details = error.diagnostics or {}
    print("Provider: groq")
    print(f"Model: {model}")
    print("Success: false")
    print(f"Category: {error.category}")
    for label, key in (("HTTP status", "http_status"), ("Provider status", "provider_status"), ("Request ID", "request_id"), ("Retry after", "retry_after"), ("Error", "sanitized_message")):
        if details.get(key) is not None:
            print(f"{label}: {details[key]}")


def main() -> int:
    settings = get_settings()
    if settings.ai_provider != "groq":
        print("Groq check requires AI_PROVIDER=groq.")
        return 2
    if not settings.groq_api_key:
        print("Groq está seleccionado pero no hay GROQ_API_KEY configurada.")
        return 2
    try:
        provider = GroqProvider(
            api_key=settings.groq_api_key,
            model=settings.ai_chat_model,
            timeout_seconds=settings.ai_timeout_seconds,
            enabled=settings.ai_enabled,
        )
        result = provider.generate([AIMessage(role="user", content="Respondé solamente OK.")], purpose="diagnostic")
    except AIProviderError as error:
        _show_failure(error, settings.ai_chat_model)
        return 1
    except ValueError as error:
        print(f"Groq configuration error: {error}")
        return 2
    print("Provider: groq")
    print(f"Model: {result.model}")
    print("Success: true")
    print(f"Input tokens: {result.input_tokens}")
    print(f"Output tokens: {result.output_tokens}")
    print(f"Cached input tokens: {result.cached_tokens}")
    print(f"Latency ms: {result.latency_ms}")
    if result.request_id:
        print(f"Request ID: {result.request_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
