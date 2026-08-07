import json
import pytest
from app.ai.fake_provider import FakeAIProvider
from app.conversation.schemas import ConversationDecision, ConversationState, Intent
from app.models.conversation import Conversation
from app.models.user import User
from app.services.conversation import ALLOWED_TRANSITIONS, ConversationService

def response(state, intent="greeting"):
 return json.dumps({"reply":"respuesta válida","intent":intent,"next_state":state.value,"reading_recommended":False,"suggested_spread":None,"memory_candidates":[]})
def create(session, state, suffix=""):
 user=User(whatsapp_jid=f"{state.value}-{suffix}@test");session.add(user);session.flush();conversation=Conversation(user_id=user.id,state=state.value);session.add(conversation);session.commit();return user,conversation

def test_every_state_transition_is_persisted_or_safely_rejected(client):
 combinations=0
 with client.app.state.SessionLocal() as session:
  for current in ConversationState:
   for proposed in ConversationState:
    combinations+=1
    user,conversation=create(session,current,combinations)
    service=ConversationService(FakeAIProvider(response(proposed)),recent_messages=1)
    result,_=service.chat(session,user,conversation,f"{current.value} a {proposed.value}")
    expected=proposed if proposed in ALLOWED_TRANSITIONS[current] else current
    assert result.next_state==expected
    assert session.get(Conversation,conversation.id).state==expected.value
 assert combinations==36

def test_invalid_state_schema_uses_fallback_without_state_change(client):
 with client.app.state.SessionLocal() as session:
  user,conversation=create(session,ConversationState.NEW)
  invalid=json.dumps({"reply":"ok","intent":"greeting","next_state":"BROKEN","reading_recommended":False,"suggested_spread":None,"memory_candidates":[]})
  result,_=ConversationService(FakeAIProvider(invalid)).chat(session,user,conversation,"hola")
  assert result.intent==Intent.unclear and session.get(Conversation,conversation.id).state=="NEW"

@pytest.mark.parametrize("intent",list(Intent))
def test_all_valid_intents_validate_and_survive_service(client,intent):
 assert ConversationDecision.model_validate_json(response(ConversationState.CHATTING,intent.value)).intent==intent
 with client.app.state.SessionLocal() as session:
  user,conversation=create(session,ConversationState.NEW)
  result,_=ConversationService(FakeAIProvider(response(ConversationState.CHATTING,intent.value))).chat(session,user,conversation,"hola")
  assert result.intent==intent

@pytest.mark.parametrize("invalid",["romance_prediction","",None])
def test_invalid_intents_fallback_without_corrupting_state(client,invalid):
 payload={"reply":"ok","intent":invalid,"next_state":"CHATTING","reading_recommended":False,"suggested_spread":None,"memory_candidates":[]}
 with client.app.state.SessionLocal() as session:
  user,conversation=create(session,ConversationState.NEW)
  result,_=ConversationService(FakeAIProvider(json.dumps(payload))).chat(session,user,conversation,"hola")
  assert result.intent==Intent.unclear and session.get(Conversation,conversation.id).state=="NEW"
