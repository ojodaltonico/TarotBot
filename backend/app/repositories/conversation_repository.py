from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.conversation import Conversation


def get_or_create_active_conversation(session: Session, user_id: int) -> Conversation:
    conversation = session.scalar(
        select(Conversation)
        .where(Conversation.user_id == user_id, Conversation.is_active.is_(True))
        .order_by(Conversation.id.desc())
    )
    if conversation is None:
        conversation = Conversation(user_id=user_id)
        session.add(conversation)
        session.flush()
    return conversation
