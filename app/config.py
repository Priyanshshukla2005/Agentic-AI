"""Central configuration, loaded from the .env file."""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


class Settings:
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "groq").strip().lower()

    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "").strip()
    GROQ_MODEL: str = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b").strip()

    OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "llama3.1:8b").strip()
    OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").strip()

    LLM_TEMPERATURE: float = float(os.getenv("LLM_TEMPERATURE", "0.3"))
    LLM_MAX_TOKENS: int = int(os.getenv("LLM_MAX_TOKENS", "2048"))

    PROMPTS_DIR: Path = BASE_DIR / "app" / "prompts"

    # --- Phase 3: RAG (scheme documents -> vector database) ---
    DOCS_DIR: Path = BASE_DIR / "data" / "docs"
    CHROMA_DIR: Path = BASE_DIR / os.getenv("CHROMA_DIR", "chroma_db")
    CHROMA_COLLECTION: str = "schemes"
    # Multilingual model: Hindi / Hinglish questions still match the English documents.
    EMBEDDING_MODEL: str = os.getenv(
        "EMBEDDING_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    ).strip()
    # Search results with a relevance score below this (0 to 1) are dropped as "not related".
    RAG_MIN_SCORE: float = float(os.getenv("RAG_MIN_SCORE", "0.25"))

    @property
    def model_name(self) -> str:
        return {
            "groq": self.GROQ_MODEL,
            "ollama": self.OLLAMA_MODEL,
        }.get(self.LLM_PROVIDER, "mock")


settings = Settings()
