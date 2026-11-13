"""Phase 3: build the scheme search index (run again whenever data/docs changes).

Run from the project folder:
    python scripts/ingest_docs.py

data/docs/*.md|.txt|.pdf -> chunks -> multilingual embeddings -> ChromaDB at ./chroma_db
Re-running deletes the old collection first, so there are never duplicate chunks.
The first run downloads the embedding model (~470 MB); later runs use the cached copy.
"""
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402
from app.rag import build_index  # noqa: E402


def main() -> int:
    start = time.perf_counter()
    print(f"Docs folder : {settings.DOCS_DIR}")
    print(f"Vector DB   : {settings.CHROMA_DIR} (collection '{settings.CHROMA_COLLECTION}')")
    print(f"Embeddings  : {settings.EMBEDDING_MODEL}\n")

    try:
        chunks = build_index(settings.DOCS_DIR, settings.CHROMA_DIR)
    except Exception as e:
        print(f"INGESTION FAILED: {e}")
        return 1

    files = sorted({c.metadata["source_file"] for c in chunks})
    per_scheme = Counter(c.metadata["scheme"] for c in chunks)
    print(f"Files loaded: {len(files)}")
    for name in files:
        print(f"  - {name}")
    print(f"\nChunks per scheme ({len(chunks)} total):")
    for scheme, count in sorted(per_scheme.items()):
        print(f"  {count:3d}  {scheme}")
    print(f"\nDone in {time.perf_counter() - start:.1f}s. Next: python scripts/eval_rag.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
