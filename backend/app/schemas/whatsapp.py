from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class InboundWhatsAppPhysicalMessage(BaseModel):
    message_id: str = Field(min_length=1, max_length=255)
    timestamp: datetime
    message_type: Literal["text", "image"]
    text: str = Field(default="", max_length=10_000)


class InboundWhatsAppMessage(InboundWhatsAppPhysicalMessage):
    sender: str = Field(min_length=1, max_length=255)
    messages: list[InboundWhatsAppPhysicalMessage] | None = Field(default=None, min_length=1, max_length=50)


class OutboundMessage(BaseModel):
    type: Literal["text", "image", "tarot_card"] = "text"
    text: str | None = Field(default=None, max_length=10_000)
    image_url: str | None = None
    card_id: str | None = None
    name: str | None = None
    orientation: str | None = None
    position: str | None = None
    image_path: str | None = None
    caption: str | None = Field(default=None, max_length=1_000)
    typing_ms: int = Field(default=0, ge=0, le=60_000)
    delay_ms: int = Field(default=0, ge=0, le=60_000)

    @model_validator(mode="after")
    def text_messages_require_text(self) -> "OutboundMessage":
        if self.type == "text" and not self.text:
            raise ValueError("text is required for text messages")
        if self.type == "image" and not self.image_path:
            raise ValueError("image_path is required for image messages")
        return self


class InboundWhatsAppResponse(BaseModel):
    messages: list[OutboundMessage]
    duplicate: bool = False
