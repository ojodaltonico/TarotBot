import json

import pytest
from sqlalchemy import select

from app.ai.fake_provider import FakeAIProvider
from app.models.conversation import Conversation
from app.models.tarot_reading import TarotInterpretation, TarotReading, TarotReadingCard
from app.services.lab import LabService


def decision(*, action="confirm_reading", recommended=False, spread=None, state="READY_FOR_READING"):
    return json.dumps({"reply":"Perfecto.", "intent":"relationship", "next_state":state, "reading_recommended":recommended, "suggested_spread":spread, "action":action, "memory_candidates":[]})


def interpretation():
    return json.dumps({"interpretation":"Las cartas muestran una dinámica que pide claridad.", "summary":"Avanzá con honestidad."})


def ready(session, key="confirm", spread="relationship_three", recommended=True, state="READY_FOR_READING"):
    service = LabService(FakeAIProvider())
    user, conversation = service.user(session, key)
    conversation.state = state
    conversation.reading_recommended = recommended
    conversation.suggested_spread = spread
    session.commit()
    return user, conversation


def test_confirm_action_creates_and_interprets_suggested_reading_once(client):
    with client.app.state.SessionLocal() as session:
        ready(session)
        provider = FakeAIProvider(responses=[decision(), interpretation()])
        service = LabService(provider)
        _, conversation, result, _, reading, output = service.chat(session, "confirm", "sí", "msg-confirm-1")
        duplicate = service.chat(session, "confirm", "sí", "msg-confirm-1")

        assert result.action.value == "confirm_reading"
        assert reading.spread_type == "relationship_three" and len(session.scalars(select(TarotReadingCard).where(TarotReadingCard.reading_id == reading.id)).all()) == 3
        assert output and output.interpretation_summary == "Avanzá con honestidad."
        assert conversation.state == "READING_ACTIVE" and conversation.reading_recommended is False
        assert duplicate[4].id == reading.id and len(provider.requests) == 2
        assert len(session.scalars(select(TarotReading)).all()) == 1


@pytest.mark.parametrize("text", ["sí", "dale", "bueno", "hacela", "tirame las cartas", "sí, quiero", "vamos", "a ver qué sale"])
def test_conceptual_confirmations_depend_on_mocked_structured_action(client, text):
    with client.app.state.SessionLocal() as session:
        ready(session, key=f"yes-{text}")
        _, conversation, _, _, reading, output = LabService(FakeAIProvider(responses=[decision(), interpretation()])).chat(session, f"yes-{text}", text, f"id-{text}")
        assert reading and output and conversation.state == "READING_ACTIVE"


@pytest.mark.parametrize("text", ["esperá", "antes te quiero preguntar algo", "no", "mejor después", "qué tipo de tirada sería?", "cuánto tarda?", "cambiemos de tema"])
def test_non_confirmations_do_not_create_readings(client, text):
    with client.app.state.SessionLocal() as session:
        ready(session, key=f"no-{text}")
        _, conversation, result, _, reading, output = LabService(FakeAIProvider(response=decision(action="none", recommended=True, spread="relationship_three"))).chat(session, f"no-{text}", text, f"id-{text}")
        assert result.action.value == "none" and reading is None and output is None
        assert conversation.state == "READY_FOR_READING" and not session.scalars(select(TarotReading)).all()


@pytest.mark.parametrize(("state", "recommended", "spread"), [("READY_FOR_READING", False, "relationship_three"), ("READY_FOR_READING", True, "bad"), ("CHATTING", True, "relationship_three")])
def test_confirmation_requires_all_backend_preconditions(client, state, recommended, spread):
    with client.app.state.SessionLocal() as session:
        ready(session, key=f"guard-{state}-{recommended}-{spread}", state=state, recommended=recommended, spread=spread)
        _, _, result, _, reading, _ = LabService(FakeAIProvider(response=decision())).chat(session, f"guard-{state}-{recommended}-{spread}", "sí", f"guard-{state}-{recommended}-{spread}")
        assert result.action.value == "none" and reading is None and not session.scalars(select(TarotReading)).all()


def test_interpretation_failure_keeps_reading_and_safe_state(client):
    with client.app.state.SessionLocal() as session:
        ready(session, key="failed")
        _, conversation, _, _, reading, output = LabService(FakeAIProvider(responses=[decision(), ""])).chat(session, "failed", "sí", "failed-confirm")
        assert reading and output is None and conversation.state == "READY_FOR_READING"
        assert len(session.scalars(select(TarotReadingCard).where(TarotReadingCard.reading_id == reading.id)).all()) == 3
        assert not session.scalars(select(TarotInterpretation).where(TarotInterpretation.reading_id == reading.id)).all()


def test_follow_up_cannot_create_another_reading(client):
    with client.app.state.SessionLocal() as session:
        ready(session, key="follow")
        service = LabService(FakeAIProvider(responses=[decision(), interpretation(), decision()]))
        service.chat(session, "follow", "sí", "follow-1")
        _, conversation, result, _, reading, _ = service.chat(session, "follow", "sí", "follow-2")
        assert conversation.state == "READING_ACTIVE" and result.action.value == "none" and reading is None
        assert len(session.scalars(select(TarotReading)).all()) == 1
