import json

import pytest
from sqlalchemy import select

from app.ai.fake_provider import FakeAIProvider
from app.conversation.schemas import ConversationState
from app.models.ai import UserMemory
from app.models.conversation import Conversation
from app.models.message import Message
from app.models.tarot_reading import TarotReading
from app.models.user import User
from app.services.conversation import ConversationService


def decision(*, reading_recommended=False, suggested_spread=None):
    return json.dumps(
        {
            "reply": "Respuesta de prueba.",
            "intent": "ask_tarot",
            "next_state": "CHATTING",
            "reading_recommended": reading_recommended,
            "suggested_spread": suggested_spread,
            "memory_candidates": [],
        }
    )


def conversation(session, jid="user@test"):
    user = User(whatsapp_jid=jid)
    session.add(user)
    session.flush()
    current = Conversation(user_id=user.id, state=ConversationState.CHATTING.value)
    session.add(current)
    session.commit()
    return user, current


@pytest.mark.parametrize(
    ("recommended", "suggested", "expected_recommended", "expected_suggested"),
    [
        (False, None, False, None),
        (False, "one_card", False, None),
        (False, "not_a_spread", False, None),
        (True, "one_card", True, "one_card"),
        (True, "general_three", True, "general_three"),
        (True, "relationship_three", True, "relationship_three"),
        (True, "not_a_spread", False, None),
        (True, None, False, None),
        (True, "", False, None),
        (True, " General_Three ", False, None),
    ],
)
def test_suggested_spread_is_normalized_without_creating_readings(
    client, recommended, suggested, expected_recommended, expected_suggested
):
    with client.app.state.SessionLocal() as session:
        user, current = conversation(session)
        result, _ = ConversationService(
            FakeAIProvider(decision(reading_recommended=recommended, suggested_spread=suggested))
        ).chat(session, user, current, "Quiero consultar algo.")

        assert result.reading_recommended is expected_recommended
        assert result.suggested_spread == expected_suggested
        assert session.scalars(select(TarotReading)).all() == []


@pytest.mark.parametrize(
    ("recent_messages", "expected_history"),
    [
        (0, []),
        (1, [("assistant", "a3")]),
        (3, [("assistant", "a1"), ("user", "u2"), ("assistant", "a3")]),
    ],
)
def test_recent_history_is_bounded_ordered_and_separate_from_memory(
    client, recent_messages, expected_history
):
    with client.app.state.SessionLocal() as session:
        user, current = conversation(session)
        other = Conversation(user_id=user.id, state=ConversationState.CHATTING.value)
        session.add_all(
            [
                other,
                UserMemory(user_id=user.id, summary="Contexto resumido", version=1),
                Message(conversation_id=current.id, direction="outgoing", message_type="text", content="a1"),
                Message(conversation_id=current.id, direction="incoming", message_type="text", content="u2"),
                Message(conversation_id=current.id, direction="outgoing", message_type="text", content="a3"),
                Message(conversation_id=current.id, direction="incoming", message_type="internal", content="tecnico"),
            ]
        )
        session.flush()
        session.add(Message(conversation_id=other.id, direction="incoming", message_type="text", content="otra charla"))
        session.commit()

        fake = FakeAIProvider(decision())
        ConversationService(fake, recent_messages=recent_messages).chat(session, user, current, "actual")

        messages, purpose, _ = fake.requests[0]
        assert purpose == "conversation"
        assert messages[1].role == "system"
        assert messages[1].content == "Memoria: Contexto resumido"
        delivered = [(message.role, message.content) for message in messages[2:]]
        assert delivered == [*expected_history, ("user", "actual")]
        assert sum(content == "actual" for _, content in delivered) == 1
        assert all(content not in {"tecnico", "otra charla"} for _, content in delivered)
