from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.models.ai import AICall, UserMemory
from app.models.conversation import Conversation
from app.models.message import Message
from app.models.tarot_reading import TarotInterpretation, TarotReading, TarotReadingCard
from app.models.user import User


PAGE_SIZE = 25


def anonymize(value: str) -> str:
    if value.startswith("lab:"):
        return f"lab:{value[4:10]}"
    digits = "".join(char for char in value if char.isdigit())
    return f"…{digits[-4:]}" if digits else f"user-{abs(hash(value)) % 10_000:04d}"


def channel(jid: str) -> str:
    return "lab" if jid.startswith("lab:") else "WhatsApp"


def _today() -> datetime:
    return datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)


def summary(session: Session) -> dict:
    today = _today()
    def count(model, criterion=None):
        query = select(func.count()).select_from(model)
        return session.scalar(query.where(criterion) if criterion is not None else query) or 0
    today_cards = {
        "users": session.scalar(select(func.count(func.distinct(Conversation.user_id))).where(Conversation.updated_at >= today)) or 0,
        "conversations": count(Conversation, Conversation.updated_at >= today),
        "incoming": count(Message, (Message.created_at >= today) & (Message.direction == "incoming")),
        "assistant": count(Message, (Message.created_at >= today) & (Message.direction == "outgoing")),
        "readings": count(TarotReading, TarotReading.created_at >= today),
        "calls": count(AICall, AICall.created_at >= today),
        "errors": count(AICall, (AICall.created_at >= today) & AICall.success.is_(False)),
        "input_tokens": session.scalar(select(func.coalesce(func.sum(AICall.input_tokens), 0)).where(AICall.created_at >= today)) or 0,
        "output_tokens": session.scalar(select(func.coalesce(func.sum(AICall.output_tokens), 0)).where(AICall.created_at >= today)) or 0,
    }
    totals = {"users": count(User), "conversations": count(Conversation), "messages": count(Message), "readings": count(TarotReading)}
    return {"today": today_cards, "totals": totals}


def conversations(session: Session, *, page: int = 1, filters: dict | None = None) -> tuple[list[dict], int]:
    filters = filters or {}
    query = select(Conversation, User).join(User).order_by(Conversation.updated_at.desc())
    text = (filters.get("q") or "").strip()
    if text:
        query = query.where((User.whatsapp_jid.contains(text)) | (func.cast(Conversation.id, __import__("sqlalchemy").String).contains(text)))
    for key, column in (("state", Conversation.state), ("intent", Conversation.last_intent)):
        if filters.get(key): query = query.where(column == filters[key])
    if filters.get("channel") == "lab": query = query.where(User.whatsapp_jid.startswith("lab:"))
    if filters.get("channel") == "whatsapp": query = query.where(~User.whatsapp_jid.startswith("lab:"))
    if filters.get("readings"): query = query.where(select(TarotReading.id).where(TarotReading.conversation_id == Conversation.id).exists())
    if filters.get("errors"): query = query.where(select(AICall.id).where(AICall.conversation_id == Conversation.id, AICall.success.is_(False)).exists())
    if filters.get("provider"): query = query.where(select(AICall.id).where(AICall.conversation_id == Conversation.id, AICall.provider == filters["provider"]).exists())
    total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = session.execute(query.offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE)).all()
    result = []
    for conversation, user in rows:
        call = session.scalar(select(AICall).where(AICall.conversation_id == conversation.id).order_by(AICall.id.desc()))
        result.append({"conversation": conversation, "user": anonymize(user.whatsapp_jid), "channel": channel(user.whatsapp_jid), "messages": session.scalar(select(func.count()).select_from(Message).where(Message.conversation_id == conversation.id)) or 0, "readings": session.scalar(select(func.count()).select_from(TarotReading).where(TarotReading.conversation_id == conversation.id)) or 0, "call": call})
    return result, total


def conversation_detail(session: Session, conversation_id: int) -> dict | None:
    row = session.execute(select(Conversation, User).join(User).where(Conversation.id == conversation_id)).first()
    if not row: return None
    conversation, user = row
    messages = session.scalars(select(Message).where(Message.conversation_id == conversation_id).order_by(Message.created_at, Message.id)).all()
    readings = session.scalars(select(TarotReading).where(TarotReading.conversation_id == conversation_id).order_by(TarotReading.created_at)).all()
    cards = defaultdict(list)
    for card in session.scalars(select(TarotReadingCard).where(TarotReadingCard.reading_id.in_([reading.id for reading in readings] or [-1])).order_by(TarotReadingCard.position_index)):
        cards[card.reading_id].append({"position": card.position_label, "name": json.loads(card.card_snapshot)["name_es"], "orientation": "invertida" if card.orientation == "reversed" else "derecha"})
    interpretations = {item.reading_id: item for item in session.scalars(select(TarotInterpretation).where(TarotInterpretation.reading_id.in_([reading.id for reading in readings] or [-1]))) }
    calls = session.scalars(select(AICall).where(AICall.conversation_id == conversation_id).order_by(AICall.created_at.desc())).all()
    memory = session.scalar(select(UserMemory).where(UserMemory.user_id == user.id))
    return {"conversation": conversation, "user": anonymize(user.whatsapp_jid), "channel": channel(user.whatsapp_jid), "messages": messages, "readings": readings, "cards": cards, "interpretations": interpretations, "calls": calls, "memory": memory}


def errors(session: Session, *, page: int = 1, filters: dict | None = None) -> tuple[list[tuple], int]:
    filters = filters or {}; query = select(AICall, Conversation, User).outerjoin(Conversation, AICall.conversation_id == Conversation.id).outerjoin(User, AICall.user_id == User.id).where(AICall.success.is_(False)).order_by(AICall.created_at.desc())
    for key, column in (("provider", AICall.provider), ("error_type", AICall.error_type), ("purpose", AICall.purpose)):
        if filters.get(key): query = query.where(column == filters[key])
    total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    return session.execute(query.offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE)).all(), total


def readings(session: Session, *, page: int = 1) -> tuple[list[tuple], int]:
    query = select(TarotReading, User, Conversation).join(User, TarotReading.user_id == User.id).join(Conversation, TarotReading.conversation_id == Conversation.id).order_by(TarotReading.created_at.desc())
    total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    return session.execute(query.offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE)).all(), total
