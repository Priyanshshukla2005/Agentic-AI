# AI Business Starter Agent

An agentic AI system that helps aspiring entrepreneurs with limited business knowledge
create personalized business plans, budget-based pricing and step-by-step launch guidance.

**Stack:** Python · FastAPI · LangChain · open-source LLM (GPT-OSS via Groq, or Llama via Ollama)

## Status

| Phase | What | Status |
|---|---|---|
| 1 | Setup + LLM connection (groq / ollama / mock) | ✅ Done |
| 2 | Multilingual intake chat (collects the business profile) | ✅ Done |
| 3-7 | RAG + calculator, plan generation, frontend, checklist, evaluation | ⏳ Next |

```
ai-business-starter/
├── app/
│   ├── main.py            # FastAPI server: /health, /api/test-prompt + Phase 2 router
│   ├── llm.py             # LLM switcher (groq / ollama / mock) via LangChain
│   ├── config.py          # Reads settings from .env
│   ├── models.py          # Phase 2: BusinessProfile, ProfileUpdate, ProfilePatch, languages
│   ├── session_store.py   # Phase 2: in-memory sessions (swap for SQLite in Phase 6)
│   ├── intake.py          # Phase 2: one chat turn = mask PII -> extract -> merge -> reply
│   ├── routes/
│   │   └── intake.py      # Phase 2: /api/session, /api/chat endpoints
│   └── prompts/
│       ├── baseline_v1.txt          # Phase 1 baseline plan prompt
│       ├── intake_extract_v1.txt    # Phase 2: pull details out of a message (with Hinglish examples)
│       ├── intake_question_v1.txt   # Phase 2: ask the next question in the user's language
│       ├── intake_summary_v1.txt    # Phase 2: summary + "Shall I create your business plan?"
│       └── intake_templates_v1.json # Phase 2: field labels + fixed mock-mode messages (en, hi)
├── scripts/
│   ├── test_llm.py          # Phase 1 terminal test - no server needed
│   ├── chat_cli.py          # Phase 2 terminal chat - no server needed
│   └── list_groq_models.py  # Shows which Groq models your key can use
├── tests/
│   └── test_intake.py       # Phase 2 tests (offline, mock mode)
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

## Phase 2: Intake chat

The agent chats with the user in their language (English, Hindi, Bengali, Marathi, Tamil,
Telugu, Gujarati) and fills in a business profile, one question at a time.

**Required** (asked in this order): `business_idea`, `budget_inr`, `location`, `skills`, `target_customers`.
**Optional** (saved if mentioned, never asked): `time_available`, `sales_channel`, `experience`, `extra_notes`.

### How one chat turn works (`app/intake.py`)

```
user message
   │
   ├─ 1. PRIVACY   mask Aadhaar / PAN / bank account / phone numbers  (never stored, never sent to the LLM)
   ├─ 2. EXTRACT   LLM structured output: json_schema → function_calling → raw JSON
   │               └─ all fail, or mock mode → rule-based extractor (regex + keywords)
   ├─ 3. MERGE     copy non-empty values into the profile (new values overwrite → corrections work)
   │               budget text → rupees in CODE: "1.5 lakh" → 150000, "bees hazaar" → 20000
   └─ 4. RESPOND   missing fields? → ONE simple question for the first missing field
                   all filled?     → summary + "Shall I create your business plan?"
```

* **Missing fields are decided in Python** (`BusinessProfile.missing_fields()`), not by the LLM,
  so the question order is predictable and testable.
* **Off-topic questions** ("GST chahiye?") get a one-line answer, then the agent asks the same question again.
* **Mock mode** uses fixed template questions (English + Hindi; other languages fall back to English).
* **Prompts are versioned files.** To try a new prompt, copy `intake_question_v1.txt` to `_v2.txt`
  and change the constant at the top of `app/intake.py`. In prompt files, `{placeholders}` are filled by
  LangChain's `ChatPromptTemplate`; literal braces (like the JSON examples) are written `{{ }}`.

### Endpoints

| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/health` | | server status + provider (Phase 1) |
| POST | `/api/test-prompt` | business details | plan from a prompt (Phase 1) |
| POST | `/api/session` | `{"language": "hi"}` | `session_id`, `reply` (greeting + first question), `profile`, `missing_fields`, `is_complete` |
| POST | `/api/chat` | `{"session_id": "...", "message": "..."}` | `reply`, `profile`, `missing_fields`, `is_complete` |
| GET | `/api/session/{id}` | | full session: profile + all messages (PII masked) |
| PATCH | `/api/session/{id}/profile` | partial profile, e.g. `{"budget_inr": "1.5 lakh"}` | updated profile (`null` or `""` clears a field) |

