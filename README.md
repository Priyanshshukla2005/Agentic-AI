# AI Business Starter Agent

An agentic AI system that helps aspiring entrepreneurs with limited business knowledge
create personalized business plans, budget-based pricing and step-by-step launch guidance.

**Stack:** Python · FastAPI · LangChain · open-source LLM (GPT-OSS via Groq, or Llama via Ollama)

## Phase 1 status: ✅ Setup + LLM connection

```
ai-business-starter/
├── app/
│   ├── main.py            # FastAPI server + /api/test-prompt endpoint
│   ├── llm.py             # LLM switcher (groq / ollama / mock) via LangChain
│   ├── config.py          # Reads settings from .env
│   └── prompts/
│       └── baseline_v1.txt  # Baseline prompt (from our submission form)
├── scripts/
│   ├── test_llm.py          # Terminal test - no server needed
│   └── list_groq_models.py  # Shows which Groq models your key can use
├── requirements.txt
└── .env.example
```

## Setup (10 minutes)

**1. Install Python 3.10+**, then in this folder:

```bash
python -m venv venv
# Windows:
venv\Scripts\activate
# Mac/Linux:
source venv/bin/activate

pip install -r requirements.txt
```

**2. Create your `.env` file**

```bash
# Windows:
copy .env.example .env
# Mac/Linux:
cp .env.example .env
```

**3. Pick an LLM (choose ONE):**

| Option | Steps |
|---|---|
| **Groq (recommended)**: free, fast, no GPU needed | Sign up at https://console.groq.com/keys → create key → paste into `.env` as `GROQ_API_KEY=...` |
| **Ollama**: runs on your laptop, works offline | Install from https://ollama.com → run `ollama pull llama3.1:8b` → set `LLM_PROVIDER=ollama` in `.env` |
| **Mock**: no LLM, just to test the app | Set `LLM_PROVIDER=mock` |

**4. Test the LLM connection**

```bash
python scripts/test_llm.py
```

You should see a business plan for the Ghaziabad meal-service example, then `Phase 1 works!`

**5. Run the server**

```bash
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000/docs → **POST /api/test-prompt** → *Try it out* → *Execute*.

## Troubleshooting

| Error | Fix |
|---|---|
| `GROQ_API_KEY is missing` | Add your key to `.env` (not `.env.example`) |
| `model ... does not exist` / `decommissioned` | Run `python scripts/list_groq_models.py` and copy an available model into `GROQ_MODEL` |
| `429 rate limit` | Free tier limit hit: wait a minute, or switch `GROQ_MODEL=openai/gpt-oss-20b` |
| `Connection refused` (Ollama) | Start Ollama: `ollama serve`, and check `ollama list` shows your model |
| `ModuleNotFoundError: app` | Run commands from the project folder (the one containing `app/`) |

## Next phases
2. Intake chat · 3. RAG + calculator · 4. Plan generation + validation · 5. Frontend · 6. Checklist, Q&A, languages · 7. Evaluation
