import json
from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy import select

from app.models.conversation import Conversation
from app.models.tarot_reading import TarotReading, TarotReadingCard
from app.models.user import User
from app.services.tarot_readings import create_reading
from app.tarot.rendering import CANVAS_SIZE, ONE_CARD_HEIGHT, THREE_CARD_HEIGHT, TarotRenderingError, render_reading


def _reading(client, spread: str, seed: str, reversed_probability: float = 0.5) -> int:
    with client.app.state.SessionLocal() as session:
        user = User(whatsapp_jid=f"render-{seed}@local")
        session.add(user)
        session.flush()
        conversation = Conversation(user_id=user.id)
        session.add(conversation)
        session.commit()
        reading_id, _ = create_reading(session, user_id=user.id, conversation_id=conversation.id, spread_type=spread, seed=seed, reversed_probability=reversed_probability)
        return reading_id


@pytest.mark.parametrize(("spread", "count"), [("one_card", 1), ("general_three", 3), ("relationship_three", 3)])
def test_renderer_uses_exactly_the_persisted_cards(client, tmp_path, spread, count):
    reading_id = _reading(client, spread, f"{spread}-seed")
    with client.app.state.SessionLocal() as session:
        cards = list(session.scalars(select(TarotReadingCard).where(TarotReadingCard.reading_id == reading_id).order_by(TarotReadingCard.position_index)))
        rendered = render_reading(session, reading_id, output_dir=tmp_path)
    assert len(rendered.placements) == count
    assert [placement.card_id for placement in rendered.placements] == [card.card_id for card in cards]
    assert rendered.path.exists()
    with Image.open(rendered.path) as image:
        assert image.size == CANVAS_SIZE
    assert rendered.path.stat().st_size < 2 * 1024 * 1024


def test_orientation_layout_is_physical_and_deterministic(client, tmp_path):
    upright_id = _reading(client, "one_card", "upright", reversed_probability=0)
    reversed_id = _reading(client, "one_card", "reversed", reversed_probability=1)
    with client.app.state.SessionLocal() as session:
        upright = render_reading(session, upright_id, output_dir=tmp_path)
        reversed_card = render_reading(session, reversed_id, output_dir=tmp_path)
        cached = render_reading(session, upright_id, output_dir=tmp_path)
    assert 1.25 <= abs(upright.placements[0].physical_rotation_degrees) <= 7
    assert 173 <= reversed_card.placements[0].physical_rotation_degrees <= 187
    assert cached.cached is True
    assert cached.placements == upright.placements


def test_different_readings_have_different_layouts_without_mutating_history(client, tmp_path):
    first_id = _reading(client, "relationship_three", "layout-one")
    second_id = _reading(client, "relationship_three", "layout-two")
    with client.app.state.SessionLocal() as session:
        original = session.get(TarotReading, first_id)
        original_audit = original.audit_metadata
        original_cards = [(card.card_id, card.orientation, card.card_snapshot) for card in original.cards]
        first = render_reading(session, first_id, output_dir=tmp_path)
        second = render_reading(session, second_id, output_dir=tmp_path)
        session.expire_all()
        persisted = session.get(TarotReading, first_id)
        persisted_cards = [(card.card_id, card.orientation, card.card_snapshot) for card in persisted.cards]
    assert first.placements != second.placements
    assert persisted.audit_metadata == original_audit
    assert persisted_cards == original_cards


def test_three_card_layout_uses_hand_placed_variation(client, tmp_path):
    reading_id = _reading(client, "relationship_three", "hand-placed", reversed_probability=0)
    with client.app.state.SessionLocal() as session:
        rendered = render_reading(session, reading_id, output_dir=tmp_path)
    placements = rendered.placements
    horizontal_gaps = [placements[index + 1].center[0] - placements[index].center[0] for index in range(2)]
    assert len({placement.center[1] for placement in placements}) > 1
    assert horizontal_gaps[0] != horizontal_gaps[1]
    assert all(0.975 <= placement.scale <= 1.025 for placement in placements)
    assert all(1.25 <= abs(placement.tilt_degrees) <= 7 for placement in placements)
    assert THREE_CARD_HEIGHT > ONE_CARD_HEIGHT > 585


def test_missing_runtime_card_is_a_controlled_error(client, tmp_path, monkeypatch):
    reading_id = _reading(client, "one_card", "missing-card")
    import app.tarot.rendering as rendering
    monkeypatch.setattr(rendering, "CARDS_DIR", tmp_path / "does-not-exist")
    with client.app.state.SessionLocal() as session:
        with pytest.raises(TarotRenderingError, match="Falta la imagen runtime"):
            render_reading(session, reading_id, output_dir=tmp_path)


def test_manifest_is_complete_and_matches_runtime_deck():
    root = Path(__file__).resolve().parents[2]
    manifest = json.loads((root / "assets" / "tarot-cards" / "manifest.json").read_text(encoding="utf-8"))
    deck = json.loads((root / "backend" / "app" / "tarot" / "data" / "deck.json").read_text(encoding="utf-8"))
    assert len(manifest["cards"]) == 78
    assert {entry["card_id"] for entry in manifest["cards"]} == {card["id"] for card in deck["cards"]}
    assert all(entry["filename"] == f"{entry['card_id']}.webp" for entry in manifest["cards"])
    assert all(entry["source_url"].startswith("https://commons.wikimedia.org/wiki/File:") for entry in manifest["cards"])
