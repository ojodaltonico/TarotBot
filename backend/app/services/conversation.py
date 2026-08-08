import json
import re
import unicodedata
from pathlib import Path
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.ai.provider import AIMessage, AIProvider, AIProviderError, AIResponse
from app.ai.costs import estimate_cost
from app.core.config import get_settings
from app.conversation.schemas import ConversationAction, ConversationDecision, ConversationState
from app.models.ai import AICall, UserMemory
from app.models.message import Message
from app.tarot.spreads import SPREADS

PROMPT_VERSION="tarotista_v3"
PROMPT_DIR=Path(__file__).parents[1]/"ai"/"prompts"
PROMPT=PROMPT_DIR/f"{PROMPT_VERSION}.txt"
ALLOWED_TRANSITIONS={ConversationState.NEW:{ConversationState.CHATTING,ConversationState.DEFINING_QUESTION,ConversationState.READY_FOR_READING},ConversationState.CHATTING:set(ConversationState),ConversationState.DEFINING_QUESTION:{ConversationState.CHATTING,ConversationState.READY_FOR_READING},ConversationState.READY_FOR_READING:{ConversationState.READING_ACTIVE,ConversationState.CHATTING},ConversationState.READING_ACTIVE:{ConversationState.FOLLOW_UP,ConversationState.CHATTING},ConversationState.FOLLOW_UP:{ConversationState.FOLLOW_UP,ConversationState.CHATTING,ConversationState.DEFINING_QUESTION}}
FALLBACK="Se me cortó un poco el hilo. Decime eso último de nuevo y seguimos."
SIMPLIFICATION_FOLLOW_UPS={"o sea","entonces","en resumen","que significa","pero si o no","y eso que quiere decir"}


CONFIRMATION_NOT_READY="Todavía no hay una tirada lista. Si querés, contame qué te gustaría mirar."


class EmptyResponseError(ValueError): pass
class InvalidResponseError(ValueError): pass


def is_simplification_follow_up(text: str) -> bool:
 normalized=unicodedata.normalize("NFKD",text).encode("ascii","ignore").decode().lower()
 normalized=re.sub(r"[^a-z0-9]+"," ",normalized).strip()
 return normalized in SIMPLIFICATION_FOLLOW_UPS

