from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.templating import Jinja2Templates

from app.admin import service
from app.tarot.rendering import TarotRenderingError, render_reading


router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
HEADERS = {"Cache-Control": "no-store, max-age=0", "X-Robots-Tag": "noindex, nofollow"}


def ensure_admin_enabled(request: Request) -> None:
    if not request.app.state.settings.admin_enabled:
        raise HTTPException(status_code=404, detail="Not found")


def render(request: Request, name: str, context: dict):
    return templates.TemplateResponse(request, name, {**context, "settings": request.app.state.settings}, headers=HEADERS)


def session_for(request: Request):
    return request.app.state.SessionLocal()


@router.get("/admin")
def home(request: Request):
    ensure_admin_enabled(request)
    session = session_for(request)
    try:
        rows, _ = service.conversations(session, page=1)
        settings = request.app.state.settings
        provider_state = "deshabilitada" if not settings.ai_enabled else ("configurado" if (settings.ai_provider != "groq" or bool(settings.groq_api_key)) and (settings.ai_provider != "gemini" or bool(settings.gemini_api_key)) else "sin configurar")
        return render(request, "home.html", {"summary": service.summary(session), "recent": rows[:8], "provider_state": provider_state})
    finally: session.close()


@router.get("/admin/conversations")
def conversation_list(request: Request, page: int = 1, q: str = "", state: str = "", intent: str = "", channel: str = "", readings: bool = False, errors: bool = False, provider: str = ""):
    ensure_admin_enabled(request)
    session = session_for(request)
    try:
        filters = {"q": q, "state": state, "intent": intent, "channel": channel, "readings": readings, "errors": errors, "provider": provider}
        rows, total = service.conversations(session, page=max(page, 1), filters=filters)
        return render(request, "conversations.html", {"rows": rows, "page": max(page, 1), "total": total, "filters": filters, "page_size": service.PAGE_SIZE})
    finally: session.close()


@router.get("/admin/conversations/{conversation_id}")
def conversation_page(conversation_id: int, request: Request):
    ensure_admin_enabled(request)
    session = session_for(request)
    try:
        detail = service.conversation_detail(session, conversation_id)
        if detail is None: raise HTTPException(status_code=404, detail="Conversation not found")
        calls = detail["calls"]
        metrics = {"calls": len(calls), "success": sum(call.success for call in calls), "failed": sum(not call.success for call in calls), "input": sum(call.input_tokens for call in calls), "output": sum(call.output_tokens for call in calls), "cached": sum(call.cached_input_tokens or 0 for call in calls), "latency": round(sum(call.latency_ms for call in calls) / len(calls)) if calls else 0}
        return render(request, "conversation_detail.html", {**detail, "metrics": metrics})
    finally: session.close()


@router.get("/admin/readings")
def reading_list(request: Request, page: int = 1):
    ensure_admin_enabled(request)
    session = session_for(request)
    try:
        rows, total = service.readings(session, page=max(page, 1))
        return render(request, "readings.html", {"rows": rows, "page": max(page, 1), "total": total, "page_size": service.PAGE_SIZE, "anonymize": service.anonymize})
    finally: session.close()


@router.get("/admin/readings/{reading_id}/image")
def reading_image(reading_id: int, request: Request):
    ensure_admin_enabled(request)
    session = session_for(request)
    try:
        rendered = render_reading(session, reading_id)
        return FileResponse(rendered.path, media_type="image/jpeg", headers=HEADERS)
    except TarotRenderingError as error:
        raise HTTPException(status_code=404, detail="Reading image not found") from error
    finally: session.close()


@router.get("/admin/errors")
def error_list(request: Request, page: int = 1, provider: str = "", error_type: str = "", purpose: str = ""):
    ensure_admin_enabled(request)
    session = session_for(request)
    try:
        filters = {"provider": provider, "error_type": error_type, "purpose": purpose}
        rows, total = service.errors(session, page=max(page, 1), filters=filters)
        return render(request, "errors.html", {"rows": rows, "page": max(page, 1), "total": total, "filters": filters, "page_size": service.PAGE_SIZE, "anonymize": service.anonymize})
    finally: session.close()
