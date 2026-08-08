import json

from app.ai.provider import AIMessage, AIProvider, AIProviderError, AIResponse


_DEFAULT = object()

class FakeAIProvider(AIProvider):
    """Deterministic provider double for conversation service tests."""

    def __init__(self, response: str | None = None, error: Exception | None = None, usage: dict | None = None, mode: str | None = None, responses: list[str] | None = None):
        self.response=response; self.error=error; self.usage=usage or {}; self.mode=mode; self.responses=list(responses) if responses is not None else None; self.requests=[]

    def _response(self, text=_DEFAULT) -> AIResponse:
        content = self.response if text is _DEFAULT else text
        return AIResponse(content, self.usage.get("model","fake-model"), self.usage.get("input_tokens",10), self.usage.get("output_tokens",5), self.usage.get("cached_tokens"), self.usage.get("latency_ms",1), self.usage.get("provider","fake"), self.usage.get("request_id"))

    def generate(self, messages: list[AIMessage], *, purpose: str, options=None) -> AIResponse:
        self.requests.append((messages,purpose,options))
        if self.error: raise self.error
        if self.responses is not None:
            if not self.responses: raise AIProviderError("provider_error", self._response())
            self.response = self.responses.pop(0)
        if self.mode == "timeout": raise AIProviderError("timeout", self._response())
        if self.mode == "provider_error": raise AIProviderError("provider_error", self._response())
        if self.mode == "generic_error":
            error = RuntimeError("fake provider error")
            error.response = self._response()
            raise error
        if self.mode in {"empty", "missing_structured"}: return self._response("")
        if self.mode == "none_text": return self._response(None)
        if self.mode == "demo":
            if purpose == "reading_interpretation": return self._response(json.dumps({"interpretation":"La tirada invita a observar el vínculo con calma y claridad.","summary":"Priorizá lo que necesitás para sentirte en paz."}))
            if purpose == "memory_summary": return self._response("Consulta de laboratorio en curso.")
            text=messages[-1].content.lower()
            state=(options or {}).get("conversation_state", "CHATTING")
            lottery=any(word in text for word in ("quiniela", "loteria", "lotería", "apuesta", "numero", "número"))
            relationship=any(word in text for word in ("ex", "relación", "persona", "nosotros", "vínculo", "vinculo"))
            affirmative=text.strip() in {"si", "sí", "dale", "ok", "okay", "de acuerdo"}
            if lottery: value={"reply":"No puedo decirte un número ganador. Si querés, podemos hablar de qué te preocupa de esa apuesta.","intent":"general_chat","next_state":"CHATTING","reading_recommended":False,"suggested_spread":None,"action":"none","memory_candidates":[]}
            elif affirmative and state == "READY_FOR_READING": value={"reply":"Voy con la tirada.","intent":"relationship","next_state":"READY_FOR_READING","reading_recommended":True,"suggested_spread":"relationship_three","action":"confirm_reading","memory_candidates":[]}
            elif affirmative: value={"reply":"Todavía no hay una tirada preparada. Si querés, contame qué te gustaría mirar.","intent":"unclear","next_state":state,"reading_recommended":False,"suggested_spread":None,"action":"none","memory_candidates":[]}
            elif "hola" in text: value={"reply":"Hola, contame qué querés mirar.","intent":"greeting","next_state":"CHATTING","reading_recommended":False,"suggested_spread":None,"memory_candidates":[]}
            elif state in {"READING_ACTIVE", "FOLLOW_UP"} and relationship: value={"reply":"Podemos abrir una consulta nueva. Contame un poco más de qué querés mirar ahora.","intent":"relationship","next_state":"CHATTING","reading_recommended":False,"suggested_spread":None,"memory_candidates":[]}
            elif state in {"READING_ACTIVE", "FOLLOW_UP"}: value={"reply":"Tomando la tirada que salió, para vos esto marca un momento de mirar con calma lo que necesitás.","intent":"follow_up","next_state":"FOLLOW_UP","reading_recommended":False,"suggested_spread":None,"memory_candidates":[]}
            elif relationship: value={"reply":"Contame un poco más del momento actual entre ustedes.","intent":"relationship","next_state":"DEFINING_QUESTION","reading_recommended":False,"suggested_spread":None,"memory_candidates":[]}
            else: value={"reply":"Con ese contexto, podemos hacer una tirada para mirar el vínculo.","intent":"relationship","next_state":"READY_FOR_READING","reading_recommended":True,"suggested_spread":"relationship_three","memory_candidates":[]}
            return self._response(json.dumps(value))
        invalid = {
            "invalid_schema": [],
            "invalid_next_state": {"reply": "hola", "intent": "greeting", "next_state": "INVALID", "reading_recommended": False, "suggested_spread": None, "memory_candidates": []},
            "invalid_intent": {"reply": "hola", "intent": "romance_prediction", "next_state": "CHATTING", "reading_recommended": False, "suggested_spread": None, "memory_candidates": []},
            "empty_reply": {"reply": "", "intent": "greeting", "next_state": "CHATTING", "reading_recommended": False, "suggested_spread": None, "memory_candidates": []},
            "blank_reply": {"reply": "   ", "intent": "greeting", "next_state": "CHATTING", "reading_recommended": False, "suggested_spread": None, "memory_candidates": []},
            "partial": {},
            "invalid_reading_recommended": {"reply": "hola", "intent": "greeting", "next_state": "CHATTING", "reading_recommended": "not-a-bool", "suggested_spread": None, "memory_candidates": []},
            "invalid_memory_candidates": {"reply": "hola", "intent": "greeting", "next_state": "CHATTING", "reading_recommended": False, "suggested_spread": None, "memory_candidates": "not-a-list"},
        }
        if self.mode in invalid: return self._response(json.dumps(invalid[self.mode]))
        return self._response()
