import json
from pathlib import Path
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from app.ai.costs import estimate_cost
from app.ai.provider import AIMessage, AIProvider, AIProviderError
from app.core.config import get_settings
from app.models.ai import AICall, UserMemory
from app.models.message import Message
from app.models.tarot_reading import TarotInterpretation, TarotReading, TarotReadingCard

PROMPT_VERSION="tarot_interpretation_v1"; PROMPT=Path(__file__).parents[1]/"ai"/"prompts"/"tarot_interpretation_v1.txt"
class InterpretationOutput(BaseModel):
 interpretation: str=Field(min_length=1); summary: str=Field(min_length=1)
class TarotInterpretationService:
 def __init__(self,provider:AIProvider,recent_messages=None,store_debug=False): self.provider=provider;self.recent_messages=get_settings().ai_recent_messages if recent_messages is None else recent_messages;self.store_debug=store_debug
 def interpret_reading(self,session,reading_id,user_id,conversation_id,force=False):
  reading=session.get(TarotReading,reading_id)
  if reading is None or reading.user_id!=user_id or reading.conversation_id!=conversation_id: raise ValueError("Reading not found for user and conversation")
  existing=session.scalar(select(TarotInterpretation).where(TarotInterpretation.reading_id==reading_id).order_by(TarotInterpretation.id.desc()))
  if existing and not force:return existing
  cards=session.scalars(select(TarotReadingCard).where(TarotReadingCard.reading_id==reading_id).order_by(TarotReadingCard.position_index)).all()
  history=list(reversed(session.scalars(select(Message).where(Message.conversation_id==conversation_id,Message.message_type!="internal").order_by(Message.id.desc()).limit(self.recent_messages)).all()))
  memory=session.scalar(select(UserMemory).where(UserMemory.user_id==user_id)); payload={"question":reading.question,"spread_type":reading.spread_type,"cards":[{"position_index":c.position_index,"position_key":c.position_key,"position_label":c.position_label,"card_id":c.card_id,"orientation":c.orientation,"snapshot":json.loads(c.card_snapshot)} for c in cards]}
  messages=[AIMessage("system",PROMPT.read_text(encoding="utf8"))]
  if memory:messages.append(AIMessage("system",f"Memoria: {memory.summary}"))
  messages += [AIMessage("user" if m.direction=="incoming" else "assistant",m.content) for m in history]
  messages.append(AIMessage("user",json.dumps(payload,ensure_ascii=False)))
  response=None
  try:
   response=self.provider.generate(messages,purpose="reading_interpretation",options={"response_schema":InterpretationOutput})
   if not response.text or not response.text.strip(): raise ValueError("empty_response")
   output=InterpretationOutput.model_validate_json(response.text)
   result=TarotInterpretation(reading_id=reading_id,interpretation_text=output.interpretation,interpretation_summary=output.summary,prompt_version=PROMPT_VERSION,model=response.model,provider=response.provider);session.add(result);self._audit(session,user_id,conversation_id,reading_id,response,True,None,{"cards":len(cards)});session.commit();return result
  except Exception as error:
   self._audit(session,user_id,conversation_id,reading_id,getattr(error,"response",None) or response,False,self._error_type(error),None);session.commit();return None
 def _error_type(self,error):
  if isinstance(error,AIProviderError): return error.category
  if isinstance(error,ValidationError): return "validation_error"
  if isinstance(error,ValueError): return "empty_response"
  if isinstance(error,TimeoutError): return "timeout"
  return "provider_error"
 def _audit(self,s,u,c,rid,r,ok,error,payload):
  s.add(AICall(user_id=u,conversation_id=c,reading_id=rid,purpose="reading_interpretation",provider=getattr(r,"provider","unknown"),model=getattr(r,"model","unknown"),prompt_version=PROMPT_VERSION,input_tokens=getattr(r,"input_tokens",0),cached_input_tokens=getattr(r,"cached_tokens",None),output_tokens=getattr(r,"output_tokens",0),latency_ms=getattr(r,"latency_ms",0),success=ok,error_type=error,estimated_cost_usd=estimate_cost(getattr(r,"provider",""),getattr(r,"model",""),getattr(r,"input_tokens",0),getattr(r,"output_tokens",0),getattr(r,"cached_tokens",None)),debug_payload=json.dumps(payload) if self.store_debug else None))
