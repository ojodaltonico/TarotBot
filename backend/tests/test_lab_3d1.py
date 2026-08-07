import importlib.util
from pathlib import Path
import os, subprocess, sys
import pytest
from app.ai.fake_provider import FakeAIProvider
from app.models.conversation import Conversation
from app.models.user import User
from app.services.lab import LabService

spec=importlib.util.spec_from_file_location("chat_tarot",Path(__file__).parents[2]/"scripts"/"chat_tarot.py");console=importlib.util.module_from_spec(spec);spec.loader.exec_module(console)
@pytest.mark.parametrize("line,expected",[("/reading",("reading",None)),("/reading one_card",("reading","one_card")),("/reading general_three",("reading","general_three")),("/reading relationship_three",("reading","relationship_three")),("/memory",("memory",None)),("/state",("state",None)),("/refresh-memory",("refresh-memory",None)),("/reset",("reset",None)),("/help",("help",None)),("/quit",("quit",None)),("  /reading   one_card  ",("reading","one_card")),("hola",("message","hola"))])
def test_parser(line,expected):assert console.parse_command(line)==expected
@pytest.mark.parametrize("line",["/unknown","/reading bad","/reading one_card extra"])
def test_invalid_parser(line):assert console.parse_command(line)[0]=="invalid"
def test_console_renderers_hide_secrets():
 data={"state":"READY_FOR_READING","last_intent":"relationship","reading_recommended":True,"suggested_spread":"relationship_three","messages":[1,2],"last_reading_id":3,"memory":"resumen","usage":{"provider":"fake","model":"x","input_tokens":2,"output_tokens":1,"estimated_cost_usd":0}}
 assert "READY_FOR_READING" in console.state_text(data) and "resumen" in console.memory_text(data) and "provider:" in console.debug_text(data) and "GEMINI_API_KEY" not in console.debug_text(data)
 assert "No hay" in console.reading_error_text("No valid reading suggestion is available") and "/reading" in console.help_text()
def test_console_gemini_without_key_aborts_cleanly():
 env={**os.environ,"AI_PROVIDER":"gemini"};env.pop("GEMINI_API_KEY",None)
 result=subprocess.run([sys.executable,str(Path(__file__).parents[2]/"scripts"/"chat_tarot.py")],capture_output=True,text=True,env=env,timeout=10)
 assert result.returncode==2 and "GEMINI_API_KEY configurada" in result.stdout and "Traceback" not in result.stderr
@pytest.mark.parametrize("spread",["one_card","general_three","relationship_three"])
def test_persisted_suggestion_creates_exact_spread(client,spread):
 with client.app.state.SessionLocal() as s:
  u=User(whatsapp_jid=f"lab:{spread}");s.add(u);s.flush();c=Conversation(user_id=u.id,state="READY_FOR_READING",last_intent="ask_tarot",reading_recommended=True,suggested_spread=spread);s.add(c);s.commit();r,_,_=LabService(FakeAIProvider(mode="demo")).reading(s,spread);assert r.spread_type==spread
@pytest.mark.parametrize("recommended,spread,state",[(False,"one_card","READY_FOR_READING"),(True,None,"READY_FOR_READING"),(True,"bad","READY_FOR_READING"),(True,"one_card","CHATTING")])
def test_invalid_suggestions_do_not_create_reading(client,recommended,spread,state):
 with client.app.state.SessionLocal() as s:
  u=User(whatsapp_jid=f"lab:x{recommended}{spread}{state}");s.add(u);s.flush();c=Conversation(user_id=u.id,state=state,reading_recommended=recommended,suggested_spread=spread);s.add(c);s.commit()
  with pytest.raises(ValueError):LabService(FakeAIProvider(mode="demo")).reading(s,u.whatsapp_jid.removeprefix("lab:"))
