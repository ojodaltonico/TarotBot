"""Persist generated tarot interpretations."""
from alembic import op
import sqlalchemy as sa
revision="20260807_04"; down_revision="20260807_03"; branch_labels=None; depends_on=None
def upgrade():
 op.create_table("tarot_interpretations",sa.Column("id",sa.Integer(),primary_key=True),sa.Column("reading_id",sa.Integer(),sa.ForeignKey("tarot_readings.id"),nullable=False),sa.Column("interpretation_text",sa.Text(),nullable=False),sa.Column("interpretation_summary",sa.Text(),nullable=False),sa.Column("prompt_version",sa.String(64),nullable=False),sa.Column("model",sa.String(128),nullable=False),sa.Column("provider",sa.String(64),nullable=False),sa.Column("interpreted_at",sa.DateTime(timezone=True),nullable=False)); op.create_index("ix_tarot_interpretations_reading_id","tarot_interpretations",["reading_id"])
def downgrade(): op.drop_index("ix_tarot_interpretations_reading_id",table_name="tarot_interpretations"); op.drop_table("tarot_interpretations")
