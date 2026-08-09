import json

import pytest
from sqlalchemy import func, select

from app.ai.fake_provider import FakeAIProvider
from app.models.conversation import Conversation
from app.models.tarot_reading import TarotReading
from app.services.lab import LabService


def decision(reply, intent="general_reading", state="READY_FOR_READING", recommended=False, spread=None, action="none"):
    return json.dumps({"reply": reply, "intent": intent, "next_state": state, "reading_recommended": recommended, "suggested_spread": spread, "action": action, "memory_candidates": []})


def reading_count(session):
    return session.scalar(select(func.count(TarotReading.id)))


def pending(session, key="pending", spread="general_three"):
    service = LabService(FakeAIProvider())
    _, conversation = service.user(session, key)
    conversation.state = "READY_FOR_READING"
    conversation.reading_recommended = True
    conversation.suggested_spread = spread
    session.commit()
    return conversation


@pytest.mark.parametrize("acceptance", ["Se", "Sí!", "sep"])
def test_short_plausible_acceptances_consume_an_existing_pending_reading(client, acceptance):
    with client.app.state.SessionLocal() as session:
        pending(session, key=f"accept-{acceptance}")
        # Simulates Groq returning action=none for a short, noisy acceptance.
        provider = FakeAIProvider(responses=[decision("¿Querés que la hagamos?", state="CHATTING"), json.dumps({"interpretation": "La lectura responde al tema laboral.", "summary": "Un paso a la vez."})])
        _, conversation, result, _, reading, output = LabService(provider).chat(session, f"accept-{acceptance}", acceptance, f"accept-{acceptance}")
        assert result.action.value == "confirm_reading"
        assert reading.spread_type == "general_three" and output is not None
        assert conversation.state == "READING_ACTIVE" and reading_count(session) == 1


def test_work_question_is_sufficient_then_se_creates_one_reading(client):
    with client.app.state.SessionLocal() as session:
        service = LabService(FakeAIProvider(mode="demo"))
        _, conversation, proposal, _, _, _ = service.chat(session, "work-direct", "si conseguire trabajo", "work-direct-1")
        assert (proposal.suggested_spread, conversation.state, conversation.reading_recommended) == ("general_three", "READY_FOR_READING", True)
        _, conversation, result, _, reading, output = service.chat(session, "work-direct", "Se", "work-direct-2")
        assert result.action.value == "confirm_reading" and reading.spread_type == "general_three" and output
        assert conversation.state == "READING_ACTIVE" and reading_count(session) == 1


def test_topic_reframe_does_not_execute_the_previous_pending_reading(client):
    with client.app.state.SessionLocal() as session:
        pending(session, key="reframe", spread="general_three")
        provider = FakeAIProvider(response=decision("Podemos mirar el amor.", intent="relationship", recommended=True, spread="relationship_three"))
        _, conversation, result, _, reading, _ = LabService(provider).chat(session, "reframe", "mejor sobre amor", "reframe-1")
        assert result.action.value == "none" and reading is None and reading_count(session) == 0
        assert conversation.state == "READY_FOR_READING" and conversation.suggested_spread == "relationship_three"


def test_se_without_pending_reading_never_creates_a_reading(client):
    with client.app.state.SessionLocal() as session:
        _, conversation, _, _, reading, _ = LabService(FakeAIProvider(mode="demo")).chat(session, "no-pending", "se", "no-pending-1")
        assert reading is None and reading_count(session) == 0
        assert conversation.state != "READING_ACTIVE"


def test_general_without_pending_starts_a_general_proposal_then_confirms(client):
    with client.app.state.SessionLocal() as session:
        service = LabService(FakeAIProvider(mode="demo"))
        _, conversation, proposal, _, reading, _ = service.chat(session, "general", "General", "general-1")
        assert reading is None and proposal.suggested_spread == "general_three"
        assert conversation.state == "READY_FOR_READING" and conversation.reading_recommended
        _, conversation, result, _, reading, output = service.chat(session, "general", "Se", "general-2")
        assert result.action.value == "confirm_reading" and reading.spread_type == "general_three" and output
        assert conversation.state == "READING_ACTIVE"


def test_invalid_confirmation_with_a_valid_structured_proposal_is_preserved(client):
    with client.app.state.SessionLocal() as session:
        provider = FakeAIProvider(response=decision("Voy con la tirada.", recommended=True, spread="general_three", action="confirm_reading"))
        _, conversation, result, _, reading, _ = LabService(provider).chat(session, "invalid-action", "General", "invalid-action-1")
        assert reading is None and result.action.value == "none"
        assert conversation.state == "READY_FOR_READING"
        assert conversation.reading_recommended and conversation.suggested_spread == "general_three"


def test_anonymized_real_sequence_creates_a_second_work_reading_after_first_reading(client):
    with client.app.state.SessionLocal() as session:
        service = LabService(FakeAIProvider(mode="demo"))
        service.chat(session, "sequence", "Quiero saber por una persona", "sequence-1")
        service.chat(session, "sequence", "Hace un tiempo no hablamos", "sequence-2")
        _, conversation, first_decision, _, first_reading, first_output = service.chat(session, "sequence", "sí", "sequence-3")
        assert first_decision.action.value == "confirm_reading" and first_reading and first_output
        assert conversation.state == "READING_ACTIVE"

        _, conversation, proposal, _, no_reading, _ = service.chat(session, "sequence", "Y sobre el trabajo", "sequence-4")
        assert no_reading is None and proposal.suggested_spread == "general_three"
        assert conversation.state == "READY_FOR_READING" and conversation.reading_recommended
        _, conversation, second_decision, _, second_reading, second_output = service.chat(session, "sequence", "Se", "sequence-5")
        assert second_decision.action.value == "confirm_reading" and second_reading and second_output
        assert second_reading.spread_type == "general_three" and conversation.state == "READING_ACTIVE"
        assert reading_count(session) == 2
