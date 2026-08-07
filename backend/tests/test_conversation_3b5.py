import json

from sqlalchemy import select

from app.ai.fake_provider import FakeAIProvider
from app.conversation.schemas import ConversationState
from app.models.ai import AICall, UserMemory
from app.models.conversation import Conversation
from app.models.message import Message
from app.models.tarot_reading import TarotReading
from app.models.user import User
from app.services.conversation import ConversationService, PROMPT, PROMPT_VERSION


def decision(reply, intent, state, recommended=False, spread=None):
    return json.dumps(
        {
            "reply": reply,
            "intent": intent,
            "next_state": state,
            "reading_recommended": recommended,
            "suggested_spread": spread,
            "memory_candidates": [],
        }
    )


def setup(session, jid="scenario@test", state=ConversationState.NEW):
    user = User(whatsapp_jid=jid)
    session.add(user)
    session.flush()
    conversation = Conversation(user_id=user.id, state=state.value)
    session.add(conversation)
    session.commit()
    return user, conversation


def test_tarotista_prompt_has_required_safety_and_conversation_instructions():
    prompt = PROMPT.read_text(encoding="utf8").lower()
    required_fragments = [
        "tarotista virtual", "no afirmes ser humana", "constantemente como ia", "preguntan directamente qué sos",
        "español natural", "no conviertas la charla en un formulario", "información ya dada", "datos personales innecesarios",
        "resulte cómodo", "certezas sobre el futuro", "tendencias, posibilidades", "enfermedades, embarazo, muerte, delitos, violencia, inversiones, apuestas",
        "decisiones graves", "estados: new", "intents válidos", "únicamente json válido", "reading_recommended", "suggested_spread",
    ]
    assert all(fragment in prompt for fragment in required_fragments)


def test_relationship_scenario_keeps_context_recommends_reading_and_audits(client):
    responses = [
        decision("Hola, contame qué querés mirar.", "greeting", "CHATTING"),
        decision("¿Qué te gustaría comprender de ese vínculo?", "relationship", "DEFINING_QUESTION"),
        decision("Con ese contexto, podemos mirar la dinámica del vínculo.", "relationship", "READY_FOR_READING", True, "relationship_three"),
    ]
    fake = FakeAIProvider(
        responses=responses,
        usage={"provider": "gemini", "model": "gemini-2.5-flash", "input_tokens": 7, "output_tokens": 3},
    )
    with client.app.state.SessionLocal() as session:
        user, conversation = setup(session)
        service = ConversationService(fake, recent_messages=12)
        service.chat(session, user, conversation, "Hola")
        service.chat(session, user, conversation, "Quiero saber por mi ex.")
        result, _ = service.chat(session, user, conversation, "Hace dos meses que no hablamos y ayer me escribió.")

        session.refresh(conversation)
        messages = session.scalars(select(Message).where(Message.conversation_id == conversation.id).order_by(Message.id)).all()
        audits = session.scalars(select(AICall).where(AICall.conversation_id == conversation.id).order_by(AICall.id)).all()
        third_context = [(message.role, message.content) for message in fake.requests[2][0]]

        assert conversation.state == ConversationState.READY_FOR_READING.value
        assert result.suggested_spread == "relationship_three"
        assert [message.content for message in messages if message.direction == "incoming"] == [
            "Hola", "Quiero saber por mi ex.", "Hace dos meses que no hablamos y ayer me escribió."
        ]
        assert len([message for message in messages if message.direction == "outgoing"]) == 3
        assert third_context[-1] == ("user", "Hace dos meses que no hablamos y ayer me escribió.")
        assert ("user", "Quiero saber por mi ex.") in third_context
        assert ("assistant", "¿Qué te gustaría comprender de ese vínculo?") in third_context
        assert session.scalars(select(TarotReading)).all() == []
        assert len(audits) == 3 and all(audit.success for audit in audits)
        assert all(audit.prompt_version == PROMPT_VERSION for audit in audits)
        assert all((audit.input_tokens, audit.output_tokens, audit.estimated_cost_usd) == (7, 3, 0) for audit in audits)


def test_general_reading_recommends_spread_without_creating_cards_or_extra_question(client):
    with client.app.state.SessionLocal() as session:
        user, conversation = setup(session)
        result, _ = ConversationService(
            FakeAIProvider(response=decision("Perfecto, hagamos una lectura general.", "general_reading", "CHATTING", True, "general_three"))
        ).chat(session, user, conversation, "Quiero una lectura general.")

        assert result.reading_recommended is True
        assert result.suggested_spread == "general_three"
        assert "?" not in result.reply
        assert session.scalars(select(TarotReading)).all() == []


def test_complete_question_is_sent_without_forcing_a_second_question(client):
    question = "Mi ex volvió a escribirme después de dos meses y quiero saber qué intención tiene conmigo."
    with client.app.state.SessionLocal() as session:
        user, conversation = setup(session)
        fake = FakeAIProvider(response=decision("Con eso alcanza para mirar la dinámica.", "relationship", "DEFINING_QUESTION", True, "relationship_three"))
        result, _ = ConversationService(fake).chat(session, user, conversation, question)

        assert conversation.state == ConversationState.DEFINING_QUESTION.value
        assert result.reading_recommended is True
        assert fake.requests[0][0][-1].content == question
        assert "?" not in result.reply
        assert session.scalars(select(TarotReading)).all() == []


def test_follow_up_does_not_recommend_or_create_another_reading(client):
    with client.app.state.SessionLocal() as session:
        user, conversation = setup(session, state=ConversationState.FOLLOW_UP)
        result, _ = ConversationService(
            FakeAIProvider(response=decision("Para vos puede señalar un momento de observar tus límites.", "follow_up", "FOLLOW_UP"))
        ).chat(session, user, conversation, "¿Y qué significa eso para mí?")

        assert conversation.state == ConversationState.FOLLOW_UP.value
        assert result.reading_recommended is False and result.suggested_spread is None
        assert session.scalars(select(TarotReading)).all() == []


def test_prompt_memory_history_and_current_message_are_distinct(client):
    with client.app.state.SessionLocal() as session:
        user, conversation = setup(session)
        session.add_all([
            UserMemory(user_id=user.id, summary="Consulta por una relación intermitente.", version=1),
            Message(conversation_id=conversation.id, direction="outgoing", message_type="text", content="Mensaje previo."),
        ])
        session.commit()
        fake = FakeAIProvider(response=decision("Podemos retomar desde ahí.", "relationship", "CHATTING"))
        ConversationService(fake, recent_messages=3).chat(session, user, conversation, "Hoy volvió a hablarme.")

        messages = fake.requests[0][0]
        assert messages[0].role == "system" and messages[0].content == PROMPT.read_text(encoding="utf8")
        assert messages[1].role == "system" and messages[1].content == "Memoria: Consulta por una relación intermitente."
        assert [(message.role, message.content) for message in messages[2:]] == [
            ("assistant", "Mensaje previo."), ("user", "Hoy volvió a hablarme.")
        ]
