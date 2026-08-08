"""Semantic response splitting and deterministic WhatsApp delivery timing."""

from __future__ import annotations

import hashlib
import re

from app.core.config import get_settings
from app.schemas.whatsapp import OutboundMessage


def _sentences(text: str) -> list[str]:
    return [piece.strip() for piece in re.split(r"(?<=[.!?¿¡])\s+", text.strip()) if piece.strip()]


def _semantic_units(text: str) -> list[str]:
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n+", text.strip()) if part.strip()]
    if len(paragraphs) > 1:
        return paragraphs
    return _sentences(text) or ([text.strip()] if text.strip() else [])


def segment_text(text: str, *, short_limit: int = 280, target_limit: int = 520, max_segments: int = 4) -> list[str]:
    """Split only at paragraph or sentence boundaries; preserve order and meaning."""
    normalized = text.strip()
    if not normalized:
        return []
    if len(normalized) <= short_limit:
        return [normalized]
    units = _semantic_units(normalized)
    segments: list[str] = []
    current = ""
    for unit in units:
        candidate = f"{current}\n\n{unit}" if current else unit
        if current and len(candidate) > target_limit and len(segments) < max_segments - 1:
            segments.append(current)
            current = unit
        else:
            current = candidate
    if current:
        segments.append(current)
    if len(segments) <= max_segments:
        return segments
    head = segments[: max_segments - 1]
    head.append("\n\n".join(segments[max_segments - 1 :]))
    return head


def _variation(seed: str, low: float, high: float) -> float:
    fraction = int.from_bytes(hashlib.sha256(seed.encode("utf-8")).digest()[:4], "big") / 2**32
    return low + (high - low) * fraction


def typing_ms(text: str, *, key: str, index: int) -> int:
    settings = get_settings()
    chars_per_second = max(1.0, settings.whatsapp_typing_chars_per_second)
    minimum = max(0, settings.whatsapp_min_typing_ms)
    maximum = max(minimum, settings.whatsapp_max_typing_ms)
    natural = (len(text.strip()) / chars_per_second) * 1000
    varied = natural * _variation(f"typing|{key}|{index}|{text}", 0.9, 1.1)
    return min(maximum, max(minimum, round(varied)))


def inter_message_delay_ms(*, key: str, index: int) -> int:
    settings = get_settings()
    low = max(0, settings.whatsapp_inter_message_delay_ms_min)
    high = max(low, settings.whatsapp_inter_message_delay_ms_max)
    return round(_variation(f"pause|{key}|{index}", low, high))


def delivery_messages(segments: list[str], *, key: str, prefix: list[OutboundMessage] | None = None) -> list[OutboundMessage]:
    """Decorate ordered bubbles; delay_ms is the pause before every non-first bubble."""
    result = list(prefix or [])
    for text in segments:
        if text.strip():
            result.append(OutboundMessage(type="text", text=text.strip()))
    for index, message in enumerate(result):
        content = message.caption or message.text or ""
        message.typing_ms = typing_ms(content, key=key, index=index)
        message.delay_ms = 0 if index == 0 else inter_message_delay_ms(key=key, index=index)
    return result
