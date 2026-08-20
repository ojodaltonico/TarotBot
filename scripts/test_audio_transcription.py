"""Explicit, manual audio transcription check. Never called by tests."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.api.routes import audio_provider_from_settings
from app.core.config import get_settings
from app.services.audio_transcription import transcribe_base64


def main() -> int:
    if len(sys.argv) != 2:
        print("Uso: python scripts/test_audio_transcription.py <archivo-de-audio>")
        return 2
    source = Path(sys.argv[1])
    if not source.is_file():
        print("No se encontró el archivo de audio indicado.")
        return 2
    settings = get_settings()
    result = transcribe_base64(audio_provider_from_settings(), __import__("base64").b64encode(source.read_bytes()).decode(), {".ogg": "audio/ogg", ".opus": "audio/opus", ".mp3": "audio/mpeg", ".m4a": "audio/m4a", ".wav": "audio/wav", ".webm": "audio/webm"}.get(source.suffix.lower(), ""), None, max_bytes=settings.audio_max_bytes, max_seconds=settings.audio_max_seconds)
    print(f"Provider: {result.provider}\nModel: {result.model}\nSuccess: {bool(result.text)}\nLatency ms: {result.latency_ms}\nError: {result.error_type or 'none'}")
    if result.text:
        print(f"Transcript: {result.text}")
    return 0 if result.text else 1


if __name__ == "__main__":
    raise SystemExit(main())
