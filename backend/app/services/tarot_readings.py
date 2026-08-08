from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.conversation import Conversation
from app.models.user import User
from app.repositories.tarot_reading_repository import create_reading as persist_reading
from app.tarot.engine import TarotEngine
from app.tarot.models import DrawResult


def create_reading(
    session: Session,
    *,
    user_id: int,
    conversation_id: int,
    spread_type: str,
    question: str | None = None,
    seed: int | str | None = None,
    reversed_enabled: bool = True,
    reversed_probability: float = 0.5,
    trigger_message_id: str | None = None,
) -> tuple[int, DrawResult]:
    user = session.get(User, user_id)
    conversation = session.get(Conversation, conversation_id)
    if user is None or conversation is None or conversation.user_id != user.id:
        raise ValueError("El usuario y la conversación deben existir y estar vinculados")
    result = TarotEngine().draw(
        spread_type, seed=seed, reversed_enabled=reversed_enabled, reversed_probability=reversed_probability
    )
    reading = persist_reading(
        session, user_id=user.id, conversation_id=conversation.id, question=question, result=result,
        trigger_message_id=trigger_message_id,
    )
    session.commit()
    return reading.id, result
