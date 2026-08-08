import json
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.ai.fake_provider import FakeAIProvider
from app.conversation.schemas import ConversationDecision
from app.models.conversation import Conversation
from app.models.tarot_reading import TarotReading, TarotReadingCard
from app.models.user import User
from app.services.conversation import ConversationService, is_simplification_follow_up
from app.services.tarot_readings import create_reading


SAFE_SUMMARY = (
    "La tirada muestra un vínculo con cosas todavía abiertas, pero no alcanza para afirmar qué siente la otra persona. "
    "Lo más útil es mirar si aparece un acercamiento concreto y qué necesitás vos para estar tranquila con eso, sin apresurarte a sacar una conclusión."
)


def decision(reply=SAFE_SUMMARY):
    return json.dumps(
        {
            "reply": reply,
            "intent": "follow_up",
            "next_state": "FOLLOW_UP",
            "reading_recommended": False,
            "suggested_spread": None,
            "action": "none",
            "memory_candidates": [],
        }
    )


@pytest.mark.parametrize(
    "message",
    ["o sea?", "entonces?", "en resumen?", "qué significa?", "pero sí o no?", "y eso qué quiere decir?", "  O SEA?  "],
)
def test_simplification_follow_up_normalization(message):
    assert is_simplification_follow_up(message)


def test_non_simplification_follow_up_is_not_misclassified():
    assert not is_simplification_follow_up("¿Qué puedo hacer ahora?")


def test_v4_and_interpretation_prompts_prohibit_third_party_certainties_and_didactic_reversals():
    conversation_prompt = Path("backend/app/ai/prompts/tarotista_v4.txt").read_text(encoding="utf8").lower()
    interpretation_prompt = Path("backend/app/ai/prompts/tarot_interpretation_v2.txt").read_text(encoding="utf8").lower()
    for phrase in ("no demuestra que alguien ama", "no prueban que alguien ama", "no expliques carta por carta", "40 a 100 palabras"):
        assert phrase in conversation_prompt or phrase in interpretation_prompt
    assert "no des una clase" in interpretation_prompt
    assert "para ver la dinámica del amor y si aún te siente" in conversation_prompt


@pytest.mark.parametrize("question", ["¿todavía me ama?", "¿me engaña?", "¿quiere volver?"])
def test_safe_simplification_after_ambiguous_reading_stays_uncertain_and_creates_no_reading(client, question):
    with client.app.state.SessionLocal() as session:
        user = User(whatsapp_jid=f"synthesis-{question}@test")
        session.add(user)
        session.flush()
        conversation = Conversation(user_id=user.id, state="FOLLOW_UP")
        session.add(conversation)
        session.commit()
        reading_id, _ = create_reading(
            session,
            user_id=user.id,
            conversation_id=conversation.id,
            spread_type="relationship_three",
            question=question,
            seed=f"ambiguous-{question}",
        )
        before = session.scalar(select(func.count(TarotReading.id)).where(TarotReading.conversation_id == conversation.id))
        provider = FakeAIProvider(response=decision())

        result, _ = ConversationService(provider).chat(session, user, conversation, "o sea?")

        assert result.reply == SAFE_SUMMARY
        assert 40 <= len(result.reply.split()) <= 100
        assert session.scalar(select(func.count(TarotReading.id)).where(TarotReading.conversation_id == conversation.id)) == before == 1
        assert session.get(Conversation, conversation.id).state == "FOLLOW_UP"
        card_names = [json.loads(card.card_snapshot)["name_es"].lower() for card in session.scalars(select(TarotReadingCard).where(TarotReadingCard.reading_id == reading_id)).all()]
        assert all(card_name not in result.reply.lower() for card_name in card_names)
        for claim in ("todavía te ama", "no ha dejado de quererte", "te engaña", "quiere volver"):
            assert claim not in result.reply.lower()
        request_messages, purpose, _ = provider.requests[0]
        assert purpose == "conversation"
        assert any("síntesis de la tirada activa" in item.content.lower() for item in request_messages if item.role == "system")


def test_simplification_response_validates_as_a_regular_follow_up():
    parsed = ConversationDecision.model_validate_json(decision())
    assert parsed.reply == SAFE_SUMMARY
    assert parsed.reading_recommended is False
