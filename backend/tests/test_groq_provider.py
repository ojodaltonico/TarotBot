import json
import sys
from types import SimpleNamespace

import pytest

from app.ai.groq_provider import GroqProvider
from app.ai.provider import AIMessage, AIProviderError
from app.conversation.schemas import ConversationDecision
from app.services.tarot_interpretation import InterpretationOutput


MODEL = "openai/gpt-oss-120b"


def decision(**values):
    payload = {
        "reply": "Contame un poco más.",
        "intent": "general_chat",
        "next_state": "CHATTING",
        "reading_recommended": False,
        "suggested_spread": None,
        "memory_candidates": [],
        "action": "none",
    }
    payload.update(values)
    return json.dumps(payload)


def completion(content, *, usage=None, request_id="req_123"):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=usage,
        model=MODEL,
        _request_id=request_id,
    )


def install_sdk(monkeypatch, outcome):
    captured = {}

    class FakeCompletions:
        def create(self, **kwargs):
            captured["request"] = kwargs
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

    class FakeGroq:
        def __init__(self, **kwargs):
            captured["client"] = kwargs
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setitem(sys.modules, "groq", SimpleNamespace(Groq=FakeGroq))
    return captured


def provider(monkeypatch, outcome):
    captured = install_sdk(monkeypatch, outcome)
    return GroqProvider(api_key="test-key", model=MODEL, timeout_seconds=17), captured


def test_structured_conversation_decision_uses_json_schema_and_maps_usage(monkeypatch):
    usage = SimpleNamespace(prompt_tokens=21, completion_tokens=8, prompt_tokens_details=SimpleNamespace(cached_tokens=3))
    service, captured = provider(monkeypatch, completion(decision(), usage=usage))

    result = service.generate([AIMessage("user", "Hola")], purpose="conversation", options={"response_schema": ConversationDecision})

    request = captured["request"]
    assert captured["client"]["max_retries"] == 0
    assert captured["client"]["timeout"] == 17
    assert request["model"] == MODEL
    assert request["messages"] == [{"role": "user", "content": "Hola"}]
    assert request["response_format"]["type"] == "json_schema"
    assert request["response_format"]["json_schema"]["schema"] == ConversationDecision.model_json_schema()
    assert request["response_format"]["json_schema"]["strict"] is False
    assert ConversationDecision.model_validate_json(result.text).reply == "Contame un poco más."
    assert (result.provider, result.model, result.input_tokens, result.output_tokens, result.cached_tokens, result.request_id) == ("groq", MODEL, 21, 8, 3, "req_123")
    assert result.latency_ms >= 0


def test_structured_interpretation_schema_is_validated(monkeypatch):
    body = json.dumps({"interpretation": "La lectura habla de un vínculo en pausa.", "summary": "Vínculo en pausa."})
    service, _ = provider(monkeypatch, completion(body))

    result = service.generate([AIMessage("user", "Interpretá")], purpose="tarot_interpretation", options={"response_schema": InterpretationOutput})

    assert InterpretationOutput.model_validate_json(result.text).summary == "Vínculo en pausa."


def test_text_response_without_schema(monkeypatch):
    service, captured = provider(monkeypatch, completion("Resumen breve."))
    result = service.generate([AIMessage("user", "Resumí")], purpose="memory")
    assert result.text == "Resumen breve."
    assert "response_format" not in captured["request"]


@pytest.mark.parametrize(
    ("usage", "expected"),
    [
        (SimpleNamespace(prompt_tokens=5, completion_tokens=2, prompt_tokens_details=SimpleNamespace(cached_tokens=1)), (5, 2, 1)),
        (SimpleNamespace(prompt_tokens=5, completion_tokens=2, prompt_tokens_details=None), (5, 2, None)),
        (None, (0, 0, None)),
    ],
)
def test_usage_mapping_never_invents_tokens(monkeypatch, usage, expected):
    service, _ = provider(monkeypatch, completion("OK", usage=usage))
    result = service.generate([AIMessage("user", "Hola")], purpose="memory")
    assert (result.input_tokens, result.output_tokens, result.cached_tokens) == expected


@pytest.mark.parametrize("body, category", [(None, "empty_response"), ("   ", "empty_response"), ("{not json", "validation_error")])
def test_empty_or_invalid_structured_response_is_controlled(monkeypatch, body, category):
    service, _ = provider(monkeypatch, completion(body))
    with pytest.raises(AIProviderError) as raised:
        service.generate([AIMessage("user", "Hola")], purpose="conversation", options={"response_schema": ConversationDecision})
    assert raised.value.category == category
    assert raised.value.response.provider == "groq"


class SDKError(Exception):
    def __init__(self, message="sdk failure", *, status_code=None, headers=None):
        super().__init__(message)
        self.status_code = status_code
        self.response = SimpleNamespace(status_code=status_code, headers=headers or {}) if status_code else None


@pytest.mark.parametrize(
    ("name", "status", "headers", "expected"),
    [
        ("APITimeoutError", None, {}, "timeout"),
        ("APIConnectionError", None, {}, "connection_error"),
        ("RateLimitError", 429, {"retry-after": "10", "x-request-id": "req_limit"}, "rate_limit"),
        ("InternalServerError", 503, {}, "provider_unavailable"),
        ("BadRequestError", 400, {}, "provider_http_error"),
        ("UnexpectedSDKError", None, {}, "provider_error"),
    ],
)
def test_sdk_errors_use_common_taxonomy(monkeypatch, name, status, headers, expected):
    error_type = type(name, (SDKError,), {})
    service, _ = provider(monkeypatch, error_type("Failure gsk_sensitive", status_code=status, headers=headers))
    with pytest.raises(AIProviderError) as raised:
        service.generate([AIMessage("user", "Hola")], purpose="conversation")
    assert raised.value.category == expected
    assert raised.value.response.provider == "groq"
    assert "gsk_sensitive" not in raised.value.diagnostics["sanitized_message"]
    if expected == "rate_limit":
        assert raised.value.diagnostics["retry_after"] == "10"
        assert raised.value.diagnostics["request_id"] == "req_limit"


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"api_key": "", "model": MODEL}, "GROQ_API_KEY"),
        ({"api_key": "test-key", "model": ""}, "AI_CHAT_MODEL"),
        ({"api_key": "test-key", "model": MODEL, "enabled": False}, "disabled"),
    ],
)
def test_configuration_errors_are_clear(monkeypatch, kwargs, message):
    install_sdk(monkeypatch, completion("unused"))
    with pytest.raises(ValueError, match=message):
        GroqProvider(**kwargs)
