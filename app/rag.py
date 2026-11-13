"""Phase 3 (A): RAG = Retrieval-Augmented Generation over official scheme documents.

Two halves:
  INDEXING  (run once, by scripts/ingest_docs.py)
      data/docs/*.md|.txt|.pdf -> split into chunks -> embeddings -> ChromaDB (./chroma_db)
  SEARCHING (every request)
      question -> embedding -> closest chunks in ChromaDB -> RetrievedChunk list with sources

Phase 4 pastes `format_context(chunks)` into the plan prompt, so the LLM can quote real schemes
with their official links instead of inventing them.
"""
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Optional

os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")  # stop ChromaDB from sending usage stats

import yaml  # noqa: E402
from langchain_core.documents import Document  # noqa: E402
from langchain_core.embeddings import Embeddings  # noqa: E402
from langchain_text_splitters import RecursiveCharacterTextSplitter  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from app.config import settings  # noqa: E402
from app.models import BusinessProfile  # noqa: E402

CHUNK_SIZE = 800
CHUNK_OVERLAP = 120
SUPPORTED_EXTENSIONS = {".md", ".txt", ".pdf"}


class IndexNotBuiltError(RuntimeError):
    """The vector database does not exist yet. API -> 503."""


class RetrievedChunk(BaseModel):
    text: str
    scheme: str
    category: str
    source_url: str
    page: Optional[int] = None
    score: float  # relevance, 0 (unrelated) to 1 (very close)
    chunk_id: str


# =====================================================================
# INDEXING: load -> split -> embed -> store
# =====================================================================

FRONT_MATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def parse_front_matter(text: str) -> tuple[dict, str]:
    """Split '---\\nyaml\\n---\\nbody' into (metadata dict, body). No front-matter -> ({}, text)."""
    match = FRONT_MATTER_RE.match(text)
    if not match:
        return {}, text
    meta = yaml.safe_load(match.group(1)) or {}
    return meta, text[match.end():]


def scheme_from_filename(path: Path) -> str:
    """'pm_svanidhi_guidelines.pdf' -> 'Pm Svanidhi Guidelines'."""
    return path.stem.replace("_", " ").replace("-", " ").title()


def clean_metadata(meta: dict, path: Path) -> dict:
    """ChromaDB only stores str/int/float/bool, so lists become comma-separated text."""
    suitable = meta.get("suitable_for") or ["any"]
    if isinstance(suitable, list):
        suitable = ", ".join(str(s) for s in suitable)
    return {
        "scheme": str(meta.get("scheme") or scheme_from_filename(path)),
        "category": str(meta.get("category") or "general"),
        "suitable_for": str(suitable),
        "source_url": str(meta.get("source_url") or f"local file: {path.name}"),
        "last_verified": str(meta.get("last_verified") or ""),
        "source_file": path.name,
    }


def load_documents(docs_dir: Path) -> list[Document]:
    """Read every .md / .txt / .pdf file. One Document per text file, one per PDF page."""
    documents: list[Document] = []
    for path in sorted(Path(docs_dir).iterdir()):
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS or path.name.lower() == "readme.md":
            continue
        if path.suffix.lower() == ".pdf":
            from pypdf import PdfReader

            meta = clean_metadata({}, path)
            for page_number, page in enumerate(PdfReader(str(path)).pages, start=1):
                text = (page.extract_text() or "").strip()
                if text:
                    documents.append(Document(page_content=text, metadata={**meta, "page": page_number}))
        else:
            meta, body = parse_front_matter(path.read_text(encoding="utf-8"))
            # page 0 = "not a PDF" (ChromaDB metadata cannot be None)
            documents.append(Document(page_content=body.strip(), metadata={**clean_metadata(meta, path), "page": 0}))
    return documents


def split_documents(documents: list[Document]) -> list[Document]:
    """Cut documents into ~800-character chunks that overlap a little, so no sentence is lost
    at a border. Each chunk keeps its document's metadata and gets a stable chunk_id."""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n## ", "\n\n", "\n", ". ", " ", ""],  # prefer cutting at section headings
    )
    chunks = splitter.split_documents(documents)
    counters: dict[str, int] = {}
    for chunk in chunks:
        key = f"{chunk.metadata['source_file']}:p{chunk.metadata['page']}"
        counters[key] = counters.get(key, 0) + 1
        chunk.metadata["chunk_id"] = f"{key}:c{counters[key]}"
        # Put the scheme name inside the text too: the embedding then "knows" which scheme the
        # chunk is about, even for a chunk like "Documents needed: ..." that never names it.
        chunk.page_content = f"{chunk.metadata['scheme']} ({chunk.metadata['category']})\n{chunk.page_content}"
    return chunks


