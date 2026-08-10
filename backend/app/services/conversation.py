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
from app.models.tarot_reading import TarotInterpretation, TarotReading
from app.tarot.spreads import SPREADS

PROMPT_VERSION="tarotista_v3"
PROMPT_DIR=Path(__file__).parents[1]/"ai"/"prompts"
PROMPT=PROMPT_DIR/f"{PROMPT_VERSION}.txt"
ALLOWED_TRANSITIONS={ConversationState.NEW:{ConversationState.CHATTING,ConversationState.DEFINING_QUESTION,ConversationState.READY_FOR_READING},ConversationState.CHATTING:set(ConversationState),ConversationState.DEFINING_QUESTION:{ConversationState.CHATTING,ConversationState.READY_FOR_READING},ConversationState.READY_FOR_READING:{ConversationState.READING_ACTIVE,ConversationState.CHATTING},ConversationState.READING_ACTIVE:{ConversationState.FOLLOW_UP,ConversationState.CHATTING,ConversationState.READY_FOR_READING},ConversationState.FOLLOW_UP:{ConversationState.FOLLOW_UP,ConversationState.CHATTING,ConversationState.DEFINING_QUESTION,ConversationState.READY_FOR_READING}}
FALLBACK="Se me cortó un poco el hilo. Decime eso último de nuevo y seguimos."
SIMPLIFICATION_FOLLOW_UPS={"o sea","entonces","en resumen","que significa","pero si o no","y eso que quiere decir"}
READING_CONFIRMATIONS={"si","sip","sep","se","dale","bueno","ok","okay","perfecto","de una","claro","hagamos","hagamosla","eso","si eso","me parece","me parece bien"}
READING_REJECTIONS={"no","mejor despues","todavia no","antes quiero preguntarte algo"}
HEALTH_TERMS={"salud","enfermedad","enfermo","enferma","cura","curar","curacion","curacion","diagnostico","diagnostico","medicamento","medicacion","tratamiento","operacion","cirugia","sintoma","dolor","embarazo","embarazada","cancer","tumor","analisis","estudio medico","medico","doctora","doctor"}
NEW_TOPIC_TERMS={"trabajo","laboral","empleo","plata","dinero","amor","pareja","relacion","relacion","ex","familia","estudio","mudanza"}
READING_REQUEST_TERMS={"otra tirada","otra lectura","una tirada","una lectura","sacar cartas","saquemos cartas","quiero otra","nueva tirada","nueva lectura","otra carta"}
INSISTENCE_TERMS={"insisto","igual quiero","quiero otra igual","hagamos otra","si quiero otra","quiero una nueva"}

class EmptyResponseError(ValueError): pass
class InvalidResponseError(ValueError): pass


def is_simplification_follow_up(text: str) -> bool:
 return _normalize_turn(text) in SIMPLIFICATION_FOLLOW_UPS


def _normalize_turn(text: str) -> str:
 normalized=unicodedata.normalize("NFKD",text.casefold()).encode("ascii","ignore").decode()
 return re.sub(r"[^a-z0-9]+"," ",normalized).strip()


def is_reading_confirmation(text: str) -> bool:
 normalized=_normalize_turn(text)
 return normalized in READING_CONFIRMATIONS or bool(re.fullmatch(r"si+",normalized))


def is_reading_rejection(text: str) -> bool:
 return _normalize_turn(text) in READING_REJECTIONS


def is_general_request(text: str) -> bool:
 return _normalize_turn(text) in {"general","tirada general","mi tarot"}


def is_health_request(text: str) -> bool:
 normalized=_normalize_turn(text)
 return any(term in normalized for term in HEALTH_TERMS)


def is_explicit_reflection_request(text: str) -> bool:
 normalized=_normalize_turn(text)
 return any(term in normalized for term in {"carta","tarot","tirada","lectura"})


def is_explicit_new_reading_request(text: str) -> bool:
 normalized=_normalize_turn(text)
 return any(term in normalized for term in READING_REQUEST_TERMS)


def is_same_topic_insistence(text: str) -> bool:
 normalized=_normalize_turn(text)
 return any(term in normalized for term in INSISTENCE_TERMS)


