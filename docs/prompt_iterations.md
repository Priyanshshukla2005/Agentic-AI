# Prompt iterations

This is the main prompt-engineering write-up of the project: how the plan prompt evolved from the
baseline (plan_v1) to the default (plan_v5), which problem each version fixes, and what we measured.
The supporting prompts (intake, Q&A, translation) are covered at the end.

All prompts are plain text files in [`app/prompts/`](../app/prompts/) and are versioned: an old version
is never edited, a change becomes a new file. That is what makes the comparison possible:
`python scripts/run_eval.py` runs every version on the same 15 test profiles
([`data/eval/test_profiles.json`](../data/eval/test_profiles.json)) and writes
[`data/eval/report.md`](../data/eval/report.md).

> **Numbers:** cells marked `[report]` are filled from `data/eval/report.md` after the Groq run
> (`python scripts/run_eval.py`). The pipeline has been checked in mock mode; mock numbers are not results.

## Overview

| Version | Builds on | Main change | Problem it fixes | Size |
|---|---|---|---|---|
| plan_v1 | - | Baseline from our submission form | - | 430 chars |
| plan_v2 | v1 | Role, 11 numbered rules, JSON schema | Unstructured, unverifiable output; profit promises; jargon | 1.9k chars |
| plan_v3 | v2 | 2 worked few-shot examples | Unrealistic or inconsistent numbers, vague steps | 8.7k chars |
| plan_v4 | v3 | Grounding in retrieved scheme documents; "do not calculate" | Invented schemes and wrong maths | 9.3k chars |
| plan_v5 | v4 | Language guidance + tone guide per language | Hard words, untranslated terms, weak regional-language output | 10.6k chars |

| Metric (averages over 15 profiles) | v1 | v2 | v3 | v4 | v5 |
|---|---|---|---|---|---|
| Judge score (1-5) | [report] | [report] | [report] | [report] | [report] |
| Structure (0-1) | [report] | [report] | [report] | [report] | [report] |
| Budget fit (% of plans) | n/a | [report] | [report] | [report] | [report] |
| Invented schemes per plan | [report] | [report] | [report] | [report] | [report] |
| Promise words per plan | [report] | [report] | [report] | [report] | [report] |
| Language match (%) | [report] | [report] | [report] | [report] | [report] |
| Issues in the first draft | n/a | [report] | [report] | [report] | [report] |

Charts: [judge score](charts/judge_scores.png), [validation issues](charts/validation_issues.png),
[language match](charts/language_match.png).

---

## plan_v1: the baseline

**What it is:** exactly the prompt from our submission form, kept unchanged for comparison
([`plan_v1.txt`](../app/prompts/plan_v1.txt)):

> You are an AI Business Starter Agent that provides a practical business plan for aspiring
> entrepreneurs in India. Based on user's business idea, budget, location, skills and target customers
> generate a practical business plan. The output must include estimated costs, product pricing,
> potential profit, marketing suggestions and steps to launch the business. Use simple language,
> state assumptions and avoid guaranteeing profits.

**Problems we saw:**
- Free text: every answer has a different shape, so the app cannot show it as cards, check it or
  build a checklist from it.
- The model does the money maths itself; totals and profit cannot be verified and are sometimes wrong.
- "Avoid guaranteeing profits" is easy to ignore: phrases like "assured income" still appear.
- It sometimes names schemes that do not exist or gives wrong loan limits.
- Business words (margin, break-even, working capital) are not explained.
- It answers in English even for Hindi users.

**Measured:** structure `[report]`, invented schemes `[report]`, promise words `[report]`,
judge `[report]`. (Budget fit and validation do not apply: the free text cannot be checked.)

## plan_v2: structure and rules

**What changed:** a clear role ("a patient business guide... many of them have little schooling"),
11 numbered rules and a JSON schema (`PlanDraft`) that the output must follow.

> 2. Your output MUST match the PlanDraft JSON schema exactly. Every field is required.
> 3. All rupee amounts are whole numbers (integers) with no symbols, commas or words.
> 4. The startup costs PLUS one month of fixed monthly costs must fit inside the budget, and at least
>    10% of the budget must stay unspent as a reserve.
> 8. Never guarantee profit or income. Do not use words like "guaranteed", "100% profit", "risk-free"...

**Why:** a fixed schema turns the plan into data. That lets the calculator compute every total, the
validator check it (budget, reserve, price vs cost, break-even, promise words, sections) and the
app show cards and a checklist. "Ask nothing, state assumptions" stops the model from replying with
questions. The budget rule with an explicit 10% reserve fixes plans that spend everything.

**Measured:** structure v1 -> v2 `[report]`; budget fit `[report]`; issues in the first draft `[report]`.

## plan_v3: few-shot examples

**What changed:** two complete worked examples, input profile -> PlanDraft JSON:
(a) healthy meal service, ₹20,000, Ghaziabad, basic cooking, gym-goers;
(b) homemade pickles, ₹5,000, Hardoi (UP), family recipe, households + WhatsApp.
Both examples were checked with our own calculator before they went into the prompt (they fit the
budget with 35%+ left, price is inside the market range, break-even is 1-2 sales a day).

**Why:** rules alone did not give realistic numbers: v2 drafts sometimes used tiny unit costs, put
ingredient costs into fixed costs, or wrote vague launch steps. Examples show the expected realism,
level of detail and number format far better than more rules. A very small budget (₹5,000) is
included on purpose so the model learns to plan small.

