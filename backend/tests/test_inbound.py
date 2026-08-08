from sqlalchemy import func, select
from fastapi.testclient import TestClient
from time import sleep

from app.ai.fake_provider import FakeAIProvider
from app.ai.provider import AIProviderError
from app.models.ai import AICall
from app.models.conversation import Conversation
from app.models.message import Message
from app.models.tarot_reading import TarotInterpretation, TarotReading, TarotReadingCard
from app.models.user import User
from app.schemas.whatsapp import InboundWhatsAppMessage
from app.services.inbound import process_inbound_message
from app.core.config import Settings
from app.main import create_app


SENDER = "5491100000000@s.whatsapp.net"


def payload(message_id: str, text: str, message_type: str = "text") -> dict:
    return {
        "sender": SENDER,
        "message_id": message_id,
        "timestamp": "2026-08-08T12:00:00Z",
        "message_type": message_type,
        "text": text,
    }


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_whatsapp_fake_end_to_end_automatic_reading_and_follow_up(client):
    hello = client.post("/internal/whatsapp/inbound", json=payload("wa-hello", "Hola"))
    question = client.post("/internal/whatsapp/inbound", json=payload("wa-question", "Quiero saber por una persona"))
    ready = client.post("/internal/whatsapp/inbound", json=payload("wa-context", "Hace dos meses que no hablamos."))
    reading = client.post("/internal/whatsapp/inbound", json=payload("wa-confirm", "sí"))

    assert hello.status_code == question.status_code == ready.status_code == reading.status_code == 200
    assert ready.json()["duplicate"] is False
    assert len(reading.json()["messages"]) == 2
    assert "Tirada:" in reading.json()["messages"][0]["text"]
    assert "La tirada invita" in reading.json()["messages"][1]["text"]

    with client.app.state.SessionLocal() as session:
        conversation = session.scalar(select(Conversation).join(User).where(User.whatsapp_jid == SENDER))
        assert conversation.state in {"READING_ACTIVE", "FOLLOW_UP"}
        assert not conversation.reading_recommended

    follow_up = client.post("/internal/whatsapp/inbound", json=payload("wa-follow-up", "¿Y qué puedo mirar ahora?"))
    assert follow_up.status_code == 200
    assert follow_up.json()["duplicate"] is False

    with client.app.state.SessionLocal() as session:
        user = session.scalar(select(User).where(User.whatsapp_jid == SENDER))
        conversation = session.scalar(select(Conversation).where(Conversation.user_id == user.id))
        reading_row = session.scalar(select(TarotReading).where(TarotReading.user_id == user.id))
        assert conversation.state == "FOLLOW_UP"
        assert reading_row.trigger_message_id == "wa-confirm"
        assert session.scalar(select(func.count()).select_from(TarotReadingCard).where(TarotReadingCard.reading_id == reading_row.id)) == 3
        assert session.scalar(select(func.count()).select_from(TarotInterpretation).where(TarotInterpretation.reading_id == reading_row.id)) == 1
        assert session.scalar(select(func.count()).select_from(TarotReading).where(TarotReading.user_id == user.id)) == 1


def test_duplicate_inbound_does_not_repeat_ai_or_reading(client):
    client.post("/internal/whatsapp/inbound", json=payload("dup-hello", "Hola"))
    client.post("/internal/whatsapp/inbound", json=payload("dup-question", "Quiero saber por una persona"))
    client.post("/internal/whatsapp/inbound", json=payload("dup-context", "Hace dos meses que no hablamos."))
    first = client.post("/internal/whatsapp/inbound", json=payload("dup-confirm", "sí"))
    with client.app.state.SessionLocal() as session:
        calls_before = session.scalar(select(func.count()).select_from(AICall))
        readings_before = session.scalar(select(func.count()).select_from(TarotReading))
        messages_before = session.scalar(select(func.count()).select_from(Message))

    second = client.post("/internal/whatsapp/inbound", json=payload("dup-confirm", "sí"))
    assert first.json()["duplicate"] is False
    assert second.json() == {"messages": [], "duplicate": True}
    with client.app.state.SessionLocal() as session:
        assert session.scalar(select(func.count()).select_from(AICall)) == calls_before
        assert session.scalar(select(func.count()).select_from(TarotReading)) == readings_before
        assert session.scalar(select(func.count()).select_from(Message)) == messages_before


