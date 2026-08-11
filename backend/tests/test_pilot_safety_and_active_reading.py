import json

import pytest
from sqlalchemy import func, select

from app.ai.fake_provider import FakeAIProvider
from app.conversation.schemas import ConversationState
from app.models.conversation import Conversation
from app.models.message import Message
from app.models.tarot_reading import TarotReading
from app.models.user import User
from app.services.conversation import ConversationService
from app.services.tarot_readings import create_reading


def provider_decision(reply="Sigo con la lectura que ya está sobre la mesa.", *, recommended=False, spread=None, state="FOLLOW_UP"):
    return json.dumps({
        "reply": reply,
        "intent": "follow_up",
        "next_state": state,
        "reading_recommended": recommended,
        "suggested_spread": spread,
        "action": "none",
        "memory_candidates": [],
    })


def active_context(session, key="active@test", spread="relationship_three"):
    user = User(whatsapp_jid=key)
    session.add(user)
    session.flush()
    conversation = Conversation(user_id=user.id, state="READING_ACTIVE")
    session.add(conversation)
    session.commit()
    create_reading(session, user_id=user.id, conversation_id=conversation.id, spread_type=spread, seed=key)
    return user, conversation


@pytest.mark.parametrize("message, expected_state", [("😔😔", "FOLLOW_UP"), ("qué tengo que hacer", "FOLLOW_UP"), ("sí", "READING_ACTIVE")])
def test_active_reading_never_starts_another_from_short_followups(client, message, expected_state):
    with client.app.state.SessionLocal() as session:
        user, conversation = active_context(session, key=f"short-{message}@test")
        provider = FakeAIProvider(response=provider_decision("Podemos hacer otra tirada.", recommended=True, spread="relationship_three", state="READY_FOR_READING"))
        result, _ = ConversationService(provider).chat(session, user, conversation, message)
        assert result.reading_recommended is False
        assert session.get(Conversation, conversation.id).state == expected_state
        assert session.scalar(select(func.count()).select_from(TarotReading).where(TarotReading.conversation_id == conversation.id)) == 1


def test_same_topic_reading_needs_clear_insistence_but_new_topic_can_be_prepared(client):
    with client.app.state.SessionLocal() as session:
        user, conversation = active_context(session, key="same-topic@test")
        proposal = provider_decision("Hagamos otra.", recommended=True, spread="relationship_three", state="READY_FOR_READING")
        first, _ = ConversationService(FakeAIProvider(response=proposal)).chat(session, user, conversation, "Quiero otra tirada sobre esto")
        assert first.reading_recommended is False
        assert "Antes de sacar otra" in first.reply

        insist, _ = ConversationService(FakeAIProvider(response=proposal)).chat(session, user, conversation, "Insisto, quiero otra tirada")
        assert insist.reading_recommended is True
        assert insist.suggested_spread == "relationship_three"
        assert session.get(Conversation, conversation.id).state == "READY_FOR_READING"

        session.get(Conversation, conversation.id).state = "READING_ACTIVE"
        new_topic = provider_decision("Podemos mirar el trabajo.", recommended=True, spread="general_three", state="READY_FOR_READING")
        decision, _ = ConversationService(FakeAIProvider(response=new_topic)).chat(session, user, conversation, "Quiero una tirada sobre trabajo")
        assert decision.reading_recommended is True
        assert decision.suggested_spread == "general_three"


def test_health_question_is_locally_limited_without_provider_or_reading(client):
    with client.app.state.SessionLocal() as session:
        user = User(whatsapp_jid="health@test")
        session.add(user)
        session.flush()
        conversation = Conversation(user_id=user.id, state="READY_FOR_READING", reading_recommended=True, suggested_spread="general_three")
        session.add(conversation)
        session.commit()
        provider = FakeAIProvider(mode="demo")
        decision, response = ConversationService(provider).chat(session, user, conversation, "¿Me voy a curar de esta enfermedad?")
        assert response is None and provider.requests == []
        assert decision.reading_recommended and decision.suggested_spread == "one_card"
        assert "controles" in decision.reply.lower()
        assert session.get(Conversation, conversation.id).state == "READY_FOR_READING"
        assert session.scalar(select(func.count()).select_from(TarotReading)) == 0


def test_health_context_allows_only_explicit_nonmedical_reflection(client):
    with client.app.state.SessionLocal() as session:
        user = User(whatsapp_jid="health-card@test")
        session.add(user)
        session.flush()
        conversation = Conversation(user_id=user.id)
        session.add(conversation)
        session.commit()
        service = ConversationService(FakeAIProvider(mode="demo"))
        service.chat(session, user, conversation, "Tengo dolor y quiero saber si el medicamento me va a curar")
        decision, response = service.chat(session, user, conversation, "Quiero una carta")
        assert response is None
        assert decision.reading_recommended is True
        assert decision.suggested_spread == "one_card"
        assert "médico" in decision.reply


def test_quoted_reply_is_human_context_for_provider_but_not_persisted_as_message_text(client):
    with client.app.state.SessionLocal() as session:
        user = User(whatsapp_jid="quote@test")
        session.add(user)
        session.flush()
        conversation = Conversation(user_id=user.id)
        session.add(conversation)
        session.commit()
        provider = FakeAIProvider(response=provider_decision())
        ConversationService(provider).chat(session, user, conversation, "Esto", physical_messages=[{
            "message_id": "quote-1", "timestamp": None, "message_type": "text", "text": "Esto", "quoted_text": "Mis hijos", "quoted_message_id": "old-id",
        }])
        sent_messages, _, _ = provider.requests[0]
        assert sent_messages[-1].content == "La persona responde a: “Mis hijos”.\nDice: “Esto”"
        incoming = session.scalar(select(Message).where(Message.whatsapp_message_id == "quote-1"))
        assert incoming.content == "Esto"


def test_prompt_covers_reference_video_and_ambiguous_emotional_safety_rules():
    prompt = open("backend/app/ai/prompts/tarotista_v4.txt", encoding="utf8").read().lower()
    for phrase in ("no cambies “él” por “él/ella”", "videollamada", "no actives un protocolo de emergencia", "no la vuelve más verdadera"):
        assert phrase in prompt
    interpretation = open("backend/app/ai/prompts/tarot_interpretation_v2.txt", encoding="utf8").read().lower()
    assert "no inventes síntomas, medicación ni conductas" in interpretation


@pytest.mark.parametrize(
    ("message", "expected", "forbidden"),
    [
        ("¿Podemos hacer una videollamada?", "No puedo hacer videollamadas", "error"),
        ("En una videollamada con él pasó algo raro", "¿Te referís", "No puedo hacer videollamadas"),
        ("No puedo salir adelante", "¿Qué es lo que más", "emergencia"),
        ("¿Necesitás el nombre para hacer la lectura?", "No hace falta", "energía alcanza"),
    ],
)
def test_fake_regressions_keep_video_emotional_and_optional_context_human(client, message, expected, forbidden):
    with client.app.state.SessionLocal() as session:
        user = User(whatsapp_jid=f"fake-{message}@test")
        session.add(user)
        session.flush()
        conversation = Conversation(user_id=user.id)
        session.add(conversation)
        session.commit()
        decision, _ = ConversationService(FakeAIProvider(mode="demo")).chat(session, user, conversation, message)
        assert expected.lower() in decision.reply.lower()
        assert forbidden.lower() not in decision.reply.lower()
