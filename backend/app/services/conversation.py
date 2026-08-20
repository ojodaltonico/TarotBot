import json
import re
import unicodedata
from datetime import datetime, timedelta, timezone
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
from app.models.tarot_reading import TarotInterpretation, TarotReading, TarotReadingCard
from app.tarot.spreads import SPREADS

PROMPT_VERSION="tarotista_v3"
PROMPT_DIR=Path(__file__).parents[1]/"ai"/"prompts"
PROMPT=PROMPT_DIR/f"{PROMPT_VERSION}.txt"
ALLOWED_TRANSITIONS={ConversationState.NEW:{ConversationState.CHATTING,ConversationState.DEFINING_QUESTION,ConversationState.READY_FOR_READING},ConversationState.CHATTING:set(ConversationState),ConversationState.DEFINING_QUESTION:{ConversationState.CHATTING,ConversationState.READY_FOR_READING},ConversationState.READY_FOR_READING:{ConversationState.READING_ACTIVE,ConversationState.CHATTING},ConversationState.READING_ACTIVE:{ConversationState.FOLLOW_UP,ConversationState.CHATTING,ConversationState.READY_FOR_READING},ConversationState.FOLLOW_UP:{ConversationState.FOLLOW_UP,ConversationState.CHATTING,ConversationState.DEFINING_QUESTION,ConversationState.READY_FOR_READING}}
FALLBACK="Se me cortó un poco el hilo. Decime eso último de nuevo y seguimos."
SIMPLIFICATION_FOLLOW_UPS={"o sea","entonces","en resumen","que significa","pero si o no","y eso que quiere decir"}
READING_CONFIRMATIONS={"si","sip","sep","se","dale","dale si","bueno","ok","okay","perfecto","de una","claro","hagamos","hagamosla","eso","si eso","me parece","me parece bien"}
READING_REJECTIONS={"no","mejor despues","todavia no","antes quiero preguntarte algo"}
HEALTH_TERMS={"salud","enfermedad","enfermo","enferma","cura","curar","curacion","diagnostico","medicamento","medicacion","tratamiento","operacion","cirugia","sintoma","dolor","embarazo","embarazada","bebe","hijo por nacer","cancer","tumor","analisis","estudio medico","medico","doctora","doctor","internada","internado"}
HEALTH_EXCLUSIONS={"que no sea salud","que no sean salud","no quiero preguntar por salud","dejemos el tema de salud","dejemos salud"}
HEALTH_PREDICTIVE_TERMS={"me voy a curar","se va a curar","esta bien","esta bien","como va","como evoluciona","va a salir bien","resultado","diagnostico","tratamiento","medicamento","operacion","cirugia","cura","curar"}
HEALTH_EMOTIONAL_TERMS={"atravesar mejor","cuidar emocionalmente","acompanarme","acompañarme","reflexion","reflexión","transitar","una carta para"}
NEW_TOPIC_TERMS={"trabajo","laboral","empleo","plata","dinero","amor","pareja","relacion","relacion","ex","familia","estudio","mudanza"}
READING_REQUEST_TERMS={"otra tirada","otra lectura","una tirada","una lectura","sacar cartas","saquemos cartas","quiero otra","nueva tirada","nueva lectura","otra carta","una nueva","tira de nuevo","tirame de nuevo","haceme una nueva","quiero preguntar otra cosa"}
INSISTENCE_TERMS={"insisto","igual quiero","quiero otra igual","hagamos otra","si quiero otra","quiero una nueva","una nueva","tira de nuevo","tirame de nuevo","haceme una nueva"}

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


def health_intent(text: str) -> str | None:
 normalized=_normalize_turn(text)
 if any(term in normalized for term in HEALTH_EXCLUSIONS): return None
 if not any(term in normalized for term in HEALTH_TERMS): return None
 if any(term in normalized for term in HEALTH_EMOTIONAL_TERMS): return "health_emotional"
 if any(term in normalized for term in HEALTH_PREDICTIVE_TERMS): return "health_predictive"
 return "health_context_only"


def is_health_request(text: str) -> bool:
 return health_intent(text) in {"health_predictive","health_emotional"}


def is_explicit_reflection_request(text: str) -> bool:
 normalized=_normalize_turn(text)
 return any(term in normalized for term in {"carta","tarot","tirada","lectura"})


def is_explicit_new_reading_request(text: str) -> bool:
 normalized=_normalize_turn(text)
 return any(term in normalized for term in READING_REQUEST_TERMS)


