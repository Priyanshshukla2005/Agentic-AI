"""Phase 2 check from the terminal: chat with the intake agent (no server needed).

Run from the project folder:
    python scripts/chat_cli.py                    # uses LLM_PROVIDER from .env
    LLM_PROVIDER=mock python scripts/chat_cli.py  # offline, fixed questions
Type 'quit' to stop.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402
from app.intake import IntakeLLMError, process_message, start_session  # noqa: E402
from app.llm import LLMConfigError  # noqa: E402
from app.models import LANGUAGES  # noqa: E402
from app.session_store import save_session  # noqa: E402


def choose_language() -> str:
    print("Choose a language:")
    codes = list(LANGUAGES)
    for i, code in enumerate(codes, start=1):
        print(f"  {i}. {LANGUAGES[code]} [{code}]")
    choice = input("Number or code (Enter = English): ").strip().lower()
    if choice.isdigit() and 1 <= int(choice) <= len(codes):
        return codes[int(choice) - 1]
    return choice if choice in LANGUAGES else "en"


def print_profile(session) -> None:
    profile = session.profile
    print("\n--- profile ---")
    print(json.dumps(profile.model_dump(), ensure_ascii=False, indent=2))
    print(f"missing: {profile.missing_fields()} | complete: {profile.is_complete}\n")


def main() -> int:
    print(f"Provider: {settings.LLM_PROVIDER} | Model: {settings.model_name}\n")
    language = choose_language()
    try:
        session, reply = start_session(language)
    except (LLMConfigError, IntakeLLMError) as e:
        print(f"ERROR: {e}")
        return 1
    print(f"\nAgent: {reply}\n")

    while not session.profile.is_complete:
        try:
            message = input("You: ").strip()
        except EOFError:  # input ran out (e.g. piped from a file)
            break
        if message.lower() in {"quit", "exit"}:
            break
        if not message:
            continue
        try:
            reply = process_message(session, message)
        except IntakeLLMError as e:
            print(f"LLM CALL FAILED: {e} (try again)")
            continue
        save_session(session)
        print(f"\nAgent: {reply}")
        print_profile(session)

    if session.profile.is_complete:
        print("Profile complete! Phase 4 will turn it into a business plan.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
