"""Deterministic composition of persisted tarot readings into a shareable image."""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageFilter, ImageOps
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.tarot_reading import TarotReading, TarotReadingCard


PROJECT_ROOT = Path(__file__).resolve().parents[3]
ASSETS_DIR = PROJECT_ROOT / "assets" / "tarot-cards"
CARDS_DIR = ASSETS_DIR / "cards"
TABLE_PATH = ASSETS_DIR / "table" / "table_v1.png"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "rendered-readings"
RENDERER_VERSION = "table_v2"
CANVAS_SIZE = (1600, 1000)
THREE_CARD_HEIGHT = 655
ONE_CARD_HEIGHT = 635


class TarotRenderingError(RuntimeError):
    """An expected local asset or persisted-reading error while rendering."""


@dataclass(frozen=True)
class CardPlacement:
    card_id: str
    orientation: str
    center: tuple[int, int]
    scale: float
    tilt_degrees: float
    physical_rotation_degrees: float


@dataclass(frozen=True)
class RenderedReading:
    path: Path
    renderer_version: str
    placements: tuple[CardPlacement, ...]
    cached: bool


def _layout_seed(reading: TarotReading) -> int:
    payload = f"{RENDERER_VERSION}|{reading.id}|{reading.audit_metadata}"
    return int.from_bytes(hashlib.sha256(payload.encode("utf-8")).digest()[:8], "big")


def layout_for_reading(reading: TarotReading, cards: list[TarotReadingCard]) -> tuple[CardPlacement, ...]:
    """Return reproducible physical placement metadata without touching the database."""
    if len(cards) not in {1, 3}:
        raise TarotRenderingError(f"La tirada {reading.id} tiene {len(cards)} cartas; el compositor admite 1 o 3")
    rng = random.Random(_layout_seed(reading))
    anchors = [(800, 505)] if len(cards) == 1 else [(395, 490), (800, 520), (1205, 485)]
    placements: list[CardPlacement] = []
    for card, (anchor_x, anchor_y) in zip(cards, anchors):
        tilt = rng.uniform(-7.0, 7.0)
        if abs(tilt) < 1.25:
            tilt = 1.25 if rng.random() >= 0.5 else -1.25
        tilt = round(tilt, 2)
        scale = round(rng.uniform(0.975, 1.025), 3)
        base = 180.0 if card.orientation == "reversed" else 0.0
        horizontal_jitter = rng.randint(-28, 28) if len(cards) == 3 else rng.randint(-24, 24)
        vertical_jitter = rng.randint(-56, 56) if len(cards) == 3 else rng.randint(-30, 30)
        placements.append(CardPlacement(
            card_id=card.card_id,
            orientation=card.orientation,
            center=(anchor_x + horizontal_jitter, anchor_y + vertical_jitter),
            scale=scale,
            tilt_degrees=tilt,
            physical_rotation_degrees=base + tilt,
        ))
    return tuple(placements)


def _cache_metadata_path(image_path: Path) -> Path:
    return image_path.with_suffix(".json")


def _cache_is_current(image_path: Path, reading: TarotReading) -> bool:
    metadata_path = _cache_metadata_path(image_path)
    if not image_path.exists() or not metadata_path.exists():
        return False
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return metadata == {"renderer_version": RENDERER_VERSION, "layout_seed": _layout_seed(reading)}


def _load_table(reading: TarotReading) -> Image.Image:
    if not TABLE_PATH.exists():
        raise TarotRenderingError(f"Falta el fondo de mesa: {TABLE_PATH}")
    with Image.open(TABLE_PATH) as source:
        image = source.convert("RGB")
    table = ImageOps.fit(image, (1900, 1200), method=Image.Resampling.LANCZOS)
    rng = random.Random(_layout_seed(reading) ^ 0xA5A5A5A5)
    left = rng.randint(0, table.width - CANVAS_SIZE[0])
    top = rng.randint(0, table.height - CANVAS_SIZE[1])
    return table.crop((left, top, left + CANVAS_SIZE[0], top + CANVAS_SIZE[1]))


def _load_card(card_id: str) -> Image.Image:
    image_path = CARDS_DIR / f"{card_id}.webp"
    if not image_path.exists():
        raise TarotRenderingError(f"Falta la imagen runtime de la carta '{card_id}'")
    try:
        with Image.open(image_path) as source:
            return source.convert("RGBA")
    except OSError as error:
        raise TarotRenderingError(f"No se pudo abrir la imagen de la carta '{card_id}'") from error


def _place_card(canvas: Image.Image, card: Image.Image, placement: CardPlacement, *, card_height: int) -> None:
    target_height = round(card_height * placement.scale)
    target_width = round(card.width * target_height / card.height)
    card = card.resize((target_width, target_height), Image.Resampling.LANCZOS)
    rotated = card.rotate(placement.physical_rotation_degrees, resample=Image.Resampling.BICUBIC, expand=True)
    x = placement.center[0] - rotated.width // 2
    y = placement.center[1] - rotated.height // 2
    shadow_mask = rotated.getchannel("A").filter(ImageFilter.GaussianBlur(radius=16))
    shadow = Image.new("RGBA", rotated.size, (0, 0, 0, 92))
    canvas.paste(shadow, (x + 9, y + 13), shadow_mask)
    canvas.alpha_composite(rotated, (x, y))


def render_reading(session: Session, reading_id: int, *, output_dir: Path | None = None, force: bool = False) -> RenderedReading:
    """Compose a persisted one- or three-card reading. It never draws or mutates cards."""
    reading = session.get(TarotReading, reading_id)
    if reading is None:
        raise TarotRenderingError(f"No existe la tirada {reading_id}")
    cards = list(session.scalars(
        select(TarotReadingCard).where(TarotReadingCard.reading_id == reading.id).order_by(TarotReadingCard.position_index)
    ))
    placements = layout_for_reading(reading, cards)
    target_dir = output_dir or DEFAULT_OUTPUT_DIR
    image_path = target_dir / f"reading_{reading.id}.jpg"
    if not force and _cache_is_current(image_path, reading):
        return RenderedReading(image_path, RENDERER_VERSION, placements, cached=True)

    canvas = _load_table(reading).convert("RGBA")
    card_height = ONE_CARD_HEIGHT if len(cards) == 1 else THREE_CARD_HEIGHT
    for card, placement in zip(cards, placements):
        _place_card(canvas, _load_card(card.card_id), placement, card_height=card_height)
    target_dir.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(image_path, "JPEG", quality=88, optimize=True, progressive=True)
    _cache_metadata_path(image_path).write_text(json.dumps({
        "renderer_version": RENDERER_VERSION, "layout_seed": _layout_seed(reading),
    }, sort_keys=True), encoding="utf-8")
    return RenderedReading(image_path, RENDERER_VERSION, placements, cached=False)


def image_delivery_contract(rendered: RenderedReading, caption: str) -> dict[str, str]:
    """Future transport-neutral contract; WhatsApp is deliberately not called here."""
    return {"type": "image", "path": str(rendered.path), "caption": caption}
