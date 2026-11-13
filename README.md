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
| 4 | Plan generation agent (LangGraph) + validation + repair | ✅ Done |
| 5-7 | Frontend, checklist, evaluation | ⏳ Next |

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
│   ├── structured.py      # Phase 4: LLM -> pydantic object with 3 fallbacks (used by intake + plan)
│   ├── plan_models.py     # Phase 4: PlanDraft, ValidationReport, BusinessPlan
│   ├── plan_validation.py # Phase 4: rule-based checks + auto-fix (no LLM)
│   ├── plan_mock.py       # Phase 4: fixed valid / invalid drafts for mock mode
│   ├── planner.py         # Phase 4: LangGraph agent: retrieve -> draft -> calculate -> validate -> ...
│   ├── routes/
│   │   ├── intake.py      # Phase 2: /api/session, /api/chat endpoints
│   │   ├── tools.py       # Phase 3: /api/rag/..., /api/calculate endpoints
│   │   └── plan.py        # Phase 4: /api/plan endpoints
│   └── prompts/
│       ├── baseline_v1.txt          # Phase 1 baseline plan prompt
│       ├── intake_extract_v1.txt    # Phase 2: pull details out of a message (with Hinglish examples)
│       ├── intake_question_v1.txt   # Phase 2: ask the next question in the user's language
│       ├── intake_summary_v1.txt    # Phase 2: summary + "Shall I create your business plan?"
│       ├── intake_templates_v1.json # Phase 2: field labels + fixed mock-mode messages (en, hi)
│       ├── plan_v1.txt ... plan_v4.txt  # Phase 4: plan prompt versions (see table below)
│       ├── plan_input_v1.txt        # Phase 4: profile + repair feedback (human message)
│       └── plan_repair_v1.txt       # Phase 4: "fix these problems" feedback text
├── data/
│   ├── docs/                # Phase 3: official scheme documents (.md now, add PDFs any time)
│   └── eval/
│       ├── rag_questions.json   # Phase 3: 12 test questions for the RAG hit-rate
│       └── sample_profiles.json # Phase 4: 5 complete profiles for plan generation
├── docs/plan_graph.md       # Phase 4: Mermaid diagram of the plan agent
├── chroma_db/               # Phase 3: vector database, built by ingest_docs.py (NOT committed)
├── scripts/
│   ├── test_llm.py          # Phase 1 terminal test - no server needed
│   ├── chat_cli.py          # Phase 2 terminal chat - no server needed
│   ├── ingest_docs.py       # Phase 3: build the scheme index
│   ├── eval_rag.py          # Phase 3: hit-rate@4 of scheme search
│   ├── generate_plan_cli.py # Phase 4: generate / compare plans in the terminal
│   └── list_groq_models.py  # Shows which Groq models your key can use
├── tests/
│   ├── test_intake.py       # Phase 2 tests (offline, mock mode)
│   ├── test_calculator.py   # Phase 3 calculator tests (exact numbers)
│   ├── test_rag.py          # Phase 3 RAG tests (fake embeddings, no download)
│   ├── test_validation.py   # Phase 4: every validation rule
│   ├── test_planner.py      # Phase 4: the whole graph (mock + fake LLM)
│   └── test_plan_api.py     # Phase 4: /api/plan endpoints
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

## Phase 4: Business plan generation + validation

```
complete profile ─► RAG retrieval ─► LLM writes plan ─► calculator ─► validate ─┬─ ok ─────────────► final plan
                                          ▲                                       ├─ problems ─► repair (feedback to LLM, max 2 rounds)
                                          └───────────────────────────────────────┘
                                                                                  └─ still wrong ─► auto_fix ─► final plan (with warnings)
```

**Core rule:** the LLM only proposes INPUT numbers (costs, unit cost, price, market range, expected sales).
The calculator computes every total, profit, break-even and payback, and the final plan shows only
calculator numbers.

### The agent graph (`app/planner.py`, LangGraph)

Diagram: [docs/plan_graph.md](docs/plan_graph.md) (regenerate with `python -m app.planner`).

