from enum import Enum
from pydantic import BaseModel, Field


class ConversationState(str, Enum):
    NEW="NEW"; CHATTING="CHATTING"; DEFINING_QUESTION="DEFINING_QUESTION"; READY_FOR_READING="READY_FOR_READING"; READING_ACTIVE="READING_ACTIVE"; FOLLOW_UP="FOLLOW_UP"

class Intent(str, Enum):
    greeting="greeting"; general_chat="general_chat"; ask_tarot="ask_tarot"; relationship="relationship"; work="work"; money="money"; decision="decision"; general_reading="general_reading"; follow_up="follow_up"; unclear="unclear"

class ConversationAction(str, Enum):
    none="none"; confirm_reading="confirm_reading"

class ConversationDecision(BaseModel):
    reply: str = Field(min_length=1)
    intent: Intent = Intent.unclear
    next_state: ConversationState = ConversationState.CHATTING
    reading_recommended: bool = False
    suggested_spread: str | None = None
    action: ConversationAction = ConversationAction.none
    memory_candidates: list[str] = []
