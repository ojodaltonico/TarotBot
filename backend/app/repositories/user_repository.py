from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.user import User


def get_or_create_user(session: Session, whatsapp_jid: str, seen_at: datetime) -> User:
    user = session.scalar(select(User).where(User.whatsapp_jid == whatsapp_jid))
    if user is None:
        user = User(whatsapp_jid=whatsapp_jid, last_seen_at=seen_at)
        session.add(user)
        session.flush()
    else:
        user.last_seen_at = seen_at
    return user
