"""Small manual Gemini stability check; never invoked by pytest."""
import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
VENV_PYTHON = ROOT_DIR / "backend" / ".venv" / "Scripts" / "python.exe"
if sys.prefix == sys.base_prefix and VENV_PYTHON.exists():
    os.execv(str(VENV_PYTHON), [str(VENV_PYTHON), str(Path(__file__).resolve()), *sys.argv[1:]])

sys.path.insert(0, str(ROOT_DIR / "backend"))

from pydantic import BaseModel, Field
from app.ai.gemini_provider import GeminiProvider
from app.ai.provider import AIMessage, AIProviderError
from app.core.config import get_settings


class StabilityOutput(BaseModel):
    answer: str = Field(min_length=1)


def result_for(index: int, response=None, error: AIProviderError | None = None) -> dict:
    if error is not None:
        return {
            "call": index,
            "success": False,
            "category": error.category,
            "latency_ms": error.response.latency_ms if error.response else None,
            "tokens": None if error.response is None else {"input": error.response.input_tokens, "output": error.response.output_tokens},
            "diagnostics": error.diagnostics,
        }
    return {
        "call": index,
        "success": True,
        "latency_ms": response.latency_ms,
        "tokens": {"input": response.input_tokens, "output": response.output_tokens},
        "request_id": response.request_id,
    }


def run(mode: str, count: int, delay: float) -> list[dict]:
    settings = get_settings()
    provider = GeminiProvider(
        api_key=settings.gemini_api_key,
        model=settings.ai_chat_model,
        timeout_seconds=settings.ai_timeout_seconds,
        enabled=settings.ai_enabled,
        trust_env_proxy=settings.ai_trust_env_proxy,
    )
    results = []
    options = {"response_schema": StabilityOutput} if mode == "structured" else {}
    prompt = "Respondé únicamente OK." if mode == "text" else "Respondé JSON con answer igual a OK."
    for index in range(1, count + 1):
        try:
            response = provider.generate([AIMessage("user", prompt)], purpose=f"stability_{mode}", options=options)
            results.append(result_for(index, response=response))
        except AIProviderError as error:
            results.append(result_for(index, error=error))
        if index < count:
            time.sleep(delay)
    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=5)
    parser.add_argument("--delay", type=float, default=1.0)
    parser.add_argument("--structured", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.count <= 10:
        parser.error("--count must be between 1 and 10")
    if args.delay < 0 or args.delay > 10:
        parser.error("--delay must be between 0 and 10 seconds")
    settings = get_settings()
    if settings.ai_provider != "gemini" or not settings.gemini_api_key:
        raise SystemExit("Gemini must be configured locally before this manual check.")
    mode = "structured" if args.structured else "text"
    print(json.dumps({"provider": "gemini", "model": settings.ai_chat_model, "mode": mode, "count": args.count, "results": run(mode, args.count, args.delay)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
