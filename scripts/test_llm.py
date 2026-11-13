"""Phase 1 check from the terminal (no server needed).

Run from the project folder:
    python scripts/test_llm.py
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from langchain_core.messages import HumanMessage, SystemMessage  # noqa: E402

from app.config import settings  # noqa: E402
from app.llm import LLMConfigError, get_llm, load_prompt  # noqa: E402

SAMPLE_INPUT = """Business idea: Healthy meal service for fitness enthusiasts
Budget: Rs 20,000
Location: Ghaziabad
Skills: Basic cooking
Target customers: Gym-goers and fitness enthusiasts seeking high-protein meals and diet plans"""


def main() -> int:
    print(f"Provider: {settings.LLM_PROVIDER} | Model: {settings.model_name}")
    try:
        llm = get_llm()
    except LLMConfigError as e:
        print(f"\nCONFIG ERROR: {e}")
        return 1

    print("Sending baseline prompt + sample input...\n")
    start = time.perf_counter()
    try:
        reply = llm.invoke(
            [SystemMessage(content=load_prompt("baseline_v1")), HumanMessage(content=SAMPLE_INPUT)]
        )
    except Exception as e:
        print(f"LLM CALL FAILED: {e}")
        if settings.LLM_PROVIDER == "ollama":
            print("Is Ollama running? Try: ollama serve   and   ollama pull " + settings.OLLAMA_MODEL)
        return 1

    print("-" * 60)
    print(reply.content)
    print("-" * 60)
    print(f"OK - answered in {time.perf_counter() - start:.1f}s. Phase 1 works!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