@lru_cache(maxsize=1)
def get_embeddings() -> Embeddings:
    """The real multilingual embedding model (downloaded on first use, then cached on disk)."""
    from langchain_huggingface import HuggingFaceEmbeddings

    return HuggingFaceEmbeddings(
        model_name=settings.EMBEDDING_MODEL,
        model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": True},
    )


def _chroma(persist_dir: Path, embeddings: Embeddings):
    from langchain_chroma import Chroma

    return Chroma(
        collection_name=settings.CHROMA_COLLECTION,
        persist_directory=str(persist_dir),
        embedding_function=embeddings,
        collection_metadata={"hnsw:space": "cosine"},  # score = cosine similarity
    )


def build_index(docs_dir: Path, persist_dir: Path, embeddings: Optional[Embeddings] = None) -> list[Document]:
    """Rebuild the collection from scratch (old one deleted first -> never any duplicates).
    Returns the chunks that were stored."""
    embeddings = embeddings or get_embeddings()
    chunks = split_documents(load_documents(docs_dir))
    if not chunks:
        raise ValueError(f"No .md, .txt or .pdf documents found in {docs_dir}")

    store = _chroma(persist_dir, embeddings)
    store.delete_collection()               # wipe the old index
    store = _chroma(persist_dir, embeddings)  # fresh, empty collection
    store.add_documents(chunks, ids=[c.metadata["chunk_id"] for c in chunks])
    reset_store()  # make the API reload the new index
    return chunks


# =====================================================================
# SEARCHING
# =====================================================================

_store = None  # module-level cache: the vector store is opened once, then reused


def reset_store() -> None:
    global _store
    _store = None


def set_store(store) -> None:
    """Use a ready-made store (tests use this with fake embeddings)."""
    global _store
    _store = store


def get_store(persist_dir: Optional[Path] = None, embeddings: Optional[Embeddings] = None):
    """Open the vector store once (lazy). Raises IndexNotBuiltError if it was never built."""
    global _store
    if _store is not None:
        return _store
    persist_dir = Path(persist_dir or settings.CHROMA_DIR)
    if not persist_dir.exists() or not any(persist_dir.iterdir()):
        raise IndexNotBuiltError(
            f"Scheme index not found at {persist_dir}. Run python scripts/ingest_docs.py first."
        )
    store = _chroma(persist_dir, embeddings or get_embeddings())
    if store._collection.count() == 0:
        raise IndexNotBuiltError("Scheme index is empty. Run python scripts/ingest_docs.py first.")
    _store = store
    return _store


def retrieve(query: str, k: int = 4, category: Optional[str] = None) -> list[RetrievedChunk]:
    """Top-k chunks for a question, best first. Results below RAG_MIN_SCORE are dropped,
    so we return nothing rather than an unrelated scheme."""
    if not query or not query.strip():
        raise ValueError("Query must not be empty.")
    store = get_store()
    search_filter = {"category": category} if category else None
    # Chroma returns a cosine DISTANCE (0 = identical). Turn it into a similarity score
    # (1 = identical, 0 = unrelated) that is easy to explain and to compare with RAG_MIN_SCORE.
    results = store.similarity_search_with_score(query, k=k, filter=search_filter)

    chunks = []
    for doc, distance in results:
        score = 1 - distance
        if score < settings.RAG_MIN_SCORE:
            continue
        meta = doc.metadata
        chunks.append(
            RetrievedChunk(
                text=doc.page_content,
                scheme=meta.get("scheme", "unknown"),
                category=meta.get("category", "general"),
                source_url=meta.get("source_url", ""),
                page=meta.get("page") or None,
                score=round(float(score), 3),
                chunk_id=meta.get("chunk_id", ""),
            )
        )
    return chunks


def list_sources() -> list[dict]:
    """Every scheme in the index with its category and official source URL."""
    metadatas = get_store().get(include=["metadatas"])["metadatas"]
    sources = {}
    for meta in metadatas:
        sources.setdefault(meta["scheme"], {
            "scheme": meta["scheme"],
            "category": meta.get("category", ""),
            "source_url": meta.get("source_url", ""),
            "last_verified": meta.get("last_verified", ""),
        })
    return sorted(sources.values(), key=lambda s: s["scheme"])


