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
    audio_mimetype: str | None = None,
    audio_duration_seconds: int | None = None,
    audio_ptt: bool | None = None,
    transcription_error: str | None = None,
) -> Message:
    message = Message(
        conversation_id=conversation_id,
        whatsapp_message_id=whatsapp_message_id,
        direction=direction,
        message_type=message_type,
        content=content,
        created_at=created_at,
        audio_mimetype=audio_mimetype,
        audio_duration_seconds=audio_duration_seconds,
        audio_ptt=audio_ptt,
        transcription_error=transcription_error,
    )
    session.add(message)
    return message
