from fastapi import APIRouter, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.schemas.whatsapp import AudioTranscriptionRequest, AudioTranscriptionResponse, InboundWhatsAppMessage, InboundWhatsAppResponse
from app.ai.audio_transcription import FakeAudioTranscriptionProvider
from app.ai.groq_audio_provider import GroqAudioTranscriptionProvider
from app.services.audio_transcription import transcribe_base64
from app.services.inbound import process_inbound_message
from app.schemas.tarot import DrawnCardResponse, SpreadSummary, TarotCardSummary, TestDrawRequest, TestDrawResponse
from app.tarot.engine import TarotEngine
from app.tarot.catalog import get_catalog
from app.tarot.spreads import SPREADS
from app.ai.fake_provider import FakeAIProvider
from app.ai.gemini_provider import GeminiProvider
from app.ai.groq_provider import GroqProvider
from app.core.config import get_settings
from app.schemas.lab import LabChatRequest, LabReadingRequest, LabChatResponse, LabUserStateResponse, LabReadingResponse, LabMemoryRefreshResponse, LabResetResponse
from app.services.lab import LabService
from app.models.ai import UserMemory


router = APIRouter()


def get_session(request: Request) -> Session:
    return request.app.state.SessionLocal()

def lab_service():
    return LabService(ai_provider_from_settings())


def ai_provider_from_settings():
    settings=get_settings()
    if settings.ai_provider=="fake": return FakeAIProvider(mode="demo")
    if settings.ai_provider=="gemini": return GeminiProvider(api_key=settings.gemini_api_key,model=settings.ai_chat_model,timeout_seconds=settings.ai_timeout_seconds,enabled=settings.ai_enabled,trust_env_proxy=settings.ai_trust_env_proxy)
    if settings.ai_provider=="groq": return GroqProvider(api_key=settings.groq_api_key,model=settings.ai_chat_model,timeout_seconds=settings.ai_timeout_seconds,enabled=settings.ai_enabled)
    raise HTTPException(status_code=422,detail="Unsupported AI_PROVIDER")

def audio_provider_from_settings():
    settings = get_settings()
    if settings.audio_transcription_provider == "fake": return FakeAudioTranscriptionProvider()
    if settings.audio_transcription_provider == "groq": return GroqAudioTranscriptionProvider(api_key=settings.groq_api_key, model=settings.audio_transcription_model, timeout_seconds=settings.ai_timeout_seconds, enabled=settings.audio_transcription_enabled)
    raise HTTPException(status_code=422, detail="Unsupported AUDIO_TRANSCRIPTION_PROVIDER")


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/internal/whatsapp/inbound", response_model=InboundWhatsAppResponse)
def whatsapp_inbound(inbound: InboundWhatsAppMessage, request: Request) -> InboundWhatsAppResponse:
    session = get_session(request)
    try:
        settings = get_settings()
        return process_inbound_message(session, inbound, ai_provider_from_settings(), store_debug=settings.ai_store_debug_payloads)
    finally:
        session.close()

@router.post("/internal/whatsapp/transcribe", response_model=AudioTranscriptionResponse)
def whatsapp_transcribe(body: AudioTranscriptionRequest) -> AudioTranscriptionResponse:
    settings = get_settings()
    result = transcribe_base64(audio_provider_from_settings(), body.audio_base64, body.mimetype, body.duration_seconds, max_bytes=settings.audio_max_bytes, max_seconds=settings.audio_max_seconds)
    return AudioTranscriptionResponse(**result.__dict__)


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

@router.post("/internal/lab/chat",response_model=LabChatResponse)
def lab_chat(body:LabChatRequest,request:Request):
 s=get_session(request)
 try:
  u,c,d,r,reading,interpretation=lab_service().chat(s,body.user_key,body.message,body.message_id)
  auto_reading=None if reading is None else {"reading_id":reading.id,"spread":reading.spread_type,"cards":[{"position":x.position_label,"name":__import__('json').loads(x.card_snapshot)["name_es"],"orientation":x.orientation} for x in s.scalars(select(__import__('app.models.tarot_reading',fromlist=['TarotReadingCard']).TarotReadingCard).where(__import__('app.models.tarot_reading',fromlist=['TarotReadingCard']).TarotReadingCard.reading_id==reading.id).order_by(__import__('app.models.tarot_reading',fromlist=['TarotReadingCard']).TarotReadingCard.position_index)).all()],"interpretation":interpretation.interpretation_text if interpretation else None,"summary":interpretation.interpretation_summary if interpretation else None,"state":c.state,"interpretation_error":None}
  return {"reply":interpretation.interpretation_text if interpretation else d.reply,"state":c.state,"intent":d.intent.value,"reading_recommended":c.reading_recommended,"suggested_spread":c.suggested_spread,"usage":None if r is None else {"provider":r.provider,"model":r.model,"input_tokens":r.input_tokens,"output_tokens":r.output_tokens,"estimated_cost_usd":None},"reading":auto_reading}
 finally:s.close()
