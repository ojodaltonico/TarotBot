from sqlalchemy import delete, func, select
from app.models.ai import AICall, UserMemory
from app.models.conversation import Conversation
from app.models.message import Message
from app.models.tarot_reading import TarotInterpretation, TarotReading, TarotReadingCard
from app.models.user import User, utc_now
from app.services.conversation import ConversationService
from app.services.memory import MemoryService
from app.services.tarot_interpretation import TarotInterpretationService
from app.services.tarot_readings import create_reading
from app.tarot.spreads import SPREADS

class LabService:
 def __init__(self,provider,store_debug=False): self.provider=provider;self.store_debug=store_debug
 def user(self,s,key):
  jid=f"lab:{key}";u=s.scalar(select(User).where(User.whatsapp_jid==jid))
  if not u:u=User(whatsapp_jid=jid,last_seen_at=utc_now());s.add(u);s.flush()
  c=s.scalar(select(Conversation).where(Conversation.user_id==u.id,Conversation.is_active.is_(True)).order_by(Conversation.id.desc()))
  if not c:c=Conversation(user_id=u.id);s.add(c);s.flush()
  s.commit();return u,c
 def chat(self,s,key,message):
  u,c=self.user(s,key);d,r=ConversationService(self.provider,store_debug=self.store_debug).chat(s,u,c,message);return u,c,d,r
 def reading(self,s,key,spread=None,question=None):
  u,c=self.user(s,key)
  if spread is None:
   if not c.reading_recommended or c.suggested_spread not in SPREADS: raise ValueError("No valid reading suggestion is available")
   spread=c.suggested_spread
  if spread not in SPREADS: raise ValueError("Invalid spread")
  if c.state!="READY_FOR_READING": raise ValueError("Conversation is not ready for a reading")
  rid,_=create_reading(s,user_id=u.id,conversation_id=c.id,spread_type=spread,question=question)
  result=TarotInterpretationService(self.provider,store_debug=self.store_debug).interpret_reading(s,rid,u.id,c.id)
  if result:c.state="READING_ACTIVE";s.commit()
  return s.get(TarotReading,rid),result,c
 def refresh_memory(self,s,key):
  u=s.scalar(select(User).where(User.whatsapp_jid==f"lab:{key}"))
  if not u: raise ValueError("Lab user not found")
  c=s.scalar(select(Conversation).where(Conversation.user_id==u.id,Conversation.is_active.is_(True)).order_by(Conversation.id.desc()));before=s.scalar(select(UserMemory).where(UserMemory.user_id==u.id));version=before.version if before else None;memory=MemoryService(self.provider,store_debug=self.store_debug).refresh_memory(s,u.id,c.id,force=True);return {"updated":bool(memory and memory.version!=version),"version":memory.version if memory else None,"summary":memory.summary if memory else None,"reason":None if memory and memory.version!=version else "No se pudo actualizar la memoria"}
 def status(self,s,key):
  u,c=self.user(s,key);msgs=s.scalars(select(Message).where(Message.conversation_id==c.id).order_by(Message.id.desc()).limit(10)).all();read=s.scalar(select(TarotReading).where(TarotReading.user_id==u.id).order_by(TarotReading.id.desc()));interp=s.scalar(select(TarotInterpretation).join(TarotReading).where(TarotReading.user_id==u.id).order_by(TarotInterpretation.id.desc()));calls=s.scalars(select(AICall).where(AICall.user_id==u.id)).all();known=[x for x in calls if x.estimated_cost_usd is not None];return u,c,msgs,read,interp,{"calls":len(calls),"total_ai_calls":len(calls),"successful_ai_calls":sum(x.success for x in calls),"failed_ai_calls":sum(not x.success for x in calls),"total_input_tokens":sum(x.input_tokens for x in calls),"total_output_tokens":sum(x.output_tokens for x in calls),"total_cached_tokens":sum(x.cached_input_tokens or 0 for x in calls),"estimated_cost_usd":sum(x.estimated_cost_usd for x in known) if known else None,"calls_with_known_cost":len(known),"calls_with_unknown_cost":len(calls)-len(known)}
 def reset(self,s,key):
  u=s.scalar(select(User).where(User.whatsapp_jid==f"lab:{key}"))
  if not u:return False
  rids=select(TarotReading.id).where(TarotReading.user_id==u.id);cids=select(Conversation.id).where(Conversation.user_id==u.id)
  s.execute(delete(AICall).where(AICall.user_id==u.id));s.execute(delete(TarotInterpretation).where(TarotInterpretation.reading_id.in_(rids)));s.execute(delete(TarotReadingCard).where(TarotReadingCard.reading_id.in_(rids)));s.execute(delete(TarotReading).where(TarotReading.user_id==u.id));s.execute(delete(Message).where(Message.conversation_id.in_(cids)));s.execute(delete(UserMemory).where(UserMemory.user_id==u.id));s.execute(delete(Conversation).where(Conversation.user_id==u.id));s.execute(delete(User).where(User.id==u.id));s.commit();return True
