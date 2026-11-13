"""Phase 6: SQLite database (Python's built-in sqlite3, no ORM).

One file (settings.DB_PATH, default data/app.db) holds everything that must survive a restart.
Delete the file to reset all data; the tables are created again automatically.

Tables
  sessions         one row per intake chat: language + profile (JSON)
  messages         intake chat messages (personal numbers already masked)
  plans            every generated plan (history); the newest row is the current plan
  checklist_items  launch steps from the plan + the user's own steps, with done / not done
  qa_messages      the "Ask a question" thread, with the sources used for each answer
  memory           rolling summary of older Q&A turns (so the prompt stays short)
"""
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

from app.config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    language TEXT NOT NULL,
    profile_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    plan_json TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS checklist_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    position INTEGER NOT NULL,
    title TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '',
    estimated_days INTEGER,
    estimated_cost_inr INTEGER,
    done INTEGER NOT NULL DEFAULT 0,
    done_at TEXT,
    is_custom INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS qa_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    sources_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS memory (
    session_id TEXT PRIMARY KEY,
    summary TEXT NOT NULL DEFAULT '',
    summarized_until INTEGER NOT NULL DEFAULT 0,  -- last qa_messages.id included in the summary
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id);
CREATE INDEX IF NOT EXISTS idx_plans_session ON plans(session_id, id);
CREATE INDEX IF NOT EXISTS idx_checklist_session ON checklist_items(session_id, position);
CREATE INDEX IF NOT EXISTS idx_qa_session ON qa_messages(session_id, id);
"""

_initialized: set[str] = set()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_db(path: Optional[Path] = None) -> None:
    """Create the folder and all tables if they do not exist yet (safe to call many times)."""
    path = Path(path or settings.DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()
    _initialized.add(str(path))


@contextmanager
def get_conn(path: Optional[Path] = None) -> Iterator[sqlite3.Connection]:
    """A short-lived connection: commits on success, rolls back on error, always closes.
    A new connection per call keeps things simple and safe with FastAPI's worker threads."""
    path = Path(path or settings.DB_PATH)
    if str(path) not in _initialized:
        init_db(path)
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row  # rows behave like dicts: row["title"]
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
