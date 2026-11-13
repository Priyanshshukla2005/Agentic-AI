"""Where chat sessions live.

Two stores with the SAME three methods (create / get / save), chosen by SESSION_STORE in .env:
  sqlite (default) - SQLiteSessionStore: data/app.db, survives server restarts (Phase 6)
  memory           - InMemorySessionStore: a Python dict, lost on restart (Phase 2, handy for tests)
The rest of the app only calls create_session(), get_session() and save_session().
"""
import json
import uuid
from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, Field

from app import db
from app.config import settings
from app.models import BusinessProfile, LanguageCode


class Message(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class Session(BaseModel):
    session_id: str
    profile: BusinessProfile
    messages: list[Message] = Field(default_factory=list)
    created_at: datetime
    # The latest generated BusinessPlan as plain JSON (None until a plan is made).
    plan: Optional[dict] = None


def _new_session(language: LanguageCode) -> Session:
    return Session(
        session_id=str(uuid.uuid4()),
        profile=BusinessProfile(language=language),
        created_at=datetime.now(timezone.utc),
    )


class InMemorySessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    def create(self, language: LanguageCode = "en") -> Session:
        session = _new_session(language)
        self.save(session)
        return session.model_copy(deep=True)

    def get(self, session_id: str) -> Optional[Session]:
        session = self._sessions.get(session_id)
        # Hand out a COPY, like a database would: changes only count after save().
        return session.model_copy(deep=True) if session else None

    def save(self, session: Session) -> None:
        self._sessions[session.session_id] = session.model_copy(deep=True)

    def list_plans(self, session_id: str) -> list[dict]:
        session = self._sessions.get(session_id)
        return [session.plan] if session and session.plan else []


class SQLiteSessionStore:
    """Sessions in SQLite. Messages are append-only and plans keep a history (newest = current)."""

    def __init__(self, path=None) -> None:
        self.path = path  # None = settings.DB_PATH at call time
        db.init_db(self.path)

    def create(self, language: LanguageCode = "en") -> Session:
        session = _new_session(language)
        self.save(session)
        return session

    def get(self, session_id: str) -> Optional[Session]:
        with db.get_conn(self.path) as conn:
            row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
            if row is None:
                return None
            messages = conn.execute(
                "SELECT role, content FROM messages WHERE session_id = ? ORDER BY id", (session_id,)
            ).fetchall()
            plan = conn.execute(
                "SELECT plan_json FROM plans WHERE session_id = ? ORDER BY id DESC LIMIT 1", (session_id,)
            ).fetchone()
        return Session(
            session_id=row["id"],
            profile=BusinessProfile.model_validate_json(row["profile_json"]),
            messages=[Message(role=m["role"], content=m["content"]) for m in messages],
            created_at=datetime.fromisoformat(row["created_at"]),
            plan=json.loads(plan["plan_json"]) if plan else None,
        )

    def save(self, session: Session) -> None:
        stamp = db.now()
        with db.get_conn(self.path) as conn:
            # 1. Session row (insert or update).
            conn.execute(
                """INSERT INTO sessions (id, language, profile_json, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET language = excluded.language,
                       profile_json = excluded.profile_json, updated_at = excluded.updated_at""",
                (session.session_id, session.profile.language, session.profile.model_dump_json(),
                 session.created_at.isoformat(), stamp),
            )
            # 2. Messages are only ever appended: insert the ones the database does not have yet.
            stored = conn.execute("SELECT COUNT(*) FROM messages WHERE session_id = ?", (session.session_id,)).fetchone()[0]
            conn.executemany(
                "INSERT INTO messages (session_id, role, content, created_at) VALUES (?, ?, ?, ?)",
                [(session.session_id, m.role, m.content, stamp) for m in session.messages[stored:]],
            )
            # 3. A new plan (different from the latest stored one) is added to the history.
            if session.plan is not None:
                latest = conn.execute(
                    "SELECT plan_json FROM plans WHERE session_id = ? ORDER BY id DESC LIMIT 1", (session.session_id,)
                ).fetchone()
                plan_json = json.dumps(session.plan, ensure_ascii=False)
                if latest is None or latest["plan_json"] != plan_json:
                    conn.execute(
                        "INSERT INTO plans (session_id, plan_json, prompt_version, created_at) VALUES (?, ?, ?, ?)",
                        (session.session_id, plan_json, session.plan.get("prompt_version", ""), stamp),
                    )

    def list_plans(self, session_id: str) -> list[dict]:
        """All plans of a session, oldest first (the last one is the current plan)."""
        with db.get_conn(self.path) as conn:
            rows = conn.execute("SELECT plan_json FROM plans WHERE session_id = ? ORDER BY id", (session_id,)).fetchall()
        return [json.loads(r["plan_json"]) for r in rows]


# One shared store, created on first use from settings.SESSION_STORE.
_store = None


def get_store():
    global _store
    if _store is None:
        _store = InMemorySessionStore() if settings.SESSION_STORE == "memory" else SQLiteSessionStore()
    return _store


def reset_store() -> None:
    """Forget the current store (tests use this after changing DB_PATH / SESSION_STORE)."""
    global _store
    _store = None


def create_session(language: LanguageCode = "en") -> Session:
    return get_store().create(language)


def get_session(session_id: str) -> Optional[Session]:
    return get_store().get(session_id)


def save_session(session: Session) -> None:
    get_store().save(session)


def list_plans(session_id: str) -> list[dict]:
    return get_store().list_plans(session_id)