def is_same_topic_insistence(text: str) -> bool:
 normalized=_normalize_turn(text)
 return any(term in normalized for term in INSISTENCE_TERMS)


def is_ambiguous_reading_request(text: str) -> bool:
 normalized=_normalize_turn(text)
 return any(term in normalized for term in {"tirame las cartas","tira las cartas","sacame las cartas","quiero una tirada","quiero cartas"}) and message_scope(text) == "unknown"


def is_other_topic_request(text: str) -> bool:
 return any(term in _normalize_turn(text) for term in {"de otra cosa","otro tema","otra consulta","quiero preguntar otra cosa"})


def is_retrospective_reading_reference(text: str) -> bool:
 normalized=_normalize_turn(text)
 return any(term in normalized for term in {"te acordas","te acordas de lo que salio","que salio","lectura anterior","tirada anterior","lo que salio sobre"})


def is_reading_recent(reading: TarotReading | None, minutes: int) -> bool:
 if reading is None or reading.created_at is None:
  return False
 created_at=reading.created_at
 now=datetime.now(timezone.utc) if created_at.tzinfo else datetime.now(timezone.utc).replace(tzinfo=None)
 return created_at >= now-timedelta(minutes=max(minutes,0))


def is_distinct_specific_question(text: str, reading: TarotReading | None) -> bool:
 normalized=_normalize_turn(text)
 previous=_normalize_turn(reading.question or "") if reading else ""
 if not normalized or normalized == previous:
  return False
 return any(marker in normalized for marker in {"esta semana","este mes","cuando","me va a","va a ","por que","por que ","que intencion","hacia donde","si me escribe"})


def active_reading_guard_was_shown(history: list[Message]) -> bool:
 return any(message.direction == "outgoing" and "antes de sacar otra" in _normalize_turn(message.content) for message in history[-4:])


def is_clearly_new_topic(text: str, spread: str) -> bool:
 normalized=_normalize_turn(text)
 if spread == "relationship_three":
  return any(term in normalized for term in {"trabajo","laboral","empleo","plata","dinero","estudio","mudanza"})
 if spread == "general_three":
  return any(term in normalized for term in NEW_TOPIC_TERMS) and is_explicit_new_reading_request(text)
 return any(term in normalized for term in NEW_TOPIC_TERMS)


def reading_scope(reading: TarotReading | None) -> str:
 if reading is None: return "unknown"
 question=_normalize_turn(reading.question or "")
 if reading.spread_type == "relationship_three" or any(term in question for term in {"amor","pareja","relacion","ex","vinculo","persona"}): return "relationship"
 if any(term in question for term in {"trabajo","laboral","empleo","rubro","profesion"}): return "work"
 return "general"


def message_scope(text: str) -> str:
 normalized=_normalize_turn(text)
 if any(term in normalized for term in {"trabajo","laboral","empleo","rubro","profesion"}): return "work"
 if any(term in normalized for term in {"amor","pareja","relacion","ex","vinculo","persona"}): return "relationship"
 if any(term in normalized for term in {"semana","futuro","panorama","general"}): return "general"
 return "unknown"


def has_clear_scope_change(text: str, reading: TarotReading | None) -> bool:
 current=message_scope(text); previous=reading_scope(reading)
 return current != "unknown" and previous != "unknown" and current != previous


def is_new_relationship_subject(text: str) -> bool:
 normalized=_normalize_turn(text)
 return any(phrase in normalized for phrase in {"otra persona","otra relacion","nuevo vinculo","alguien distinto"})


def active_reading_reply() -> str:
 return "Antes de sacar otra, miraría un poco más esta lectura: todavía tiene cosas para decir sobre lo que preguntaste. Si de verdad querés una nueva sobre lo mismo, decímelo claro."


def ambiguous_reading_request_reply(has_recent_reading: bool) -> str:
 if has_recent_reading:
  return "Sí. ¿Querés seguir con la lectura que veníamos viendo o hacemos una nueva general o sobre algún tema en particular?"
 return "Sí. ¿Querés hacer una nueva general o mirar algún tema en particular?"


def health_limit_reply() -> str:
 return "Sobre cómo evoluciona la salud o el embarazo no te lo marcaría con las cartas; eso es para verlo con tus controles. Pero podemos sacar una carta sobre cómo estás transitando este momento y qué necesitás cuidar emocionalmente. ¿Te parece?"


def health_reflection_reply() -> str:
 return "Podemos sacar una carta como reflexión emocional para acompañarte en esta etapa, sin usarla para responder algo médico. ¿Te parece?"


