from fastapi import APIRouter, Request
from sqlalchemy.orm import Session

from app.schemas.whatsapp import InboundWhatsAppMessage, InboundWhatsAppResponse
from app.services.inbound import process_inbound_message


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
