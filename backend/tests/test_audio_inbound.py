import base64
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from app.ai.audio_transcription import FakeAudioTranscriptionProvider
from app.ai.fake_provider import FakeAIProvider
from app.models.ai import AICall
from app.models.message import Message
from app.schemas.whatsapp import InboundWhatsAppMessage
from app.services.audio_transcription import transcribe_base64
from app.services.inbound import process_inbound_message


def inbound(message_id, text, *, sender="audio-a@s.whatsapp.net", message_type="audio", **extra):
    return InboundWhatsAppMessage(
        sender=sender, message_id=message_id, timestamp=datetime.now(timezone.utc),
        message_type=message_type, text=text, **extra,
    )


def test_audio_transcription_accepts_whatsapp_ogg_and_removes_temp_file():
    provider = FakeAudioTranscriptionProvider(["Consulta sobre trabajo."])
    result = transcribe_base64(provider, base64.b64encode(b"ogg bytes").decode(), "audio/ogg; codecs=opus", 12, max_bytes=1000, max_seconds=300)
    assert result.text == "Consulta sobre trabajo."
    assert provider.requests[0][1] == "audio/ogg"
    assert not list(Path("data/temp/audio").glob("*"))


def test_audio_limits_and_empty_transcript_do_not_call_conversation_provider():
    provider = FakeAudioTranscriptionProvider(mode="empty")
    empty = transcribe_base64(provider, base64.b64encode(b"bytes").decode(), "audio/ogg", 1, max_bytes=1000, max_seconds=300)
    too_long = transcribe_base64(provider, base64.b64encode(b"bytes").decode(), "audio/ogg", 301, max_bytes=1000, max_seconds=300)
    too_large = transcribe_base64(provider, base64.b64encode(b"x" * 100).decode(), "audio/ogg", 1, max_bytes=10, max_seconds=300)
    assert empty.error_type == "empty_transcription"
    assert too_long.error_type == "audio_too_long"
    assert too_large.error_type == "audio_too_large"


def test_audio_temp_file_is_removed_after_provider_error():
    provider = FakeAudioTranscriptionProvider(mode="error")
    result = transcribe_base64(provider, base64.b64encode(b"bytes").decode(), "audio/ogg", 1, max_bytes=1000, max_seconds=300)
    assert result.error_type == "transcription_provider_error"
    assert not list(Path("data/temp/audio").glob("*"))


def test_audio_is_one_physical_message_with_persisted_transcript_and_audit(client):
    session = client.app.state.SessionLocal()
    try:
        response = process_inbound_message(session, inbound("audio-1", "Quiero consultar por trabajo.", audio_mimetype="audio/ogg", audio_duration_seconds=18, audio_ptt=True, transcription_provider="fake", transcription_model="fake-audio", transcription_latency_ms=3), FakeAIProvider(mode="demo"))
        message = session.scalar(select(Message).where(Message.whatsapp_message_id == "audio-1"))
        call = session.scalar(select(AICall).where(AICall.purpose == "audio_transcription"))
        assert response.messages
        assert message.message_type == "audio"
        assert message.content == "Quiero consultar por trabajo."
        assert message.audio_mimetype == "audio/ogg"
        assert message.audio_ptt is True
        assert call.success is True and call.provider == "fake"
    finally:
        session.close()


def test_text_audio_text_is_one_logical_turn_in_order_and_duplicate_is_ignored(client):
    session = client.app.state.SessionLocal()
    try:
        first = inbound("audio-order-1", "Pasa que...", message_type="text")
        audio = inbound("audio-order-2", "estoy buscando trabajo hace meses", audio_mimetype="audio/ogg", transcription_provider="fake", transcription_model="fake-audio")
        last = inbound("audio-order-3", "y no sé si cambiar de rubro", message_type="text")
        payload = InboundWhatsAppMessage.model_validate({**first.model_dump(), "messages": [first.model_dump(exclude={"sender", "messages"}), audio.model_dump(exclude={"sender", "messages"}), last.model_dump(exclude={"sender", "messages"})]})
        result = process_inbound_message(session, payload, FakeAIProvider(mode="demo"))
        duplicate = process_inbound_message(session, payload, FakeAIProvider(mode="demo"))
        stored = session.scalars(select(Message).where(Message.whatsapp_message_id.in_(["audio-order-1", "audio-order-2", "audio-order-3"])).order_by(Message.id)).all()
        assert result.messages and duplicate.duplicate
        assert [message.content for message in stored] == ["Pasa que...", "estoy buscando trabajo hace meses", "y no sé si cambiar de rubro"]
        assert stored[1].message_type == "audio"
    finally:
        session.close()


def test_failed_audio_persists_natural_fallback_without_conversation_call(client):
    session = client.app.state.SessionLocal()
    try:
        result = process_inbound_message(session, inbound("audio-fail", "", transcription_error="transcription_timeout", audio_mimetype="audio/ogg"), FakeAIProvider(mode="demo"))
        messages = session.scalars(select(Message).order_by(Message.id)).all()
        audit = session.scalar(select(AICall).where(AICall.purpose == "audio_transcription"))
        assert len(result.messages) == 1
        assert "audio" in result.messages[0].text.lower()
        assert [message.message_type for message in messages] == ["audio", "text"]
        assert audit.success is False and audit.error_type == "transcription_timeout"
    finally:
        session.close()


def test_dashboard_renders_audio_transcript(client):
    session = client.app.state.SessionLocal()
    try:
        process_inbound_message(session, inbound("audio-dashboard", "Texto transcripto", transcription_provider="fake", transcription_model="fake-audio"), FakeAIProvider(mode="demo"))
        conversation_id = session.scalar(select(Message.conversation_id).where(Message.whatsapp_message_id == "audio-dashboard"))
    finally:
        session.close()
    page = client.get(f"/admin/conversations/{conversation_id}")
    assert page.status_code == 200
    assert "Audio" in page.text and "Texto transcripto" in page.text
