"""Persist latest structured conversation decision."""
from alembic import op
import sqlalchemy as sa
revision="20260807_05";down_revision="20260807_04";branch_labels=None;depends_on=None
def upgrade():
 op.add_column("conversations",sa.Column("last_intent",sa.String(),nullable=True));op.add_column("conversations",sa.Column("reading_recommended",sa.Boolean(),nullable=False,server_default=sa.false()));op.add_column("conversations",sa.Column("suggested_spread",sa.String(),nullable=True))
def downgrade():op.drop_column("conversations","suggested_spread");op.drop_column("conversations","reading_recommended");op.drop_column("conversations","last_intent")
