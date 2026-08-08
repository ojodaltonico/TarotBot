from sqlalchemy import select
import pytest
from app.ai.fake_provider import FakeAIProvider
from app.models.ai import AICall, UserMemory
from app.models.conversation import Conversation
from app.models.message import Message
from app.models.user import User
from app.services.lab import LabService
from app.schemas.lab import LabReadingResponse

def make(session,key):
 u=User(whatsapp_jid=f"lab:{key}");session.add(u);session.flush();c=Conversation(user_id=u.id);session.add(c);session.flush();session.add(Message(conversation_id=c.id,direction="incoming",message_type="text",content="contexto"));session.commit();return u,c
@pytest.mark.parametrize("calls,expected",[
 ([],(0,0,0,0,0,0,None,0,0)),
 ([(True,3,2,1,0.1)],(1,1,0,3,2,1,0.1,1,0)),
 ([(False,0,0,None,None)],(1,0,1,0,0,0,None,0,1)),
 ([(False,4,3,0,0.2)],(1,0,1,4,3,0,0.2,1,0)),
 ([(True,1,2,0,0.1),(True,3,4,2,0.2)],(2,2,0,4,6,2,0.3,2,0)),
 ([(True,1,1,None,0.1),(False,2,3,0,None),(True,4,5,1,0.2)],(3,2,1,7,9,1,0.3,2,1)),
])
def test_metrics_all_cases(client,calls,expected):
 with client.app.state.SessionLocal() as s:
  u,c=make(s,"metrics")
  for ok,i,o,cached,cost in calls:s.add(AICall(user_id=u.id,conversation_id=c.id,reading_id=None,purpose="x",provider="fake",model="m",prompt_version="v",input_tokens=i,output_tokens=o,cached_input_tokens=cached,latency_ms=0,success=ok,error_type=None,estimated_cost_usd=cost,debug_payload=None))
  s.commit();m=LabService(FakeAIProvider()).status(s,"metrics")[-1]
  assert (m['total_ai_calls'],m['successful_ai_calls'],m['failed_ai_calls'],m['total_input_tokens'],m['total_output_tokens'],m['total_cached_tokens'],m['estimated_cost_usd'],m['calls_with_known_cost'],m['calls_with_unknown_cost'])==pytest.approx(expected)
def test_metrics_are_isolated(client):
 with client.app.state.SessionLocal() as s:
  a,ca=make(s,'a');b,cb=make(s,'b');s.add(AICall(user_id=a.id,conversation_id=ca.id,reading_id=None,purpose='x',provider='x',model='x',prompt_version='x',input_tokens=9,output_tokens=0,cached_input_tokens=None,latency_ms=0,success=True,error_type=None,estimated_cost_usd=None,debug_payload=None));s.commit();assert LabService(FakeAIProvider()).status(s,'b')[-1]['total_ai_calls']==0
@pytest.mark.parametrize("mode",[None,"timeout","provider_error","empty"])
def test_refresh_preserves_or_updates_memory(client,mode):
 with client.app.state.SessionLocal() as s:
  u,c=make(s,f"refresh{mode}");s.add(UserMemory(user_id=u.id,summary="anterior",version=1));s.commit();p=FakeAIProvider(response="nueva memoria" if mode is None else None,mode=mode);out=LabService(p).refresh_memory(s,u.whatsapp_jid.removeprefix('lab:'));mem=s.scalar(select(UserMemory).where(UserMemory.user_id==u.id))
  if mode is None:assert out['updated'] and mem.summary=='nueva memoria' and mem.version==2
  else:assert not out['updated'] and mem.summary=='anterior'
  assert s.scalar(select(AICall).where(AICall.user_id==u.id)) is not None
def test_refresh_new_memory_and_endpoint_missing(client):
 with client.app.state.SessionLocal() as s:
  u,c=make(s,'new');out=LabService(FakeAIProvider(response='primera')).refresh_memory(s,'new');assert out['updated'] and out['version']==1
 assert client.post('/internal/lab/users/notfound/memory/refresh').status_code==404
def test_reading_failure_diagnostic_contract_is_sanitized():
 result=LabReadingResponse(reading_id=1,spread='one_card',cards=[],interpretation=None,summary=None,state='READY_FOR_READING',interpretation_error={'category':'provider_error','provider':'gemini','model':'gemini-3.6-flash'})
 assert result.interpretation_error.category=='provider_error' and result.interpretation_error.request_id is None
