from __future__ import annotations

import base64
import binascii
import tempfile
from pathlib import Path

from app.ai.audio_transcription import AudioTranscriptionProvider, TranscriptionResult

SUPPORTED_AUDIO = {"audio/ogg", "audio/opus", "audio/mpeg", "audio/mp4", "audio/m4a", "audio/wav", "audio/webm"}
EXTENSIONS = {"audio/ogg": ".ogg", "audio/opus": ".ogg", "audio/mpeg": ".mp3", "audio/mp4": ".m4a", "audio/m4a": ".m4a", "audio/wav": ".wav", "audio/webm": ".webm"}


def transcribe_base64(provider: AudioTranscriptionProvider, encoded: str, mimetype: str | None, duration_seconds: int | None, *, max_bytes: int, max_seconds: int) -> TranscriptionResult:
    normalized_mimetype = (mimetype or "").split(";", 1)[0].strip().lower()
    if normalized_mimetype not in SUPPORTED_AUDIO: return TranscriptionResult(None, "unknown", "unknown", error_type="unsupported_audio")
    if duration_seconds is not None and duration_seconds > max_seconds: return TranscriptionResult(None, "unknown", "unknown", error_type="audio_too_long")
    if len(encoded) > (max_bytes * 4 // 3) + 8: return TranscriptionResult(None, "unknown", "unknown", error_type="audio_too_large")
    try: data = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError): return TranscriptionResult(None, "unknown", "unknown", error_type="download_error")
    if len(data) > max_bytes: return TranscriptionResult(None, "unknown", "unknown", error_type="audio_too_large")
    temp_dir = Path("data/temp/audio"); temp_dir.mkdir(parents=True, exist_ok=True)
    path = None
    try:
        with tempfile.NamedTemporaryFile(dir=temp_dir, suffix=EXTENSIONS[normalized_mimetype], delete=False) as handle:
            handle.write(data); path = handle.name
        result = provider.transcribe(path, normalized_mimetype)
        return result if result.text and result.text.strip() else TranscriptionResult(None, result.provider, result.model, result.latency_ms, result.language, result.request_id, result.error_type or "empty_transcription")
    finally:
        if path:
            Path(path).unlink(missing_ok=True)