def is_clearly_new_topic(text: str, spread: str) -> bool:
 normalized=_normalize_turn(text)
 if spread == "relationship_three":
  return any(term in normalized for term in {"trabajo","laboral","empleo","plata","dinero","estudio","mudanza"})
 if spread == "general_three":
  return any(term in normalized for term in NEW_TOPIC_TERMS) and is_explicit_new_reading_request(text)
 return any(term in normalized for term in NEW_TOPIC_TERMS)


def active_reading_reply() -> str:
 return "Antes de sacar otra, miraría un poco más esta lectura: todavía tiene cosas para decir sobre lo que preguntaste. Si de verdad querés una nueva sobre lo mismo, decímelo claro."


def health_limit_reply() -> str:
 return "Con la salud no haría una tirada para decir si algo se cura, empeora o qué tratamiento necesitás. Para eso conviene hablarlo con un profesional. Si querés, puedo acompañarte con una carta como reflexión emocional, sin convertirla en una respuesta médica."


def confirmation_not_ready_reply(current: ConversationState) -> str:
 if current is ConversationState.DEFINING_QUESTION:
  return "Decime un poco más qué querés mirar y la enfocamos ahí."
 if current is ConversationState.READY_FOR_READING:
  return "Esa propuesta ya no está disponible. Podemos hacer una general, o enfocarla en trabajo, amor u otro tema."
 return "Podemos hacer una tirada. Decime si la querés general, sobre trabajo, amor u otro tema."


