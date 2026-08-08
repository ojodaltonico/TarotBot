"""Persist confirmation actions and idempotent reading triggers."""
from alembic import op
import sqlalchemy as sa

revision = "20260807_06"
down_revision = "20260807_05"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("conversations", sa.Column("last_action", sa.String(), nullable=True))
    op.add_column("tarot_readings", sa.Column("trigger_message_id", sa.String(length=255), nullable=True))
    op.create_index("uq_tarot_readings_trigger_message_id", "tarot_readings", ["trigger_message_id"], unique=True)


def downgrade():
    op.drop_index("uq_tarot_readings_trigger_message_id", table_name="tarot_readings")
    op.drop_column("tarot_readings", "trigger_message_id")
    op.drop_column("conversations", "last_action")
