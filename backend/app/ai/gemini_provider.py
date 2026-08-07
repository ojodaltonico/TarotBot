"""Gemini adapter using the SDK's native structured-output support."""

import time

from pydantic import ValidationError

from app.ai.provider import AIMessage, AIProvider, AIProviderError, AIResponse


class GeminiProvider(AIProvider):
    def __init__(self, *, api_key: str, model: str, timeout_seconds: int = 30, enabled: bool = True):
        if not enabled:
            raise ValueError("AI is disabled")
        if not api_key:
            raise ValueError("GEMINI_API_KEY is not configured")
        if not model or not model.strip():
            raise ValueError("AI_CHAT_MODEL is not configured")
        self.model = model
        self.timeout_seconds = timeout_seconds
        from google import genai

        self.client = genai.Client(api_key=api_key)

    def generate(self, messages: list[AIMessage], *, purpose: str, options: dict | None = None) -> AIResponse:
        started = time.perf_counter()
        options = dict(options or {})
        schema = options.pop("response_schema", None)
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
        except TimeoutError:
            raise AIProviderError("timeout", self._failure_metadata(started)) from None
        except Exception:
            raise AIProviderError("provider_error", self._failure_metadata(started)) from None

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

    def _failure_metadata(self, started: float) -> AIResponse:
        return AIResponse(
            text=None,
            model=self.model,
            provider="gemini",
            latency_ms=max(0, round((time.perf_counter() - started) * 1000)),
        )
