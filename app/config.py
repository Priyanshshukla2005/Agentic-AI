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
    # Business plans are long JSON answers, so plan calls get a bigger output limit.
    PLAN_MAX_TOKENS: int = int(os.getenv("PLAN_MAX_TOKENS", "4096"))

    PROMPTS_DIR: Path = BASE_DIR / "app" / "prompts"

    # --- Phase 6: persistence ---
    # Sessions, chats, plans, checklist and Q&A live in this SQLite file (delete it to reset).
    DB_PATH: Path = BASE_DIR / os.getenv("DB_PATH", "data/app.db")
    # "sqlite" (default, survives restarts) or "memory" (sessions only, lost on restart).
    SESSION_STORE: str = os.getenv("SESSION_STORE", "sqlite").strip().lower()

    # --- Phase 6: plan prompt + languages ---
    DEFAULT_PLAN_VERSION: str = os.getenv("DEFAULT_PLAN_VERSION", "plan_v5").strip()
    # "auto" uses TRANSLATE_MODE_MAP per language; "direct" or "pivot" forces one mode for all.
    #   direct = the LLM writes the plan in the user's language
    #   pivot  = the LLM writes in English, then the text is translated (smaller models do better)
    TRANSLATE_MODE: str = os.getenv("TRANSLATE_MODE", "auto").strip().lower()
    TRANSLATE_MODE_MAP: str = os.getenv(
        "TRANSLATE_MODE_MAP", "en:direct,hi:direct,bn:pivot,mr:pivot,ta:pivot,te:pivot,gu:pivot"
    ).strip()

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

    def translate_mode(self, language: str) -> str:
        """direct or pivot for this language (see TRANSLATE_MODE above)."""
        if self.TRANSLATE_MODE in ("direct", "pivot"):
            return self.TRANSLATE_MODE
        modes = dict(pair.split(":") for pair in self.TRANSLATE_MODE_MAP.split(",") if ":" in pair)
        return modes.get(language, "direct").strip()

    @property
    def model_name(self) -> str:
        return {
            "groq": self.GROQ_MODEL,
            "ollama": self.OLLAMA_MODEL,
        }.get(self.LLM_PROVIDER, "mock")


settings = Settings()