**Measured:** practicality (judge) `[report]`; issues in the first draft `[report]`; repairs needed `[report]`.

## plan_v4: grounding

**What changed:** the retrieved official scheme documents are inserted as `{scheme_context}`, and
three grounding rules are added:

> 12. Suggest ONLY schemes that appear in the Scheme context below, and copy their scheme name and
>     source_url exactly. If none fit, return an empty "schemes" list.
> 13. Do NOT calculate totals, profit, break-even or payback. Only provide the input numbers...
> 14. Write all text fields in {language_name}.

**Why:** v2/v3 still invented schemes ("PM Startup Yojana") and loan limits. With RAG the model
can only cite what our documents contain, and the validator rejects any scheme whose name or URL
is not in the retrieved chunks (`HALLUCINATED_SCHEME`). Rule 13 separates the jobs: the LLM proposes
numbers, the calculator computes. This is also the first version that writes in the user's language.

**Measured:** invented schemes `[report]`; grounding (judge) `[report]`; language match `[report]`.

## plan_v5: language guidance (default)

**What changed:** language rules on top of v4:

> 16. The first time you use a business term, explain it in brackets in simple words, for example
>     "break-even (the point of no profit, no loss)", "margin (what you keep from each sale)".
> 17. Write rupee amounts in text as digits with the ₹ sign and Indian commas, for example ₹1,50,000.
> 18. Use local examples people know: the nearby mandi, kirana shop, mohalla or colony, WhatsApp
>     groups, festival seasons, UPI payments.
> 19. Tone guide: Hindi - simple Hindustani ("aap" form); Bengali - polite "apni" form, not formal
>     sadhu bhasha; Tamil - polite, simple spoken Tamil; ... (one line per language)

**Why:** our professor asked us to go beyond Hindi and English. v4 plans in Bengali, Tamil, Telugu,
Marathi and Gujarati were often too formal, mixed in English, or wrote amounts in words. Together
with v5 we added:
- **pivot translation** for the five newer languages (write in English, translate with
  `translate_v1`; numbers and links are copied back from the English draft);
- **language checks**: `WRONG_LANGUAGE` (under 60% of letters in the right script; retry once in
  pivot mode) and `NUMBER_MISMATCH` (₹ amounts changed by the translation).

**Measured:** simplicity (judge) `[report]`; language match per language `[report]`
(see the language table in `data/eval/report.md`); human review: `[report]`% preferred v5 over v1.

---

## Supporting prompts

### intake_extract_v1 (Phase 2)
Extracts business details from each chat message into a `ProfileUpdate` JSON. Key rules: "only extract
what the user actually said; never guess; leave unknown fields null", and 3 Hinglish few-shot pairs
(e.g. *"mere paas bees hazaar hai, ghar se tiffin service shuru karni hai for office walo"*). The
budget is copied as text ("bees hazaar") and turned into a number by code (`parse_budget_inr`),
because models are unreliable at "1.5 lakh = 150000". If all LLM attempts fail, a rule-based
extractor takes over, so the chat never gets stuck.

### intake_question_v1 (Phase 2)
Writes the next question: one question at a time, reply only in `{language_name}`, about Class 6
reading level, max 2 sentences plus a tiny example answer, briefly acknowledge what the user said,
answer an off-topic question in one line first. Which field to ask next is decided in code, not by the
LLM, so the order is predictable.

### qa_v1 (Phase 6)
The "Ask a question" agent: answer in `{language_name}`, ~120 words, practical steps for this business;
use ONLY calculator/tool numbers for money maths (the ReAct agent calls `calculate_break_even` for
"what if I sell at ₹150?"); mention schemes only from the retrieved context with the source; never
guarantee profit; send legal/tax specifics to the official office or a CA; never ask for Aadhaar/PAN/bank
details; steer off-topic questions back. Context: profile, plan numbers, checklist progress, the last 6
turns and a rolling summary of older turns.

### translate_v1 (Phase 6)
Translates the text values of a PlanDraft JSON. Keep keys, numbers, ₹ amounts, URLs, "kind" values and
scheme names unchanged; keep everyday English terms (WhatsApp, FSSAI, UPI); use simple spoken language.
Code then copies every number and link back from the English draft, so the translation cannot
change money or sources; `NUMBER_MISMATCH` catches ₹ amounts changed inside sentences.

### eval_judge_v1 (Phase 7)
The blind LLM judge: a small-business mentor scores personalisation, practicality, simplicity,
grounding and completeness from 1 to 5 with a one-line reason each, at temperature 0. It never sees
the prompt version, and plans are judged in shuffled order.

## Lessons learned

1. **Structure first.** The single biggest step was v1 -> v2: once the output is data, code can check
   and fix it, and the LLM no longer needs to be trusted with arithmetic.
2. **Show, don't tell.** Two good examples (v3) did more for realism than more rules.
3. **Ground facts, don't ask for honesty.** "Don't invent schemes" barely works; giving the documents
   and rejecting anything else (v4 + validator) does.
4. **Prompt + code together.** Every prompt rule we care about is also checked in code
   (budget, price, schemes, promise words, language), with a repair loop and safe auto-fixes.
5. **Languages need more than "reply in X".** Tone guides, explaining terms and pivot translation
   with number checks were needed for the newer languages.
