import json

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import Settings
from app.main import create_app
from app.models.ai import AICall, UserMemory
from app.models.conversation import Conversation
from app.models.message import Message
from app.models.tarot_reading import TarotInterpretation, TarotReadingCard
from app.models.user import User
from app.services.tarot_readings import create_reading


def admin_client(tmp_path):
    app = create_app(Settings(database_url=f"sqlite:///{tmp_path / 'admin.db'}", run_migrations_on_startup=True, admin_enabled=True))
    return TestClient(app)


def fixture_data(client):
    with client.app.state.SessionLocal() as session:
        user = User(whatsapp_jid="549114821@s.whatsapp.net")
        session.add(user); session.flush()
        conversation = Conversation(user_id=user.id, state="READING_ACTIVE", last_intent="relationship")
        session.add(conversation); session.flush()
        session.add_all([Message(conversation_id=conversation.id, direction="incoming", message_type="text", content="Consulta ficticia."), Message(conversation_id=conversation.id, direction="outgoing", message_type="text", content="Respuesta ficticia.")])
        session.add(UserMemory(user_id=user.id, summary="Memoria ficticia.", version=2))
        session.commit()
        reading_id, _ = create_reading(session, user_id=user.id, conversation_id=conversation.id, spread_type="one_card", seed="admin-fixture")
        session.add(TarotInterpretation(reading_id=reading_id, interpretation_text="Interpretación ficticia.", interpretation_summary="Resumen ficticio.", prompt_version="tarot_interpretation_v2", provider="fake", model="fake-model"))
        session.add_all([AICall(user_id=user.id, conversation_id=conversation.id, purpose="conversation", provider="groq", model="openai/gpt-oss-120b", prompt_version="tarotista_v4", input_tokens=10, output_tokens=5, latency_ms=12, success=True), AICall(user_id=user.id, conversation_id=conversation.id, purpose="conversation", provider="groq", model="openai/gpt-oss-120b", prompt_version="tarotista_v4", input_tokens=0, output_tokens=0, latency_ms=20, success=False, error_type="rate_limit")])
        session.commit()
        return conversation.id, reading_id, user.whatsapp_jid


def test_admin_opens_without_credentials(tmp_path):
    disabled = TestClient(create_app(Settings(database_url=f"sqlite:///{tmp_path / 'disabled.db'}", run_migrations_on_startup=True, admin_enabled=False)))
    assert disabled.get("/admin").status_code == 404
    with admin_client(tmp_path) as client:
        response = client.get("/admin")
        assert response.status_code == 200 and response.headers["cache-control"].startswith("no-store") and response.headers["x-robots-tag"] == "noindex, nofollow"


def test_admin_home_lists_anonymized_conversations_and_metrics(tmp_path):
    with admin_client(tmp_path) as client:
        conversation_id, _, jid = fixture_data(client)
        response = client.get("/admin")
        assert response.status_code == 200
        assert "…4821" in response.text and jid not in response.text and "input tokens" in response.text
        listing = client.get("/admin/conversations?state=READING_ACTIVE&readings=true")
        assert listing.status_code == 200 and f"/admin/conversations/{conversation_id}" in listing.text


def test_detail_reading_image_errors_and_privacy(tmp_path):
    with admin_client(tmp_path) as client:
        conversation_id, reading_id, jid = fixture_data(client)
        detail = client.get(f"/admin/conversations/{conversation_id}")
        assert detail.status_code == 200
        assert "Consulta ficticia." in detail.text and "Memoria ficticia." in detail.text and "Interpretación ficticia." in detail.text
        assert jid not in detail.text and "rate_limit" in detail.text
        image = client.get(f"/admin/readings/{reading_id}/image")
        assert image.status_code == 200 and image.headers["content-type"] == "image/jpeg"
        assert client.get("/admin/readings/999999/image").status_code == 404
        errors = client.get("/admin/errors?provider=groq&error_type=rate_limit")
        assert errors.status_code == 200 and "rate_limit" in errors.text and jid not in errors.text
