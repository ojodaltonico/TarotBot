import json
from datetime import datetime, timedelta

from sqlalchemy import func, select

from app.ai.fake_provider import FakeAIProvider
from app.models.conversation import Conversation
from app.models.message import Message
from app.models.tarot_reading import TarotReading
from app.models.user import User
from app.services.conversation import ConversationService
from app.services.tarot_readings import create_reading


def decision(reply="Sigo con la lectura.", *, recommended=False, spread=None, state="FOLLOW_UP", action="none"):
    return json.dumps({"reply": reply, "intent": "follow_up", "next_state": state, "reading_recommended": recommended, "suggested_spread": spread, "action": action, "memory_candidates": []})


def active(session, key="reading-context@test", spread="relationship_three", question="Consulta sobre una ex pareja"):
    user = User(whatsapp_jid=key); session.add(user); session.flush()
    conversation = Conversation(user_id=user.id, state="CHATTING"); session.add(conversation); session.commit()
    create_reading(session, user_id=user.id, conversation_id=conversation.id, spread_type=spread, question=question, seed=key)
    return user, conversation


def count_readings(session, conversation):
    return session.scalar(select(func.count(TarotReading.id)).where(TarotReading.conversation_id == conversation.id))


def test_interpreted_reading_remains_context_for_multiple_followups(client):
    with client.app.state.SessionLocal() as session:
        user, conversation = active(session)
        provider = FakeAIProvider(response=decision("Podemos sacar otra.", recommended=True, spread="relationship_three", state="READY_FOR_READING"))
        for text in ("¿qué significa para mí?", "¿y cómo lo puedo encarar?"):
            result, _ = ConversationService(provider).chat(session, user, conversation, text)
            assert result.reading_recommended is False
            assert result.action.value == "none"
        assert count_readings(session, conversation) == 1
        assert any("cartas persistidas" in message.content for message in provider.requests[0][0] if message.role == "system")


def test_same_link_specific_question_reuses_reading_but_love_to_work_opens_new_scope(client):
    with client.app.state.SessionLocal() as session:
        user, conversation = active(session)
        same = ConversationService(FakeAIProvider(response=decision("Hagamos otra.", recommended=True, spread="relationship_three", state="READY_FOR_READING"))).chat(session, user, conversation, "¿Qué pasa si le escribo a mi ex?")[0]
        assert same.reading_recommended is False
        work = ConversationService(FakeAIProvider(response=decision("Podemos mirar trabajo.", recommended=True, spread="general_three", state="READY_FOR_READING"))).chat(session, user, conversation, "Ahora quiero mirar trabajo")[0]
        assert work.reading_recommended and work.suggested_spread == "general_three"
        assert count_readings(session, conversation) == 1


def test_quoted_this_and_quoted_yes_prioritize_the_referenced_proposal(client):
    with client.app.state.SessionLocal() as session:
        user = User(whatsapp_jid="quoted-confirm@test"); session.add(user); session.flush()
        conversation = Conversation(user_id=user.id, state="READY_FOR_READING", reading_recommended=True, suggested_spread="general_three"); session.add(conversation); session.commit()
        provider = FakeAIProvider(response=decision("Voy con la tirada.", state="CHATTING"))
        result, _ = ConversationService(provider).chat(session, user, conversation, "sí", physical_messages=[{"message_id": "quoted-yes", "timestamp": None, "message_type": "text", "text": "sí", "quoted_text": "Podemos hacer una tirada de tres cartas. ¿Te parece bien?", "quoted_message_id": "proposal"}])
        assert result.action.value == "confirm_reading"
        assert provider.requests[0][0][-1].content.startswith("La persona responde a:")


def test_nonconfirmation_after_pending_topic_change_cannot_trigger_old_reading(client):
    with client.app.state.SessionLocal() as session:
        user, conversation = active(session, key="stale@test")
        conversation.state = "READY_FOR_READING"; conversation.reading_recommended = True; conversation.suggested_spread = "relationship_three"; session.commit()
        result, _ = ConversationService(FakeAIProvider(response=decision("Trabajo.", recommended=True, spread="general_three", state="READY_FOR_READING"))).chat(session, user, conversation, "Ahora quiero mirar trabajo")
        assert result.action.value == "none"
        assert result.suggested_spread == "general_three"
        assert count_readings(session, conversation) == 1


