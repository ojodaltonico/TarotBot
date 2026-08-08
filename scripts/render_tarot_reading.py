"""Create a local persisted development reading and render it without AI."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.db.database import create_session_factory, create_sqlite_engine
from app.main import run_migrations
from app.repositories.conversation_repository import get_or_create_active_conversation
from app.repositories.user_repository import get_or_create_user
from app.services.tarot_readings import create_reading
from app.tarot.rendering import DEFAULT_OUTPUT_DIR, render_reading


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spread", choices=("one_card", "general_three", "relationship_three"), default="relationship_three")
    parser.add_argument("--seed", default="123")
    parser.add_argument("--database-url", default=f"sqlite:///{(ROOT / 'data' / 'render-preview.db').as_posix()}")
    args = parser.parse_args()
    run_migrations(args.database_url)
    factory = create_session_factory(create_sqlite_engine(args.database_url))
    with factory() as session:
        user = get_or_create_user(session, "render-preview@local", datetime.now(timezone.utc))
        conversation = get_or_create_active_conversation(session, user.id)
        session.commit()
        reading_id, _ = create_reading(session, user_id=user.id, conversation_id=conversation.id, spread_type=args.spread, seed=args.seed)
        rendered = render_reading(session, reading_id, output_dir=DEFAULT_OUTPUT_DIR)
    print(rendered.path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
