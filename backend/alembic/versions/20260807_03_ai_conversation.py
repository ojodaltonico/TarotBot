"""Add conversation state, memory and AI audit."""
from alembic import op
import sqlalchemy as sa
revision="20260807_03"; down_revision="20260807_02"; branch_labels=None; depends_on=None
def upgrade():
    op.add_column("conversations", sa.Column("state", sa.String(), nullable=False, server_default="NEW"))
    op.create_table("user_memories", sa.Column("id",sa.Integer(),primary_key=True),sa.Column("user_id",sa.Integer(),sa.ForeignKey("users.id"),nullable=False,unique=True),sa.Column("summary",sa.Text(),nullable=False),sa.Column("version",sa.Integer(),nullable=False),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False),sa.Column("updated_at",sa.DateTime(timezone=True),nullable=False))
    op.create_table("ai_calls", sa.Column("id",sa.Integer(),primary_key=True),sa.Column("user_id",sa.Integer(),sa.ForeignKey("users.id")),sa.Column("conversation_id",sa.Integer(),sa.ForeignKey("conversations.id")),sa.Column("reading_id",sa.Integer(),sa.ForeignKey("tarot_readings.id")),sa.Column("purpose",sa.String(64),nullable=False),sa.Column("provider",sa.String(64),nullable=False),sa.Column("model",sa.String(128),nullable=False),sa.Column("prompt_version",sa.String(64),nullable=False),sa.Column("input_tokens",sa.Integer(),nullable=False),sa.Column("cached_input_tokens",sa.Integer()),sa.Column("output_tokens",sa.Integer(),nullable=False),sa.Column("latency_ms",sa.Integer(),nullable=False),sa.Column("success",sa.Boolean(),nullable=False),sa.Column("error_type",sa.String(128)),sa.Column("estimated_cost_usd",sa.Float()),sa.Column("debug_payload",sa.Text()),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False))
    op.create_index("ix_ai_calls_user_id", "ai_calls", ["user_id"])
    op.create_index("ix_ai_calls_conversation_id", "ai_calls", ["conversation_id"])
    op.create_index("ix_ai_calls_reading_id", "ai_calls", ["reading_id"])
    op.create_index("ix_ai_calls_purpose", "ai_calls", ["purpose"])
def downgrade():
    op.drop_index("ix_ai_calls_purpose",table_name="ai_calls"); op.drop_index("ix_ai_calls_reading_id",table_name="ai_calls"); op.drop_index("ix_ai_calls_conversation_id",table_name="ai_calls"); op.drop_index("ix_ai_calls_user_id",table_name="ai_calls"); op.drop_table("ai_calls"); op.drop_table("user_memories"); op.drop_column("conversations","state")
