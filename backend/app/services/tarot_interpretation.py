import json
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy import select

from app.ai.costs import estimate_cost
from app.ai.provider import AIMessage, AIProvider, AIProviderError
from app.core.config import get_settings
from app.models.ai import AICall, UserMemory
from app.models.message import Message
from app.models.tarot_reading import TarotInterpretation, TarotReading, TarotReadingCard
from app.services.response_segments import segment_text


PROMPT_DIR = Path(__file__).parents[1] / "ai" / "prompts"
PROMPT_VERSION = "tarot_interpretation_v2"
PROMPT = PROMPT_DIR / f"{PROMPT_VERSION}.txt"
SPREAD_CONTEXT = {
    "general_three": "La lectura es general_three: usá sólo Situación actual, Influencia o desafío y Tendencia o consejo; no la conviertas en una lectura relacional.",
    "relationship_three": "La lectura es relationship_three: podés usar Tu posición, La otra parte y Energía o tendencia del vínculo.",
    "one_card": "La lectura es one_card: interpretá una sola carta como mensaje, energía o consejo puntual.",
}


class InterpretationOutput(BaseModel):
    interpretation: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    segments: list[str] = Field(default_factory=list, max_length=4)

    @field_validator("segments")
    @classmethod
    def nonempty_segments(cls, segments: list[str]) -> list[str]:
        if any(not segment.strip() for segment in segments):
            raise ValueError("segments cannot be empty")
        return [segment.strip() for segment in segments]


class TarotInterpretationService:
    def __init__(self, provider: AIProvider, recent_messages=None, store_debug=False, prompt_version=None):
        settings = get_settings()
        self.provider = provider
        self.recent_messages = settings.ai_recent_messages if recent_messages is None else recent_messages
        self.store_debug = store_debug
        self.prompt_version = prompt_version or settings.ai_tarot_interpretation_prompt_version
        self.prompt = PROMPT_DIR / f"{self.prompt_version}.txt"

    def interpret_reading(self, session, reading_id, user_id, conversation_id, force=False):
        reading = session.get(TarotReading, reading_id)
        if reading is None or reading.user_id != user_id or reading.conversation_id != conversation_id:
            raise ValueError("Reading not found for user and conversation")
        existing = session.scalar(
            select(TarotInterpretation).where(TarotInterpretation.reading_id == reading_id).order_by(TarotInterpretation.id.desc())
        )
        if existing and not force:
            return existing
        cards = session.scalars(
            select(TarotReadingCard)
            .where(TarotReadingCard.reading_id == reading_id)
            .order_by(TarotReadingCard.position_index)
        ).all()
        history = list(
            reversed(
                session.scalars(
                    select(Message)
                    .where(Message.conversation_id == conversation_id, Message.message_type != "internal")
                    .order_by(Message.id.desc())
                    .limit(self.recent_messages)
                ).all()
            )
        )
        memory = session.scalar(select(UserMemory).where(UserMemory.user_id == user_id))
        payload = {
            "question": reading.question,
            "spread_type": reading.spread_type,
            "cards": [
                {
                    "position_index": card.position_index,
                    "position_key": card.position_key,
                    "position_label": card.position_label,
                    "card_id": card.card_id,
                    "orientation": card.orientation,
                    "snapshot": json.loads(card.card_snapshot),
                }
                for card in cards
            ],
        }
        messages = [AIMessage("system", f"{self.prompt.read_text(encoding='utf8')}\n\n{SPREAD_CONTEXT[reading.spread_type]}")]
        if memory:
            messages.append(AIMessage("system", f"Memoria: {memory.summary}"))
        messages += [AIMessage("user" if message.direction == "incoming" else "assistant", message.content) for message in history]
        messages.append(AIMessage("user", json.dumps(payload, ensure_ascii=False)))
        response = None
        try:
            response = self.provider.generate(messages, purpose="reading_interpretation", options={"response_schema": InterpretationOutput})
            if not response.text or not response.text.strip():
                raise ValueError("empty_response")
            output = InterpretationOutput.model_validate_json(response.text)
            result = TarotInterpretation(
                reading_id=reading_id,
                interpretation_text=output.interpretation,
                interpretation_summary=output.summary,
                prompt_version=self.prompt_version,
                model=response.model,
                provider=response.provider,
            )
            # The canonical interpretation remains persisted as one text. These are
            # transport-only semantic bubbles for the response currently in flight.
            result.delivery_segments = output.segments or segment_text(output.interpretation)
            session.add(result)
            self._audit(session, user_id, conversation_id, reading_id, response, True, None, {"cards": len(cards)})
            session.commit()
            return result
        except Exception as error:
            self._audit(
                session,
                user_id,
                conversation_id,
                reading_id,
                getattr(error, "response", None) or response,
                False,
                self._error_type(error),
                getattr(error, "diagnostics", None),
            )
            session.commit()
            return None

    def segments_for(self, interpretation: TarotInterpretation) -> list[str]:
        """Persisted rows keep canonical text; split it safely for transport at delivery time."""
        return getattr(interpretation, "delivery_segments", None) or segment_text(interpretation.interpretation_text)

    @staticmethod
    def _error_type(error):
        if isinstance(error, AIProviderError):
            return error.category
        if isinstance(error, ValidationError):
            return "validation_error"
        if isinstance(error, ValueError):
            return "empty_response"
        if isinstance(error, TimeoutError):
            return "timeout"
        return "provider_error"

    def _audit(self, session, user_id, conversation_id, reading_id, response, success, error_type, payload):
        session.add(
            AICall(
                user_id=user_id,
                conversation_id=conversation_id,
                reading_id=reading_id,
                purpose="reading_interpretation",
                provider=getattr(response, "provider", "unknown"),
                model=getattr(response, "model", "unknown"),
                prompt_version=self.prompt_version,
                input_tokens=getattr(response, "input_tokens", 0),
                cached_input_tokens=getattr(response, "cached_tokens", None),
                output_tokens=getattr(response, "output_tokens", 0),
                latency_ms=getattr(response, "latency_ms", 0),
                success=success,
                error_type=error_type,
                estimated_cost_usd=estimate_cost(
                    getattr(response, "provider", ""),
                    getattr(response, "model", ""),
                    getattr(response, "input_tokens", 0),
                    getattr(response, "output_tokens", 0),
                    getattr(response, "cached_tokens", None),
                ),
                debug_payload=json.dumps(payload) if self.store_debug else None,
            )
        )
