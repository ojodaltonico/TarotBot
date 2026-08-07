from dataclasses import dataclass
from typing import Literal


Orientation = Literal["upright", "reversed"]


@dataclass(frozen=True)
class TarotCard:
    id: str
    name_es: str
    name_en: str
    card_type: Literal["major", "minor"]
    number: int | None
    suit: str | None
    rank: str | None
    image_path: str
    upright_meaning: str
    reversed_meaning: str
    upright_keywords: tuple[str, ...]
    reversed_keywords: tuple[str, ...]
    context_meanings: dict[str, dict[str, str]]


@dataclass(frozen=True)
class DrawnCard:
    card: TarotCard
    position_index: int
    position_key: str
    position_label: str
    orientation: Orientation


@dataclass(frozen=True)
class DrawResult:
    spread_type: str
    spread_label: str
    cards: tuple[DrawnCard, ...]
    audit_metadata: dict[str, object]