def test_retry_after_gateway_timeout_uses_the_completed_message_id_once(client):
    class SlowFakeProvider(FakeAIProvider):
        def generate(self, *args, **kwargs):
            sleep(0.01)  # Represents work continuing after a gateway timeout, without a slow test.
            return super().generate(*args, **kwargs)

    inbound = InboundWhatsAppMessage(**payload("timeout-retry", "Hola"))
    with client.app.state.SessionLocal() as session:
        provider = SlowFakeProvider(mode="demo")
        first = process_inbound_message(session, inbound, provider)
        retry = process_inbound_message(session, inbound, provider)
        assert first.duplicate is False
        assert retry.duplicate is True
        assert len(provider.requests) == 1
        assert session.scalar(select(func.count()).select_from(Message)) == 2


def test_empty_image_caption_is_silently_ignored_without_persistence(client):
    response = client.post("/internal/whatsapp/inbound", json=payload("image-no-caption", "", "image"))
    assert response.status_code == 200
    assert response.json() == {"messages": [], "duplicate": False}
    with client.app.state.SessionLocal() as session:
        assert session.scalar(select(func.count()).select_from(Message)) == 0


def test_image_caption_uses_the_conversation_flow(client):
    response = client.post("/internal/whatsapp/inbound", json=payload("image-caption", "Hola", "image"))
    assert response.status_code == 200
    assert response.json()["messages"][0]["type"] == "text"
    with client.app.state.SessionLocal() as session:
        message = session.scalar(select(Message).where(Message.whatsapp_message_id == "image-caption"))
        assert message.content == "Hola"


def test_whatsapp_user_is_never_a_lab_user(client):
    client.post("/internal/lab/chat", json={"user_key": "same", "message": "Hola"})
    client.post("/internal/whatsapp/inbound", json=payload("separate", "Hola"))
    with client.app.state.SessionLocal() as session:
        users = session.scalars(select(User).order_by(User.whatsapp_jid)).all()
        assert {user.whatsapp_jid for user in users} == {"lab:same", SENDER}


def test_whatsapp_conversation_continues_after_backend_restart(client):
    client.post("/internal/whatsapp/inbound", json=payload("restart-hello", "Hola"))
    database_url = str(client.app.state.engine.url)
    restarted = create_app(Settings(database_url=database_url, run_migrations_on_startup=False, ai_provider="fake"))
    with TestClient(restarted) as restarted_client:
        response = restarted_client.post(
            "/internal/whatsapp/inbound", json=payload("restart-question", "Quiero saber por una persona")
        )
        assert response.status_code == 200
    with client.app.state.SessionLocal() as session:
        assert session.scalar(select(func.count()).select_from(User).where(User.whatsapp_jid == SENDER)) == 1
        assert session.scalar(select(func.count()).select_from(Conversation)) == 1


def test_provider_failure_returns_persisted_safe_fallback_and_keeps_state(client):
    with client.app.state.SessionLocal() as session:
        user = User(whatsapp_jid=SENDER)
        session.add(user)
        session.flush()
        conversation = Conversation(
            user_id=user.id,
            state="READY_FOR_READING",
            reading_recommended=True,
            suggested_spread="relationship_three",
        )
        session.add(conversation)
        session.commit()
        result = process_inbound_message(
            session,
            InboundWhatsAppMessage(**payload("rate-limited", "sí")),
            FakeAIProvider(error=AIProviderError("rate_limit")),
        )
        session.refresh(conversation)
        failed_call = session.scalar(select(AICall).where(AICall.conversation_id == conversation.id))
        outgoing = session.scalar(
            select(Message).where(Message.conversation_id == conversation.id, Message.direction == "outgoing")
        )
        assert result.messages[0].text == outgoing.content
        assert conversation.state == "READY_FOR_READING"
        assert conversation.reading_recommended
        assert failed_call.success is False
        assert failed_call.error_type == "rate_limit"
        assert session.scalar(select(func.count()).select_from(TarotReading)) == 0


