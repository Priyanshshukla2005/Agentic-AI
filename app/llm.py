"""LLM connection layer.

Every other part of the app calls `get_llm()` and never cares which provider is behind it.
Switch providers by changing LLM_PROVIDER in .env - no code changes needed.
"""
from functools import lru_cache

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.language_models.fake_chat_models import FakeListChatModel

from app.config import settings

MOCK_REPLY = (
    "Business Plan (MOCK MODE - no real LLM connected)\n"
    "Startup Budget: Ingredients Rs 8,000; packaging Rs 3,000; equipment Rs 4,000; "
    "marketing Rs 1,000; reserve Rs 4,000.\n"
    "Pricing: Rs 150-200 per serving.\n"
    "Set LLM_PROVIDER=groq or ollama in .env to get real answers."
)


class LLMConfigError(RuntimeError):
    """Raised when the chosen provider is missing required settings."""


@lru_cache(maxsize=1)
def get_llm() -> BaseChatModel:
    provider = settings.LLM_PROVIDER

    if provider == "groq":
        if not settings.GROQ_API_KEY or settings.GROQ_API_KEY.startswith("your_"):
            raise LLMConfigError(
                "GROQ_API_KEY is missing. Get a free key at https://console.groq.com/keys "
                "and put it in your .env file."
            )
        from langchain_groq import ChatGroq

        return ChatGroq(
            model=settings.GROQ_MODEL,
            api_key=settings.GROQ_API_KEY,
            temperature=settings.LLM_TEMPERATURE,
            max_tokens=settings.LLM_MAX_TOKENS,
            max_retries=2,
        )

    if provider == "ollama":
        from langchain_ollama import ChatOllama

        return ChatOllama(
            model=settings.OLLAMA_MODEL,
            base_url=settings.OLLAMA_BASE_URL,
            temperature=settings.LLM_TEMPERATURE,
            num_predict=settings.LLM_MAX_TOKENS,
        )

    if provider == "mock":
        return FakeListChatModel(responses=[MOCK_REPLY])

    raise LLMConfigError(f"Unknown LLM_PROVIDER '{provider}'. Use groq, ollama or mock.")


def load_prompt(name: str) -> str:
    """Read a prompt file from app/prompts/ (e.g. 'baseline_v1')."""
    path = settings.PROMPTS_DIR / f"{name}.txt"
    if not path.exists():
        raise FileNotFoundError(f"Prompt '{name}' not found at {path}")
    return path.read_text(encoding="utf-8").strip()
