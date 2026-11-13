"""Phase 6: the launch checklist, stored on the server (table checklist_items).

Plan steps come from plan.draft.launch_steps (is_custom = 0); users can add their own steps
(is_custom = 1). When a new plan is generated, sync_from_plan() replaces the plan steps but keeps
the user's own steps, and keeps "done" for steps whose title did not change.
"""
from typing import Optional

from pydantic import BaseModel

from app import db


class ChecklistItem(BaseModel):
    id: int
    position: int
    title: str
    detail: str
    estimated_days: Optional[int] = None
    estimated_cost_inr: Optional[int] = None
    done: bool
    done_at: Optional[str] = None
    is_custom: bool


class Progress(BaseModel):
    done: int
    total: int
    percent: int


def _norm(title: str) -> str:
    return " ".join(title.lower().split())


def _row_to_item(row) -> ChecklistItem:
    return ChecklistItem(
        id=row["id"], position=row["position"], title=row["title"], detail=row["detail"],
        estimated_days=row["estimated_days"], estimated_cost_inr=row["estimated_cost_inr"],
        done=bool(row["done"]), done_at=row["done_at"], is_custom=bool(row["is_custom"]),
    )


def list_items(session_id: str) -> list[ChecklistItem]:
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM checklist_items WHERE session_id = ? ORDER BY position, id", (session_id,)
        ).fetchall()
    return [_row_to_item(r) for r in rows]


def progress(items: list[ChecklistItem]) -> Progress:
    done = sum(i.done for i in items)
    total = len(items)
    return Progress(done=done, total=total, percent=round(done / total * 100) if total else 0)


def next_step(items: list[ChecklistItem]) -> Optional[ChecklistItem]:
    """The first step that is not done yet (None when everything is done)."""
    return next((i for i in items if not i.done), None)


def sync_from_plan(session_id: str, launch_steps: list) -> list[ChecklistItem]:
    """Replace the plan steps with the new plan's launch_steps. Custom steps stay (after the plan
    steps); a plan step whose title is unchanged keeps its done state."""
    with db.get_conn() as conn:
        old = conn.execute(
            "SELECT * FROM checklist_items WHERE session_id = ? ORDER BY position, id", (session_id,)
        ).fetchall()
        done_before = {_norm(r["title"]): (r["done"], r["done_at"]) for r in old if not r["is_custom"]}
        custom = [r for r in old if r["is_custom"]]

        conn.execute("DELETE FROM checklist_items WHERE session_id = ? AND is_custom = 0", (session_id,))
        for position, step in enumerate(launch_steps):
            done, done_at = done_before.get(_norm(step.title), (0, None))
            conn.execute(
                """INSERT INTO checklist_items (session_id, position, title, detail, estimated_days,
                       estimated_cost_inr, done, done_at, is_custom) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)""",
                (session_id, position, step.title, step.detail, step.estimated_days,
                 step.estimated_cost_inr, done, done_at),
            )
        for offset, row in enumerate(custom):  # own steps go after the plan steps, in their order
            conn.execute("UPDATE checklist_items SET position = ? WHERE id = ?", (len(launch_steps) + offset, row["id"]))
    return list_items(session_id)


def set_done(session_id: str, item_id: int, done: bool) -> Optional[ChecklistItem]:
    with db.get_conn() as conn:
        cursor = conn.execute(
            "UPDATE checklist_items SET done = ?, done_at = ? WHERE id = ? AND session_id = ?",
            (int(done), db.now() if done else None, item_id, session_id),
        )
        if cursor.rowcount == 0:
            return None
        row = conn.execute("SELECT * FROM checklist_items WHERE id = ?", (item_id,)).fetchone()
    return _row_to_item(row)


def add_custom(session_id: str, title: str, detail: str = "") -> ChecklistItem:
    with db.get_conn() as conn:
        position = conn.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 FROM checklist_items WHERE session_id = ?", (session_id,)
        ).fetchone()[0]
        cursor = conn.execute(
            """INSERT INTO checklist_items (session_id, position, title, detail, done, is_custom)
               VALUES (?, ?, ?, ?, 0, 1)""",
            (session_id, position, title.strip(), detail.strip()),
        )
        row = conn.execute("SELECT * FROM checklist_items WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return _row_to_item(row)


def delete_item(session_id: str, item_id: int) -> str:
    """Returns "deleted", "not_found" or "forbidden" (plan steps cannot be deleted, only ticked)."""
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT is_custom FROM checklist_items WHERE id = ? AND session_id = ?", (item_id, session_id)
        ).fetchone()
        if row is None:
            return "not_found"
        if not row["is_custom"]:
            return "forbidden"
        conn.execute("DELETE FROM checklist_items WHERE id = ?", (item_id,))
    return "deleted"