def index_info(persist_dir: Optional[Path] = None) -> dict:
    """Quick look at the index WITHOUT loading the embedding model (used by the startup log and
    the evaluation): {"built": bool, "chunks": int, "sources": [{"scheme", "source_url"}]}."""
    persist_dir = Path(persist_dir or settings.CHROMA_DIR)
    if not persist_dir.exists() or not any(persist_dir.iterdir()):
        return {"built": False, "chunks": 0, "sources": []}
    try:
        import chromadb

        client = chromadb.PersistentClient(path=str(persist_dir), settings=chromadb.config.Settings(anonymized_telemetry=False))
        collection = client.get_collection(settings.CHROMA_COLLECTION)
        metadatas = collection.get(include=["metadatas"])["metadatas"]
    except Exception:
        return {"built": False, "chunks": 0, "sources": []}
    sources = {m["scheme"]: {"scheme": m["scheme"], "source_url": m.get("source_url", "")} for m in metadatas}
    return {"built": bool(metadatas), "chunks": len(metadatas), "sources": sorted(sources.values(), key=lambda x: x["scheme"])}


# =====================================================================
# PROFILE -> SEARCHES
# =====================================================================

# Words that tell us the business sells food (-> FSSAI) or is a street vendor (-> SVANidhi).
FOOD_WORDS = [
    "food", "pickle", "achar", "achaar", "tiffin", "kitchen", "snack", "sweet", "mithai", "bakery",
    "cake", "tea", "chai", "juice", "khana", "meal", "restaurant", "dhaba", "catering", "momo",
    "samosa", "namkeen", "papad", "spice", "masala", "dairy", "milk", "paneer", "chaat", "biryani",
    "cook", "thali", "dosa", "idli", "fruit", "vegetable", "sabzi", "sabji",
]
VENDOR_WORDS = [
    "street", "cart", "thela", "thel", "rehri", "rehdi", "hawker", "vendor", "stall", "footpath",
    "pheri", "ठेला", "रेहड़ी",
]
MANUFACTURING_WORDS = ["manufactur", "make", "making", "factory", "unit", "production", "machine"]
WOMEN_SC_ST_WORDS = [
    "woman", "women", "mahila", "lady", "female", "sc/st", "scheduled caste", "scheduled tribe", "dalit", "adivasi",
]


def _has_any(text: str, words: list[str]) -> bool:
    return any(w in text for w in words)


def build_query_from_profile(profile: BusinessProfile) -> list[str]:
    """Turn a profile into 2-3 focused searches (one search per need works better than one long one)."""
    idea = profile.business_idea or "small business"
    text = " ".join(
        str(v) for v in [profile.business_idea, profile.skills, profile.target_customers,
                         profile.sales_channel, profile.experience, profile.extra_notes] if v
    ).lower() + " "
    is_food = _has_any(text, FOOD_WORDS)
    is_vendor = _has_any(text, VENDOR_WORDS)

    # 1. Money: a loan sized to the budget.
    budget = f" of about {profile.budget_inr} rupees" if profile.budget_inr else ""
    queries = [f"collateral-free loan for a small business{budget} to start {idea}"]

    # 2. Registration / licence for this type of business.
    if is_food:
        queries.append(f"FSSAI food registration licence needed to sell {idea}, turnover up to 12 lakh")
    else:
        queries.append(f"free Udyam MSME registration and GST registration limit for {idea}")

    # 3. A specific extra search if something stands out.
    if is_vendor:
        queries.append(f"street vendor loan for cart, thela or stall selling {idea}")
    elif _has_any(text, WOMEN_SC_ST_WORDS):
        queries.append(f"bank loan for women or SC/ST entrepreneurs to start a new {idea} enterprise")
    elif _has_any(text, MANUFACTURING_WORDS) or (profile.budget_inr or 0) >= 200_000:
        queries.append(f"government subsidy margin money for a new {idea} unit")
    return queries


def retrieve_for_profile(profile: BusinessProfile, k_per_query: int = 3, max_results: int = 8) -> list[RetrievedChunk]:
    """Run the profile's searches, merge them, remove duplicates (keep the best score), best first."""
    best: dict[str, RetrievedChunk] = {}
    for query in build_query_from_profile(profile):
        for chunk in retrieve(query, k=k_per_query):
            if chunk.chunk_id not in best or chunk.score > best[chunk.chunk_id].score:
                best[chunk.chunk_id] = chunk
    return sorted(best.values(), key=lambda c: c.score, reverse=True)[:max_results]


def format_context(chunks: list[RetrievedChunk]) -> str:
    """Numbered context block for an LLM prompt, every chunk tagged with its source."""
    if not chunks:
        return "No matching official scheme documents were found."
    parts = []
    for i, chunk in enumerate(chunks, start=1):
        page = f", page {chunk.page}" if chunk.page else ""
        parts.append(f"[{i}] [source: {chunk.scheme} | {chunk.source_url}{page}]\n{chunk.text.strip()}")
    return "\n\n".join(parts)
