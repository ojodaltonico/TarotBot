import json

from sqlalchemy.orm import Session

from app.models.tarot_reading import TarotReading, TarotReadingCard
from app.tarot.models import DrawResult, TarotCard


def card_snapshot(card: TarotCard, deck_version: str) -> str:
    return json.dumps({
        "deck_version": deck_version, "name_es": card.name_es, "name_en": card.name_en,
        "image_path": card.image_path, "upright_meaning": card.upright_meaning,
        "reversed_meaning": card.reversed_meaning, "upright_keywords": card.upright_keywords,
        "reversed_keywords": card.reversed_keywords,
    }, ensure_ascii=False, sort_keys=True)


def create_reading(
    session: Session, *, user_id: int, conversation_id: int, question: str | None, result: DrawResult
) -> TarotReading:
    reading = TarotReading(
        user_id=user_id, conversation_id=conversation_id, spread_type=result.spread_type,
        question=question, audit_metadata=json.dumps(result.audit_metadata, ensure_ascii=False, sort_keys=True),
    )
    session.add(reading)
    session.flush()
    deck_version = str(result.audit_metadata["deck_version"])
    for drawn in result.cards:
        session.add(TarotReadingCard(
            reading_id=reading.id, position_index=drawn.position_index, position_key=drawn.position_key,
            position_label=drawn.position_label, card_id=drawn.card.id, orientation=drawn.orientation,
            card_snapshot=card_snapshot(drawn.card, deck_version),
        ))
    return reading
