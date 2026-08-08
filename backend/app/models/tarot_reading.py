from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.user import utc_now


class TarotReading(Base):
    __tablename__ = "tarot_readings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"), nullable=False, index=True)
    spread_type: Mapped[str] = mapped_column(String(64), nullable=False)
    question: Mapped[str | None] = mapped_column(Text, nullable=True)
    trigger_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    audit_metadata: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    cards: Mapped[list["TarotReadingCard"]] = relationship(
        back_populates="reading", cascade="all, delete-orphan", order_by="TarotReadingCard.position_index"
    )
    interpretations: Mapped[list["TarotInterpretation"]] = relationship(back_populates="reading", cascade="all, delete-orphan")


class TarotReadingCard(Base):
    __tablename__ = "tarot_reading_cards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reading_id: Mapped[int] = mapped_column(ForeignKey("tarot_readings.id"), nullable=False, index=True)
    position_index: Mapped[int] = mapped_column(Integer, nullable=False)
    position_key: Mapped[str] = mapped_column(String(64), nullable=False)
    position_label: Mapped[str] = mapped_column(String(255), nullable=False)
    card_id: Mapped[str] = mapped_column(String(128), nullable=False)
    orientation: Mapped[str] = mapped_column(String(16), nullable=False)
    card_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    reading: Mapped["TarotReading"] = relationship(back_populates="cards")

class TarotInterpretation(Base):
    __tablename__ = "tarot_interpretations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reading_id: Mapped[int] = mapped_column(ForeignKey("tarot_readings.id"), nullable=False, index=True)
    interpretation_text: Mapped[str] = mapped_column(Text, nullable=False)
    interpretation_summary: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    interpreted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    reading: Mapped["TarotReading"] = relationship(back_populates="interpretations")
