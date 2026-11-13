# Slides outline (12 slides, ~8 minutes)

`[RESULT]` = fill from `data/eval/report.md` after the Groq run.

### 1. Business Starter
- A multilingual agent that helps first-time micro-entrepreneurs plan and launch a small business
- 7 Indian languages, checked numbers, official schemes, launch checklist
- Team names, course, date
- **Visual:** `docs/screenshots/01_welcome.png` (phone frame)

### 2. The problem
- Vendors, home cooks, tailors and artisans have ideas, not plans
- Unknowns: costs, price, sales needed, licences, loans, first steps
- Existing tools: English, jargon, paid; chatbots invent numbers and schemes
- **Visual:** photo/illustration of a street vendor + 3 question marks

### 3. Why it matters
- MSMEs: 31.1% of GDP, 35.4% of manufacturing output, 48.58% of exports (Economic Survey 2025-26)
- 9.16 crore MSMEs on Udyam, employing 40+ crore people (PIB, Aug 2026)
- Schemes exist (SVANidhi, Mudra, PMEGP, FSSAI) but are hard to find and read
- **Visual:** big-number stat tiles

### 4. Our solution in one flow
- Choose language -> 5 simple questions (text or voice) -> checked plan -> checklist + advisor
- The LLM proposes, the calculator computes, the validator checks
- Works on a cheap phone; PDF download
- **Visual:** the overview flowchart from `docs/architecture.md`

### 5. Live demo (Hindi)
- Sunita, pickles, ₹5,000, Lucknow
- Plan in Hindi with budget bar, profit table, FSSAI with official link
- Checklist tick + "what if I lower my price?" answered with the calculator
- **Visual:** live demo, or `docs/screenshots/06_plan_hindi_sample.png` + `09_plan_checklist_ask.png`

### 6. Architecture
- FastAPI + LangChain/LangGraph + GPT-OSS 120B (Groq) / Llama (Ollama)
- RAG: ChromaDB + multilingual embeddings over official documents
- LangGraph planner: retrieve -> draft -> translate -> calculate -> validate -> repair -> finalize
- **Visual:** the planner graph from `docs/plan_graph.md`

### 7. Baseline prompt and its problems
- Our original prompt (plan_v1) in one box
- Free text: cannot be checked; maths by the model
- Invented schemes, profit promises, English only
- **Visual:** baseline output excerpt with problems highlighted (`data/eval/report.md` section 5)

### 8. Prompt iterations v1 -> v5
- v2 structure + rules + schema; v3 two worked examples
- v4 grounding in official documents, "do not calculate"
- v5 plain words, terms explained, tone per language
- **Visual:** timeline table from `docs/prompt_iterations.md`

### 9. Results
- Judge score v1 -> v5: [RESULT] -> [RESULT]
- Invented schemes: [RESULT] -> [RESULT]; budget fit [RESULT]%
- Human review: [RESULT]% preferred v5 (blind A/B)
- **Visual:** `docs/charts/judge_scores.png` + `docs/charts/validation_issues.png`

### 10. Professor's feedback: beyond Hindi and English
- UI, plans and Q&A in 7 languages, Noto fonts, voice
- Pivot translation for bn/mr/ta/te/gu with numbers locked
- Automatic WRONG_LANGUAGE and NUMBER_MISMATCH checks
- **Visual:** `docs/charts/language_match.png` + a Tamil plan screenshot

### 11. Trust and safety
- Every rupee from the calculator; schemes only from official documents, with links
- 11 checks + repair loop; problems shown, never hidden
- Aadhaar/PAN/phone numbers masked; no accounts; local SQLite
- **Visual:** "Checks we ran" card screenshot + privacy icons

### 12. Limitations and future work
- LLM-judge bias, small test set, script-only language check, starter scheme set
- Next: voice-first flow, WhatsApp bot, Indic translation models, live mandi prices
- Pilot with a self-help group
- **Visual:** roadmap with 4 icons; thank-you + repo link