def proposal_reply(spread: str) -> str:
 if spread == "general_three":
  return "Podemos hacer una tirada general de tres cartas. ¿Te parece bien?"
 if spread == "relationship_three":
  return "Podemos hacer una tirada de tres cartas para mirar esa dinámica. ¿Te parece bien?"
 return "Podemos sacar una carta para mirar eso. ¿Te parece bien?"

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
  active_reading=session.scalar(select(TarotReading).where(TarotReading.conversation_id==conversation.id).order_by(TarotReading.id.desc()))
  has_active_reading=current in {ConversationState.READING_ACTIVE,ConversationState.FOLLOW_UP} and active_reading is not None
  prior_health_context=any(is_health_request(message.content) for message in history)
  if is_health_request(text):
   next_state=ConversationState.CHATTING if current is ConversationState.READY_FOR_READING else current
   decision=ConversationDecision(reply=health_limit_reply(),intent="general_chat",next_state=next_state,reading_recommended=False,suggested_spread=None)
   conversation.state=next_state.value;conversation.last_intent=decision.intent.value;conversation.last_action=decision.action.value;conversation.reading_recommended=False;conversation.suggested_spread=None
   session.add(Message(conversation_id=conversation.id,whatsapp_message_id=None,direction="outgoing",message_type="text",content=decision.reply));session.commit();return decision,None
  if prior_health_context and is_explicit_reflection_request(text):
   decision=ConversationDecision(reply="Podemos sacar una carta sólo como reflexión sobre cómo cuidarte emocionalmente mientras atravesás esto, sin usarla para responder algo médico. ¿Te parece?",intent="ask_tarot",next_state=ConversationState.READY_FOR_READING,reading_recommended=True,suggested_spread="one_card")
   conversation.state=decision.next_state.value;conversation.last_intent=decision.intent.value;conversation.last_action=decision.action.value;conversation.reading_recommended=True;conversation.suggested_spread="one_card"
   session.add(Message(conversation_id=conversation.id,whatsapp_message_id=None,direction="outgoing",message_type="text",content=decision.reply));session.commit();return decision,None
  memory=session.scalar(select(UserMemory).where(UserMemory.user_id==user.id)); messages=[AIMessage("system",self.prompt.read_text(encoding="utf8"))]
  if has_active_reading:
   latest_interpretation=session.scalar(select(TarotInterpretation).where(TarotInterpretation.reading_id==active_reading.id).order_by(TarotInterpretation.id.desc()))
   summary=latest_interpretation.interpretation_summary if latest_interpretation else "Interpretación pendiente"
   messages.append(AIMessage("system",f"Hay una lectura activa (id {active_reading.id}, spread {active_reading.spread_type}). Usala como contexto: {summary}. No propongas una lectura nueva por emojis, afirmaciones breves ni preguntas de seguimiento. Sólo se permite una lectura nueva si la persona la pide expresamente y trae un tema claramente distinto, o insiste de forma inequívoca en otra sobre el mismo tema."))
  if current in {ConversationState.READING_ACTIVE,ConversationState.FOLLOW_UP} and is_simplification_follow_up(text):
   messages.append(AIMessage("system","El último mensaje pide una síntesis de la tirada activa. Respondé directo en 40 a 100 palabras, con uno o dos párrafos breves. No expliques carta por carta ni recites las tres; respondé la consulta original con lenguaje de tendencia o posibilidad, sin convertir emociones, intenciones o hechos de otra persona en certezas."))
  if memory: messages.append(AIMessage("system",f"Memoria: {memory.summary}"))
  messages += [AIMessage("user" if m.direction=="incoming" else "assistant",m.content) for m in history]
  quoted=[item.get("quoted_text","").strip() for item in physical_messages if item.get("quoted_text") and item.get("quoted_text").strip()]
  model_text=text if not quoted else f"La persona responde a: “{quoted[-1]}”.\nDice: “{text}”"
  messages.append(AIMessage("user",model_text))
  try:
   response=self.provider.generate(messages,purpose="conversation",options={"response_schema": ConversationDecision,"conversation_state":current.value})
   if not response.text or not response.text.strip(): raise EmptyResponseError()
   decision=ConversationDecision.model_validate_json(response.text)
   if not decision.reply.strip(): raise InvalidResponseError()
   allowed_new_reading=has_active_reading and (is_clearly_new_topic(text,active_reading.spread_type) or (is_explicit_new_reading_request(text) and is_same_topic_insistence(text)))
   if has_active_reading and not allowed_new_reading:
    if decision.reading_recommended or decision.action is ConversationAction.confirm_reading:
     decision=decision.model_copy(update={"reply":active_reading_reply(),"next_state":current if is_reading_confirmation(text) else ConversationState.FOLLOW_UP,"reading_recommended":False,"suggested_spread":None,"action":ConversationAction.none})
    elif not is_clearly_new_topic(text,active_reading.spread_type) and decision.intent.value == "follow_up":
     decision=decision.model_copy(update={"next_state":current if is_reading_confirmation(text) else ConversationState.FOLLOW_UP,"reading_recommended":False,"suggested_spread":None,"action":ConversationAction.none})
   proposal_is_ready=(current is ConversationState.READY_FOR_READING and conversation.reading_recommended and conversation.suggested_spread in SPREADS)
   if proposal_is_ready and is_reading_confirmation(text) and decision.action is not ConversationAction.confirm_reading:
    decision=decision.model_copy(update={"action":ConversationAction.confirm_reading,"next_state":ConversationState.READY_FOR_READING,"reading_recommended":True,"suggested_spread":conversation.suggested_spread})
   if proposal_is_ready and decision.action is ConversationAction.none and not decision.reading_recommended and not is_reading_rejection(text) and decision.next_state is ConversationState.READY_FOR_READING:
    decision=decision.model_copy(update={"reading_recommended":True,"suggested_spread":conversation.suggested_spread})
   can_confirm_reading=(current is ConversationState.READY_FOR_READING and conversation.reading_recommended and conversation.suggested_spread in SPREADS and decision.action is ConversationAction.confirm_reading)
   if decision.action is ConversationAction.confirm_reading and not can_confirm_reading:
    if decision.reading_recommended and decision.suggested_spread in SPREADS and not is_reading_confirmation(text):
     decision=decision.model_copy(update={"action":ConversationAction.none,"reply":proposal_reply(decision.suggested_spread),"next_state":ConversationState.READY_FOR_READING})
    elif is_general_request(text):
     decision=decision.model_copy(update={"action":ConversationAction.none,"reply":proposal_reply("general_three"),"intent":"general_reading","next_state":ConversationState.READY_FOR_READING,"reading_recommended":True,"suggested_spread":"general_three"})
    else:
     decision=decision.model_copy(update={"action":ConversationAction.none,"reply":confirmation_not_ready_reply(current),"next_state":current,"reading_recommended":False,"suggested_spread":None})
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
