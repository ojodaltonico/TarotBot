from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class AIMessage:
    role: str
    content: str


@dataclass(frozen=True)
class AIResponse:
    text: str | None
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int | None = None
    latency_ms: int = 0
    provider: str = "unknown"
    request_id: str | None = None


class AIProviderError(Exception):
    """Provider failure with optional usage metadata and a stable category."""

    def __init__(self, category: str = "provider_error", response: AIResponse | None = None, diagnostics: dict | None = None):
        super().__init__(category)
        self.category = category
        self.response = response
        self.diagnostics = diagnostics or {}


class AIProvider(ABC):
    @abstractmethod
    def generate(self, messages: list[AIMessage], *, purpose: str, options: dict | None = None) -> AIResponse: ...
