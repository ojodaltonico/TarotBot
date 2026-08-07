from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class InboundWhatsAppMessage(BaseModel):
    sender: str = Field(min_length=1, max_length=255)
    message_id: str = Field(min_length=1, max_length=255)
    timestamp: datetime
    message_type: Literal["text", "image"]
    text: str = Field(default="", max_length=10_000)


class OutboundMessage(BaseModel):
    type: Literal["text", "image"] = "text"
    text: str | None = Field(default=None, max_length=10_000)
    image_url: str | None = None
    typing_ms: int = Field(default=0, ge=0, le=10_000)
    delay_ms: int = Field(default=0, ge=0, le=10_000)

    @model_validator(mode="after")
    def text_messages_require_text(self) -> "OutboundMessage":
        if self.type == "text" and not self.text:
            raise ValueError("text is required for text messages")
        return self


class InboundWhatsAppResponse(BaseModel):
    messages: list[OutboundMessage]
    duplicate: bool = False
