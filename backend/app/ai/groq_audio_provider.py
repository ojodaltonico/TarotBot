from __future__ import annotations

import time

from app.ai.audio_transcription import AudioTranscriptionProvider, TranscriptionResult


class GroqAudioTranscriptionProvider(AudioTranscriptionProvider):
    def __init__(self, *, api_key: str, model: str, timeout_seconds: int = 30, enabled: bool = True):
        if not enabled: raise ValueError("Audio transcription is disabled")
        if not api_key: raise ValueError("GROQ_API_KEY is not configured")
        if not model.strip(): raise ValueError("AUDIO_TRANSCRIPTION_MODEL is not configured")
        from groq import Groq
        self.model = model
        self.client = Groq(api_key=api_key, timeout=timeout_seconds, max_retries=0)

    def transcribe(self, file_path: str, mimetype: str | None = None) -> TranscriptionResult:
        started = time.perf_counter()
        try:
            with open(file_path, "rb") as audio:
                result = self.client.audio.transcriptions.create(file=(file_path, audio.read()), model=self.model, response_format="verbose_json", temperature=0.0)
            return TranscriptionResult(getattr(result, "text", None), "groq", self.model, max(0, round((time.perf_counter()-started)*1000)), getattr(result, "language", None), getattr(result, "_request_id", None) or getattr(getattr(result, "x_groq", None), "id", None))
        except Exception as error:
            status = getattr(error, "status_code", None)
            name = type(error).__name__.lower()
            if "timeout" in name: category = "transcription_timeout"
            elif status == 429 or "ratelimit" in name: category = "transcription_rate_limit"
            else: category = "transcription_provider_error"
            return TranscriptionResult(None, "groq", self.model, max(0, round((time.perf_counter()-started)*1000)), request_id=getattr(error, "request_id", None), error_type=category)
