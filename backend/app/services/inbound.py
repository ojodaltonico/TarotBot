"""WhatsApp-specific orchestration over the shared conversation services."""

import json
import logging
from time import perf_counter

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.ai.provider import AIProvider
from app.conversation.schemas import ConversationAction
from app.models.tarot_reading import TarotReading, TarotReadingCard
from app.models.user import utc_now
from app.repositories.conversation_repository import get_or_create_active_conversation
from app.repositories.message_repository import add_message, get_by_whatsapp_message_id
from app.repositories.user_repository import get_or_create_user
from app.schemas.whatsapp import InboundWhatsAppMessage, InboundWhatsAppResponse, OutboundMessage
from app.services.conversation import ConversationService
from app.services.tarot_interpretation import TarotInterpretationService
from app.services.tarot_readings import create_reading
from app.tarot.spreads import SPREADS


LOGGER = logging.getLogger(__name__)


def _safe_message_id(message_id: str) -> str:
    return message_id[:8]


def _provider_name(provider: AIProvider) -> str:
    return type(provider).__name__.removesuffix("Provider").lower()


READING_FALLBACK = "Las cartas ya quedaron sobre la mesa, pero se me cortó la interpretación. Probemos seguir con esta lectura en un momento."


def _format_cards(reading: TarotReading, cards: list[TarotReadingCard]) -> str:
    lines = [f"Tirada: {reading.spread_type.replace('_', ' ')}"]
    for card in cards:
        snapshot = json.loads(card.card_snapshot)
        orientation = "invertida" if card.orientation == "reversed" else "derecha"
        lines.append(f"{card.position_label}: {snapshot['name_es']} — {orientation}")
    return "\n".join(lines)


def _persist_outgoing(session: Session, conversation_id: int, text: str) -> OutboundMessage:
    add_message(
        session,
        conversation_id=conversation_id,
        whatsapp_message_id=None,
        direction="outgoing",
        message_type="text",
        content=text,
    )
    return OutboundMessage(type="text", text=text)


def _automatic_reading(
    session: Session,
    provider: AIProvider,
    user,
    conversation,
    message_id: str,
    store_debug: bool,
) -> list[OutboundMessage]:
    if (
        conversation.state != "READY_FOR_READING"
        or not conversation.reading_recommended
        or conversation.suggested_spread not in SPREADS
    ):
        return []

    existing = session.scalar(select(TarotReading).where(TarotReading.trigger_message_id == message_id))
    if existing is not None:
        return []

    reading_id, _ = create_reading(
        session,
        user_id=user.id,
        conversation_id=conversation.id,
        spread_type=conversation.suggested_spread,
        trigger_message_id=message_id,
    )
    reading = session.get(TarotReading, reading_id)
    interpretation = TarotInterpretationService(provider, store_debug=store_debug).interpret_reading(
        session, reading_id, user.id, conversation.id
    )
    if interpretation is None:
        fallback = _persist_outgoing(session, conversation.id, READING_FALLBACK)
        session.commit()
        return [fallback]

    cards = session.scalars(
        select(TarotReadingCard)
        .where(TarotReadingCard.reading_id == reading_id)
        .order_by(TarotReadingCard.position_index)
    ).all()
    conversation.state = "READING_ACTIVE"
    conversation.reading_recommended = False
    conversation.suggested_spread = None
    conversation.last_action = "none"
    messages = [
        _persist_outgoing(session, conversation.id, _format_cards(reading, cards)),
        _persist_outgoing(session, conversation.id, interpretation.interpretation_text),
    ]
    session.commit()
    return messages


def process_inbound_message(
    session: Session,
    inbound: InboundWhatsAppMessage,
    provider: AIProvider,
    *,
    store_debug: bool = False,
) -> InboundWhatsAppResponse:
    """Persist physical bubbles once and send their combined logical turn to the conversation service."""
    physical = sorted(inbound.messages or [inbound], key=lambda item: item.timestamp)
    new_messages, seen_ids = [], set()
    for item in physical:
        if item.message_id in seen_ids or get_by_whatsapp_message_id(session, item.message_id):
            continue
        seen_ids.add(item.message_id)
        if item.text.strip():
            new_messages.append(item)
    if not new_messages:
        duplicate = bool(physical) and all(get_by_whatsapp_message_id(session, item.message_id) for item in physical)
        LOGGER.info("whatsapp_inbound id=%s result=%s duplicate=%s", _safe_message_id(inbound.message_id), "duplicate" if duplicate else "ignored", str(duplicate).lower())
        return InboundWhatsAppResponse(messages=[], duplicate=duplicate)

    logical_text = "\n".join(item.text.strip() for item in new_messages)
    trigger_message_id = new_messages[-1].message_id

    started = perf_counter()
    user = get_or_create_user(session, inbound.sender, inbound.timestamp)
    conversation = get_or_create_active_conversation(session, user.id)
    conversation.updated_at = utc_now()
    try:
        decision, response = ConversationService(provider, store_debug=store_debug).chat(
            session,
            user,
            conversation,
            logical_text,
            message_id=trigger_message_id,
            created_at=new_messages[-1].timestamp,
            physical_messages=[{"message_id":item.message_id,"timestamp":item.timestamp,"message_type":item.message_type,"text":item.text} for item in new_messages],
        )
        if decision.action is ConversationAction.confirm_reading:
            messages = _automatic_reading(session, provider, user, conversation, trigger_message_id, store_debug)
            if messages:
                LOGGER.info("whatsapp_inbound id=%s provider=%s latency_ms=%d result=success duplicate=false", _safe_message_id(inbound.message_id), _provider_name(provider), round((perf_counter() - started) * 1000))
                return InboundWhatsAppResponse(messages=messages)
        result = "success" if response is not None else "fallback"
        LOGGER.info("whatsapp_inbound id=%s provider=%s latency_ms=%d result=%s duplicate=false", _safe_message_id(inbound.message_id), _provider_name(provider), round((perf_counter() - started) * 1000), result)
        return InboundWhatsAppResponse(messages=[OutboundMessage(type="text", text=decision.reply)])
    except IntegrityError:
        session.rollback()
        LOGGER.info("whatsapp_inbound id=%s result=duplicate duplicate=true", _safe_message_id(inbound.message_id))
        return InboundWhatsAppResponse(messages=[], duplicate=True)
