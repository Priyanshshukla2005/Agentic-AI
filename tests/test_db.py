"""Phase 6: SQLite persistence (each test gets its own temp DB file from conftest.py)."""
import sqlite3

from app import db, session_store
from app.session_store import Message, SQLiteSessionStore

TABLES = {"sessions", "messages", "plans", "checklist_items", "qa_messages", "memory"}


def test_tables_created(temp_database):
    db.init_db()
    db.init_db()  # idempotent: second call must not fail
    with sqlite3.connect(temp_database) as conn:
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert TABLES <= names


def test_session_survives_a_restart(temp_database):
    store = SQLiteSessionStore()
    session = store.create("hi")
    session.profile.business_idea = "achar"
    session.profile.budget_inr = 5000
    session.messages += [Message(role="assistant", content="नमस्ते"), Message(role="user", content="achar")]
    store.save(session)
    store.save(session)  # saving twice must not duplicate messages

    restarted = SQLiteSessionStore()  # a brand-new store object = the server started again
    loaded = restarted.get(session.session_id)
    assert loaded.profile.language == "hi"
    assert loaded.profile.business_idea == "achar" and loaded.profile.budget_inr == 5000
    assert [m.content for m in loaded.messages] == ["नमस्ते", "achar"]
    assert loaded.created_at == session.created_at
    assert restarted.get("does-not-exist") is None


def test_plan_history_keeps_latest():
    store = SQLiteSessionStore()
    session = store.create("en")
    session.plan = {"prompt_version": "plan_v4", "generated_at": "1"}
    store.save(session)
    store.save(session)  # unchanged plan: no new history row
    session.plan = {"prompt_version": "plan_v5", "generated_at": "2"}
    store.save(session)

    assert store.get(session.session_id).plan["generated_at"] == "2"
    history = store.list_plans(session.session_id)
    assert [p["generated_at"] for p in history] == ["1", "2"]


def test_memory_store_still_available(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "SESSION_STORE", "memory")
    session_store.reset_store()
    s = session_store.create_session("ta")
    assert isinstance(session_store.get_store(), session_store.InMemorySessionStore)
    assert session_store.get_session(s.session_id).profile.language == "ta"
