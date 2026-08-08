"""Interactive local laboratory client for the internal lab API."""
import argparse,json,urllib.request,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"backend"))
from app.core.config import get_settings
BASE="http://127.0.0.1:5001/internal/lab";KEY="local_test";SPREADS={"one_card","general_three","relationship_three"}
def parse_command(line):
 p=line.strip().split()
 if not p:return ("message",line)
 if not p[0].startswith("/"):return ("message",line.strip())
 if p[0]=="/reading":return ("reading",None) if len(p)==1 else (("reading",p[1]) if len(p)==2 and p[1] in SPREADS else ("invalid","Uso: /reading [one_card|general_three|relationship_three]"))
 if p[0] in {"/memory","/state","/refresh-memory","/reset","/help","/quit"} and len(p)==1:return (p[0][1:],None)
 return ("invalid","Comando desconocido")
def state_text(data):return f"Estado: {data.get('state','-')}\nIntent: {data.get('last_intent','-')}\nTirada sugerida: {data.get('suggested_spread','-')}\nMensajes: {len(data.get('messages',[]))}\nÚltima lectura: {data.get('last_reading_id','-')}"
def memory_text(data):return data.get("memory") or "Todavía no hay memoria."
def help_text():return "Comandos: /reading [one_card|general_three|relationship_three], /memory, /state, /refresh-memory, /reset, /help, /quit"
def reading_error_text(error):
 text=str(error)
 if "suggestion" in text:return "No hay una tirada recomendada disponible."
 if "ready" in text:return "El estado actual no permite crear una tirada."
 if "Invalid spread" in text:return "El spread indicado no es válido."
 return "No se pudo crear o interpretar la tirada."
def debug_text(data):
 u=data.get("usage") or {};return "[debug]\nstate: %s\nintent: %s\nreading_recommended: %s\nsuggested_spread: %s\nprovider: %s\nmodel: %s\ninput_tokens: %s\noutput_tokens: %s\nestimated_cost_usd: %s\naccumulated_cost_usd: -\nmemory_version: -\n[/debug]"%(data.get("state","-"),data.get("intent","-"),data.get("reading_recommended","-"),data.get("suggested_spread","-"),u.get("provider","-"),u.get("model","-"),u.get("input_tokens","-"),u.get("output_tokens","-"),u.get("estimated_cost_usd","-"))
def call(path,data=None):
 req=urllib.request.Request(BASE+path,data=json.dumps(data).encode() if data is not None else None,headers={"Content-Type":"application/json"},method="POST" if data is not None else "GET");return json.loads(urllib.request.urlopen(req).read())
def main():
 parser=argparse.ArgumentParser();parser.add_argument("--debug",action="store_true");debug=parser.parse_args().debug
 settings=get_settings()
 if settings.ai_provider=="gemini" and not settings.gemini_api_key:print("Gemini está seleccionado pero no hay GEMINI_API_KEY configurada.");return 2
 print("TarotBot - laboratorio\n")
 while True:
  kind,arg=parse_command(input("Vos: "))
  if kind=="quit":return 0
  if kind=="help":print(help_text());continue
  if kind=="invalid":print(arg);continue
  if kind=="reading":
   try:print(call(f"/users/{KEY}/reading",{"spread_type":arg}))
   except Exception as error:print(reading_error_text(error))
   continue
  if kind=="memory":print(memory_text(call(f"/users/{KEY}")));continue
  if kind=="state":print(state_text(call(f"/users/{KEY}")));continue
  if kind=="refresh-memory":print(call(f"/users/{KEY}/memory/refresh",{}));continue
  if kind=="reset":
   if input("¿Resetear este usuario de laboratorio? [s/N] ").lower()=="s":print(call(f"/users/{KEY}/reset",{}))
   continue
  data=call("/chat",{"user_key":KEY,"message":arg});print("Tarotista:",data["reply"]);print(debug_text(data) if debug else "")
if __name__=="__main__":raise SystemExit(main() or 0)
