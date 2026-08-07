import json
from dataclasses import replace

import pytest
from sqlalchemy import func, select

from app.models.conversation import Conversation
from app.models.tarot_reading import TarotReading, TarotReadingCard
from app.models.user import User
from app.services.tarot_readings import create_reading
from app.tarot.catalog import get_catalog
from app.tarot.engine import TarotEngine
from app.tarot.spreads import SPREADS


def test_catalog_has_complete_rws_deck():
    catalog = get_catalog()
    assert len(catalog.cards) == 78
    assert len({card.id for card in catalog.cards}) == 78
    assert sum(card.card_type == "major" for card in catalog.cards) == 22
    assert sum(card.card_type == "minor" for card in catalog.cards) == 56
    assert all(sum(card.suit == suit for card in catalog.cards) == 14 for suit in ("wands", "cups", "swords", "pentacles"))
    expected_majors = [
        "fool", "magician", "high_priestess", "empress", "emperor", "hierophant", "lovers", "chariot",
        "strength", "hermit", "wheel_of_fortune", "justice", "hanged_man", "death", "temperance",
        "devil", "tower", "star", "moon", "sun", "judgement", "world",
    ]
    assert [card.id for card in catalog.cards if card.card_type == "major"] == [
        f"major_{number:02d}_{name}" for number, name in enumerate(expected_majors)
    ]
    for card in catalog.cards:
        assert card.name_es and card.name_en and card.image_path
        assert card.upright_meaning != card.reversed_meaning
        assert card.upright_keywords and card.reversed_keywords


def test_draw_does_not_repeat_cards_and_uses_valid_orientation():
    result = TarotEngine().draw("general_three", seed=123)
    assert len({drawn.card.id for drawn in result.cards}) == 3
    assert {drawn.orientation for drawn in result.cards}.issubset({"upright", "reversed"})
    engine = TarotEngine()
    assert len(engine.shuffle(seed=1)) == 78
    all_cards = engine.draw_cards(78, seed=2)
    assert len(all_cards) == len(set(all_cards)) == 78


def test_orientation_options_and_seed_reproducibility():
    engine = TarotEngine()
    first = engine.draw("relationship_three", seed="known-seed", reversed_enabled=False)
    second = engine.draw("relationship_three", seed="known-seed", reversed_enabled=False)
    different = engine.draw("relationship_three", seed="other-seed", reversed_enabled=False)
    assert [(card.card.id, card.orientation) for card in first.cards] == [(card.card.id, card.orientation) for card in second.cards]
    assert [card.orientation for card in first.cards] == ["upright"] * 3
    assert [card.card.id for card in first.cards] != [card.card.id for card in different.cards]
    assert all(card.orientation == "reversed" for card in engine.draw("one_card", seed=1, reversed_probability=1).cards)
    assert all(card.orientation == "upright" for card in engine.draw("one_card", seed=1, reversed_probability=0).cards)


def test_spreads_have_expected_positions_and_unknown_fails():
    assert len(SPREADS["one_card"].positions) == 1
    assert len(SPREADS["general_three"].positions) == 3
    assert len(SPREADS["relationship_three"].positions) == 3
    with pytest.raises(ValueError, match="Spread no soportado"):
        TarotEngine().draw("missing", seed=1)


def test_persisted_reading_keeps_card_snapshot(client):
    with client.app.state.SessionLocal() as session:
        user = User(whatsapp_jid="5491100000000@s.whatsapp.net")
        session.add(user)
        session.flush()
        conversation = Conversation(user_id=user.id)
        session.add(conversation)
        session.commit()
        reading_id, result = create_reading(
            session, user_id=user.id, conversation_id=conversation.id, spread_type="relationship_three",
            question="¿Cómo está el vínculo?", seed="persistence-test",
        )
        assert len(result.cards) == 3

    with client.app.state.SessionLocal() as session:
        reading = session.get(TarotReading, reading_id)
        cards = session.scalars(
            select(TarotReadingCard).where(TarotReadingCard.reading_id == reading_id).order_by(TarotReadingCard.position_index)
        ).all()
        assert reading is not None
        assert len(cards) == 3
        snapshot_before = cards[0].card_snapshot
        snapshot = json.loads(snapshot_before)
        assert snapshot["name_es"]
        assert session.scalar(select(func.count()).select_from(TarotReading)) == 1
        assert session.scalar(select(func.count()).select_from(TarotReadingCard)) == 3

    catalog = get_catalog()
    original_card = catalog.get(cards[0].card_id)
    changed_card = replace(original_card, upright_meaning="SIGNIFICADO TEMPORAL DE PRUEBA")
    index = list(catalog.cards).index(original_card)
    original_cards = catalog.cards
    original_by_id = catalog._by_id
    try:
        catalog.cards = tuple(changed_card if item.id == original_card.id else item for item in catalog.cards)
        catalog._by_id = {**catalog._by_id, original_card.id: changed_card}
        with client.app.state.SessionLocal() as session:
            historical = session.scalars(
                select(TarotReadingCard).where(TarotReadingCard.reading_id == reading_id).order_by(TarotReadingCard.position_index)
            ).first()
            assert json.loads(historical.card_snapshot)["upright_meaning"] == snapshot["upright_meaning"]
            assert json.loads(historical.card_snapshot)["upright_meaning"] != changed_card.upright_meaning
    finally:
        catalog.cards = original_cards
        catalog._by_id = original_by_id


def test_development_endpoints(client):
    assert len(client.get("/internal/tarot/cards").json()) == 78
    assert len(client.get("/internal/tarot/spreads").json()) == 3
    response = client.post("/internal/tarot/test-draw", json={"spread_type": "one_card", "seed": 7})
    assert response.status_code == 200
    assert len(response.json()["cards"]) == 1
    invalid = client.post("/internal/tarot/test-draw", json={"spread_type": "missing"})
    assert invalid.status_code == 422
