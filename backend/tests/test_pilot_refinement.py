import json

import pytest

from app.ai.fake_provider import FakeAIProvider
from app.core.config import Settings
from app.models.conversation import Conversation
from app.models.user import User
from app.services.conversation import ConversationService
from app.schemas.whatsapp import OutboundMessage
from app.services.response_segments import delivery_messages, segment_text, typing_ms
from app.services.tarot_interpretation import InterpretationOutput, TarotInterpretationService
from app.services.tarot_readings import create_reading


def test_tarotista_v4_keeps_the_required_tone_boundaries():
    prompt = open("backend/app/ai/prompts/tarotista_v4.txt", encoding="utf8").read().lower()
    for expected in ("español rioplatense", "vos", "contame", "no afirmes ser humana", "no pidas datos personales", "no cierres consultas sentimentales normales con terapia", "no arranques con fórmulas terapéuticas", "nunca recites las tres cartas"):
        assert expected in prompt
    for forbidden in ("vosotros", "estáis", "terapia de pareja"):
        assert forbidden not in prompt


def test_interpretation_v2_schema_accepts_semantic_segments_and_uses_them(client):
    with client.app.state.SessionLocal() as session:
        user = User(whatsapp_jid="segments@test")
        session.add(user)
        session.flush()
        conversation = Conversation(user_id=user.id)
        session.add(conversation)
        session.commit()
        reading_id, _ = create_reading(session, user_id=user.id, conversation_id=conversation.id, spread_type="one_card", seed="segments")
        response = json.dumps({"interpretation": "Primero. Después.", "summary": "Síntesis.", "segments": ["Primero.", "Después."]})
        service = TarotInterpretationService(FakeAIProvider(response=response))
        interpretation = service.interpret_reading(session, reading_id, user.id, conversation.id)
        assert service.segments_for(interpretation) == ["Primero.", "Después."]
        assert service.prompt_version == "tarot_interpretation_v2"


def test_interpretation_v2_requires_spanish_orientation_and_limited_follow_up_style():
    prompt = open("backend/app/ai/prompts/tarot_interpretation_v2.txt", encoding="utf8").read().lower()
    assert "“derecha” para upright" in prompt
    assert "nunca uses esos términos en inglés" in prompt
    assert "sólo una o dos cartas relevantes" in prompt


def test_interpretation_output_rejects_empty_segments():
    with pytest.raises(ValueError):
        InterpretationOutput.model_validate({"interpretation": "Texto", "summary": "Resumen", "segments": [" "]})


def test_valid_recommendation_from_new_is_ready_for_natural_confirmation(client):
    payload = json.dumps({"reply": "¿Querés que saque las cartas?", "intent": "relationship", "next_state": "NEW", "reading_recommended": True, "suggested_spread": "relationship_three", "action": "none", "memory_candidates": []})
    with client.app.state.SessionLocal() as session:
        user = User(whatsapp_jid="ready@test")
        session.add(user)
        session.flush()
        conversation = Conversation(user_id=user.id, state="NEW")
        session.add(conversation)
        session.commit()
        decision, _ = ConversationService(FakeAIProvider(response=payload)).chat(session, user, conversation, "Quiero mirar mi relación.")
        assert decision.next_state.value == "READY_FOR_READING"
        assert session.get(Conversation, conversation.id).state == "READY_FOR_READING"


def test_semantic_segments_keep_short_reply_in_one_bubble():
    assert segment_text("¿Querés que miremos eso con una tirada?") == ["¿Querés que miremos eso con una tirada?"]


def test_semantic_segments_split_long_text_only_between_complete_sentences():
    sentences = [f"Esta es la oración número {index} y mantiene una idea completa." for index in range(1, 18)]
    text = " ".join(sentences)
    segments = segment_text(text, short_limit=40, target_limit=180)
    assert 2 <= len(segments) <= 4
    assert " ".join(segments).replace("\n\n", " ") == text
    assert all(segment.endswith(".") for segment in segments)


def test_semantic_segments_make_two_bubbles_for_medium_reply():
    text = " ".join(f"La oración {index} conserva una idea completa." for index in range(1, 9))
    segments = segment_text(text, short_limit=40, target_limit=170)
    assert len(segments) == 2
    assert all(segment.endswith(".") for segment in segments)


def test_delivery_timing_is_proportional_bounded_and_deterministic(monkeypatch):
    settings = Settings(
        whatsapp_typing_chars_per_second=20,
        whatsapp_min_typing_ms=2000,
        whatsapp_max_typing_ms=6000,
        whatsapp_inter_message_delay_ms_min=600,
        whatsapp_inter_message_delay_ms_max=800,
    )
    monkeypatch.setattr("app.services.response_segments.get_settings", lambda: settings)
    short = typing_ms("hola", key="a", index=0)
    medium = typing_ms("x" * 100, key="b", index=0)
    long = typing_ms("x" * 1000, key="c", index=0)
    assert short == 2000
    assert 4000 <= medium <= 6000
    assert long == 6000
    decorated = delivery_messages(["Primero.", "Segundo."], key="reading:1", prefix=[OutboundMessage(type="image", image_path="C:/safe.jpg", caption="Cartas")])
    assert [item.type for item in decorated] == ["image", "text", "text"]
    assert decorated[0].delay_ms == 0
    assert all(item.typing_ms >= 2000 for item in decorated)
    assert all(600 <= item.delay_ms <= 800 for item in decorated[1:])
