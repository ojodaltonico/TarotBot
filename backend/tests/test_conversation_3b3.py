import json

import pytest
from sqlalchemy import select

from app.ai.fake_provider import FakeAIProvider
from app.conversation.schemas import ConversationState
from app.models.ai import AICall
from app.models.conversation import Conversation
from app.models.message import Message
from app.models.tarot_reading import TarotReading
from app.models.user import User
from app.services.conversation import ConversationService, FALLBACK


def create_conversation(session, state=ConversationState.DEFINING_QUESTION):
    user = User(whatsapp_jid="fallback@test")
    session.add(user)
    session.flush()
    conversation = Conversation(user_id=user.id, state=state.value)
    session.add(conversation)
    session.commit()
    return user, conversation


@pytest.mark.parametrize(
    ("mode", "error_type"),
    [
        ("timeout", "timeout"),
        ("provider_error", "provider_error"),
        ("empty", "empty_response"),
        ("none_text", "empty_response"),
        ("missing_structured", "empty_response"),
        ("invalid_schema", "validation_error"),
        ("invalid_next_state", "validation_error"),
        ("invalid_intent", "validation_error"),
        ("empty_reply", "validation_error"),
        ("blank_reply", "invalid_response"),
        ("partial", "validation_error"),
        ("invalid_reading_recommended", "validation_error"),
        ("invalid_memory_candidates", "validation_error"),
    ],
)
def test_invalid_provider_results_persist_safe_fallback(client, mode, error_type):
    with client.app.state.SessionLocal() as session:
        user, conversation = create_conversation(session)
        result, response = ConversationService(
            FakeAIProvider(mode=mode, usage={"model": "known-model", "input_tokens": 12, "output_tokens": 4, "latency_ms": 23})
        ).chat(session, user, conversation, "Mi consulta")

        session.refresh(conversation)
        messages = session.scalars(
            select(Message).where(Message.conversation_id == conversation.id).order_by(Message.id)
        ).all()
        audit = session.scalar(select(AICall).where(AICall.conversation_id == conversation.id))

        assert response is None
        assert result.reply == FALLBACK
        assert conversation.state == ConversationState.DEFINING_QUESTION.value
        assert [(message.direction, message.content) for message in messages] == [
            ("incoming", "Mi consulta"),
            ("outgoing", FALLBACK),
        ]
        assert session.scalars(select(TarotReading)).all() == []
        assert audit.success is False
        assert audit.purpose == "conversation"
        assert audit.error_type == error_type
        assert audit.provider == "fake"
        assert audit.model == "known-model"
        assert (audit.input_tokens, audit.output_tokens, audit.latency_ms) == (12, 4, 23)
        assert audit.estimated_cost_usd is None


def test_generic_exception_is_classified_without_escaping_to_caller(client):
    with client.app.state.SessionLocal() as session:
        user, conversation = create_conversation(session)
        result, response = ConversationService(FakeAIProvider(mode="generic_error")).chat(
            session, user, conversation, "Mi consulta"
        )

        audit = session.scalar(select(AICall).where(AICall.conversation_id == conversation.id))
        assert response is None
        assert result.reply == FALLBACK
        assert conversation.state == ConversationState.DEFINING_QUESTION.value
        assert audit.error_type == "provider_error"
        assert audit.success is False
        assert (audit.input_tokens, audit.output_tokens, audit.latency_ms) == (10, 5, 1)


def test_conversation_recovers_after_a_fallback(client):
    valid = json.dumps(
        {
            "reply": "Ahora sí, contame un poco más.",
            "intent": "general_chat",
            "next_state": "CHATTING",
            "reading_recommended": False,
            "suggested_spread": None,
            "memory_candidates": [],
        }
    )
    with client.app.state.SessionLocal() as session:
        user, conversation = create_conversation(session, ConversationState.NEW)
        ConversationService(FakeAIProvider(mode="timeout")).chat(session, user, conversation, "primero")
        result, response = ConversationService(FakeAIProvider(response=valid)).chat(
            session, user, conversation, "segundo"
        )

        session.refresh(conversation)
        audits = session.scalars(
            select(AICall).where(AICall.conversation_id == conversation.id).order_by(AICall.id)
        ).all()
        assert response is not None
        assert result.reply == "Ahora sí, contame un poco más."
        assert conversation.state == ConversationState.CHATTING.value
        assert [audit.success for audit in audits] == [False, True]
