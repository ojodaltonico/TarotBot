"""Auditoría no frágil de cobertura y orientación del motor de tarot."""
from collections import Counter
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.tarot.engine import TarotEngine  # noqa: E402


SAMPLES = 20_000


def main() -> None:
    engine = TarotEngine()
    card_counts: Counter[str] = Counter()
    orientations: Counter[str] = Counter()
    for _ in range(SAMPLES):
        result = engine.draw("general_three", reversed_probability=0.5)
        ids = [drawn.card.id for drawn in result.cards]
        assert len(ids) == len(set(ids)), "Carta repetida dentro de una tirada"
        card_counts.update(ids)
        orientations.update(drawn.orientation for drawn in result.cards)
    missing = set(card.id for card in engine.catalog.cards).difference(card_counts)
    ratio = orientations["reversed"] / sum(orientations.values())
    expected = sum(card_counts.values()) / len(engine.catalog.cards)
    low, high = min(card_counts.values()), max(card_counts.values())
    assert not missing, f"Cartas sin aparecer: {sorted(missing)}"
    assert 0.47 <= ratio <= 0.53, f"Proporción invertida inesperada: {ratio:.4f}"
    assert low >= expected * 0.65 and high <= expected * 1.35, "Sesgo evidente en conteos de cartas"

    disabled = [drawn.orientation for _ in range(500) for drawn in engine.draw("one_card", reversed_enabled=False).cards]
    assert set(disabled) == {"upright"}
    print(f"Muestras: {SAMPLES} tiradas de 3 ({sum(card_counts.values())} cartas)")
    print(f"Cobertura: {len(card_counts)}/78; mínimo={low}, máximo={high}, esperado_aprox={expected:.1f}")
    print(f"Invertidas: {orientations['reversed']}/{sum(orientations.values())} ({ratio:.2%})")
    print("Con invertidas desactivadas: 500/500 derechas")


if __name__ == "__main__":
    main()
