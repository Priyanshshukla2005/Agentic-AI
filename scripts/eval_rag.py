"""Phase 3: measure how well scheme search works (hit-rate@4).

Run from the project folder (after python scripts/ingest_docs.py):
    python scripts/eval_rag.py

For each question in data/eval/rag_questions.json we search the top 4 chunks (with the same
relevance threshold the app uses). A question is a HIT if the expected scheme is among them.
hit-rate@4 = hits / questions. We also print hit-rate@1 (expected scheme ranked first). Do not edit the questions to raise the score; improve the
documents, chunking or queries instead.
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import BASE_DIR, settings  # noqa: E402
from app.rag import IndexNotBuiltError, retrieve  # noqa: E402

K = 4
QUESTIONS_FILE = BASE_DIR / "data" / "eval" / "rag_questions.json"


def main() -> int:
    questions = json.loads(QUESTIONS_FILE.read_text(encoding="utf-8"))
    print(f"Embeddings: {settings.EMBEDDING_MODEL} | min score: {settings.RAG_MIN_SCORE} | k={K}\n")

    start = time.perf_counter()
    misses = []
    top1_hits = 0
    for q in questions:
        try:
            chunks = retrieve(q["question"], k=K)
        except IndexNotBuiltError as e:
            print(f"ERROR: {e}")
            return 1
        found = [c.scheme for c in chunks]
        hit = q["expected_scheme"] in found
        top1_hits += bool(found) and found[0] == q["expected_scheme"]
        best = f"{chunks[0].scheme} ({chunks[0].score:.2f})" if chunks else "nothing above threshold"
        print(f"{'HIT ' if hit else 'MISS'}  #{q['id']:<2} [{q['lang']:<8}] {q['question'][:60]:<60} -> top: {best}")
        if not hit:
            misses.append((q, found))

    hits = len(questions) - len(misses)
    print(f"\nhit-rate@{K}: {hits}/{len(questions)} = {hits / len(questions):.0%}  ({time.perf_counter() - start:.1f}s)")
    print(f"hit-rate@1: {top1_hits}/{len(questions)} = {top1_hits / len(questions):.0%}  (expected scheme ranked first)")
    if misses:
        print("\nMisses:")
        for q, found in misses:
            print(f"  #{q['id']} expected '{q['expected_scheme']}', got {found or 'nothing'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