def test_same_topic_can_open_successive_readings_only_after_explicit_request_and_confirmation(client):
    with client.app.state.SessionLocal() as session:
        user, conversation = active(session, key="successive@test")
        proposal = decision("Podemos hacer otra específica.", recommended=True, spread="relationship_three", state="READY_FOR_READING")
        requested, _ = ConversationService(FakeAIProvider(response=proposal)).chat(session, user, conversation, "Insisto, quiero otra tirada sobre mi ex")
        assert requested.reading_recommended is True
        confirmed, _ = ConversationService(FakeAIProvider(response=decision("Dale.", state="CHATTING"))).chat(session, user, conversation, "sí")
        assert confirmed.action.value == "confirm_reading"
        assert count_readings(session, conversation) == 1


def test_multiple_physical_messages_are_one_turn_and_do_not_consume_an_old_confirmation(client):
    with client.app.state.SessionLocal() as session:
        user, conversation = active(session, key="multi@test")
        provider = FakeAIProvider(response=decision("Sigo con esta lectura."))
        result, _ = ConversationService(provider).chat(session, user, conversation, "sí, pero ahora te cuento algo de mi trabajo", physical_messages=[
            {"message_id": "multi-1", "timestamp": None, "message_type": "text", "text": "sí,"},
            {"message_id": "multi-2", "timestamp": None, "message_type": "text", "text": "pero ahora te cuento algo de mi trabajo"},
        ])
        assert result.action.value == "none"
        assert len(provider.requests) == 1
        assert count_readings(session, conversation) == 1
        assert session.scalar(select(func.count(Message.id)).where(Message.conversation_id == conversation.id, Message.direction == "incoming")) == 2


def test_old_reading_does_not_block_a_new_request_after_an_ambiguous_opening(client):
    with client.app.state.SessionLocal() as session:
        user, conversation = active(session, key="old-reading@test")
        reading = session.scalar(select(TarotReading).where(TarotReading.conversation_id == conversation.id))
        reading.created_at = datetime.now().astimezone().replace(tzinfo=None) - timedelta(days=7)
        session.commit()

        provider = FakeAIProvider(response=decision("Nueva general.", recommended=True, spread="general_three", state="READY_FOR_READING"))
        opening, _ = ConversationService(provider).chat(session, user, conversation, "tirame las cartas")
        assert opening.reading_recommended is False
        assert "nueva general" in opening.reply.lower()
        assert provider.requests == []

        requested, _ = ConversationService(provider).chat(session, user, conversation, "quiero una nueva")
        assert requested.reading_recommended is True
        assert requested.suggested_spread == "general_three"
        assert count_readings(session, conversation) == 1


def test_immediate_same_question_is_guarded_once_then_explicit_insistence_can_propose(client):
    with client.app.state.SessionLocal() as session:
        user, conversation = active(session, key="same-question@test")
        proposal = decision("Hagamos otra.", recommended=True, spread="relationship_three", state="READY_FOR_READING")
        first, _ = ConversationService(FakeAIProvider(response=proposal)).chat(session, user, conversation, "quiero otra tirada sobre mi ex")
        assert first.reading_recommended is False
        assert "antes de sacar otra" in first.reply.lower()

        second, _ = ConversationService(FakeAIProvider(response=proposal)).chat(session, user, conversation, "sí, tirá de nuevo")
        assert second.reading_recommended is True
        assert second.suggested_spread == "relationship_three"
        assert "antes de sacar otra" not in second.reply.lower()


def test_new_specific_question_on_same_topic_can_propose_an_expansion(client):
    with client.app.state.SessionLocal() as session:
        user, conversation = active(session, key="specific-expansion@test", question="Qué pasa entre nosotros")
        provider = FakeAIProvider(response=decision("Podemos mirar esa semana.", recommended=True, spread="relationship_three", state="READY_FOR_READING"))
        result, _ = ConversationService(provider).chat(session, user, conversation, "¿Me va a escribir esta semana?")
        assert result.reading_recommended is True
        assert result.suggested_spread == "relationship_three"


def test_other_topic_clears_current_scope_then_weekly_question_opens_general_reading(client):
    with client.app.state.SessionLocal() as session:
        user, conversation = active(session, key="other-topic@test")
        reset, _ = ConversationService(FakeAIProvider(response=decision())).chat(session, user, conversation, "de otra cosa")
        assert reset.reading_recommended is False
        assert reset.next_state.value == "DEFINING_QUESTION"

        provider = FakeAIProvider(response=decision("Miremos la semana.", recommended=True, spread="general_three", state="READY_FOR_READING"))
        weekly, _ = ConversationService(provider).chat(session, user, conversation, "quiero saber qué tal la semana")
        assert weekly.reading_recommended is True
        assert weekly.suggested_spread == "general_three"
