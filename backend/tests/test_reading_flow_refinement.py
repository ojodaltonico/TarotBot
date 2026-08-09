import json

import pytest
from sqlalchemy import func, select

from app.ai.fake_provider import FakeAIProvider
from app.models.conversation import Conversation
from app.models.tarot_reading import TarotReading
from app.models.user import User
from app.services.conversation import ConversationService, is_reading_confirmation
from app.services.lab import LabService
from app.services.tarot_interpretation import TarotInterpretationService
from app.services.tarot_readings import create_reading


def decision(reply, intent, state, recommended=False, spread=None, action="none"):
    return json.dumps(
        {
            "reply": reply,
            "intent": intent,
            "next_state": state,
            "reading_recommended": recommended,
            "suggested_spread": spread,
            "action": action,
            "memory_candidates": [],
        }
    )


def interpretation(text="La lectura reúne las cartas en una orientación clara."):
    return json.dumps({"interpretation": text, "summary": "Una síntesis clara."})


@pytest.mark.parametrize("text", ["sí", "si", "Siii", "dale", "perfecto", "de una", "bueno", "hagámosla", "eso", "sí, eso", "me parece bien"])
def test_natural_confirmation_normalizer(text):
    assert is_reading_confirmation(text)


def test_general_proposal_persists_and_siii_creates_its_suggested_reading(client):
    with client.app.state.SessionLocal() as session:
        service = LabService(FakeAIProvider(mode="demo"))
        _, conversation, first, _, _, _ = service.chat(session, "general-a", "Quiero una tirada general", "general-a-1")
        assert (first.suggested_spread, conversation.state, conversation.reading_recommended, conversation.last_action) == ("general_three", "READY_FOR_READING", True, "none")

        _, conversation, accepted, _, reading, output = service.chat(session, "general-a", "Siii", "general-a-2")
        assert accepted.action.value == "confirm_reading"
        assert reading.spread_type == "general_three" and output is not None
        assert conversation.state == "READING_ACTIVE"


def test_general_week_request_and_si_eso_create_reading_directly(client):
    with client.app.state.SessionLocal() as session:
        service = LabService(FakeAIProvider(mode="demo"))
        _, conversation, first, _, _, _ = service.chat(session, "general-b", "Buenas, me hacés una tirada general para saber cómo va a estar mi semana?", "general-b-1")
        assert first.suggested_spread == "general_three" and conversation.state == "READY_FOR_READING"
        _, conversation, accepted, _, reading, output = service.chat(session, "general-b", "si, eso", "general-b-2")
        assert accepted.action.value == "confirm_reading" and reading.spread_type == "general_three" and output
        assert conversation.state == "READING_ACTIVE"


def test_work_context_is_sufficient_for_general_three_and_confirmation(client):
    with client.app.state.SessionLocal() as session:
        service = LabService(FakeAIProvider(mode="demo"))
        _, conversation, _, _, _, _ = service.chat(session, "work", "Y en lo laboral?", "work-1")
        _, conversation, proposal, _, _, _ = service.chat(session, "work", "Sobre mi trabajo", "work-2")
        assert proposal.suggested_spread == "general_three" and conversation.reading_recommended
        _, conversation, accepted, _, reading, output = service.chat(session, "work", "perfecto", "work-3")
        assert accepted.action.value == "confirm_reading" and reading.spread_type == "general_three" and output
        assert conversation.state == "READING_ACTIVE"


def test_third_party_question_offers_relationship_three_and_acceptance_creates_reading(client):
    with client.app.state.SessionLocal() as session:
        service = LabService(FakeAIProvider(mode="demo"))
        _, conversation, proposal, _, _, _ = service.chat(session, "third-party", "Mi compañera de trabajo le tiene ganas al jefe?", "third-1")
        assert proposal.suggested_spread == "relationship_three" and conversation.state == "READY_FOR_READING"
        _, conversation, accepted, _, reading, output = service.chat(session, "third-party", "Si", "third-2")
        assert accepted.action.value == "confirm_reading" and reading.spread_type == "relationship_three" and output
        assert conversation.state == "READING_ACTIVE"


