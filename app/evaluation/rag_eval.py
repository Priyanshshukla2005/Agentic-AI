"""Phase 3/7: scheme search quality - hit-rate@4 (and @1) on data/eval/rag_questions.json.

Used by scripts/eval_rag.py (prints a table) and by the evaluation report.
"""
import json

from app.config import BASE_DIR
from app.rag import IndexNotBuiltError, retrieve

QUESTIONS_FILE = BASE_DIR / "data" / "eval" / "rag_questions.json"


def evaluate_rag(k: int = 4) -> dict:
    """{"hits", "hits_at_1", "total", "hit_rate", "hit_rate_at_1", "rows": [...]} or {"error": ...}."""
    questions = json.loads(QUESTIONS_FILE.read_text(encoding="utf-8"))
    rows, hits, top1 = [], 0, 0
    for q in questions:
        try:
            chunks = retrieve(q["question"], k=k)
        except IndexNotBuiltError as e:
            return {"error": str(e)}
        except Exception as e:  # e.g. the embedding model cannot be loaded
            return {"error": f"Scheme search failed: {e}"}
        found = [c.scheme for c in chunks]
        hit = q["expected_scheme"] in found
        first = bool(found) and found[0] == q["expected_scheme"]
        hits += hit
        top1 += first
        rows.append({**q, "found": found, "hit": hit, "top1": first,
                     "best": f"{chunks[0].scheme} ({chunks[0].score:.2f})" if chunks else "nothing above threshold"})
    n = len(questions)
    return {"k": k, "hits": hits, "hits_at_1": top1, "total": n,
            "hit_rate": round(hits / n, 3), "hit_rate_at_1": round(top1 / n, 3), "rows": rows}
