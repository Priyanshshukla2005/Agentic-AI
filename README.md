# AI Business Starter Agent

An agentic AI system that helps aspiring entrepreneurs with limited business knowledge
create personalized business plans, budget-based pricing and step-by-step launch guidance.

**Stack:** Python · FastAPI · LangChain · open-source LLM (GPT-OSS via Groq, or Llama via Ollama)

## Status

| Phase | What | Status |
|---|---|---|
| 1 | Setup + LLM connection (groq / ollama / mock) | ✅ Done |
| 2 | Multilingual intake chat (collects the business profile) | ✅ Done |
| 3 | RAG over official scheme documents + pricing/profit calculator | ✅ Done |
| 4-7 | Plan generation, frontend, checklist, evaluation | ⏳ Next |

```
ai-business-starter/
├── app/
│   ├── main.py            # FastAPI server: /health, /api/test-prompt + Phase 2 router
│   ├── llm.py             # LLM switcher (groq / ollama / mock) via LangChain
│   ├── config.py          # Reads settings from .env
│   ├── models.py          # Phase 2: BusinessProfile, ProfileUpdate, ProfilePatch, languages
│   ├── session_store.py   # Phase 2: in-memory sessions (swap for SQLite in Phase 6)
│   ├── intake.py          # Phase 2: one chat turn = mask PII -> extract -> merge -> reply
│   ├── rag.py             # Phase 3: load/split/embed docs, search ChromaDB, profile -> searches
│   ├── calculator.py      # Phase 3: budget, price, break-even, scenarios, GST/FSSAI flags (no LLM)
│   ├── tools.py           # Phase 3: LangChain @tool wrappers for the Phase 4 agent (ALL_TOOLS)
│   ├── routes/
│   │   ├── intake.py      # Phase 2: /api/session, /api/chat endpoints
│   │   └── tools.py       # Phase 3: /api/rag/..., /api/calculate endpoints
│   └── prompts/
│       ├── baseline_v1.txt          # Phase 1 baseline plan prompt
│       ├── intake_extract_v1.txt    # Phase 2: pull details out of a message (with Hinglish examples)
│       ├── intake_question_v1.txt   # Phase 2: ask the next question in the user's language
│       ├── intake_summary_v1.txt    # Phase 2: summary + "Shall I create your business plan?"
│       └── intake_templates_v1.json # Phase 2: field labels + fixed mock-mode messages (en, hi)
├── data/
│   ├── docs/                # Phase 3: official scheme documents (.md now, add PDFs any time)
│   └── eval/rag_questions.json  # Phase 3: 12 test questions for the RAG hit-rate
├── chroma_db/               # Phase 3: vector database, built by ingest_docs.py (NOT committed)
├── scripts/
│   ├── test_llm.py          # Phase 1 terminal test - no server needed
│   ├── chat_cli.py          # Phase 2 terminal chat - no server needed
│   ├── ingest_docs.py       # Phase 3: build the scheme index
│   ├── eval_rag.py          # Phase 3: hit-rate@4 of scheme search
│   └── list_groq_models.py  # Shows which Groq models your key can use
├── tests/
│   ├── test_intake.py       # Phase 2 tests (offline, mock mode)
│   ├── test_calculator.py   # Phase 3 calculator tests (exact numbers)
│   └── test_rag.py          # Phase 3 RAG tests (fake embeddings, no download)
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

Phase 3 tests use fake embeddings and a temporary database, so they also run offline.
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

## Phase 3: Scheme search (RAG) + money calculator

Phase 4 will give the agent two tools, and both are ready now:

* **RAG (`app/rag.py`)** finds the right government schemes in official documents, with the source link.
* **Calculator (`app/calculator.py`)** does ALL the money maths in plain Python. The LLM never calculates
  prices or profits itself; it only explains the calculator's numbers.

### Install the extra packages

```bash
# Optional but recommended: CPU-only torch is ~2 GB smaller than the default build
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
```

### How the RAG works

```
INDEX (once):  data/docs/*.md|.txt|.pdf ─► chunks of 800 chars (120 overlap) ─► multilingual embeddings ─► chroma_db/
SEARCH:        question ─► embedding ─► 4 closest chunks ─► drop if score < RAG_MIN_SCORE ─► chunks + source URLs
```

* The embedding model `paraphrase-multilingual-MiniLM-L12-v2` understands Hindi and other Indian languages,
  so *"ठेले पर फल बेचता हूँ, लोन मिलेगा?"* finds the English PM SVANidhi document. It runs on CPU.
* `build_query_from_profile()` turns a profile into 2-3 focused searches: a loan sized to the budget,
  a licence search (food -> FSSAI, otherwise Udyam/GST) and, if relevant, a street-vendor,
  women/SC-ST or subsidy search. `retrieve_for_profile()` merges them without duplicates.
* `format_context()` gives a numbered block like `[1] [source: PM SVANidhi | https://...]` for the Phase 4 prompt.

### Build the index and measure it

```bash
python scripts/ingest_docs.py   # first run downloads the embedding model (~470 MB)
python scripts/eval_rag.py      # prints hit-rate@4 and lists misses
```

Current result on the 12 test questions (4 in Hindi/Hinglish): **hit-rate@4 = 12/12 (100%)**,
hit-rate@1 = 9/12 (75%). Off-topic questions ("how to train my pet dog") return no results because
of the relevance threshold.

### Adding official PDFs

Drop official PDFs into `data/docs/` and run `python scripts/ingest_docs.py` again (it rebuilds the
index cleanly, no duplicates). Then run `python scripts/eval_rag.py` to check the score.
Details and rules: [data/docs/README.md](data/docs/README.md).

Starter documents (each fact taken from an official page, linked in the file's `source_url`):
PM Mudra Yojana, PMEGP, PM SVANidhi, Stand-Up India, Udyam Registration, FSSAI Registration,
GST Registration basics, Trade License / Shop Act.

### The calculator (all money in whole rupees)

| Function | What it answers |
|---|---|
| `budget_summary(items, budget)` | Do one-time costs + first month fit the budget? Warns if over budget or reserve < 10% |
| `unit_economics(cost, price)` | Profit and margin on one item. Warns if price <= cost |
| `suggest_price(cost, margin=40, low, high)` | Price for a target margin, rounded to Rs 5, kept inside the market range |
| `break_even(fixed, profit_per_unit, days=26)` | Sales needed per month/day. "Not possible" if there is no profit per item |
| `monthly_scenarios(...)` | Revenue, cost, profit for low / expected / high months (ESTIMATES) |
| `payback_months(startup, monthly_profit)` | Months to earn the investment back (None if no profit) |
| `compliance_flags(revenue, food, service)` | GST and FSSAI hints from the official limits in `THRESHOLDS` |
| `full_financials(input)` | All of the above in one `FinancialSummary` |

### Phase 3 endpoints

| Method | Path | Body | Returns |
|---|---|---|---|
| POST | `/api/rag/search` | `{"query": "...", "k": 4, "category": "loan"}` (k, category optional) | matching chunks with `scheme`, `source_url`, `score` + ready `context` |
| POST | `/api/rag/for-session` | `{"session_id": "..."}` | schemes for that intake profile + the searches used |
| GET | `/api/rag/sources` | | every scheme in the index with its official URL |
| POST | `/api/calculate` | `FinancialInput` (see below) | `FinancialSummary` |

Errors: **400** empty query / impossible input (e.g. market_low > market_high) · **404** unknown session ·
**422** wrong field types or unknown category · **503** index not built yet (run `python scripts/ingest_docs.py`).

`category` is one of `loan`, `subsidy`, `registration`, `license`, `tax`.

### Example: `/api/calculate` (healthy-meal tiffin business)

```bash
curl -X POST localhost:8000/api/calculate -H "Content-Type: application/json" -d '{
  "budget_inr": 20000,
  "cost_items": [
    {"name": "Stove and utensils", "amount_inr": 6000, "kind": "one_time"},
    {"name": "Kitchen rent share", "amount_inr": 3000, "kind": "monthly"}
  ],
  "unit_cost": 100, "selling_price": 170,
  "units_per_day_low": 5, "units_per_day_expected": 10, "units_per_day_high": 15,
  "is_food_business": true
}'
```

Response (the low and high scenarios are left out here to keep it short):

```json
{
  "budget": {
    "budget_inr": 20000,
    "one_time_total": 6000,
    "monthly_total": 3000,
    "startup_need": 9000,
    "remaining": 11000,
    "percent_used": 45.0,
    "over_budget": false,
    "warnings": []
  },
  "price": {
    "suggested_price": 165,
    "unit_cost": 100,
    "margin_percent": 39.4,
    "reason": "Cost Rs 100 + 40% margin, rounded to the nearest Rs 5.",
    "warnings": []
  },
  "unit": {
    "unit_cost": 100,
    "selling_price": 170,
    "profit_per_unit": 70,
    "margin_percent": 41.2,
    "warnings": []
  },
  "break_even": {
    "possible": true,
    "units_per_month": 43,
    "units_per_day": 2,
    "message": "Sell at least 43 units a month (about 2 a day over 26 working days) to cover fixed costs."
  },
  "scenarios": {
    "scenarios": [
      {
        "label": "expected",
        "units_per_day": 10,
        "units_per_month": 260,
        "revenue": 44200,
        "total_cost": 29000,
        "profit": 15200
      }
    ],
    "note": "These are ESTIMATES based on your numbers, not guarantees. Real sales and costs will differ."
  },
  "payback_months": 0.4,
  "compliance": {
    "annual_revenue_estimate": 530400,
    "flags": [
      "GST: below the GST registration limit, not needed yet (verify).",
      "FSSAI: basic FSSAI Registration is needed before selling food (turnover up to Rs 12,00,000) (verify).",
      "Udyam: free MSME registration, useful for loans and schemes (recommended)."
    ]
  },
  "warnings": [],
  "disclaimer": "These are ESTIMATES based on your numbers, not guarantees. Real sales and costs will differ."
}
```

Leave out `selling_price` to use the suggested price; leave out `fixed_monthly_costs` to use the total of the
`monthly` cost items.

## Troubleshooting

| Error | Fix |
|---|---|
| `GROQ_API_KEY is missing` | Add your key to `.env` (not `.env.example`) |
| `model ... does not exist` / `decommissioned` | Run `python scripts/list_groq_models.py` and copy an available model into `GROQ_MODEL` |
| `429 rate limit` | Free tier limit hit: wait a minute, or switch `GROQ_MODEL=openai/gpt-oss-20b` |
| `Connection refused` (Ollama) | Start Ollama: `ollama serve`, and check `ollama list` shows your model |
| Chat replies are in English although I chose Tamil | You are in mock mode (templates exist for en + hi only). Use groq or ollama |
| `503 ... Run python scripts/ingest_docs.py first` | The scheme index is not built yet: run `python scripts/ingest_docs.py` |
| Embedding model download fails | Check internet access to huggingface.co, or set `EMBEDDING_MODEL` in `.env` to a model you already have |
| `ModuleNotFoundError: app` | Run commands from the project folder (the one containing `app/`) |

## Next phases
4. Plan generation + validation · 5. Frontend · 6. Checklist, Q&A, languages · 7. Evaluation
