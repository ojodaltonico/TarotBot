"""Groq adapter using the official SDK and JSON Schema structured outputs."""

from __future__ import annotations

import re
import time
from urllib.parse import urlsplit

from pydantic import BaseModel, ValidationError

from app.ai.provider import AIMessage, AIProvider, AIProviderError, AIResponse


class GroqProvider(AIProvider):
    def __init__(self, *, api_key: str, model: str, timeout_seconds: int = 30, enabled: bool = True):
        if not enabled:
            raise ValueError("AI is disabled")
        if not api_key:
            raise ValueError("GROQ_API_KEY is not configured")
        if not model or not model.strip():
            raise ValueError("AI_CHAT_MODEL is not configured")
        self.model = model
        self.timeout_seconds = timeout_seconds
        from groq import Groq

        # The official SDK retries connection, 429 and 5xx failures by default.
        # TarotBot deliberately disables that behavior so every attempt is audited once.
        self.client = Groq(api_key=api_key, timeout=timeout_seconds, max_retries=0)

    def generate(self, messages: list[AIMessage], *, purpose: str, options: dict | None = None) -> AIResponse:
        started = time.perf_counter()
        options = dict(options or {})
        schema = options.pop("response_schema", None)
        options.pop("conversation_state", None)
        request = {"model": self.model, "messages": [{"role": message.role, "content": message.content} for message in messages]}
        if schema is not None:
            request["response_format"] = self._response_format(schema)
        try:
            completion = self.client.chat.completions.create(**request)
            metadata = self._response_metadata(completion, started)
            audit_response = AIResponse(text=None, **metadata)
            content = self._content(completion)
            if not content or not content.strip():
                raise AIProviderError("empty_response", audit_response)
            if schema is None:
                return AIResponse(text=content, **metadata)
            try:
                validated = schema.model_validate_json(content)
            except (ValidationError, TypeError, ValueError):
                raise AIProviderError("validation_error", audit_response) from None
            return AIResponse(text=validated.model_dump_json(), **metadata)
        except AIProviderError:
            raise
        except Exception as error:
            diagnostics = self._diagnostics(error)
            raise AIProviderError(diagnostics["error_category"], self._failure_metadata(started, diagnostics), diagnostics) from None

    @staticmethod
    def _response_format(schema: type[BaseModel]) -> dict:
        return {
            "type": "json_schema",
            "json_schema": {"name": schema.__name__.lower(), "strict": False, "schema": schema.model_json_schema()},
        }

    @staticmethod
    def _content(completion) -> str | None:
        choices = getattr(completion, "choices", None) or []
        message = getattr(choices[0], "message", None) if choices else None
        return getattr(message, "content", None)

    def _response_metadata(self, completion, started: float) -> dict:
        usage = getattr(completion, "usage", None)
        prompt_details = getattr(usage, "prompt_tokens_details", None)
        return {
            "model": getattr(completion, "model", None) or self.model,
            "provider": "groq",
            "input_tokens": getattr(usage, "prompt_tokens", 0) or 0,
            "output_tokens": getattr(usage, "completion_tokens", 0) or 0,
            "cached_tokens": getattr(prompt_details, "cached_tokens", None),
            "latency_ms": max(0, round((time.perf_counter() - started) * 1000)),
            "request_id": getattr(completion, "_request_id", None) or getattr(completion, "id", None),
        }

    def _failure_metadata(self, started: float, diagnostics: dict) -> AIResponse:
        return AIResponse(None, self.model, latency_ms=max(0, round((time.perf_counter() - started) * 1000)), provider="groq", request_id=diagnostics.get("request_id"))

    @staticmethod
    def _sanitize_message(value: object) -> str:
        text = str(value or "")
        text = re.sub(r"([?&](?:key|api_key)=)[^&\s]+", r"\1[REDACTED]", text, flags=re.I)
        text = re.sub(r"(authorization\s*[:=]\s*)\S+", r"\1[REDACTED]", text, flags=re.I)
        text = re.sub(r"gsk_[\w-]+|AIza[\w-]+|AQ\.[\w.-]+", "[REDACTED]", text)
        return text[:800]

    @staticmethod
    def _exception_chain(error: Exception) -> list[BaseException]:
        chain, current = [], error
        while current is not None and current not in chain:
            chain.append(current)
            current = current.__cause__ or current.__context__
        return chain

    def _diagnostics(self, error: Exception) -> dict:
        chain = self._exception_chain(error)
        names = [type(item).__name__ for item in chain]
        lower_names = " ".join(name.lower() for name in names)
        response = getattr(error, "response", None)
        status = getattr(error, "status_code", None) or getattr(response, "status_code", None)
        status = status if isinstance(status, int) else None
        headers = getattr(response, "headers", {}) or {}
        header = lambda *keys: next((headers.get(key) for key in keys if headers.get(key)), None)
        request = getattr(error, "request", None) or getattr(response, "request", None)
        url = getattr(request, "url", None)
        try:
            host = urlsplit(str(url)).hostname if url else None
        except ValueError:
            host = None
        message = self._sanitize_message(getattr(error, "message", None) or error)
        if "timeout" in lower_names:
            category = "timeout"
        elif status == 429 or "ratelimit" in lower_names:
            category = "rate_limit"
        elif status is not None and status >= 500:
            category = "provider_unavailable"
        elif status is not None and status >= 400:
            category = "provider_http_error"
        elif any(token in lower_names for token in ("connection", "connecterror", "gaierror", "sslerror", "certificateerror")):
            category = "connection_error"
        else:
            category = "provider_error"
        return {
            "error_category": category,
            "exception_type": names[0],
            "cause_type": names[1] if len(names) > 1 else None,
            "http_status": status,
            "provider_status": getattr(error, "code", None) if isinstance(getattr(error, "code", None), str) else None,
            "request_id": getattr(error, "request_id", None) or header("x-request-id"),
            "retry_after": header("retry-after"),
            "sanitized_message": message,
            "host": host,
        }
