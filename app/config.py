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

    @property
    def model_name(self) -> str:
        return {
            "groq": self.GROQ_MODEL,
            "ollama": self.OLLAMA_MODEL,
        }.get(self.LLM_PROVIDER, "mock")


settings = Settings()