def is_safe_health_pending(conversation, history: list[Message]) -> bool:
 return conversation.reading_recommended and conversation.suggested_spread == "one_card" and any("emocional" in message.content.lower() for message in history if message.direction == "outgoing")


def pending_health_question(conversation, history: list[Message]) -> str | None:
 if is_safe_health_pending(conversation, history):
  return "Reflexión emocional no médica para transitar un contexto de salud."
 return None


def separate_topics_reply(history: list[Message]) -> str:
 joined=" ".join(message.content.lower() for message in history if message.direction == "incoming")
 topics=[label for label, terms in (("familia",("familia",)),("viajes",("viaje","viajes")),("patrones",("patron","patrones","comportamiento"))) if any(term in joined for term in terms)]
 options=", ".join(topics) if topics else "el tema que más te importe"
 return f"Dale. ¿Con cuál arrancamos: {options}?"


def is_separate_topics_request(text: str) -> bool:
 return "por separado" in _normalize_turn(text)


def is_retrospective_topic_mapping(text: str, reading: TarotReading) -> bool:
 normalized=_normalize_turn(text)
 return reading.spread_type == "general_three" and "carta" in normalized and any(topic in normalized for topic in {"viaje","viajes"}) and "viaje" not in _normalize_turn(reading.question or "")


