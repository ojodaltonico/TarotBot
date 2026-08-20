"""Persist audio message metadata while retaining transcript in messages.content."""
from alembic import op
import sqlalchemy as sa

revision = "20260811_07"
down_revision = "20260807_06"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("messages", sa.Column("audio_mimetype", sa.String(length=128), nullable=True))
    op.add_column("messages", sa.Column("audio_duration_seconds", sa.Integer(), nullable=True))
    op.add_column("messages", sa.Column("audio_ptt", sa.Boolean(), nullable=True))
    op.add_column("messages", sa.Column("transcription_error", sa.String(length=128), nullable=True))

def downgrade():
    op.drop_column("messages", "transcription_error")
    op.drop_column("messages", "audio_ptt")
    op.drop_column("messages", "audio_duration_seconds")
    op.drop_column("messages", "audio_mimetype")
