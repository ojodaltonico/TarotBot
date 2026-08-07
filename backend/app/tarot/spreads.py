from dataclasses import dataclass


@dataclass(frozen=True)
class SpreadPosition:
    key: str
    label: str


@dataclass(frozen=True)
class Spread:
    key: str
    label: str
    positions: tuple[SpreadPosition, ...]


SPREADS: dict[str, Spread] = {
    "one_card": Spread(
        key="one_card",
        label="Una carta",
        positions=(SpreadPosition("guidance", "Mensaje, energía o consejo"),),
    ),
    "general_three": Spread(
        key="general_three",
        label="Lectura general de tres cartas",
        positions=(
            SpreadPosition("current_situation", "Situación actual"),
            SpreadPosition("challenge", "Influencia o desafío"),
            SpreadPosition("guidance", "Tendencia o consejo"),
        ),
    ),
    "relationship_three": Spread(
        key="relationship_three",
        label="Relación de tres cartas",
        positions=(
            SpreadPosition("self", "Tu posición"),
            SpreadPosition("other", "La otra parte"),
            SpreadPosition("connection", "Energía o tendencia del vínculo"),
        ),
    ),
}


def get_spread(spread_type: str) -> Spread:
    try:
        return SPREADS[spread_type]
    except KeyError as error:
        raise ValueError(f"Spread no soportado: {spread_type}") from error
