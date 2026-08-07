"""Ejecuta una tirada reproducible sin persistir ni usar IA."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.tarot.engine import TarotEngine  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("spread", choices=("one_card", "general_three", "relationship_three"))
    parser.add_argument("--seed", default=None, help="Semilla opcional para reproducir la tirada")
    parser.add_argument("--no-reversed", action="store_true", help="Desactiva cartas invertidas")
    args = parser.parse_args()
    result = TarotEngine().draw(args.spread, seed=args.seed, reversed_enabled=not args.no_reversed)
    print(f"Tirada: {result.spread_label}")
    for card in result.cards:
        orientation = "derecha" if card.orientation == "upright" else "invertida"
        print(f"{card.position_index}. {card.position_label} -> {card.card.name_es} ({orientation})")
    print(f"Auditoría: {result.audit_metadata}")


if __name__ == "__main__":
    main()
