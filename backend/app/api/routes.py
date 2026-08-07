from fastapi import APIRouter, HTTPException, Request
from sqlalchemy.orm import Session

from app.schemas.whatsapp import InboundWhatsAppMessage, InboundWhatsAppResponse
from app.services.inbound import process_inbound_message
from app.schemas.tarot import DrawnCardResponse, SpreadSummary, TarotCardSummary, TestDrawRequest, TestDrawResponse
from app.tarot.engine import TarotEngine
from app.tarot.catalog import get_catalog
from app.tarot.spreads import SPREADS


router = APIRouter()


def get_session(request: Request) -> Session:
    return request.app.state.SessionLocal()


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/internal/whatsapp/inbound", response_model=InboundWhatsAppResponse)
def whatsapp_inbound(inbound: InboundWhatsAppMessage, request: Request) -> InboundWhatsAppResponse:
    session = get_session(request)
    try:
        return process_inbound_message(session, inbound)
    finally:
        session.close()


@router.get("/internal/tarot/cards", response_model=list[TarotCardSummary])
def tarot_cards() -> list[TarotCardSummary]:
    return [TarotCardSummary(**{
        "id": card.id, "name_es": card.name_es, "name_en": card.name_en, "card_type": card.card_type,
        "number": card.number, "suit": card.suit, "rank": card.rank, "image_path": card.image_path,
    }) for card in get_catalog().cards]


@router.get("/internal/tarot/spreads", response_model=list[SpreadSummary])
def tarot_spreads() -> list[SpreadSummary]:
    return [SpreadSummary(
        key=spread.key, label=spread.label,
        positions=[{"key": position.key, "label": position.label} for position in spread.positions],
    ) for spread in SPREADS.values()]


@router.post("/internal/tarot/test-draw", response_model=TestDrawResponse)
def tarot_test_draw(request: TestDrawRequest) -> TestDrawResponse:
    try:
        result = TarotEngine().draw(
            request.spread_type, seed=request.seed, reversed_enabled=request.reversed_enabled,
            reversed_probability=request.reversed_probability,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return TestDrawResponse(
        spread=result.spread_type, spread_label=result.spread_label, audit_metadata=result.audit_metadata,
        cards=[DrawnCardResponse(
            position=drawn.position_key, position_label=drawn.position_label, card_id=drawn.card.id,
            name=drawn.card.name_es, orientation=drawn.orientation, image_path=drawn.card.image_path,
        ) for drawn in result.cards],
    )
