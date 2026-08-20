"""Provider-neutral speech-to-text contract. Audio files never outlive a request."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TranscriptionResult:
    text: str | None
    provider: str
    model: str
    latency_ms: int = 0
    language: str | None = None
    request_id: str | None = None
    error_type: str | None = None


class AudioTranscriptionProvider:
    def transcribe(self, file_path: str, mimetype: str | None = None) -> TranscriptionResult:
        raise NotImplementedError


class FakeAudioTranscriptionProvider(AudioTranscriptionProvider):
    def __init__(self, transcripts: list[str] | None = None, mode: str | None = None):
        self.transcripts = list(transcripts or ["Transcripción de prueba."])
        self.mode = mode
        self.requests: list[tuple[str, str | None]] = []

    def transcribe(self, file_path: str, mimetype: str | None = None) -> TranscriptionResult:
        self.requests.append((file_path, mimetype))
        if self.mode == "timeout": return TranscriptionResult(None, "fake", "fake-audio", error_type="transcription_timeout")
        if self.mode == "error": return TranscriptionResult(None, "fake", "fake-audio", error_type="transcription_provider_error")
        text = "" if self.mode == "empty" else (self.transcripts.pop(0) if self.transcripts else "")
        return TranscriptionResult(text, "fake", "fake-audio", latency_ms=1, language="es")
