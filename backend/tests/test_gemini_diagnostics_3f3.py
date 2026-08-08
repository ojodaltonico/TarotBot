import json
import sys
from types import ModuleType, SimpleNamespace

import httpx
import pytest
from sqlalchemy import select

from app.ai.fake_provider import FakeAIProvider
from app.ai.gemini_provider import GeminiProvider
from app.ai.provider import AIProviderError, AIResponse
from app.models.ai import AICall
from app.models.conversation import Conversation
from app.models.user import User
from app.services.conversation import ConversationService


def install_sdk(monkeypatch, outcome):
    def factory(*, api_key, http_options=None):
        return SimpleNamespace(models=SimpleNamespace(generate_content=lambda **kwargs: (_ for _ in ()).throw(outcome)))

    google = ModuleType("google")
    google.genai = SimpleNamespace(Client=factory)
    monkeypatch.setitem(sys.modules, "google", google)


def provider_error(monkeypatch, outcome):
    install_sdk(monkeypatch, outcome)
    with pytest.raises(AIProviderError) as caught:
        GeminiProvider(api_key="test-key", model="test-model").generate([], purpose="diagnostic")
    return caught.value


def request():
    return httpx.Request("GET", "https://generativelanguage.googleapis.com/v1/models?key=secret-value")


def test_connection_error_is_sanitized_and_stable(monkeypatch):
    error = httpx.ConnectError("connection failed", request=request())
    error.__cause__ = ConnectionRefusedError()
    caught = provider_error(monkeypatch, error)
    assert caught.category == "connection_error"
    assert caught.diagnostics["exception_type"] == "ConnectError"
    assert caught.diagnostics["cause_type"] == "ConnectionRefusedError"
    assert caught.diagnostics["host"] == "generativelanguage.googleapis.com"
    assert "secret-value" not in caught.diagnostics["sanitized_message"]


@pytest.mark.parametrize(("outcome", "category", "status"), [
    (httpx.ReadTimeout("slow", request=request()), "timeout", None),
    (httpx.HTTPStatusError("limited", request=request(), response=httpx.Response(429, headers={"retry-after": "7", "x-request-id": "req-429"}, request=request())), "rate_limit", 429),
    (httpx.HTTPStatusError("unavailable", request=request(), response=httpx.Response(503, request=request())), "provider_unavailable", 503),
    (RuntimeError("unexpected ?key=secret-value"), "provider_error", None),
])
def test_provider_errors_have_stable_categories(monkeypatch, outcome, category, status):
    caught = provider_error(monkeypatch, outcome)
    assert caught.category == category
    assert caught.diagnostics["http_status"] == status
    assert "secret-value" not in caught.diagnostics["sanitized_message"]


def test_retry_after_is_read_from_a_safe_header_or_provider_message(monkeypatch):
    limited = httpx.HTTPStatusError("Please retry in 12.5s", request=request(), response=httpx.Response(429, request=request()))
    assert provider_error(monkeypatch, limited).diagnostics["retry_after"] == "12.5"


def test_debug_audit_persists_sanitized_diagnostics_only(client):
    with client.app.state.SessionLocal() as session:
        user = User(whatsapp_jid="diagnostic@test")
        session.add(user); session.flush()
        conversation = Conversation(user_id=user.id)
        session.add(conversation); session.commit()
        response = AIResponse(None, "test-model", provider="gemini")
        error = AIProviderError("connection_error", response, {"error_category": "connection_error", "exception_type": "ConnectError", "sanitized_message": "connection failed"})
        ConversationService(FakeAIProvider(error=error), store_debug=True).chat(session, user, conversation, "hola")
        call = session.scalar(select(AICall).where(AICall.conversation_id == conversation.id))
        assert call.error_type == "connection_error"
        assert json.loads(call.debug_payload)["exception_type"] == "ConnectError"


def test_non_debug_audit_does_not_store_diagnostics(client):
    with client.app.state.SessionLocal() as session:
        user = User(whatsapp_jid="diagnostic-private@test")
        session.add(user); session.flush()
        conversation = Conversation(user_id=user.id)
        session.add(conversation); session.commit()
        error = AIProviderError("connection_error", AIResponse(None, "test-model", provider="gemini"), {"sanitized_message": "connection failed"})
        ConversationService(FakeAIProvider(error=error), store_debug=False).chat(session, user, conversation, "hola")
        call = session.scalar(select(AICall).where(AICall.conversation_id == conversation.id))
        assert call.debug_payload is None
