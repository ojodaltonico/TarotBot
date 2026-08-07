import json
import sys
from types import ModuleType, SimpleNamespace

import pytest

from app.ai.gemini_provider import GeminiProvider
from app.ai.provider import AIMessage, AIProviderError
from app.conversation.schemas import ConversationDecision


class MockClient:
    def __init__(self, api_key, outcome):
        self.api_key = api_key
        self.outcome = outcome
        self.calls = []
        self.models = self

    def generate_content(self, *, model, contents, config):
        self.calls.append({"model": model, "contents": contents, "config": config})
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def install_mock_sdk(monkeypatch, outcome):
    captured = {}

    def client_factory(*, api_key):
        client = MockClient(api_key, outcome)
        captured["client"] = client
        return client

    google = ModuleType("google")
    google.genai = SimpleNamespace(Client=client_factory)
    monkeypatch.setitem(sys.modules, "google", google)
    return captured


def valid_decision():
    return {
        "reply": "Veamos eso con calma.",
        "intent": "ask_tarot",
        "next_state": "CHATTING",
        "reading_recommended": False,
        "suggested_spread": None,
        "memory_candidates": [],
    }


def response(*, text="sdk text", parsed=None, usage=None, response_id="request-1"):
    return SimpleNamespace(text=text, parsed=parsed, usage_metadata=usage, response_id=response_id)


def test_native_structured_output_validates_parsed_result_and_maps_metadata(monkeypatch):
    usage = SimpleNamespace(prompt_token_count=21, candidates_token_count=8, cached_content_token_count=5)
    captured = install_mock_sdk(monkeypatch, response(parsed=valid_decision(), usage=usage))
    provider = GeminiProvider(api_key="test-key", model="gemini-2.5-flash", timeout_seconds=7)

    result = provider.generate(
        [AIMessage("system", "Contexto"), AIMessage("user", "Hola")],
        purpose="conversation",
        options={"response_schema": ConversationDecision},
    )

    call = captured["client"].calls[0]
    assert captured["client"].api_key == "test-key"
    assert call["model"] == "gemini-2.5-flash"
    assert call["contents"] == "system: Contexto\nuser: Hola"
    assert call["config"]["response_mime_type"] == "application/json"
    assert call["config"]["response_schema"] is ConversationDecision
    assert call["config"]["http_options"] == {"timeout": 7000}
    assert ConversationDecision.model_validate_json(result.text).reply == "Veamos eso con calma."
    assert (result.provider, result.model) == ("gemini", "gemini-2.5-flash")
    assert (result.input_tokens, result.output_tokens, result.cached_tokens) == (21, 8, 5)
    assert result.latency_ms >= 0
    assert result.request_id == "request-1"


@pytest.mark.parametrize(
    ("usage", "expected"),
    [
        (SimpleNamespace(prompt_token_count=9, candidates_token_count=4, cached_content_token_count=2), (9, 4, 2)),
        (SimpleNamespace(prompt_token_count=9, candidates_token_count=4), (9, 4, None)),
        (SimpleNamespace(prompt_token_count=9), (9, 0, None)),
        (None, (0, 0, None)),
    ],
)
def test_usage_metadata_never_invents_consumption(monkeypatch, usage, expected):
    install_mock_sdk(monkeypatch, response(parsed=valid_decision(), usage=usage))
    provider = GeminiProvider(api_key="test-key", model="test-model")

    result = provider.generate([], purpose="conversation", options={"response_schema": ConversationDecision})

    assert (result.input_tokens, result.output_tokens, result.cached_tokens) == expected


@pytest.mark.parametrize(
    ("outcome", "options"),
    [
        (response(text="", parsed=None), {"response_schema": ConversationDecision}),
        (response(text="", parsed=valid_decision()), None),
        (response(text="ignored", parsed=None), {"response_schema": ConversationDecision}),
    ],
)
def test_empty_gemini_results_raise_stable_empty_response(monkeypatch, outcome, options):
    install_mock_sdk(monkeypatch, outcome)
    provider = GeminiProvider(api_key="test-key", model="test-model")

    with pytest.raises(AIProviderError) as caught:
        provider.generate([], purpose="conversation", options=options)

    assert caught.value.category == "empty_response"
    assert caught.value.response.provider == "gemini"
    assert caught.value.response.model == "test-model"


def test_invalid_structured_result_is_rejected_by_pydantic(monkeypatch):
    install_mock_sdk(monkeypatch, response(parsed={}))
    provider = GeminiProvider(api_key="test-key", model="test-model")

    with pytest.raises(AIProviderError) as caught:
        provider.generate([], purpose="conversation", options={"response_schema": ConversationDecision})

    assert caught.value.category == "validation_error"


@pytest.mark.parametrize(
    ("outcome", "expected_category"),
    [(TimeoutError(), "timeout"), (RuntimeError(), "provider_error")],
)
def test_sdk_failures_are_wrapped_without_sdk_details(monkeypatch, outcome, expected_category):
    install_mock_sdk(monkeypatch, outcome)
    provider = GeminiProvider(api_key="test-key", model="test-model")

    with pytest.raises(AIProviderError) as caught:
        provider.generate([], purpose="conversation")

    assert caught.value.category == expected_category
    assert caught.value.response.provider == "gemini"
    assert caught.value.response.model == "test-model"


def test_text_output_is_supported_without_response_schema(monkeypatch):
    captured = install_mock_sdk(monkeypatch, response(text="Respuesta normal"))
    provider = GeminiProvider(api_key="test-key", model="test-model", timeout_seconds=3)

    result = provider.generate([AIMessage("user", "Hola")], purpose="conversation", options={"temperature": 0.2})

    config = captured["client"].calls[0]["config"]
    assert result.text == "Respuesta normal"
    assert config["temperature"] == 0.2
    assert config["http_options"] == {"timeout": 3000}
    assert "response_schema" not in config
    assert "response_mime_type" not in config


@pytest.mark.parametrize(
    "kwargs",
    [
        {"api_key": "", "model": "test-model"},
        {"api_key": "test-key", "model": ""},
        {"api_key": "test-key", "model": "test-model", "enabled": False},
    ],
)
def test_invalid_or_disabled_configuration_fails_before_sdk_initialization(monkeypatch, kwargs):
    install_mock_sdk(monkeypatch, response())

    with pytest.raises(ValueError):
        GeminiProvider(**kwargs)
