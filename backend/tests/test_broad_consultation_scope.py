import json
from pathlib import Path

from sqlalchemy import select

from app.ai.fake_provider import FakeAIProvider
from app.models.conversation import Conversation
from app.models.user import User
from app.services.lab import LabService
from app.services.tarot_interpretation import TarotInterpretationService
from app.services.tarot_readings import create_reading


def test_broad_love_asks_general_or_specific_without_assuming_a_partner(client):
    with client.app.state.SessionLocal() as session:
        _, conversation, result, _, reading, _ = LabService(FakeAIProvider(mode="demo")).chat(session, "love-broad", "Quiero saber sobre el amor", "love-broad-1")
        assert reading is None and conversation.state == "DEFINING_QUESTION"
        assert "general" in result.reply.lower() and "alguien" in result.reply.lower()
        assert "ex" not in result.reply.lower() and "pareja" not in result.reply.lower()


def test_general_after_broad_love_recommends_general_three(client):
    with client.app.state.SessionLocal() as session:
        service = LabService(FakeAIProvider(mode="demo"))
        service.chat(session, "love-general", "amor", "love-general-1")
        _, conversation, result, _, reading, _ = service.chat(session, "love-general", "General", "love-general-2")
        assert reading is None and result.suggested_spread == "general_three"
        assert conversation.state == "READY_FOR_READING" and conversation.reading_recommended


def test_interested_person_gets_one_useful_clarifying_question(client):
    with client.app.state.SessionLocal() as session:
        _, conversation, result, _, reading, _ = LabService(FakeAIProvider(mode="demo")).chat(session, "interest", "Hay alguien que me interesa", "interest-1")
        assert reading is None and conversation.state == "DEFINING_QUESTION"
        assert "entre ustedes" in result.reply.lower() or "hacia dónde" in result.reply.lower()
        assert "nombre" not in result.reply.lower() and "fecha" not in result.reply.lower()


def test_specific_ex_question_is_sufficient_without_another_question(client):
    with client.app.state.SessionLocal() as session:
        _, conversation, result, _, reading, _ = LabService(FakeAIProvider(mode="demo")).chat(session, "ex", "Mi ex me escribió después de dos meses y quiero saber qué intención tiene", "ex-1")
        assert reading is None and result.suggested_spread == "relationship_three"
        assert conversation.state == "READY_FOR_READING" and not result.reply.rstrip().endswith("?")


def test_broad_work_is_framed_but_specific_work_is_sufficient(client):
    with client.app.state.SessionLocal() as session:
        service = LabService(FakeAIProvider(mode="demo"))
        _, conversation, broad, _, reading, _ = service.chat(session, "work-broad", "Trabajo", "work-broad-1")
        assert reading is None and conversation.state == "DEFINING_QUESTION" and "general" in broad.reply.lower()
        _, conversation, specific, _, reading, _ = service.chat(session, "work-specific", "¿Voy a conseguir trabajo?", "work-specific-1")
        assert reading is None and specific.suggested_spread == "general_three"
        assert conversation.state == "READY_FOR_READING" and conversation.reading_recommended


def test_prompt_documents_scope_and_sufficiency_rules():
    prompt = Path("backend/app/ai/prompts/tarotista_v4.txt").read_text(encoding="utf8").lower()
    for scope in ("general", "specific_relationship", "specific_work", "specific_question"):
        assert scope in prompt
    assert "no pidas nombre" in prompt and "una sola pregunta útil" in prompt


def test_general_and_relationship_interpretations_keep_their_structural_language_separate(client):
    with client.app.state.SessionLocal() as session:
        user = User(whatsapp_jid="scope-spreads@test")
        session.add(user)
        session.flush()
        conversation = Conversation(user_id=user.id)
        session.add(conversation)
        session.commit()
        for spread, text, forbidden in (
            ("general_three", "La situación actual se ordena; el desafío pide paciencia y la tendencia trae un consejo concreto.", ("la otra parte", "entre ustedes")),
            ("relationship_three", "Tu posición busca claridad, la otra parte se muestra reservada y entre ustedes hay una tensión.", ()),
        ):
            reading_id, _ = create_reading(session, user_id=user.id, conversation_id=conversation.id, spread_type=spread, seed=f"scope-{spread}")
            result = TarotInterpretationService(FakeAIProvider(response=json.dumps({"interpretation": text, "summary": "Síntesis."}))).interpret_reading(session, reading_id, user.id, conversation.id)
            assert all(phrase not in result.interpretation_text.lower() for phrase in forbidden)
