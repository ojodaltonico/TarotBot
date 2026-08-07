import random
import secrets

from app.tarot.catalog import TarotCatalog, get_catalog
from app.tarot.models import DrawResult, DrawnCard, Orientation
from app.tarot.spreads import get_spread


class TarotEngine:
    def __init__(self, catalog: TarotCatalog | None = None):
        self.catalog = catalog or get_catalog()

    def draw(
        self,
        spread_type: str,
        *,
        seed: int | str | None = None,
        reversed_enabled: bool = True,
        reversed_probability: float = 0.5,
    ) -> DrawResult:
        if not 0 <= reversed_probability <= 1:
            raise ValueError("reversed_probability debe estar entre 0 y 1")
        spread = get_spread(spread_type)
        rng = self._rng(seed)
        selected = rng.sample(self.catalog.cards, len(spread.positions))
        cards: list[DrawnCard] = []
        for index, (position, card) in enumerate(zip(spread.positions, selected), start=1):
            orientation: Orientation = "reversed" if reversed_enabled and rng.random() < reversed_probability else "upright"
            cards.append(DrawnCard(card, index, position.key, position.label, orientation))
        audit: dict[str, object] = {
            "deck_version": self.catalog.version,
            "random_source": "seeded_prng" if seed is not None else "system_random",
            "seed": str(seed) if seed is not None else None,
            "reversed_enabled": reversed_enabled,
            "reversed_probability": reversed_probability,
        }
        return DrawResult(spread.key, spread.label, tuple(cards), audit)

    def shuffle(self, *, seed: int | str | None = None) -> tuple[str, ...]:
        cards = list(self.catalog.cards)
        self._rng(seed).shuffle(cards)
        return tuple(card.id for card in cards)

    def draw_cards(self, count: int, *, seed: int | str | None = None) -> tuple[str, ...]:
        if not 0 <= count <= len(self.catalog.cards):
            raise ValueError("count debe estar entre 0 y 78")
        return tuple(card.id for card in self._rng(seed).sample(self.catalog.cards, count))

    @staticmethod
    def _rng(seed: int | str | None) -> random.Random | secrets.SystemRandom:
        return random.Random(seed) if seed is not None else secrets.SystemRandom()
