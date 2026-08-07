from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.repositories.conversation_repository import get_or_create_active_conversation
from app.repositories.message_repository import add_message, get_by_whatsapp_message_id
from app.repositories.user_repository import get_or_create_user
from app.schemas.whatsapp import InboundWhatsAppMessage, InboundWhatsAppResponse, OutboundMessage
from app.models.user import utc_now


TEMPORARY_REPLY = "Hola. TarotBot está conectado correctamente. 🔮"


def process_inbound_message(session: Session, inbound: InboundWhatsAppMessage) -> InboundWhatsAppResponse:
    if get_by_whatsapp_message_id(session, inbound.message_id):
        return InboundWhatsAppResponse(messages=[], duplicate=True)

    user = get_or_create_user(session, inbound.sender, inbound.timestamp)
    conversation = get_or_create_active_conversation(session, user.id)
    conversation.updated_at = utc_now()
    add_message(
        session,
        conversation_id=conversation.id,
        whatsapp_message_id=inbound.message_id,
        direction="incoming",
        message_type=inbound.message_type,
        content=inbound.text,
        created_at=inbound.timestamp,
    )
    add_message(
        session,
        conversation_id=conversation.id,
        whatsapp_message_id=None,
        direction="outgoing",
        message_type="text",
        content=TEMPORARY_REPLY,
    )
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        return InboundWhatsAppResponse(messages=[], duplicate=True)

    return InboundWhatsAppResponse(messages=[OutboundMessage(type="text", text=TEMPORARY_REPLY)])
