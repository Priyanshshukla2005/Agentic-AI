"""Print the models your Groq key can use right now (Groq changes its list often).

Run:  python scripts/list_groq_models.py
Then copy a model id into GROQ_MODEL in .env.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from groq import Groq  # noqa: E402

from app.config import settings  # noqa: E402

if not settings.GROQ_API_KEY or settings.GROQ_API_KEY.startswith("your_"):
    sys.exit("Set GROQ_API_KEY in .env first.")

client = Groq(api_key=settings.GROQ_API_KEY)
models = sorted(m.id for m in client.models.list().data)
print("Models available to your key:")
for m in models:
    marker = "  <- current" if m == settings.GROQ_MODEL else ""
    print(f"  {m}{marker}")
