"""Gemini adapter using the SDK's native structured-output support."""

import re
import time
from urllib.parse import urlsplit

from pydantic import ValidationError

from app.ai.provider import AIMessage, AIProvider, AIProviderError, AIResponse


class GeminiProvider(AIProvider):
    def __init__(self, *, api_key: str, model: str, timeout_seconds: int = 30, enabled: bool = True, trust_env_proxy: bool = False):
        if not enabled:
            raise ValueError("AI is disabled")
        if not api_key:
            raise ValueError("GEMINI_API_KEY is not configured")
        if not model or not model.strip():
            raise ValueError("AI_CHAT_MODEL is not configured")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.trust_env_proxy = trust_env_proxy
        from google import genai

        # google-genai 2.17.0 exposes HttpOptions.client_args, forwarded to its
        # httpx client. This scopes proxy policy to this SDK client only.
        self.client = genai.Client(api_key=api_key, http_options={"client_args": {"trust_env": trust_env_proxy}})

    def generate(self, messages: list[AIMessage], *, purpose: str, options: dict | None = None) -> AIResponse:
        started = time.perf_counter()
        options = dict(options or {})
        schema = options.pop("response_schema", None)
        options.pop("conversation_state", None)
        config = {**options, "http_options": {"timeout": self.timeout_seconds * 1000}}
        if schema is not None:
            config.update(response_mime_type="application/json", response_schema=schema)
        prompt = "\n".join(f"{message.role}: {message.content}" for message in messages)

        try:
            response = self.client.models.generate_content(model=self.model, contents=prompt, config=config)
            metadata = self._response_metadata(response, started)
            audit_response = AIResponse(text=None, **metadata)
            if schema is None:
                if not getattr(response, "text", None):
                    raise AIProviderError("empty_response", audit_response)
                return AIResponse(text=response.text, **metadata)

            parsed = getattr(response, "parsed", None)
            if parsed is None:
                raise AIProviderError("empty_response", audit_response)
            try:
                validated = schema.model_validate(parsed)
            except (ValidationError, TypeError, ValueError):
                raise AIProviderError("validation_error", audit_response) from None
            return AIResponse(text=validated.model_dump_json(), **metadata)
        except AIProviderError:
            raise
        except AIProviderError:
            raise
        except Exception as error:
            diagnostics = self._diagnostics(error)
            raise AIProviderError(diagnostics["error_category"], self._failure_metadata(started, diagnostics), diagnostics) from None

    def _response_metadata(self, response, started: float) -> dict:
        usage = getattr(response, "usage_metadata", None)
        return {
            "model": self.model,
            "provider": "gemini",
            "input_tokens": getattr(usage, "prompt_token_count", 0) or 0,
            "output_tokens": getattr(usage, "candidates_token_count", 0) or 0,
            "cached_tokens": getattr(usage, "cached_content_token_count", None),
            "latency_ms": max(0, round((time.perf_counter() - started) * 1000)),
            "request_id": getattr(response, "response_id", None),
        }

    def _failure_metadata(self, started: float, diagnostics: dict | None = None) -> AIResponse:
        return AIResponse(
            text=None,
            model=self.model,
            provider="gemini",
            latency_ms=max(0, round((time.perf_counter() - started) * 1000)),
            request_id=(diagnostics or {}).get("request_id"),
        )

    @staticmethod
    def _sanitize_message(value: object) -> str:
        text = str(value or "")
        text = re.sub(r"([?&](?:key|api_key)=)[^&\s]+", r"\1[REDACTED]", text, flags=re.I)
        text = re.sub(r"(authorization\s*[:=]\s*)\S+", r"\1[REDACTED]", text, flags=re.I)
        text = re.sub(r"AIza[\w-]+|AQ\.[\w.-]+", "[REDACTED]", text)
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
        if not isinstance(status, int):
            status = None
        headers = getattr(response, "headers", {}) or {}
        header = lambda *keys: next((headers.get(key) for key in keys if headers.get(key)), None)
        request = getattr(error, "request", None) or getattr(response, "request", None)
        url = getattr(request, "url", None)
        host = None
        if url:
            try:
                host = urlsplit(str(url)).hostname
            except ValueError:
                host = None
        provider_status = getattr(error, "status", None)
        message = self._sanitize_message(getattr(error, "message", None) or error)
        status_match = re.search(r"\b(INVALID_ARGUMENT|UNAUTHENTICATED|PERMISSION_DENIED|NOT_FOUND|RESOURCE_EXHAUSTED)\b", message)
        provider_status = provider_status if isinstance(provider_status, str) else (status_match.group(1) if status_match else None)
        retry_after = header("retry-after")
        if retry_after is None:
            retry_match = re.search(r"retry in\s+([\d.]+)s", message, flags=re.I)
            retry_after = retry_match.group(1) if retry_match else None
        subtype = None
        if "timeout" in lower_names:
            category = "timeout"
            subtype = "connect" if "connecttimeout" in lower_names else "read" if "readtimeout" in lower_names else "general"
        elif status == 429:
            category = "rate_limit"
        elif status is not None and status >= 500:
            category = "provider_unavailable"
        elif status is not None and status >= 400:
            category = "provider_http_error"
        elif any(token in lower_names for token in ("connecterror", "connectionrefused", "connectionreset", "gaierror", "sslerror", "certificateerror")):
            category = "connection_error"
            subtype = "refused" if "connectionrefused" in lower_names else "reset" if "connectionreset" in lower_names else "dns" if "gaierror" in lower_names else "tls" if "ssl" in lower_names or "certificate" in lower_names else "connect"
        else:
            category = "provider_error"
        return {
            "error_category": category,
            "exception_type": names[0],
            "cause_type": names[1] if len(names) > 1 else None,
            "http_status": status,
            "provider_status": provider_status,
            "request_id": getattr(error, "request_id", None) or header("x-request-id", "x-goog-request-id"),
            "retry_after": retry_after,
            "sanitized_message": message,
            "host": host,
            "subtype": subtype,
        }
