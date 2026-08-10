from pathlib import Path
from sqlalchemy import select
from app.ai.provider import AIMessage, AIProvider, AIProviderError
from app.ai.costs import estimate_cost
from app.models.message import Message
from app.models.tarot_reading import TarotInterpretation, TarotReading
from app.repositories.ai_repository import add_call, get_memory, upsert_memory

PROMPT_VERSION="memory_v1"
PROMPT=Path(__file__).parents[1]/"ai"/"prompts"/"memory_v1.txt"
class MemoryService:
 def __init__(self, provider: AIProvider, interval=8, store_debug=False): self.provider=provider; self.interval=interval; self.store_debug=store_debug
 def get_memory(self,session,user_id): return get_memory(session,user_id)
 def create_or_update_memory(self,session,user_id,summary):
  if not summary or not summary.strip(): return get_memory(session,user_id)
  value=upsert_memory(session,user_id,summary.strip()); session.commit(); return value
 def refresh_memory(self,session,user_id,conversation_id,force=False):
  messages=list(reversed(session.scalars(select(Message).where(Message.conversation_id==conversation_id).order_by(Message.id.desc()).limit(self.interval)).all()))
  if not force and len(messages)<self.interval: return get_memory(session,user_id)
  context="\n".join(f"{m.direction}: {m.content}" for m in messages)
  latest_reading=session.scalar(select(TarotReading).where(TarotReading.user_id==user_id, TarotReading.conversation_id==conversation_id).order_by(TarotReading.id.desc()))
  if latest_reading:
   interpretation=session.scalar(select(TarotInterpretation).where(TarotInterpretation.reading_id==latest_reading.id).order_by(TarotInterpretation.id.desc()))
   if interpretation:
    context += f"\nlectura_persistida: id={latest_reading.id}; spread={latest_reading.spread_type}; resumen={interpretation.interpretation_summary}"
  try:
   response=self.provider.generate([AIMessage("system",PROMPT.read_text(encoding="utf8")),AIMessage("user",context)],purpose="memory_summary",options={})
   if not response.text or not response.text.strip(): raise ValueError("empty_memory_summary")
   memory=upsert_memory(session,user_id,response.text.strip())
   self._audit(session,user_id,conversation_id,response,True,None,{"history":context}); session.commit(); return memory
  except Exception as error:
   self._audit(session,user_id,conversation_id,getattr(error,"response",None),False,error.category if isinstance(error,AIProviderError) else type(error).__name__,getattr(error,"diagnostics",None)); session.commit(); return get_memory(session,user_id)
 def _audit(self,s,u,c,r,ok,error,payload):
  add_call(s,user_id=u,conversation_id=c,reading_id=None,purpose="memory_summary",provider=getattr(r,"provider","unknown"),model=getattr(r,"model","unknown"),prompt_version=PROMPT_VERSION,input_tokens=getattr(r,"input_tokens",0),cached_input_tokens=getattr(r,"cached_tokens",None),output_tokens=getattr(r,"output_tokens",0),latency_ms=getattr(r,"latency_ms",0),success=ok,error_type=error,estimated_cost_usd=estimate_cost(getattr(r,"provider",""),getattr(r,"model",""),getattr(r,"input_tokens",0),getattr(r,"output_tokens",0),getattr(r,"cached_tokens",None)),debug_payload=str(payload) if self.store_debug else None)
