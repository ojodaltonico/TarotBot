from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.message import Message


def get_by_whatsapp_message_id(session: Session, message_id: str) -> Message | None:
    return session.scalar(select(Message).where(Message.whatsapp_message_id == message_id))


def add_message(
    session: Session,
    *,
    conversation_id: int,
    whatsapp_message_id: str | None,
    direction: str,
    message_type: str,
    content: str,
    created_at: datetime | None = None,
) -> Message:
    message = Message(
        conversation_id=conversation_id,
        whatsapp_message_id=whatsapp_message_id,
        direction=direction,
        message_type=message_type,
        content=content,
        created_at=created_at,
    )
    session.add(message)
    return message