| Node | What it does |
|---|---|
| `retrieve` | `rag.retrieve_for_profile(profile)`. Index missing -> empty context + warning, no crash |
| `draft` | Builds the prompt for the chosen version and gets a `PlanDraft` via `invoke_structured` (plan_v1: free text -> straight to `finalize`) |
| `calculate` | `calculator.full_financials(...)` from the draft numbers + the profile budget |
| `validate` | Plain Python rules (table below), no LLM |
| `repair` | Blocking issues -> "Fix these problems: ..." feedback -> back to `draft` (at most 2 rounds) |
| `auto_fix` | After the last round: drop invented schemes, soften promise words. Budget/price problems stay visible |
| `finalize` | Builds the `BusinessPlan`, records timings per node, saves it in the session |

`generate_plan(profile, language, prompt_version="plan_v4") -> BusinessPlan` runs the whole graph.

### Validation rules (`app/plan_validation.py`)

| Code | Severity | Triggered when |
|---|---|---|
| `BUDGET_OVER` | blocking | one-time costs + first month of fixed costs > budget |
| `LOW_RESERVE` | warning | less than 10% of the budget is left |
| `PRICE_BELOW_COST` | blocking | selling price <= unit cost |
| `PRICE_OUT_OF_MARKET` | warning | price outside the market low-high range |
| `BREAK_EVEN_UNREALISTIC` | blocking | break-even units/day > units_per_day_high |
| `HALLUCINATED_SCHEME` | blocking | scheme name or source_url not in the retrieved documents |
| `GUARANTEE_LANGUAGE` | blocking | promise words in any text: "guaranteed", "100% profit", "risk-free", "definitely earn", "pakka munafa", "गारंटी" ... ("bina guarantee" loans and "Credit Guarantee Fund" are allowed) |
| `MISSING_SECTION` | blocking | empty marketing_ideas, launch_steps or assumptions |
| `BAD_STEP_COUNT` | blocking | launch steps not between 5 and 8 |
| `INVALID_NUMBERS` | blocking | the calculator could not use the numbers |

Blocking issues trigger a repair round; warnings are shown in the plan. Anything still wrong at the end
appears in `validation.issues` and `warnings`: it is never hidden.

### Prompt versions (our prompt-engineering story)

| Version | Builds on | What it adds | Output |
|---|---|---|---|
| `plan_v1` | | Exactly our baseline prompt from the submission form | Free text (not validated, comparison only) |
| `plan_v2` | v1 | Clear role, 11 numbered rules, PlanDraft JSON schema, "ask nothing, state assumptions", no profit guarantees, Class 8 words, integer rupees, fit the budget with a 10% reserve | Structured JSON |
| `plan_v3` | v2 | 2 few-shot examples: healthy meals (Rs 20,000, Ghaziabad) and homemade pickles (Rs 5,000, Hardoi), both checked with the calculator | Structured JSON |
| `plan_v4` | v3 | Grounding: `{scheme_context}` from RAG, "only schemes from the context, copy source_url exactly", "do not calculate totals", answer in `{language_name}` | Structured JSON (default) |

Placeholders: `{profile_json}`, `{scheme_context}`, `{language_name}`, `{validation_feedback}`.
Plan calls use `PLAN_MAX_TOKENS` (default 4096) because plans are long.

### Phase 4 endpoints

| Method | Path | Body | Returns |
|---|---|---|---|
| POST | `/api/plan` | `{"session_id": "...", "prompt_version": "plan_v4"}` | `BusinessPlan` (also saved in the session) |
| GET | `/api/plan/{session_id}` | | last plan of that session |
| POST | `/api/plan/preview` | `{"profile": {...}, "language": "hi", "prompt_version": "plan_v4"}` | `BusinessPlan` without a session |
| POST | `/api/plan/compare` | `{"profile": {...}, "versions": ["plan_v1", "plan_v2", "plan_v3", "plan_v4"]}` | one result per version: plan, validation, seconds |

Errors: **404** unknown session / no plan yet · **409** profile incomplete (`detail.missing_fields` lists what is
missing) · **422** unknown prompt version · **500** LLM not configured · **502** LLM call failed.

Every plan includes the `validation` report and the `sources` (retrieved chunks), so the UI can show them.

### Try it

