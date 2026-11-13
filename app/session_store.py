"""Where chat sessions live.

Phase 2: a plain Python dict in memory (lost when the server restarts).
Phase 6: swap InMemorySessionStore for a SQLite version with the SAME three methods
(create / get / save) and nothing else in the app has to change.
"""
import uuid
from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.models import BusinessProfile, LanguageCode


class Message(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class Session(BaseModel):
    session_id: str
    profile: BusinessProfile
    messages: list[Message] = Field(default_factory=list)
    created_at: datetime
    # Phase 4: the last generated BusinessPlan, stored as plain JSON (easy to put in SQLite later).
    plan: Optional[dict] = None


class InMemorySessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    def create(self, language: LanguageCode = "en") -> Session:
        session = Session(
            session_id=str(uuid.uuid4()),
            profile=BusinessProfile(language=language),
            created_at=datetime.now(timezone.utc),
        )
        self.save(session)
        return session.model_copy(deep=True)

    def get(self, session_id: str) -> Optional[Session]:
        session = self._sessions.get(session_id)
        # Hand out a COPY, like a database would: changes only count after save().
        return session.model_copy(deep=True) if session else None

    def save(self, session: Session) -> None:
        self._sessions[session.session_id] = session.model_copy(deep=True)


# One shared store for the whole app.
store = InMemorySessionStore()


def create_session(language: LanguageCode = "en") -> Session:
    return store.create(language)


def get_session(session_id: str) -> Optional[Session]:
    return store.get(session_id)


def save_session(session: Session) -> None:
    store.save(session)