Errors: **404** unknown session · **422** unsupported language / bad field / unreadable budget ·
**500** LLM not configured (e.g. missing key) · **502** LLM call failed (the session is left unchanged, just retry).

### Try it in the terminal (no server)

```bash
python scripts/chat_cli.py                    # uses LLM_PROVIDER from .env
LLM_PROVIDER=mock python scripts/chat_cli.py  # offline, fixed questions
```

(Windows PowerShell: `$env:LLM_PROVIDER="mock"; python scripts/chat_cli.py`)

Pick a language, then chat. The profile JSON is printed after every turn; the chat stops when the profile is complete.

### Run the tests

```bash
pytest -v
```

Tests always run in mock mode (forced in `tests/conftest.py`), so they need no API key and no internet.
They cover budget parsing (digits, `k`, lakh, Hindi words), PII masking, question order, a full API chat,
budget corrections, the PATCH endpoint, error codes, and the LLM fallback chain (with a fake model).

### Sample conversation with curl (mock mode)

```bash
curl -X POST localhost:8000/api/session -H "Content-Type: application/json" -d '{"language": "en"}'
```
```json
{"session_id": "ea7348cf-...", "reply": "Namaste! I will help you plan your business, one small question at a time.\nWhat business do you want to start? (Example: \"I want to sell homemade pickles\")",
 "missing_fields": ["business_idea", "budget_inr", "location", "skills", "target_customers"], "is_complete": false, "profile": {...}}
```

```bash
curl -X POST localhost:8000/api/chat -H "Content-Type: application/json" -d '{"session_id": "ea7348cf-...", "message": "I want to start a tiffin service"}'
```
```json
{"reply": "Got it, thank you!\nHow much money can you put into this business? (Example: \"20,000 rupees\" or \"1 lakh\")",
 "missing_fields": ["budget_inr", "location", "skills", "target_customers"], "is_complete": false, ...}
```

Then send `"Rs. 50k"`, `"I live in Pune"`, `"I cook good home-style food"`, `"Students and office workers"`. The last reply is:

```json
{"reply": "Thank you! Here is what I know about your business:\n- Business idea: I want to start a tiffin service\n- Budget: ₹50,000\n- Location: Pune\n- Skills: I cook good home-style food\n- Customers: Students and office workers\nShall I create your business plan?",
 "missing_fields": [], "is_complete": true, ...}
```

Fix a field directly:

```bash
curl -X PATCH localhost:8000/api/session/ea7348cf-.../profile -H "Content-Type: application/json" -d '{"budget_inr": "1.5 lakh"}'
```

With Groq or Ollama, the replies are written by the LLM in the chosen language and a single message
can fill several fields at once (e.g. *"mere paas bees hazaar hai, Lucknow mein tiffin service"*).

## Troubleshooting

| Error | Fix |
|---|---|
| `GROQ_API_KEY is missing` | Add your key to `.env` (not `.env.example`) |
| `model ... does not exist` / `decommissioned` | Run `python scripts/list_groq_models.py` and copy an available model into `GROQ_MODEL` |
| `429 rate limit` | Free tier limit hit: wait a minute, or switch `GROQ_MODEL=openai/gpt-oss-20b` |
| `Connection refused` (Ollama) | Start Ollama: `ollama serve`, and check `ollama list` shows your model |
| Chat replies are in English although I chose Tamil | You are in mock mode (templates exist for en + hi only). Use groq or ollama |
| `ModuleNotFoundError: app` | Run commands from the project folder (the one containing `app/`) |

## Next phases
3. RAG + calculator · 4. Plan generation + validation · 5. Frontend · 6. Checklist, Q&A, languages · 7. Evaluation