```bash
LLM_PROVIDER=mock python scripts/generate_plan_cli.py --profile 0 --all-versions   # offline comparison
LLM_PROVIDER=mock python scripts/generate_plan_cli.py --profile 0 --mock-variant invalid  # see repair + auto_fix
python scripts/generate_plan_cli.py --profile 2 --version plan_v4                  # real LLM (Hindi profile)
```

Profiles 0-4 in `data/eval/sample_profiles.json`: meal service (Rs 20k, Ghaziabad), pickles (Rs 5k, Hardoi, hi),
vegetable cart (Rs 8k, Lucknow, hi), home boutique (Rs 30k, Indore), block-print crafts online (Rs 15k, Jaipur).

In mock mode the draft is always the healthy-meal plan (`app/plan_mock.py`); set `MOCK_PLAN_VARIANT=invalid`
(or `--mock-variant invalid`) to get a broken plan (over budget + promise words + invented scheme).

### Sample `/api/plan` response (mock mode, trimmed)

```json
{
  "profile": {
    "language": "en",
    "business_idea": "I want to start a healthy tiffin service",
    "budget_inr": 20000,
    "location": "Ghaziabad",
    "...": "..."
  },
  "draft": {
    "business_summary": "A home kitchen in Ghaziabad that cooks fresh, high-protein lunch boxes for gym-goers. Meals are delivered near 3-4 local gyms. Start small with lunch only and grow with regular monthly customers.",
    "unit_name": "meal",
    "startup_costs": [
      {
        "name": "Gas stove and pressure cooker",
        "amount_inr": 3500,
        "kind": "one_time"
      },
      {
        "name": "Utensils and kitchen scale",
        "amount_inr": 2500,
        "kind": "one_time"
      },
      "..."
    ],
    "unit_cost_inr": 100,
    "selling_price_inr": 170,
    "schemes": [
      {
        "scheme": "FSSAI Registration",
        "why_it_fits": "Found in the official documents for this business (license).",
        "source_url": "https://fssai.gov.in/upload/uploadfiles/files/FAQs_Licensing_Registration_21_12_2022.pdf"
      }
    ],
    "launch_steps": [
      {
        "title": "Fix the menu",
        "detail": "Plan 6 high-protein dishes and write the protein in grams for each.",
        "estimated_days": 3,
        "estimated_cost_inr": null
      },
      "..."
    ],
    "...": "..."
  },
  "financials": {
    "budget": {
      "budget_inr": 20000,
      "startup_need": 13000,
      "remaining": 7000,
      "percent_used": 65.0,
      "over_budget": false
    },
    "unit": {
      "profit_per_unit": 70,
      "margin_percent": 41.2
    },
    "break_even": {
      "possible": true,
      "units_per_month": 43,
      "units_per_day": 2,
      "message": "Sell at least 43 units a month (about 2 a day over 26 working days) to cover fixed costs."
    },
    "payback_months": 0.7,
    "...": "..."
  },
  "validation": {
    "passed": true,
    "issues": [],
    "repairs_made": [],
    "attempts": 1
  },
  "sources": [
    {
      "scheme": "FSSAI Registration",
      "source_url": "https://fssai.gov.in/upload/uploadfiles/files/FAQs_Licensing_Registration_21_12_2022.pdf",
      "score": 0.737
    },
    "..."
  ],
  "warnings": [],
  "language": "en",
  "prompt_version": "plan_v4",
  "provider": "mock",
  "model": "mock",
  "timings": {
    "retrieve": 8.248,
    "draft": 0.0,
    "calculate": 0.0,
    "validate": 0.001,
    "total": 8.255
  }
}
```

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
| Plan shows `HALLUCINATED_SCHEME` for every scheme | The scheme index is missing or empty: run `python scripts/ingest_docs.py` |
| `502 LLM call failed` on `/api/plan` | Groq rate limit or a model that cannot return JSON: wait, or try `GROQ_MODEL=openai/gpt-oss-20b` |
| `ModuleNotFoundError: app` | Run commands from the project folder (the one containing `app/`) |

## Next phases
5. Frontend · 6. Checklist, Q&A, languages · 7. Evaluation
