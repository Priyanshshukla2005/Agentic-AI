"""Force mock mode BEFORE the app is imported, so tests never call a real LLM.
(load_dotenv does not overwrite variables that are already set.)"""
import os
import sys
from pathlib import Path

os.environ["LLM_PROVIDER"] = "mock"
os.environ["MOCK_PLAN_VARIANT"] = "valid"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


import pytest  # noqa: E402


@pytest.fixture
def fake_scheme_index(tmp_path, monkeypatch):
    """Index the REAL data/docs with fake embeddings (no model download) and make the app use it.
    Fake vectors give random scores, so the relevance threshold is switched off."""
    from langchain_core.embeddings import DeterministicFakeEmbedding

    from app import rag
    from app.config import settings

    embeddings = DeterministicFakeEmbedding(size=64)
    rag.build_index(settings.DOCS_DIR, tmp_path / "db", embeddings=embeddings)
    rag.set_store(rag._chroma(tmp_path / "db", embeddings))
    monkeypatch.setattr(settings, "RAG_MIN_SCORE", -1.0)
    yield
    rag.reset_store()


@pytest.fixture
def no_scheme_index(tmp_path, monkeypatch):
    """Pretend scripts/ingest_docs.py was never run."""
    from app import rag
    from app.config import settings

    rag.reset_store()
    monkeypatch.setattr(settings, "CHROMA_DIR", tmp_path / "missing_db")
    yield
    rag.reset_store()


@pytest.fixture(autouse=True)
def temp_database(tmp_path, monkeypatch):
    """Every test gets its own empty SQLite file, so tests never touch data/app.db or each other."""
    from app import session_store
    from app.config import settings

    monkeypatch.setattr(settings, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(settings, "SESSION_STORE", "sqlite")
    session_store.reset_store()
    yield tmp_path / "test.db"
    session_store.reset_store()