def confirmation_not_ready_reply(current: ConversationState) -> str:
 if current is ConversationState.DEFINING_QUESTION:
  return "Decime un poco más qué querés mirar y la enfocamos ahí."
 if current is ConversationState.READY_FOR_READING:
  return "Ahora no tengo una tirada pendiente. Si querés, preparamos una según lo que quieras mirar."
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
   if physical.get("message_type") == "audio":
    values.update({"audio_mimetype":physical.get("audio_mimetype"),"audio_duration_seconds":physical.get("audio_duration_seconds"),"audio_ptt":physical.get("audio_ptt"),"transcription_error":physical.get("transcription_error")})
   if physical.get("timestamp") is not None: values["created_at"]=physical["timestamp"]
   current_messages.append(Message(**values))
  session.add_all(current_messages); session.flush()
  for physical in physical_messages:
   if physical.get("message_type") == "audio" and physical.get("transcription_provider"):
    self._audit(session,user.id,conversation.id,AIResponse(None,physical.get("transcription_model") or "unknown",latency_ms=physical.get("transcription_latency_ms") or 0,provider=physical["transcription_provider"]),not bool(physical.get("transcription_error")),physical.get("transcription_error"),{"purpose":"audio_transcription"},purpose="audio_transcription",prompt_version="audio_transcription_v1")
  current_ids=[message.id for message in current_messages]
  history=list(reversed(session.scalars(select(Message).where(Message.conversation_id==conversation.id,Message.id.not_in(current_ids),Message.message_type!="internal").order_by(Message.id.desc()).limit(self.recent_messages)).all()))
  current=ConversationState(conversation.state)
  latest_reading=session.scalar(select(TarotReading).where(TarotReading.conversation_id==conversation.id).order_by(TarotReading.created_at.desc(),TarotReading.id.desc()))
  # A completed reading is historical data forever, but only a recent one has strong
  # conversational priority unless the person explicitly brings it back.
  active_reading=latest_reading if is_reading_recent(latest_reading,get_settings().reading_active_context_minutes) or is_retrospective_reading_reference(text) else None
  has_active_reading=active_reading is not None
  current_health_intent=health_intent(text)
  prior_health_context=any(health_intent(message.content) in {"health_predictive","health_emotional"} for message in history)
  if current_health_intent in {"health_predictive","health_emotional"}:
   reply=health_limit_reply() if current_health_intent == "health_predictive" else health_reflection_reply()
   decision=ConversationDecision(reply=reply,intent="ask_tarot",next_state=ConversationState.READY_FOR_READING,reading_recommended=True,suggested_spread="one_card")
   conversation.state=decision.next_state.value;conversation.last_intent=decision.intent.value;conversation.last_action=decision.action.value;conversation.reading_recommended=True;conversation.suggested_spread="one_card"
   session.add(Message(conversation_id=conversation.id,whatsapp_message_id=None,direction="outgoing",message_type="text",content=decision.reply));session.commit();return decision,None
  if is_separate_topics_request(text):
   decision=ConversationDecision(reply=separate_topics_reply(history+current_messages),intent="general_chat",next_state=ConversationState.DEFINING_QUESTION,reading_recommended=False,suggested_spread=None)
   conversation.state=decision.next_state.value;conversation.last_intent=decision.intent.value;conversation.last_action=decision.action.value;conversation.reading_recommended=False;conversation.suggested_spread=None
   session.add(Message(conversation_id=conversation.id,whatsapp_message_id=None,direction="outgoing",message_type="text",content=decision.reply));session.commit();return decision,None
  if latest_reading and is_ambiguous_reading_request(text):
   decision=ConversationDecision(reply=ambiguous_reading_request_reply(has_active_reading),intent="ask_tarot",next_state=ConversationState.DEFINING_QUESTION,reading_recommended=False,suggested_spread=None)
   conversation.state=decision.next_state.value;conversation.last_intent=decision.intent.value;conversation.last_action=decision.action.value;conversation.reading_recommended=False;conversation.suggested_spread=None
   session.add(Message(conversation_id=conversation.id,whatsapp_message_id=None,direction="outgoing",message_type="text",content=decision.reply));session.commit();return decision,None
  if latest_reading and is_other_topic_request(text):
   decision=ConversationDecision(reply="Dale, ¿qué querés mirar ahora?",intent="ask_tarot",next_state=ConversationState.DEFINING_QUESTION,reading_recommended=False,suggested_spread=None)
   conversation.state=decision.next_state.value;conversation.last_intent=decision.intent.value;conversation.last_action=decision.action.value;conversation.reading_recommended=False;conversation.suggested_spread=None
   session.add(Message(conversation_id=conversation.id,whatsapp_message_id=None,direction="outgoing",message_type="text",content=decision.reply));session.commit();return decision,None
  if has_active_reading and is_retrospective_topic_mapping(text,active_reading):
   decision=ConversationDecision(reply="Esa tirada no separó una posición para viajes: las cartas quedaron en situación actual, influencia o desafío y tendencia o consejo. Si querés mirar viajes en particular, conviene abrir una consulta aparte.",intent="follow_up",next_state=ConversationState.FOLLOW_UP,reading_recommended=False,suggested_spread=None)
   conversation.state=decision.next_state.value;conversation.last_intent=decision.intent.value;conversation.last_action=decision.action.value;conversation.reading_recommended=False;conversation.suggested_spread=None
   session.add(Message(conversation_id=conversation.id,whatsapp_message_id=None,direction="outgoing",message_type="text",content=decision.reply));session.commit();return decision,None
  if prior_health_context and is_explicit_reflection_request(text):
   decision=ConversationDecision(reply=health_reflection_reply(),intent="ask_tarot",next_state=ConversationState.READY_FOR_READING,reading_recommended=True,suggested_spread="one_card")
   conversation.state=decision.next_state.value;conversation.last_intent=decision.intent.value;conversation.last_action=decision.action.value;conversation.reading_recommended=True;conversation.suggested_spread="one_card"
   session.add(Message(conversation_id=conversation.id,whatsapp_message_id=None,direction="outgoing",message_type="text",content=decision.reply));session.commit();return decision,None
  memory=session.scalar(select(UserMemory).where(UserMemory.user_id==user.id)); messages=[AIMessage("system",self.prompt.read_text(encoding="utf8"))]
  if has_active_reading:
   latest_interpretation=session.scalar(select(TarotInterpretation).where(TarotInterpretation.reading_id==active_reading.id).order_by(TarotInterpretation.id.desc()))
   summary=latest_interpretation.interpretation_summary if latest_interpretation else "Interpretación pendiente"
   cards=session.scalars(select(TarotReadingCard).where(TarotReadingCard.reading_id==active_reading.id).order_by(TarotReadingCard.position_index)).all()
   card_context=", ".join(f"{card.position_label}: {json.loads(card.card_snapshot).get('name_es',card.card_id)} ({card.orientation})" for card in cards)
   messages.append(AIMessage("system",f"Hay una lectura activa (id {active_reading.id}, scope {reading_scope(active_reading)}, spread {active_reading.spread_type}). Usala para responder y profundizar con sus cartas persistidas: {card_context}. Síntesis: {summary}. No propongas una lectura nueva al final de un follow-up, por emojis ni por afirmaciones breves. Una lectura nueva sobre el mismo asunto sólo procede si la persona la pide explícitamente; un cambio claro de tema puede abrir otra consulta."))
  if current in {ConversationState.READING_ACTIVE,ConversationState.FOLLOW_UP} and is_simplification_follow_up(text):
   messages.append(AIMessage("system","El último mensaje pide una síntesis de la tirada activa. Respondé directo en 40 a 100 palabras, con uno o dos párrafos breves. No expliques carta por carta ni recites las tres; respondé la consulta original con lenguaje de tendencia o posibilidad, sin convertir emociones, intenciones o hechos de otra persona en certezas."))
  if memory: messages.append(AIMessage("system",f"Memoria: {memory.summary}"))
  messages += [AIMessage("user" if m.direction=="incoming" else "assistant",m.content) for m in history]
  quoted=[]
  for item in physical_messages:
   quote=(item.get("quoted_text") or "").strip()
   if not quote and item.get("quoted_message_id"):
    quoted_message=session.scalar(select(Message).where(Message.whatsapp_message_id==item["quoted_message_id"]))
    quote=(quoted_message.content if quoted_message else "").strip()
   if quote: quoted.append(quote)
  quoted_proposal=any(any(marker in _normalize_turn(quote) for marker in {"tirada","cartas","te parece","sacar"}) for quote in quoted)
  model_text=text if not quoted else f"La persona responde a: “{quoted[-1]}”.\nDice: “{text}”"
  messages.append(AIMessage("user",model_text))
  try:
   response=self.provider.generate(messages,purpose="conversation",options={"response_schema": ConversationDecision,"conversation_state":current.value})
   if not response.text or not response.text.strip(): raise EmptyResponseError()
   decision=ConversationDecision.model_validate_json(response.text)
   if not decision.reply.strip(): raise InvalidResponseError()
   allowed_new_reading=has_active_reading and (has_clear_scope_change(text,active_reading) or is_new_relationship_subject(text) or is_distinct_specific_question(text,active_reading) or (current is ConversationState.DEFINING_QUESTION and conversation.last_intent == "relationship") or is_clearly_new_topic(text,active_reading.spread_type) or (is_explicit_new_reading_request(text) and (is_same_topic_insistence(text) or active_reading_guard_was_shown(history))))
   if has_active_reading and not allowed_new_reading:
    if decision.reading_recommended or decision.action is ConversationAction.confirm_reading:
     decision=decision.model_copy(update={"reply":active_reading_reply(),"next_state":current if is_reading_confirmation(text) else ConversationState.FOLLOW_UP,"reading_recommended":False,"suggested_spread":None,"action":ConversationAction.none})
    elif not is_clearly_new_topic(text,active_reading.spread_type) and decision.intent.value == "follow_up":
     decision=decision.model_copy(update={"next_state":current if is_reading_confirmation(text) else ConversationState.FOLLOW_UP,"reading_recommended":False,"suggested_spread":None,"action":ConversationAction.none})
   proposal_is_ready=(current is ConversationState.READY_FOR_READING and conversation.reading_recommended and conversation.suggested_spread in SPREADS)
   if proposal_is_ready and has_clear_scope_change(text,active_reading):
    proposal_is_ready=False
    conversation.reading_recommended=False;conversation.suggested_spread=None
   confirmation_for_pending=not quoted or quoted_proposal
   if proposal_is_ready and is_reading_confirmation(text) and confirmation_for_pending and decision.action is not ConversationAction.confirm_reading:
    decision=decision.model_copy(update={"action":ConversationAction.confirm_reading,"next_state":ConversationState.READY_FOR_READING,"reading_recommended":True,"suggested_spread":conversation.suggested_spread})
   if proposal_is_ready and decision.action is ConversationAction.none and not decision.reading_recommended and not is_reading_rejection(text) and decision.next_state is ConversationState.READY_FOR_READING:
    decision=decision.model_copy(update={"reading_recommended":True,"suggested_spread":conversation.suggested_spread})
   can_confirm_reading=(proposal_is_ready and confirmation_for_pending and conversation.reading_recommended and conversation.suggested_spread in SPREADS and decision.action is ConversationAction.confirm_reading)
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
 def _audit(self,s,u,c,r,ok,error,payload,purpose="conversation",prompt_version=None):
  s.add(AICall(user_id=u,conversation_id=c,reading_id=None,purpose=purpose,provider=getattr(r,"provider","unknown"),model=getattr(r,"model","unknown"),prompt_version=prompt_version or self.prompt_version,input_tokens=getattr(r,"input_tokens",0),cached_input_tokens=getattr(r,"cached_tokens",None),output_tokens=getattr(r,"output_tokens",0),latency_ms=getattr(r,"latency_ms",0),success=ok,error_type=error,estimated_cost_usd=estimate_cost(getattr(r,"provider",""),getattr(r,"model",""),getattr(r,"input_tokens",0),getattr(r,"output_tokens",0),getattr(r,"cached_tokens",None)),debug_payload=json.dumps(payload) if self.store_debug else None))
