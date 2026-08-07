import json
from dataclasses import replace
import pytest
from sqlalchemy import select
from app.ai.fake_provider import FakeAIProvider
from app.models.ai import AICall, UserMemory
from app.models.conversation import Conversation
from app.models.message import Message
from app.models.tarot_reading import TarotInterpretation, TarotReadingCard
from app.models.user import User
from app.services.tarot_interpretation import PROMPT, PROMPT_VERSION, TarotInterpretationService
from app.services.tarot_readings import create_reading
from app.tarot.catalog import get_catalog

def output(): return json.dumps({"interpretation":"La tirada muestra un proceso de apertura y ajuste.","summary":"Avanzá con calma y claridad."})
def setup(session,spread):
 u=User(whatsapp_jid=f"{spread}@test");session.add(u);session.flush();c=Conversation(user_id=u.id);session.add(c);session.commit();rid,_=create_reading(session,user_id=u.id,conversation_id=c.id,spread_type=spread,question="¿Qué necesito mirar?",seed=f"{spread}-seed");return u,c,rid
@pytest.mark.parametrize("spread,count",[("one_card",1),("general_three",3),("relationship_three",3)])
def test_interpretation_uses_persisted_cards_and_persists_result(client,spread,count):
 with client.app.state.SessionLocal() as s:
  u,c,rid=setup(s,spread);s.add_all([UserMemory(user_id=u.id,summary="Memoria relevante",version=1),Message(conversation_id=c.id,direction="incoming",message_type="text",content="historial relevante")]);s.commit()
  fake=FakeAIProvider(response=output(),usage={"provider":"gemini","model":"gemini-2.5-flash","input_tokens":11,"output_tokens":6})
  result=TarotInterpretationService(fake,recent_messages=3,store_debug=True).interpret_reading(s,rid,u.id,c.id)
  cards=s.scalars(select(TarotReadingCard).where(TarotReadingCard.reading_id==rid).order_by(TarotReadingCard.position_index)).all(); payload=json.loads(fake.requests[0][0][-1].content)
  assert result.interpretation_summary=="Avanzá con calma y claridad." and result.prompt_version==PROMPT_VERSION
  assert [(x["card_id"],x["orientation"],x["position_key"]) for x in payload["cards"]]==[(x.card_id,x.orientation,x.position_key) for x in cards]
  assert len(payload["cards"])==count and payload["question"]=="¿Qué necesito mirar?"
  assert fake.requests[0][0][1].content=="Memoria: Memoria relevante" and any(m.content=="historial relevante" for m in fake.requests[0][0])
  call=s.scalar(select(AICall).where(AICall.reading_id==rid));assert call.success and call.purpose=="reading_interpretation" and call.estimated_cost_usd==0 and call.debug_payload
def test_snapshot_is_used_and_result_is_idempotent(client):
 with client.app.state.SessionLocal() as s:
  u,c,rid=setup(s,"general_three");card=s.scalars(select(TarotReadingCard).where(TarotReadingCard.reading_id==rid)).first();snap=json.loads(card.card_snapshot);fake=FakeAIProvider(response=output());catalog=get_catalog();original=catalog.get(card.card_id);old_cards,old_by_id=catalog.cards,catalog._by_id
  try:
   changed=replace(original,name_es="CATALOGO ALTERADO");catalog.cards=tuple(changed if x.id==original.id else x for x in catalog.cards);catalog._by_id={**catalog._by_id,original.id:changed}
   result=TarotInterpretationService(fake).interpret_reading(s,rid,u.id,c.id);again=TarotInterpretationService(fake).interpret_reading(s,rid,u.id,c.id)
   payload=json.loads(fake.requests[0][0][-1].content);assert payload["cards"][0]["snapshot"]["name_es"]==snap["name_es"] and payload["cards"][0]["snapshot"]["name_es"]!="CATALOGO ALTERADO" and result.id==again.id and len(fake.requests)==1
  finally: catalog.cards,catalog._by_id=old_cards,old_by_id
@pytest.mark.parametrize(("mode","error_type"),[("timeout","timeout"),("provider_error","provider_error"),("empty","empty_response"),("invalid_schema","validation_error")])
def test_failure_ownership_and_prompt_integrity(client,mode,error_type):
 with client.app.state.SessionLocal() as s:
  u,c,rid=setup(s,"one_card");result=TarotInterpretationService(FakeAIProvider(mode=mode)).interpret_reading(s,rid,u.id,c.id)
  assert result is None and not s.scalars(select(TarotInterpretation).where(TarotInterpretation.reading_id==rid)).all()
  call=s.scalar(select(AICall).where(AICall.reading_id==rid));assert not call.success and call.error_type==error_type
  with pytest.raises(ValueError): TarotInterpretationService(FakeAIProvider(response=output())).interpret_reading(s,rid,u.id+1,c.id)
 prompt=PROMPT.read_text(encoding="utf8").lower();assert all(x in prompt for x in ["no inventes cartas","no cambies posiciones ni orientaciones","certezas absolutas","síntesis concreta","salud, embarazo, muerte, delitos, apuestas, inversiones"])
