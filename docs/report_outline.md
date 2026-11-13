# Report outline (mapped to our submission form)

Each section below has the content to use, with links to the files in this repo.
`[RESULT]` = a number to copy from `data/eval/report.md` after the Groq evaluation run.

## 1. Title and use case

**Business Starter: a multilingual planning and launch agent for first-time micro-entrepreneurs in India.**
An agentic system (FastAPI + LangChain/LangGraph + an open-source LLM) that chats with a person in
their language, collects five details (idea, budget, location, skills, customers) and produces a
practical, checked business plan with costs, pricing, profit estimates, marketing ideas, government
schemes with official links and a launch checklist; then answers follow-up questions as an advisor.

## 2. Problem

Aspiring entrepreneurs with limited business knowledge (vegetable vendors, pickle makers, home cooks,
tailors, artisans) cannot easily turn an idea into a plan: they do not know what it will cost, what price
to charge, how many sales they need, which registrations and loans apply, or what to do first.
Business-plan tools and consultants assume English, business vocabulary and money to pay for help.
A plain chatbot is not a solution either: it invents numbers and schemes and can promise profit.

## 3. Context

- MSMEs account for **31.1% of India's GDP, 35.4% of manufacturing output and 48.58% of exports**
  (Economic Survey 2025-26), and **9.16 crore MSMEs** were registered on the Udyam platform as of August
  2026, employing **more than 40 crore people** (PIB factsheet on the MSME Development (Amendment) Bill,
  2026: https://www.pib.gov.in/FactsheetDetails.aspx?Id=150826&reg=48&lang=2).
- Most of these are micro enterprises; the schemes meant for them (PM SVANidhi, Mudra, PMEGP, FSSAI basic
  registration, Udyam) are documented in English, in long official releases.

## 4. Who is affected

First-time micro-entrepreneurs: street vendors, home food businesses, small manufacturers (pickles,
candles, agarbatti), service providers (tailoring, beauty, repair, tuition), artisans; often women and
people in small towns and villages, with limited schooling, low digital literacy and cheap phones.
Our 15 test profiles cover these groups across 7 languages and budgets from ₹3,000 to ₹1,00,000
([`data/eval/test_profiles.json`](../data/eval/test_profiles.json)).

## 5. Why prompt engineering

The core difficulty is not missing data but **getting a general LLM to behave like a careful, honest,
simple-language advisor for this audience**: structured output that code can check, realistic numbers,
no invented schemes, no profit promises, plain words, and Indian languages. Each of these was addressed
with a prompt change, measured on a fixed test set, and backed by a code check
([docs/prompt_iterations.md](prompt_iterations.md)).

## 6. Models and tools, and why

| Component | Choice | Why |
|---|---|---|
| Main LLM | GPT-OSS 120B (open-weight) on Groq's free tier | Strong open model, fast, free for students |
| Offline LLM | Llama 3.1 8B via Ollama | Runs on a laptop with no internet |
| Framework | LangChain + LangGraph | Structured output with fallbacks, tools, an explicit agent graph |
| Retrieval | ChromaDB + multilingual MiniLM embeddings | CPU-only; Hindi questions find English documents |
| Calculator | Pure Python | The LLM never does money maths |
| Evaluation judge | `JUDGE_MODEL` (default GPT-OSS 120B), temperature 0, blind | Repeatable scoring; human review checks its bias |
| App | FastAPI + plain HTML/JS + SQLite | Simple to run (`./run.sh`), light on phones |

Architecture: [docs/architecture.md](architecture.md).

## 7. Data and privacy

- **Knowledge data:** 8 starter documents on PM Mudra Yojana, PMEGP, PM SVANidhi, Stand-Up India, Udyam,
  FSSAI, GST basics and trade licences, each fact from an official page (mostly PIB releases, FSSAI and GST
  portals) with `source_url` and `last_verified` ([`data/docs/`](../data/docs/)). RAG hit-rate@4:
  **12/12 (100%)**, hit-rate@1 9/12 (75%) on 12 test questions (4+ in Hindi/Hinglish).
- **User data:** only the business profile, chats, plans, checklist and questions, in a local SQLite file.
  Aadhaar, PAN, bank and phone numbers are masked before storing or sending to the LLM; no accounts or names.

## 8. Existing solutions and the gap

| Solution | What it offers | Gap for our users |
|---|---|---|
| Upmetrics | Online business-plan software with templates, financial forecasting and writing assistance | English-first, subscription pricing, assumes business vocabulary; not tied to Indian micro-enterprise schemes |
| Uttos | [team: one line from our submission form] | [team: gap noted in the submission form] |
| General chatbots | Free text answers in many languages | Invented numbers and schemes, possible profit promises, no checks, no launch tracking |
| Government portals (Udyam, PM SVANidhi, FoSCoS) | Official registration and loans | Each covers one scheme; no planning help; formal language |

**Our gap:** a free, multilingual, voice-friendly agent for micro-entrepreneurs that computes numbers
exactly, cites only official schemes, checks itself, and stays with the user through launch.

## 9. Baseline prompt and output

Baseline prompt (from the submission form, kept as `plan_v1`):

> You are an AI Business Starter Agent that provides a practical business plan for aspiring entrepreneurs
> in India. Based on user's business idea, budget, location, skills and target customers generate a
> practical business plan. The output must include estimated costs, product pricing, potential profit,
> marketing suggestions and steps to launch the business. Use simple language, state assumptions and
> avoid guaranteeing profits.

Baseline output: `[RESULT: paste an excerpt of data/eval/results/raw/plan_v1/p01.json -> plan.raw_text]`.
Problems observed: free-form output that cannot be checked, maths done by the model, invented schemes,
unexplained jargon, English for Hindi users (see section 2 of the evaluation report).

## 10. Iterations and results

Five versions (details and excerpts in [docs/prompt_iterations.md](prompt_iterations.md)):
v2 structure + rules + JSON schema; v3 few-shot examples; v4 grounding in official documents + "do not
calculate"; v5 language guidance and tone per language (default), with pivot translation and language checks.

| | v1 | v2 | v3 | v4 | v5 |
|---|---|---|---|---|---|
| Judge score (1-5) | [RESULT] | [RESULT] | [RESULT] | [RESULT] | [RESULT] |
| Budget fit | n/a | [RESULT] | [RESULT] | [RESULT] | [RESULT] |
| Invented schemes / plan | [RESULT] | [RESULT] | [RESULT] | [RESULT] | [RESULT] |
| Promise words / plan | [RESULT] | [RESULT] | [RESULT] | [RESULT] | [RESULT] |
| Language match | [RESULT] | [RESULT] | [RESULT] | [RESULT] | [RESULT] |

Charts: `docs/charts/judge_scores.png`, `validation_issues.png`, `language_match.png`.
Human review (blind A/B, 6 profiles): `[RESULT]`% preferred v5; clarity/usefulness/trust `[RESULT]`.
Edge cases (₹3,000 cloud kitchen, vague idea, Hinglish): `[RESULT: section 3 of the report]`; the
low-budget plan must show the over-budget warning rather than hide it.

Beyond the plan prompt: the validation + repair loop (9 checks + 2 language checks), the calculator, and
the Q&A agent (`qa_v1`) with memory and tools.

## 11. Professor's feedback and how we addressed it

**Feedback:** expand multilingual support beyond Hindi and English.
**What we did:**
- The whole UI is translated into 7 languages (English, Hindi, Bengali, Marathi, Tamil, Telugu, Gujarati),
  with Noto fonts for every script and voice input/output where the phone supports it.
- `plan_v5` adds language guidance and a tone guide per language.
- **Pivot mode** for the five newer languages: the plan is written in English and translated
  (`translate_v1`), with numbers and links copied back from the English draft.
- **Automatic checks:** `WRONG_LANGUAGE` (script detection with Unicode ranges; one retry in pivot mode)
  and `NUMBER_MISMATCH` (₹ amounts changed in translation), also applied to Q&A answers.
- **Measured** per language: `[RESULT: language table in data/eval/report.md and data/eval/language_report.md]`.

## 12. Limitations

- LLM-judge bias (mitigated by blind judging, shuffled order and human review); small test set (15 profiles,
  one run per version).
- Language checks verify the script, not grammar or naturalness; Bengali, Marathi, Tamil, Telugu and
  Gujarati texts need native-speaker review.
- Scheme documents are a starter set (8 topics), mostly from PIB releases because several official scheme
  sites were not reachable from our cloud test machine; facts must be re-checked against scheme websites,
  and some (e.g. whether Stand-Up India continues after 2025) could not be confirmed.
- Market prices come from the model's knowledge, not live data.
- No user accounts; sessions are protected only by their random id.

## 13. Future work

- **Voice-first flow** for users who cannot read comfortably (speech in, speech out, end to end).
- **WhatsApp bot**, since our users already live on WhatsApp.
- **More languages** (Kannada, Malayalam, Odia, Punjabi, Assamese) via dedicated Indic translation models
  (e.g. IndicTrans2) instead of a general LLM.
- **Live market price data** (mandi prices, local rents) to ground costs and selling prices.
- Larger, community-validated scheme knowledge base with automatic freshness checks; user accounts;
  a pilot with real entrepreneurs through an NGO or self-help group.
