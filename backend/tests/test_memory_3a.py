from sqlalchemy import select
from app.ai.fake_provider import FakeAIProvider
from app.ai.provider import AIResponse
from app.ai.costs import estimate_cost
from app.models.ai import AICall, UserMemory
from app.models.conversation import Conversation
from app.models.message import Message
from app.models.user import User
from app.services.memory import MemoryService

def setup(session):
 u=User(whatsapp_jid="memory@test"); session.add(u); session.flush(); c=Conversation(user_id=u.id); session.add(c); session.flush()
 for i in range(3): session.add(Message(conversation_id=c.id,whatsapp_message_id=None,direction="incoming",message_type="text",content=f"dato {i}"))
 session.commit(); return u,c
def test_memory_create_update_recover_and_audit(client):
 with client.app.state.SessionLocal() as s:
  u,c=setup(s); user_id=u.id; p=FakeAIProvider("Consulta por Martín; quedó una pregunta pendiente."); service=MemoryService(p,interval=3,store_debug=True); memory=service.refresh_memory(s,user_id,c.id)
  assert memory.version==1 and "Martín" in memory.summary
  memory=service.create_or_update_memory(s,u.id,"Resumen actualizado"); assert memory.version==2
 with client.app.state.SessionLocal() as s:
  assert s.scalar(select(UserMemory).where(UserMemory.user_id==user_id)).summary=="Resumen actualizado"
  call=s.scalar(select(AICall).where(AICall.user_id==user_id)); assert call.success and call.input_tokens==10 and call.debug_payload
def test_memory_failure_and_empty_keep_previous(client):
 with client.app.state.SessionLocal() as s:
  u,c=setup(s); service=MemoryService(FakeAIProvider("estable"),interval=3); service.refresh_memory(s,u.id,c.id)
  MemoryService(FakeAIProvider(error=TimeoutError()),interval=3).refresh_memory(s,u.id,c.id,force=True)
  MemoryService(FakeAIProvider(""),interval=3).refresh_memory(s,u.id,c.id,force=True)
  assert service.get_memory(s,u.id).summary=="estable"
  assert len(s.scalars(select(AICall).where(AICall.success.is_(False))).all())==2
def test_cost_known_unknown_and_debug_off(client):
 assert estimate_cost("gemini","gemini-2.5-flash",10,10)==0
 assert estimate_cost("gemini","other",10,10) is None
 with client.app.state.SessionLocal() as s:
  u,c=setup(s); MemoryService(FakeAIProvider("x"),interval=3,store_debug=False).refresh_memory(s,u.id,c.id)
  assert s.scalar(select(AICall).where(AICall.success.is_(True))).debug_payload is None
