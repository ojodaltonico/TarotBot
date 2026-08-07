from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.ai import AICall, UserMemory

def get_memory(session: Session, user_id: int): return session.scalar(select(UserMemory).where(UserMemory.user_id==user_id))
def upsert_memory(session: Session, user_id: int, summary: str):
    memory=get_memory(session,user_id)
    if memory is None: memory=UserMemory(user_id=user_id,summary=summary,version=1); session.add(memory)
    else: memory.summary=summary; memory.version+=1
    session.flush(); return memory
def add_call(session: Session, **values):
    call=AICall(**values); session.add(call); session.flush(); return call
