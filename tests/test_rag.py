"""Phase 3 RAG tests. Fake embeddings + a temporary Chroma folder: no model download, no network."""
import pytest
from fastapi.testclient import TestClient
from langchain_core.embeddings import DeterministicFakeEmbedding

from app import rag
from app.config import settings
from app.main import app
from app.models import BusinessProfile
from app.session_store import create_session, save_session

client = TestClient(app)

FOOD_DOC = """---
scheme: Test Food Licence
category: license
suitable_for: [food business, street vendor]
source_url: https://example.gov.in/food
last_verified: 2026-11-13
---

## What it is
Small food sellers need a food licence before selling pickles or tiffin.

## How much / cost
Registration is for businesses with turnover up to 12 lakh.
"""

PLAIN_DOC = "Loan scheme for street vendors. Small working capital loans for carts and stalls."


@pytest.fixture
def fake_index(tmp_path, monkeypatch):
    """Two tiny docs indexed with fake embeddings; the app uses this index during the test."""
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "food_licence.md").write_text(FOOD_DOC, encoding="utf-8")
    (docs / "vendor_loan.txt").write_text(PLAIN_DOC, encoding="utf-8")
    (docs / "README.md").write_text("not a scheme, must be skipped", encoding="utf-8")

    embeddings = DeterministicFakeEmbedding(size=64)
    chunks = rag.build_index(docs, tmp_path / "db", embeddings=embeddings)
    rag.set_store(rag._chroma(tmp_path / "db", embeddings))
    monkeypatch.setattr(settings, "RAG_MIN_SCORE", -1.0)  # fake vectors give random scores
    yield chunks
    rag.reset_store()


# ---------- Loading and metadata ----------

def test_front_matter_parsing():
    meta, body = rag.parse_front_matter(FOOD_DOC)
    assert meta["scheme"] == "Test Food Licence"
    assert meta["suitable_for"] == ["food business", "street vendor"]
    assert body.lstrip().startswith("## What it is")
    assert rag.parse_front_matter("no front matter") == ({}, "no front matter")


def test_ingestion_metadata(fake_index):
    files = {c.metadata["source_file"] for c in fake_index}
    assert files == {"food_licence.md", "vendor_loan.txt"}  # README skipped

    food = next(c for c in fake_index if c.metadata["source_file"] == "food_licence.md")
    assert food.metadata["category"] == "license"
    assert food.metadata["suitable_for"] == "food business, street vendor"  # list -> text
    assert food.metadata["source_url"] == "https://example.gov.in/food"

    plain = next(c for c in fake_index if c.metadata["source_file"] == "vendor_loan.txt")
    assert plain.metadata["scheme"] == "Vendor Loan"  # from the file name
    assert plain.metadata["source_url"] == "local file: vendor_loan.txt"
    assert len({c.metadata["chunk_id"] for c in fake_index}) == len(fake_index)


def test_rebuilding_does_not_duplicate(fake_index, tmp_path):
    embeddings = DeterministicFakeEmbedding(size=64)
    rag.build_index(tmp_path / "docs", tmp_path / "db", embeddings=embeddings)
    store = rag._chroma(tmp_path / "db", embeddings)
    assert store._collection.count() == len(fake_index)


# ---------- Searching ----------

def test_exact_text_is_top_result(fake_index):
    target = fake_index[0]
    results = rag.retrieve(target.page_content, k=2)
    assert results[0].chunk_id == target.metadata["chunk_id"]
    assert results[0].score > 0.99


def test_threshold_filters_results(fake_index, monkeypatch):
    assert len(rag.retrieve("anything", k=10)) == len(fake_index)
    monkeypatch.setattr(settings, "RAG_MIN_SCORE", 1.01)
    assert rag.retrieve("anything", k=10) == []


def test_category_filter(fake_index):
    results = rag.retrieve("licence", k=10, category="license")
    assert results and all(r.category == "license" for r in results)


def test_empty_query_rejected(fake_index):
    with pytest.raises(ValueError):
        rag.retrieve("   ")


def test_build_query_from_profile():
    food_vendor = BusinessProfile(business_idea="pickle stall", budget_inr=15000)
    queries = rag.build_query_from_profile(food_vendor)
    assert len(queries) == 3
    assert "15000" in queries[0]
    assert "FSSAI" in queries[1]
    assert "street vendor" in queries[2]

    tailor = BusinessProfile(business_idea="tailoring shop", budget_inr=30000)
    queries = rag.build_query_from_profile(tailor)
    assert "Udyam" in queries[1] and len(queries) == 2


def test_retrieve_for_profile_deduplicates(fake_index):
    profile = BusinessProfile(business_idea="pickle stall", budget_inr=15000)
    # 3 queries x 10 results each, but there are only a few chunks: every chunk must appear once.
    results = rag.retrieve_for_profile(profile, k_per_query=10, max_results=50)
    ids = [r.chunk_id for r in results]
    assert len(ids) == len(set(ids)) == len(fake_index)
    assert [r.score for r in results] == sorted([r.score for r in results], reverse=True)


def test_format_context(fake_index):
    chunks = rag.retrieve("food licence", k=2)
    context = rag.format_context(chunks)
    assert context.startswith("[1] [source: ")
    assert "[2] [source: " in context
    assert "https://example.gov.in/food" in context or "local file: vendor_loan.txt" in context
    assert rag.format_context([]) == "No matching official scheme documents were found."


def test_missing_index_raises(tmp_path):
    rag.reset_store()
    with pytest.raises(rag.IndexNotBuiltError, match="Run python scripts/ingest_docs.py first"):
        rag.get_store(persist_dir=tmp_path / "does_not_exist")


# ---------- Endpoints ----------

def test_search_endpoint(fake_index):
    r = client.post("/api/rag/search", json={"query": "pickle licence", "k": 2})
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["chunks"]) == 2
    assert {"text", "scheme", "category", "source_url", "page", "score"} <= set(body["chunks"][0])
    assert body["context"].startswith("[1]")


def test_search_endpoint_errors(fake_index):
    assert client.post("/api/rag/search", json={"query": " "}).status_code == 400
    assert client.post("/api/rag/search", json={"query": "x", "category": "food"}).status_code == 422


def test_sources_endpoint(fake_index):
    sources = client.get("/api/rag/sources").json()["sources"]
    assert {s["scheme"] for s in sources} == {"Test Food Licence", "Vendor Loan"}


def test_for_session_endpoint(fake_index):
    session = create_session("en")
    session.profile.business_idea = "pickle stall"
    session.profile.budget_inr = 15000
    save_session(session)
    r = client.post("/api/rag/for-session", json={"session_id": session.session_id})
    assert r.status_code == 200, r.text
    assert len(r.json()["queries"]) == 3 and r.json()["chunks"]

    empty = create_session("en")
    assert client.post("/api/rag/for-session", json={"session_id": empty.session_id}).status_code == 400
    assert client.post("/api/rag/for-session", json={"session_id": "nope"}).status_code == 404


def test_search_returns_503_without_index(tmp_path, monkeypatch):
    rag.reset_store()
    monkeypatch.setattr(settings, "CHROMA_DIR", tmp_path / "empty")
    r = client.post("/api/rag/search", json={"query": "loan"})
    assert r.status_code == 503
    assert "ingest_docs.py" in r.json()["detail"]
    assert client.get("/api/rag/sources").status_code == 503
