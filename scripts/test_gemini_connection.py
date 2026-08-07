"""Prueba manual y explícita de Gemini; nunca se usa desde tests."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.ai.gemini_provider import GeminiProvider
from app.ai.provider import AIMessage

key = os.getenv("GEMINI_API_KEY")
if not key:
    raise SystemExit("Definí GEMINI_API_KEY en .env o en el entorno antes de ejecutar este script.")
provider = GeminiProvider(api_key=key, model=os.getenv("AI_CHAT_MODEL", "gemini-2.5-flash"))
response = provider.generate([AIMessage("user", "Respondé exactamente: conexión correcta")], purpose="connection_test")
print(f"Modelo: {response.model}; tokens: {response.input_tokens}+{response.output_tokens}")
print(response.text)