def test_interpretation_failure_keeps_reading_state_safe_and_persists_fallback(client):
    decision = (
        '{"reply":"Voy con la tirada.","intent":"relationship","next_state":"READY_FOR_READING",'
        '"reading_recommended":true,"suggested_spread":"relationship_three","action":"confirm_reading",'
        '"memory_candidates":[]}'
    )
    with client.app.state.SessionLocal() as session:
        user = User(whatsapp_jid=SENDER)
        session.add(user)
        session.flush()
        conversation = Conversation(
            user_id=user.id,
            state="READY_FOR_READING",
            reading_recommended=True,
            suggested_spread="relationship_three",
        )
        session.add(conversation)
        session.commit()
        result = process_inbound_message(
            session,
            InboundWhatsAppMessage(**payload("interpretation-failure", "sí")),
            FakeAIProvider(responses=[decision, ""]),
        )
        session.refresh(conversation)
        failed_call = session.scalar(
            select(AICall).where(AICall.conversation_id == conversation.id, AICall.purpose == "reading_interpretation")
        )
        fallback = session.scalar(
            select(Message)
            .where(Message.conversation_id == conversation.id, Message.direction == "outgoing")
            .order_by(Message.id.desc())
        )
        assert result.messages[0].text == fallback.content
        assert conversation.state == "READY_FOR_READING"
        assert conversation.reading_recommended
        assert session.scalar(select(func.count()).select_from(TarotReading)) == 1
        assert failed_call.success is False
        assert failed_call.error_type == "empty_response"


def test_fake_follow_up_topic_change_and_new_reading_cycle(client):
    for message_id, text in [
        ("cycle-hello", "Hola"),
        ("cycle-question", "Quiero saber por una persona"),
        ("cycle-context", "Hace un tiempo que no hablamos"),
        ("cycle-confirm-one", "sí"),
    ]:
        client.post("/internal/whatsapp/inbound", json=payload(message_id, text))

    with client.app.state.SessionLocal() as session:
        conversation = session.scalar(select(Conversation).join(User).where(User.whatsapp_jid == SENDER))
        assert (conversation.state, conversation.reading_recommended, conversation.suggested_spread, conversation.last_action) == (
            "READING_ACTIVE", False, None, "none"
        )
        assert session.scalar(select(func.count()).select_from(TarotReading)) == 1

    follow_up = client.post("/internal/whatsapp/inbound", json=payload("cycle-follow-up", "¿Y qué significa eso para mí?"))
    assert "Tomando la tirada" in follow_up.json()["messages"][0]["text"]
    with client.app.state.SessionLocal() as session:
        conversation = session.scalar(select(Conversation).join(User).where(User.whatsapp_jid == SENDER))
        assert conversation.state == "FOLLOW_UP"
        assert not conversation.reading_recommended and conversation.suggested_spread is None
        assert session.scalar(select(func.count()).select_from(TarotReading)) == 1

    lottery = client.post("/internal/whatsapp/inbound", json=payload("cycle-lottery", "Qué número sale en la quiniela mañana?"))
    rejected_yes = client.post("/internal/whatsapp/inbound", json=payload("cycle-lottery-yes", "sí"))
    assert "número ganador" in lottery.json()["messages"][0]["text"]
    assert "Voy con la tirada" not in rejected_yes.json()["messages"][0]["text"]
    with client.app.state.SessionLocal() as session:
        conversation = session.scalar(select(Conversation).join(User).where(User.whatsapp_jid == SENDER))
        assert conversation.state == "CHATTING"
        assert not conversation.reading_recommended and conversation.suggested_spread is None
        assert session.scalar(select(func.count()).select_from(TarotReading)) == 1

    for message_id, text in [
        ("cycle-new-question", "Quiero saber por otra persona"),
        ("cycle-new-context", "Hace meses que no hablamos"),
        ("cycle-confirm-two", "sí"),
    ]:
        client.post("/internal/whatsapp/inbound", json=payload(message_id, text))
    with client.app.state.SessionLocal() as session:
        conversation = session.scalar(select(Conversation).join(User).where(User.whatsapp_jid == SENDER))
        assert conversation.state == "READING_ACTIVE"
        assert not conversation.reading_recommended and conversation.suggested_spread is None
        assert session.scalar(select(func.count()).select_from(TarotReading)) == 2


