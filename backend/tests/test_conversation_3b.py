import json
from sqlalchemy import select
from app.ai.fake_provider import FakeAIProvider
from app.conversation.schemas import ConversationState
from app.models.ai import AICall, UserMemory
from app.models.conversation import Conversation
from app.models.message import Message
from app.models.user import User
from app.services.conversation import ConversationService

def setup(s):
 u=User(whatsapp_jid="chat@test");s.add(u);s.flush();c=Conversation(user_id=u.id);s.add(c);s.commit();return u.id,c.id
def decision(**kw): return json.dumps({"reply":"Hola, contame qué querés mirar.","intent":"greeting","next_state":"CHATTING","reading_recommended":False,"suggested_spread":None,"memory_candidates":[],**kw})
def test_chat_persists_messages_state_and_audit(client):
 with client.app.state.SessionLocal() as s:
  u,c=setup(s); d,r=ConversationService(FakeAIProvider(decision()),recent_messages=1).chat(s,s.get(User,u),s.get(Conversation,c),"hola")
  assert d.intent.value=="greeting" and s.get(Conversation,c).state=="CHATTING"
  assert len(s.scalars(select(Message).where(Message.conversation_id==c)).all())==2
  assert s.scalar(select(AICall).where(AICall.conversation_id==c)).success
def test_invalid_spread_and_error_are_safe(client):
 with client.app.state.SessionLocal() as s:
  u,c=setup(s); d,_=ConversationService(FakeAIProvider(decision(reading_recommended=True,suggested_spread="inventado"))).chat(s,s.get(User,u),s.get(Conversation,c),"tirada")
  assert not d.reading_recommended and d.suggested_spread is None
  d,_=ConversationService(FakeAIProvider(error=TimeoutError())).chat(s,s.get(User,u),s.get(Conversation,c),"otra")
  assert d.intent.value=="unclear" and not s.scalar(select(AICall).where(AICall.success.is_(False))) is None
def test_memory_and_history_are_sent(client):
 with client.app.state.SessionLocal() as s:
  u,c=setup(s);s.add(UserMemory(user_id=u,summary="Consulta por Martín",version=1));s.add(Message(conversation_id=c,direction="outgoing",message_type="text",content="anterior"));s.commit()
  fake=FakeAIProvider(decision(intent="relationship"));ConversationService(fake,recent_messages=1).chat(s,s.get(User,u),s.get(Conversation,c),"nuevo")
  contents=[m.content for m in fake.requests[0][0]];assert "Memoria: Consulta por Martín" in contents and contents[-2:]==["anterior","nuevo"]
