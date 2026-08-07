from sqlalchemy import func, select

from app.models.conversation import Conversation
from app.models.message import Message
from app.models.user import User
from app.services.inbound import TEMPORARY_REPLY


PAYLOAD = {
    "sender": "5491100000000@s.whatsapp.net",
    "message_id": "message-123",
    "timestamp": "2026-08-07T12:00:00Z",
    "message_type": "text",
    "text": "Hola",
}


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_inbound_creates_user_and_stores_both_messages(client):
    response = client.post("/internal/whatsapp/inbound", json=PAYLOAD)
    assert response.status_code == 200
    assert response.json() == {
        "messages": [{"type": "text", "text": TEMPORARY_REPLY, "image_url": None, "typing_ms": 0, "delay_ms": 0}],
        "duplicate": False,
    }

    with client.app.state.SessionLocal() as session:
        assert session.scalar(select(func.count()).select_from(User)) == 1
        assert session.scalar(select(func.count()).select_from(Conversation)) == 1
        assert session.scalar(select(func.count()).select_from(Message)) == 2


def test_duplicate_message_id_does_not_create_second_reply(client):
    first = client.post("/internal/whatsapp/inbound", json=PAYLOAD)
    second = client.post("/internal/whatsapp/inbound", json=PAYLOAD)
    assert first.json()["duplicate"] is False
    assert second.json() == {"messages": [], "duplicate": True}

    with client.app.state.SessionLocal() as session:
        assert session.scalar(select(func.count()).select_from(Message)) == 2