def test_rejection_after_valid_proposal_never_creates_a_reading(client):
    with client.app.state.SessionLocal() as session:
        provider = FakeAIProvider(
            responses=[
                decision("Podemos hacer una general.", "general_reading", "READY_FOR_READING", True, "general_three"),
                decision("Lo dejamos para después.", "general_chat", "CHATTING"),
            ]
        )
        service = LabService(provider)
        service.chat(session, "reject", "Quiero una tirada general", "reject-1")
        _, conversation, result, _, reading, _ = service.chat(session, "reject", "no, mejor después", "reject-2")
        assert result.action.value == "none" and reading is None
        assert conversation.state == "CHATTING" and not conversation.reading_recommended and conversation.suggested_spread is None
        assert session.scalar(select(func.count(TarotReading.id))) == 0


def test_pending_proposal_survives_a_non_rejection_when_model_keeps_ready_state(client):
    with client.app.state.SessionLocal() as session:
        provider = FakeAIProvider(
            responses=[
                decision("Podemos hacer una general.", "general_reading", "READY_FOR_READING", True, "general_three"),
                decision("Es una tirada breve.", "general_reading", "READY_FOR_READING"),
            ]
        )
        service = LabService(provider)
        service.chat(session, "pending", "Quiero una tirada general", "pending-1")
        _, conversation, result, _, reading, _ = service.chat(session, "pending", "Qué tipo de tirada sería?", "pending-2")
        assert result.action.value == "none" and reading is None
        assert conversation.state == "READY_FOR_READING"
        assert conversation.reading_recommended and conversation.suggested_spread == "general_three"


@pytest.mark.parametrize(
    ("spread", "text", "required", "forbidden"),
    [
        ("general_three", "La situación actual pide orden; el desafío es sostenerlo y la tendencia invita a decidir con calma.", "situación actual", ("la otra parte", "entre ustedes", "del otro lado")),
        ("relationship_three", "Tu posición busca claridad, la otra parte aparece distante y entre ustedes hay una tensión que pide tiempo.", "la otra parte", ()),
        ("one_card", "Esta carta trae un consejo puntual: ordená tus prioridades antes de decidir.", "consejo puntual", ("tres cartas", "la otra parte", "entre ustedes")),
    ],
)
def test_interpretation_uses_spread_specific_context_and_mocked_semantics(client, spread, text, required, forbidden):
    with client.app.state.SessionLocal() as session:
        user = User(whatsapp_jid=f"spread-{spread}@test")
        session.add(user)
        session.flush()
        conversation = Conversation(user_id=user.id)
        session.add(conversation)
        session.commit()
        reading_id, _ = create_reading(session, user_id=user.id, conversation_id=conversation.id, spread_type=spread, seed=f"spread-{spread}")
        provider = FakeAIProvider(response=interpretation(text))
        result = TarotInterpretationService(provider).interpret_reading(session, reading_id, user.id, conversation.id)
        assert required in result.interpretation_text.lower()
        assert all(phrase not in result.interpretation_text.lower() for phrase in forbidden)
        system_contexts = [item.content.lower() for item in provider.requests[0][0] if item.role == "system"]
        assert any(spread in context for context in system_contexts)


def test_confirmation_without_a_valid_proposal_uses_a_contextual_human_reply(client):
    with client.app.state.SessionLocal() as session:
        user = User(whatsapp_jid="no-proposal@test")
        session.add(user)
        session.flush()
        conversation = Conversation(user_id=user.id, state="CHATTING")
        session.add(conversation)
        session.commit()
        result, _ = ConversationService(FakeAIProvider(response=decision("Voy con la tirada.", "general_reading", "READY_FOR_READING", action="confirm_reading"))).chat(session, user, conversation, "dale")
        assert result.action.value == "none"
        assert "general" in result.reply.lower() and "todavía no hay una tirada lista" not in result.reply.lower()
