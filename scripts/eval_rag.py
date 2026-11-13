"""Phase 3: measure how well scheme search works (hit-rate@4).

Run from the project folder (after python scripts/ingest_docs.py):
    python scripts/eval_rag.py

For each question in data/eval/rag_questions.json we search the top 4 chunks (with the same
relevance threshold the app uses). A question is a HIT if the expected scheme is among them.
hit-rate@4 = hits / questions. We also print hit-rate@1 (expected scheme ranked first).
Do not edit the questions to raise the score; improve the documents, chunking or queries instead.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402
from app.evaluation.rag_eval import evaluate_rag  # noqa: E402


def main() -> int:
    print(f"Embeddings: {settings.EMBEDDING_MODEL} | min score: {settings.RAG_MIN_SCORE} | k=4\n")
    start = time.perf_counter()
    result = evaluate_rag(k=4)
    if "error" in result:
        print(f"ERROR: {result['error']}")
        return 1
    for r in result["rows"]:
        print(f"{'HIT ' if r['hit'] else 'MISS'}  #{r['id']:<2} [{r['lang']:<8}] {r['question'][:60]:<60} -> top: {r['best']}")
    n = result["total"]
    print(f"\nhit-rate@4: {result['hits']}/{n} = {result['hit_rate']:.0%}  ({time.perf_counter() - start:.1f}s)")
    print(f"hit-rate@1: {result['hits_at_1']}/{n} = {result['hit_rate_at_1']:.0%}  (expected scheme ranked first)")
    misses = [r for r in result["rows"] if not r["hit"]]
    if misses:
        print("\nMisses:")
        for r in misses:
            print(f"  #{r['id']} expected '{r['expected_scheme']}', got {r['found'] or 'nothing'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