@router.get("/internal/lab/users/{user_key}",response_model=LabUserStateResponse)
def lab_status(user_key:str,request:Request):
 s=get_session(request)
 try:
  if not s.scalar(select(__import__('app.models.user',fromlist=['User']).User).where(__import__('app.models.user',fromlist=['User']).User.whatsapp_jid==f"lab:{user_key}")): raise HTTPException(status_code=404,detail="Lab user not found")
  u,c,msgs,read,interp,metrics=lab_service().status(s,user_key)
  memory=s.scalar(select(UserMemory).where(UserMemory.user_id==u.id));cards=[] if not read else [{"position":x.position_label,"card_id":x.card_id,"orientation":x.orientation} for x in s.scalars(select(__import__('app.models.tarot_reading',fromlist=['TarotReadingCard']).TarotReadingCard).where(__import__('app.models.tarot_reading',fromlist=['TarotReadingCard']).TarotReadingCard.reading_id==read.id)).all()]
  return {"user_key":user_key,"user_id":u.id,"conversation_id":c.id,"state":c.state,"last_intent":c.last_intent,"reading_recommended":c.reading_recommended,"suggested_spread":c.suggested_spread,"memory":memory.summary if memory else None,"memory_version":memory.version if memory else None,"message_count":len(msgs),"messages":[{"direction":m.direction,"content":m.content} for m in reversed(msgs)],"last_reading_id":read.id if read else None,"last_reading":None if not read else {"reading_id":read.id,"spread":read.spread_type,"created_at":read.created_at.isoformat(),"cards":cards},"last_interpretation":interp.interpretation_summary if interp else None,"metrics":metrics}
 finally:s.close()
@router.post("/internal/lab/users/{user_key}/reading",response_model=LabReadingResponse)
def lab_reading(user_key:str,body:LabReadingRequest,request:Request):
 s=get_session(request)
 try:
  reading,interpretation,c=lab_service().reading(s,user_key,body.spread_type,body.question)
  cards=s.scalars(select(__import__('app.models.tarot_reading',fromlist=['TarotReadingCard']).TarotReadingCard).where(__import__('app.models.tarot_reading',fromlist=['TarotReadingCard']).TarotReadingCard.reading_id==reading.id).order_by(__import__('app.models.tarot_reading',fromlist=['TarotReadingCard']).TarotReadingCard.position_index)).all()
  failed=s.scalar(select(__import__('app.models.ai',fromlist=['AICall']).AICall).where(__import__('app.models.ai',fromlist=['AICall']).AICall.reading_id==reading.id,__import__('app.models.ai',fromlist=['AICall']).AICall.success.is_(False)).order_by(__import__('app.models.ai',fromlist=['AICall']).AICall.id.desc()))
  diagnostic=None if interpretation or not failed else {"category":failed.error_type or "provider_error","provider":failed.provider,"model":failed.model,"http_status":None,"google_status":None,"request_id":None}
  return {"reading_id":reading.id,"spread":reading.spread_type,"cards":[{"position":x.position_label,"name":__import__('json').loads(x.card_snapshot)["name_es"],"orientation":x.orientation} for x in cards],"interpretation":interpretation.interpretation_text if interpretation else None,"summary":interpretation.interpretation_summary if interpretation else None,"state":c.state,"interpretation_error":diagnostic}
 except ValueError as e:raise HTTPException(status_code=422,detail=str(e))
 finally:s.close()
@router.post("/internal/lab/users/{user_key}/memory/refresh",response_model=LabMemoryRefreshResponse)
def lab_memory(user_key:str,request:Request):
 s=get_session(request)
 try:
  return lab_service().refresh_memory(s,user_key)
 except ValueError as e: raise HTTPException(status_code=404,detail=str(e))
 finally:s.close()
@router.post("/internal/lab/users/{user_key}/reset",response_model=LabResetResponse)
def lab_reset(user_key:str,request:Request):
 s=get_session(request)
 try:return {"reset":lab_service().reset(s,user_key),"user_key":user_key}
 finally:s.close()
