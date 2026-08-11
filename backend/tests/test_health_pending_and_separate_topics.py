import pytest
from sqlalchemy import func, select

from app.ai.fake_provider import FakeAIProvider
from app.models.conversation import Conversation
from app.models.tarot_reading import TarotReading
from app.models.user import User
from app.services.conversation import ConversationService, health_intent
from app.services.lab import LabService
from app.services.tarot_readings import create_reading


@pytest.mark.parametrize("acceptance", ["dale", "ok", "dale si", "perfecto"])
def test_predictive_health_reframe_keeps_a_safe_pending_one_card(client, acceptance):
    with client.app.state.SessionLocal() as session:
        service = LabService(FakeAIProvider(mode="demo"))
        _, conversation, proposal, response, reading, _ = service.chat(
            session, f"pregnancy-{acceptance}", "Quiero saber cómo va mi embarazo y mi hijo por nacer", f"pregnancy-question-{acceptance}"
        )
        assert response is None and reading is None
        assert (conversation.state, proposal.suggested_spread, proposal.reading_recommended) == ("READY_FOR_READING", "one_card", True)
        assert "controles" in proposal.reply

        _, conversation, decision, _, reading, interpretation = service.chat(session, f"pregnancy-{acceptance}", acceptance, f"pregnancy-confirm-{acceptance}")
        assert decision.action.value == "confirm_reading"
        assert reading and interpretation and reading.spread_type == "one_card"
        assert reading.question == "Reflexión emocional no médica para transitar un contexto de salud."
        assert conversation.state == "READING_ACTIVE"


def test_health_exclusions_and_context_do_not_trigger_the_medical_reframe(client):
    with client.app.state.SessionLocal() as session:
        service = LabService(FakeAIProvider(mode="demo"))
        service.chat(session, "other-topics", "Cómo va mi embarazo", "other-health")
        service.chat(session, "other-topics", "dale", "other-confirm")
        _, _, decision, response, _, _ = service.chat(session, "other-topics", "Qué otros temas puedo preguntar que no sean salud", "other-topics-question")
        assert response is not None
        assert "familia" in decision.reply.lower()
        assert "controles" not in decision.reply.lower()

        _, conversation, work, response, _, _ = service.chat(session, "context-only", "Estoy embarazada y quiero saber si voy a conseguir trabajo", "context-work")
        assert response is not None
        assert work.suggested_spread == "general_three"
        assert conversation.state == "READY_FOR_READING"


@pytest.mark.parametrize("text", ["que no sea salud", "no quiero preguntar por salud", "dejemos el tema de salud", "hablemos de otra cosa"])
def test_health_exclusions_are_not_classified_as_medical_predictions(text):
    assert health_intent(text) is None


def test_multiple_topics_can_be_selected_separately_without_a_reading(client):
    with client.app.state.SessionLocal() as session:
        service = LabService(FakeAIProvider(mode="demo"))
        _, conversation, proposal, _, reading, _ = service.chat(session, "separate", "Familia, viajes y patrones de comportamiento", "topics")
        assert proposal.reading_recommended and reading is None
        _, conversation, choice, response, reading, _ = service.chat(session, "separate", "No, esta vez las quiero por separado", "separate-choice")
        assert response is None and reading is None
        assert conversation.state == "DEFINING_QUESTION"
        assert not choice.reading_recommended
        assert all(topic in choice.reply.lower() for topic in ("familia", "viajes", "patrones"))
        assert session.scalar(select(func.count()).select_from(TarotReading).where(TarotReading.conversation_id == conversation.id)) == 0


def test_general_three_follow_up_does_not_invent_a_travel_position(client):
    with client.app.state.SessionLocal() as session:
        user = User(whatsapp_jid="general-follow-up@test")
        session.add(user)
        session.flush()
        conversation = Conversation(user_id=user.id, state="READING_ACTIVE")
        session.add(conversation)
        session.commit()
        create_reading(session, user_id=user.id, conversation_id=conversation.id, spread_type="general_three", seed="general")
        provider = FakeAIProvider(mode="demo")
        decision, response = ConversationService(provider).chat(session, user, conversation, "¿Cuál era la carta de viajes?")
        assert response is None and provider.requests == []
        assert "no separó una posición para viajes" in decision.reply
        assert session.get(Conversation, conversation.id).state == "FOLLOW_UP"
