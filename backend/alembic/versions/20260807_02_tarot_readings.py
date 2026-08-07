"""Add persisted tarot readings and immutable card snapshots.

Revision ID: 20260807_02
Revises: 20260807_01
Create Date: 2026-08-07
"""

from alembic import op
import sqlalchemy as sa


revision = "20260807_02"
down_revision = "20260807_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tarot_readings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=False),
        sa.Column("spread_type", sa.String(length=64), nullable=False),
        sa.Column("question", sa.Text(), nullable=True),
        sa.Column("audit_metadata", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tarot_readings_user_id", "tarot_readings", ["user_id"], unique=False)
    op.create_index("ix_tarot_readings_conversation_id", "tarot_readings", ["conversation_id"], unique=False)
    op.create_table(
        "tarot_reading_cards",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("reading_id", sa.Integer(), nullable=False),
        sa.Column("position_index", sa.Integer(), nullable=False),
        sa.Column("position_key", sa.String(length=64), nullable=False),
        sa.Column("position_label", sa.String(length=255), nullable=False),
        sa.Column("card_id", sa.String(length=128), nullable=False),
        sa.Column("orientation", sa.String(length=16), nullable=False),
        sa.Column("card_snapshot", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["reading_id"], ["tarot_readings.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tarot_reading_cards_reading_id", "tarot_reading_cards", ["reading_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_tarot_reading_cards_reading_id", table_name="tarot_reading_cards")
    op.drop_table("tarot_reading_cards")
    op.drop_index("ix_tarot_readings_conversation_id", table_name="tarot_readings")
    op.drop_index("ix_tarot_readings_user_id", table_name="tarot_readings")
    op.drop_table("tarot_readings")