def test_rejected_confirmation_never_claims_that_a_reading_started(client):
    with client.app.state.SessionLocal() as session:
        user = User(whatsapp_jid=SENDER)
        session.add(user)
        session.flush()
        conversation = Conversation(user_id=user.id, state="READY_FOR_READING")
        session.add(conversation)
        session.commit()
        result = process_inbound_message(
            session,
            InboundWhatsAppMessage(**payload("reject-confirm", "sí")),
            FakeAIProvider(mode="demo"),
        )
        session.refresh(conversation)
        assert "Voy con la tirada" not in result.messages[0].text
        assert conversation.last_action == "none"
        assert not conversation.reading_recommended and conversation.suggested_spread is None
        assert session.scalar(select(func.count()).select_from(TarotReading)) == 0


def test_webhook_batch_persists_physical_messages_in_order_and_calls_ai_once(client):
    body = payload("batch-root", "primero")
    body["messages"] = [
        {"message_id": "batch-one", "timestamp": "2026-08-08T12:00:00Z", "message_type": "text", "text": "primero"},
        {"message_id": "batch-two", "timestamp": "2026-08-08T12:00:02Z", "message_type": "text", "text": "segundo"},
        {"message_id": "batch-three", "timestamp": "2026-08-08T12:00:01Z", "message_type": "text", "text": "tercero"},
    ]
    response = client.post("/internal/whatsapp/inbound", json=body)
    assert response.status_code == 200 and not response.json()["duplicate"]
    with client.app.state.SessionLocal() as session:
        conversation = session.scalar(select(Conversation).join(User).where(User.whatsapp_jid == SENDER))
        physical = session.scalars(
            select(Message).where(Message.conversation_id == conversation.id, Message.direction == "incoming").order_by(Message.created_at)
        ).all()
        assert [message.whatsapp_message_id for message in physical] == ["batch-one", "batch-three", "batch-two"]
        assert [message.content for message in physical] == ["primero", "tercero", "segundo"]
        assert session.scalar(select(func.count()).select_from(AICall).where(AICall.conversation_id == conversation.id)) == 1


def test_webhook_batch_discards_duplicates_but_processes_new_physical_message(client):
    client.post("/internal/whatsapp/inbound", json=payload("known-physical", "Hola"))
    body = payload("known-physical", "Hola")
    body["messages"] = [
        {"message_id": "known-physical", "timestamp": "2026-08-08T12:00:00Z", "message_type": "text", "text": "Hola"},
        {"message_id": "new-physical", "timestamp": "2026-08-08T12:00:01Z", "message_type": "text", "text": "seguimos"},
    ]
    response = client.post("/internal/whatsapp/inbound", json=body)
    assert response.status_code == 200 and not response.json()["duplicate"]
    with client.app.state.SessionLocal() as session:
        incoming_ids = session.scalars(select(Message.whatsapp_message_id).where(Message.whatsapp_message_id.is_not(None)).order_by(Message.id)).all()
        assert incoming_ids == ["known-physical", "new-physical"]
