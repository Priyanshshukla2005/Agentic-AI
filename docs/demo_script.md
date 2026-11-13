# 3-minute live demo script

**Goal:** show that a first-time entrepreneur can get a checked, practical plan in their own language,
and that our prompt engineering measurably improved the plans.

## Before the demo (10 minutes earlier)

- [ ] Laptop charged, phone on the same Wi-Fi. Start the server: `./run.sh` (or `run.bat`).
- [ ] `.env` has `LLM_PROVIDER=groq` and a working `GROQ_API_KEY`; run `python scripts/test_llm.py` once.
- [ ] Scheme index built (startup log says "Scheme index: 33 chunks"); otherwise `python scripts/ingest_docs.py`.
- [ ] Open on the phone: `http://<laptop-ip>:8000` (the run script prints it). Mirror the phone screen or
      use the laptop browser in phone size (DevTools, 390 px wide).
- [ ] Reset old data so the demo starts clean: stop the server, delete `data/app.db`, start again.
- [ ] Open a second tab with `http://127.0.0.1:8000/compare.html` and `data/eval/report.md` / the charts.
- [ ] Backup ready (see the end): mock mode command and the recorded video.

## The demo

| Time | Click / do | Say |
|---|---|---|
| 0:00-0:20 | Show the welcome screen | "Meet Sunita from Lucknow. She makes great pickles but has never written a business plan, and English is hard for her. India has over 9 crore registered small businesses (PIB, 2026), most of them tiny ones like hers." |
| 0:20-0:30 | Tap **हिन्दी** | "Everything works in 7 Indian languages. She picks Hindi." |
| 0:30-1:05 | Answer in Hinglish: *"main achar bechna chahti hoon"* → tap the **₹5,000** chip → *"Lucknow mein rehti hoon"* → *"maa ki recipe se achar banati hoon"* → *"padosi aur WhatsApp groups"* | "She answers in her own words, mixing Hindi and English, or by voice. The agent pulls out the details, converts 'bees hazaar' or '₹5,000' to a number in code, and asks one simple question at a time. Notice the progress bar." |
| 1:05-1:15 | Tap **मेरा बिज़नेस प्लान बनाएँ** | "Now the agent finds government schemes in official documents, writes the plan, and checks it." (Loading messages rotate.) |
| 1:15-1:50 | Scroll the plan: next-step card, budget bar, profit table, schemes with **सरकारी स्रोत देखें** | "Every rupee here is computed by our calculator, not by the LLM. The budget fits with a reserve. Schemes like FSSAI come with the official link - the model is not allowed to invent schemes. And it says clearly: estimates, not guaranteed." |
| 1:50-2:05 | Open **हमने क्या जाँचा** (Checks we ran) | "Behind the scenes, nine checks run: budget, price, break-even, real schemes, no promises of profit, language. If one fails, the plan is sent back to the LLM to fix." |
| 2:05-2:30 | Tick 2 checklist steps; tap the suggested question **अगर मैं दाम कम करूँ तो?** or type *"agar ₹120 mein bechun to?"* | "She ticks steps as she goes, saved on the server. She can ask questions: this answer used the calculator (see the 🧮 note), so the numbers are right." |
| 2:30-2:55 | Switch to the compare page / show `docs/charts/judge_scores.png` | "This is a prompt-engineering project. We tested 5 prompt versions on 15 profiles. From our baseline v1 to v5, the judge score went from [X] to [Y], invented schemes dropped to [Z], and [N]% of human reviewers preferred v5." |
| 2:55-3:00 | Back to the plan, tap **PDF डाउनलोड करें** | "She can download it as a PDF and take it to the bank. Thank you!" |

**Optional (if time):** start a new chat in **தமிழ்** to show a Tamil plan (written in English and
translated, with the numbers checked); or restart the server and show "Continue my plan".

## Backup plan (internet or Groq fails)

1. **Mock mode, fully offline:** stop the server and start it with `LLM_PROVIDER=mock` in `.env`
   (or `LLM_PROVIDER=mock uvicorn app.main:app --host 0.0.0.0`). The whole Hindi flow above works with
   fixed answers (Hindi plan, checklist, Q&A with the real calculator and scheme search). Say:
   "We are in offline mode, so the text is a fixed sample, but every step is the real app."
2. **Pre-recorded video:** play `docs/demo_video.mp4` (to be recorded by the team with the steps above,
   2-3 minutes, phone-size screen, Hindi flow).
3. **Screenshots:** `docs/screenshots/` has every screen (welcome, chat, plan, Hindi plan, checklist +
   questions, compare page) if even video playback fails.
4. **Results without the app:** `data/eval/report.md` and `docs/charts/` are committed files.

## Likely questions

- *"How do you stop the model from making up numbers?"* The LLM only proposes input numbers; the
  calculator computes everything; the validator rejects plans over budget or with price below cost.
- *"How do you stop invented schemes?"* RAG over official documents + a rule to cite only retrieved
  schemes + a code check that drops anything else.
- *"How good is it in Tamil/Bengali?"* Script match and checks per language are in the report; pivot
  translation keeps numbers safe; native speakers should still review the text.
- *"What data do you store?"* Business details only; Aadhaar/PAN/phone numbers are masked before
  storing or sending; no accounts.