class ConversationService:
 """Persist a safe fallback for any unusable AI decision; valid decisions alone may change state."""
 def __init__(self, provider: AIProvider, recent_messages=None, store_debug=False, prompt_version=None):
  settings=get_settings();self.provider=provider;self.recent_messages=settings.ai_recent_messages if recent_messages is None else recent_messages;self.store_debug=store_debug;self.prompt_version=prompt_version or settings.ai_conversation_prompt_version;self.prompt=PROMPT_DIR/f"{self.prompt_version}.txt"
  if not self.prompt.is_file(): raise ValueError("Unsupported conversation prompt version")
 def chat(self, session: Session, user, conversation, text: str, message_id: str | None = None, created_at=None, physical_messages=None):
  physical_messages=physical_messages or [{"message_id":message_id,"timestamp":created_at,"message_type":"text","text":text}]
  current_messages=[]
  for physical in physical_messages:
   values={"conversation_id":conversation.id,"whatsapp_message_id":physical["message_id"],"direction":"incoming","message_type":physical.get("message_type","text"),"content":physical.get("text","")}
   if physical.get("timestamp") is not None: values["created_at"]=physical["timestamp"]
   current_messages.append(Message(**values))
  session.add_all(current_messages); session.flush()
  current_ids=[message.id for message in current_messages]
  history=list(reversed(session.scalars(select(Message).where(Message.conversation_id==conversation.id,Message.id.not_in(current_ids),Message.message_type!="internal").order_by(Message.id.desc()).limit(self.recent_messages)).all()))
  current=ConversationState(conversation.state)
  memory=session.scalar(select(UserMemory).where(UserMemory.user_id==user.id)); messages=[AIMessage("system",self.prompt.read_text(encoding="utf8"))]
  if current in {ConversationState.READING_ACTIVE,ConversationState.FOLLOW_UP} and is_simplification_follow_up(text):
   messages.append(AIMessage("system","El último mensaje pide una síntesis de la tirada activa. Respondé directo en 40 a 100 palabras, con uno o dos párrafos breves. No expliques carta por carta ni recites las tres; respondé la consulta original con lenguaje de tendencia o posibilidad, sin convertir emociones, intenciones o hechos de otra persona en certezas."))
  if memory: messages.append(AIMessage("system",f"Memoria: {memory.summary}"))
  messages += [AIMessage("user" if m.direction=="incoming" else "assistant",m.content) for m in history]
  messages.append(AIMessage("user",text))
  try:
   response=self.provider.generate(messages,purpose="conversation",options={"response_schema": ConversationDecision,"conversation_state":current.value})
   if not response.text or not response.text.strip(): raise EmptyResponseError()
   decision=ConversationDecision.model_validate_json(response.text)
   if not decision.reply.strip(): raise InvalidResponseError()
   can_confirm_reading=(current is ConversationState.READY_FOR_READING and conversation.reading_recommended and conversation.suggested_spread in SPREADS and decision.action is ConversationAction.confirm_reading)
   if decision.action is ConversationAction.confirm_reading and not can_confirm_reading: decision=decision.model_copy(update={"action":ConversationAction.none,"reply":CONFIRMATION_NOT_READY,"next_state":current,"reading_recommended":False,"suggested_spread":None})
   if not decision.reading_recommended: decision=decision.model_copy(update={"suggested_spread":None})
   elif decision.suggested_spread not in SPREADS: decision=decision.model_copy(update={"suggested_spread":None,"reading_recommended":False})
   else: decision=decision.model_copy(update={"next_state":ConversationState.READY_FOR_READING})
   next_state=current if can_confirm_reading else (decision.next_state if decision.next_state in ALLOWED_TRANSITIONS[current] else current)
   if next_state != decision.next_state: decision=decision.model_copy(update={"next_state":next_state})
   conversation.state=next_state.value;conversation.last_intent=decision.intent.value;conversation.last_action=decision.action.value
   if not can_confirm_reading: conversation.reading_recommended=decision.reading_recommended;conversation.suggested_spread=decision.suggested_spread
   if not can_confirm_reading: session.add(Message(conversation_id=conversation.id,whatsapp_message_id=None,direction="outgoing",message_type="text",content=decision.reply))
   self._audit(session,user.id,conversation.id,response,True,None,{"history":len(history)}); session.commit(); return decision,response
  except Exception as error:
   audit_response=getattr(error,"response",None)
   if audit_response is None and "response" in locals(): audit_response=response
   session.add(Message(conversation_id=conversation.id,whatsapp_message_id=None,direction="outgoing",message_type="text",content=FALLBACK)); self._audit(session,user.id,conversation.id,audit_response,False,self._error_category(error),getattr(error,"diagnostics",None)); session.commit(); return ConversationDecision(reply=FALLBACK,intent="unclear",next_state=ConversationState(conversation.state)),None
 def _error_category(self,error):
  if isinstance(error,AIProviderError): return error.category
  if isinstance(error,TimeoutError): return "timeout"
  if isinstance(error,EmptyResponseError): return "empty_response"
  if isinstance(error,InvalidResponseError): return "invalid_response"
  if isinstance(error,ValidationError): return "validation_error"
  return "provider_error"
 def _audit(self,s,u,c,r,ok,error,payload):
  s.add(AICall(user_id=u,conversation_id=c,reading_id=None,purpose="conversation",provider=getattr(r,"provider","unknown"),model=getattr(r,"model","unknown"),prompt_version=self.prompt_version,input_tokens=getattr(r,"input_tokens",0),cached_input_tokens=getattr(r,"cached_tokens",None),output_tokens=getattr(r,"output_tokens",0),latency_ms=getattr(r,"latency_ms",0),success=ok,error_type=error,estimated_cost_usd=estimate_cost(getattr(r,"provider",""),getattr(r,"model",""),getattr(r,"input_tokens",0),getattr(r,"output_tokens",0),getattr(r,"cached_tokens",None)),debug_payload=json.dumps(payload) if self.store_debug else None))
