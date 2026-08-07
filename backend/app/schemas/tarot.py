from typing import Literal

from pydantic import BaseModel, Field


class TarotCardSummary(BaseModel):
    id: str
    name_es: str
    name_en: str
    card_type: Literal["major", "minor"]
    number: int | None
    suit: str | None
    rank: str | None
    image_path: str


class SpreadSummary(BaseModel):
    key: str
    label: str
    positions: list[dict[str, str]]


class TestDrawRequest(BaseModel):
    spread_type: str = "one_card"
    seed: int | str | None = None
    reversed_enabled: bool = True
    reversed_probability: float = Field(default=0.5, ge=0, le=1)


class DrawnCardResponse(BaseModel):
    position: str
    position_label: str
    card_id: str
    name: str
    orientation: Literal["upright", "reversed"]
    image_path: str


class TestDrawResponse(BaseModel):
    spread: str
    spread_label: str
    cards: list[DrawnCardResponse]
    audit_metadata: dict[str, object]
