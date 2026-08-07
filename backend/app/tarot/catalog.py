import json
from functools import lru_cache
from pathlib import Path

from app.tarot.models import TarotCard


DATA_PATH = Path(__file__).parent / "data" / "deck.json"


class DeckValidationError(ValueError):
    pass


class TarotCatalog:
    def __init__(self, *, version: str, cards: tuple[TarotCard, ...]):
        if len(cards) != 78:
            raise DeckValidationError(f"El mazo debe tener 78 cartas; recibió {len(cards)}")
        ids = [card.id for card in cards]
        if len(ids) != len(set(ids)):
            raise DeckValidationError("El mazo contiene IDs duplicados")
        if sum(card.card_type == "major" for card in cards) != 22:
            raise DeckValidationError("El mazo debe incluir 22 arcanos mayores")
        if sum(card.card_type == "minor" for card in cards) != 56:
            raise DeckValidationError("El mazo debe incluir 56 arcanos menores")
        for suit in ("wands", "cups", "swords", "pentacles"):
            if sum(card.suit == suit for card in cards) != 14:
                raise DeckValidationError(f"El palo {suit} debe incluir 14 cartas")
        self.version = version
        self.cards = cards
        self._by_id = {card.id: card for card in cards}

    def get(self, card_id: str) -> TarotCard:
        try:
            return self._by_id[card_id]
        except KeyError as error:
            raise KeyError(f"Carta inexistente: {card_id}") from error


def _parse_card(raw: dict[str, object]) -> TarotCard:
    required = {
        "id", "name_es", "name_en", "card_type", "number", "suit", "rank", "image_path",
        "upright_meaning", "reversed_meaning", "upright_keywords", "reversed_keywords",
    }
    missing = required.difference(raw)
    if missing:
        raise DeckValidationError(f"Carta incompleta: faltan {', '.join(sorted(missing))}")
    card_type = raw["card_type"]
    if card_type not in {"major", "minor"}:
        raise DeckValidationError(f"Tipo de carta inválido: {card_type}")
    return TarotCard(
        id=str(raw["id"]), name_es=str(raw["name_es"]), name_en=str(raw["name_en"]),
        card_type=card_type, number=raw["number"], suit=raw["suit"], rank=raw["rank"],
        image_path=str(raw["image_path"]), upright_meaning=str(raw["upright_meaning"]),
        reversed_meaning=str(raw["reversed_meaning"]), upright_keywords=tuple(raw["upright_keywords"]),
        reversed_keywords=tuple(raw["reversed_keywords"]), context_meanings=raw.get("context_meanings", {}),
    )


@lru_cache
def get_catalog() -> TarotCatalog:
    raw = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    cards = tuple(_parse_card(card) for card in raw["cards"])
    return TarotCatalog(version=str(raw["version"]), cards=cards)
