"""Phase 6: the "Ask a question" advisor - a Q&A agent with memory, tools and guidance.

For every question the model gets:
  1. what we know: profile, plan summary + key calculator numbers, checklist progress + next step
  2. memory: the last 6 Q&A turns word for word + a rolling summary of older turns
  3. RAG chunks for the question (official scheme documents, with sources)
Then a LangGraph ReAct agent answers, calling the Phase 3 tools for what-if maths ("what if I sell
at Rs 150?") and scheme look-ups. If the model cannot call tools, we fall back to ONE grounded
LLM call (same context, no tools).
After answering: promise words are softened, the language is checked, and the Q&A is stored.

Mock mode (LLM_PROVIDER=mock) gives deterministic answers (still using the real calculator
tools and RAG), so everything is testable offline.
"""
import json
import logging
import re
import warnings
from functools import lru_cache
from typing import Optional

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from app import checklist, db, rag
from app.calculator import _inr as _rs_format
from app.config import settings
from app.intake import mask_pii
from app.language import is_wrong_language
from app.llm import get_llm, load_prompt
from app.models import LANGUAGES
from app.plan_validation import find_banned_phrases, soften_text
from app.session_store import Session
from app.structured import message_text
from app.tools import ALL_TOOLS, calculate_break_even

logger = logging.getLogger(__name__)

QA_PROMPT = "qa_v1"
SUMMARY_PROMPT = "qa_summary_v1"
GUIDE_PROMPT = "qa_guide_v1"
TEMPLATES_FILE = "qa_templates_v1.json"
VERBATIM_TURNS = 6    # last turns given word for word
SUMMARIZE_AFTER = 10  # more turns than this -> older ones go into the rolling summary


class AdvisorLLMError(RuntimeError):
    """The LLM failed completely (also in the fallback). API -> 502."""


class Source(BaseModel):
    scheme: str
    source_url: str


class AskResult(BaseModel):
    answer: str
    sources: list[Source] = Field(default_factory=list)
    used_tools: list[str] = Field(default_factory=list)
    next_step_hint: Optional[str] = Field(None, description="Title of the next unfinished checklist step")
    checks: list[str] = Field(default_factory=list, description="Checks that changed or flagged the answer")


class QAMessage(BaseModel):
    role: str
    content: str
    sources: list[Source] = Field(default_factory=list)
    created_at: str


class GuideCard(BaseModel):
    next_step: Optional[checklist.ChecklistItem] = None
    tip: Optional[str] = None
    progress_line: str
    progress: checklist.Progress


@lru_cache(maxsize=1)
def templates() -> dict:
    return json.loads((settings.PROMPTS_DIR / TEMPLATES_FILE).read_text(encoding="utf-8"))


def _inr(amount: int) -> str:
    """150000 -> "₹1,50,000" (Indian grouping, rupee sign) for answers shown to users."""
    return _rs_format(amount).replace("Rs ", "₹")


def is_mock() -> bool:
    return settings.LLM_PROVIDER == "mock"


def lang_templates(section: str, language: str) -> dict:
    block = templates()[section]
    return block.get(language, block["en"])


# =====================================================================
# Storage: Q&A thread + rolling memory (tables qa_messages and memory)
# =====================================================================

def history(session_id: str) -> list[QAMessage]:
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT role, content, sources_json, created_at FROM qa_messages WHERE session_id = ? ORDER BY id",
            (session_id,),
        ).fetchall()
    return [QAMessage(role=r["role"], content=r["content"], sources=json.loads(r["sources_json"]),
                      created_at=r["created_at"]) for r in rows]


def _store_turn(session_id: str, question: str, answer: str, sources: list[Source]) -> None:
    stamp = db.now()
    with db.get_conn() as conn:
        conn.execute("INSERT INTO qa_messages (session_id, role, content, sources_json, created_at) VALUES (?, 'user', ?, '[]', ?)",
                     (session_id, question, stamp))
        conn.execute("INSERT INTO qa_messages (session_id, role, content, sources_json, created_at) VALUES (?, 'assistant', ?, ?, ?)",
                     (session_id, answer, json.dumps([s.model_dump() for s in sources], ensure_ascii=False), stamp))


def _turns(session_id: str) -> list[dict]:
    """Q&A pairs, oldest first: [{"id": answer row id, "q": ..., "a": ...}]."""
    with db.get_conn() as conn:
        rows = conn.execute("SELECT id, role, content FROM qa_messages WHERE session_id = ? ORDER BY id", (session_id,)).fetchall()
    turns, question = [], None
    for r in rows:
        if r["role"] == "user":
            question = r["content"]
        elif question is not None:
            turns.append({"id": r["id"], "q": question, "a": r["content"]})
            question = None
    return turns


def get_memory(session_id: str) -> dict:
    with db.get_conn() as conn:
        row = conn.execute("SELECT summary, summarized_until FROM memory WHERE session_id = ?", (session_id,)).fetchone()
    return {"summary": row["summary"], "summarized_until": row["summarized_until"]} if row else {"summary": "", "summarized_until": 0}


def summarize(previous: str, turns: list[dict]) -> str:
    """Fold older turns into the summary: with the LLM, or (mock mode) a simple truncation."""
    text = "\n".join(f"Q: {t['q']}\nA: {t['a']}" for t in turns)
    if is_mock():
        short = " | ".join(f"Q: {t['q'][:80]} A: {t['a'][:80]}" for t in turns)
        return f"{previous} | {short}".strip(" |")[-1500:]
    prompt = ChatPromptTemplate.from_messages([("human", load_prompt(SUMMARY_PROMPT))])
    try:
        return (prompt | get_llm() | StrOutputParser()).invoke({"summary": previous or "(none)", "turns": text}).strip()
    except Exception as e:  # memory is a nice-to-have: never fail the answer because of it
        logger.warning("Memory summary failed, truncating instead: %s", e)
        return f"{previous} | {text}"[-1500:]


def update_memory(session_id: str) -> None:
    """When there are more than 10 turns, move every turn except the last 6 into the summary."""
    turns = _turns(session_id)
    if len(turns) <= SUMMARIZE_AFTER:
        return
    memory = get_memory(session_id)
    to_fold = [t for t in turns[:-VERBATIM_TURNS] if t["id"] > memory["summarized_until"]]
    if not to_fold:
        return
    summary = summarize(memory["summary"], to_fold)
    with db.get_conn() as conn:
        conn.execute(
            """INSERT INTO memory (session_id, summary, summarized_until, updated_at) VALUES (?, ?, ?, ?)
               ON CONFLICT(session_id) DO UPDATE SET summary = excluded.summary,
                   summarized_until = excluded.summarized_until, updated_at = excluded.updated_at""",
            (session_id, summary, to_fold[-1]["id"], db.now()),
        )


def memory_text(session_id: str) -> str:
    memory = get_memory(session_id)
    recent = _turns(session_id)[-VERBATIM_TURNS:]
    parts = []
    if memory["summary"]:
        parts.append(f"Summary of older questions: {memory['summary']}")
    parts += [f"User: {t['q']}\nGuide: {t['a']}" for t in recent]
    return "\n".join(parts) or "(this is the first question)"


# =====================================================================
# Context: profile + plan numbers + checklist
# =====================================================================

def context_text(session: Session, items: list[checklist.ChecklistItem]) -> str:
    p = session.profile
    lines = [f"Business: {p.business_idea} | Budget: {_inr(p.budget_inr or 0)} | Place: {p.location} | "
             f"Skills: {p.skills} | Customers: {p.target_customers}"]
    plan = session.plan or {}
    draft, fin = plan.get("draft"), plan.get("financials")
    if draft and fin:
        be = fin["break_even"]
        expected = fin["scenarios"]["scenarios"][1]
        lines += [
            f"Plan summary: {draft['business_summary']}",
            f"Unit: {draft['unit_name']} | cost per unit {_inr(fin['unit']['unit_cost'])} | price {_inr(fin['unit']['selling_price'])} "
            f"| profit per unit {_inr(fin['unit']['profit_per_unit'])}",
            f"Fixed monthly costs {_inr(fin['budget']['monthly_total'])} | needed to start {_inr(fin['budget']['startup_need'])} "
            f"| left from budget {_inr(fin['budget']['remaining'])}",
            f"Break-even: {be['units_per_day']} a day / {be['units_per_month']} a month" if be["possible"] else "Break-even: not possible at this price",
            f"Normal month estimate: {expected['units_per_month']} sold, profit {_inr(expected['profit'])}",
            f"Expected sales per day: low {draft['units_per_day_low']}, normal {draft['units_per_day_expected']}, high {draft['units_per_day_high']}",
        ]
    else:
        lines.append("No business plan has been made yet.")
    if items:
        done = [i.title for i in items if i.done]
        nxt = checklist.next_step(items)
        lines.append(f"Checklist: {len(done)} of {len(items)} steps done" + (f" ({'; '.join(done)})" if done else ""))
        lines.append(f"Next step: {nxt.title} - {nxt.detail}" if nxt else "All checklist steps are done.")
    return "\n".join(lines)


def sources_in_answer(answer: str, chunks: list[rag.RetrievedChunk]) -> list[Source]:
    """Only the schemes the answer actually talks about become clickable sources."""
    found: dict[str, Source] = {}
    lower = answer.lower()
    for c in chunks:
        if c.scheme.lower() in lower or c.source_url in answer:
            found.setdefault(c.scheme, Source(scheme=c.scheme, source_url=c.source_url))
    return list(found.values())


# =====================================================================
# Answering: mock / ReAct agent / grounded fallback
# =====================================================================

PRICE_WORDS = re.compile(r"price|sell|daam|dam\b|keemat|kimat|rate|what if|agar|₹|\brs\b|rupee|दाम|कीमत|बेच", re.I)
BREAK_EVEN_WORDS = re.compile(r"break.?even|how many|kitne|kitna|कितने|कितनी", re.I)
SCHEME_WORDS = re.compile(r"loan|scheme|yojana|fssai|regist|licen[cs]e|gst|udyam|subsid|mudra|svanidhi|लोन|योजना|रजिस्ट्रेशन|लाइसेंस", re.I)
CUSTOMER_WORDS = re.compile(r"customer|market|sell more|advertis|promot|grahak|ग्राहक|प्रचार", re.I)
OFF_TOPIC_WORDS = re.compile(r"cricket|movie|film|weather|politic|joke|song|recipe for|match score", re.I)
NUMBER_RE = re.compile(r"(\d[\d,]*)")


def mock_answer(question: str, session: Session, items, chunks, language: str) -> tuple[str, list[str], list[Source]]:
    """Deterministic answers for offline tests/demos. Money maths still goes through the real
    calculator tools; scheme answers come from the real RAG chunks."""
    t = lang_templates("mock", language)
    plan = session.plan or {}
    fin, draft = plan.get("financials"), plan.get("draft")
    number = NUMBER_RE.search(question)

    if OFF_TOPIC_WORDS.search(question):
        return t["off_topic"], [], []

    if fin and (BREAK_EVEN_WORDS.search(question) or (number and PRICE_WORDS.search(question))):
        price = int(number.group(1).replace(",", "")) if number and PRICE_WORDS.search(question) else fin["unit"]["selling_price"]
        cost, fixed = fin["unit"]["unit_cost"], fin["budget"]["monthly_total"]
        result = calculate_break_even.invoke({"fixed_monthly_costs": fixed, "profit_per_unit": price - cost})
        unit = draft["unit_name"] if draft else "unit"
        if not result["possible"]:
            return t["loss"].format(price=_inr(price), unit=unit, cost=_inr(cost)), ["calculate_break_even"], []
        answer = t["what_if"].format(price=_inr(price), profit=_inr(price - cost), unit=unit, fixed=_inr(fixed),
                                     day=result["units_per_day"], month=result["units_per_month"])
        return answer, ["calculate_break_even"], []

    if SCHEME_WORDS.search(question) and chunks:
        top = chunks[0]
        body = top.text.split("\n", 1)[-1]
        snippet = re.sub(r"[#*]+", "", " ".join(body.split()))[:220].rsplit(" ", 1)[0] + "…"
        answer = t["scheme"].format(scheme=top.scheme, snippet=snippet)
        return answer, ["search_schemes"], [Source(scheme=top.scheme, source_url=top.source_url)]

    if CUSTOMER_WORDS.search(question) and draft and draft.get("marketing_ideas"):
        return t["customers"].format(idea=draft["marketing_ideas"][0].rstrip(".")), [], []

    nxt = checklist.next_step(items)
    if nxt:
        return t["next_step"].format(title=nxt.title, detail=nxt.detail), [], []
    return t["all_done"], [], []


def build_system_prompt(session: Session, items, chunks, language: str, extra: str = "") -> str:
    prompt = ChatPromptTemplate.from_messages([("system", load_prompt(QA_PROMPT))])
    text = prompt.format_messages(
        language_name=LANGUAGES.get(language, "English"),
        context=context_text(session, items),
        memory=memory_text(session.session_id),
        scheme_context=rag.format_context(chunks),
    )[0].content
    return text + (f"\n\n{extra}" if extra else "")


def react_answer(llm, system_prompt: str, question: str) -> tuple[str, list[str]]:
    """LangGraph's prebuilt ReAct agent with the Phase 3 tools. Raises if tool calling fails."""
    from langgraph.prebuilt import create_react_agent

    # LangGraph 1.x still ships create_react_agent but says it will move to the separate
    # `langchain` package in 2.0; we keep it to avoid an extra dependency for now.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        warnings.filterwarnings("ignore", message=".*create_react_agent.*")
        agent = create_react_agent(llm, ALL_TOOLS, prompt=SystemMessage(content=system_prompt))
    result = agent.invoke({"messages": [HumanMessage(content=question)]}, {"recursion_limit": 8})
    used = []
    for message in result["messages"]:
        if isinstance(message, AIMessage):
            for call in message.tool_calls or []:
                if call["name"] not in used:
                    used.append(call["name"])
    answer = message_text(result["messages"][-1]).strip()
    if not answer:
        raise ValueError("Agent returned an empty answer")
    return answer, used


def grounded_answer(llm, system_prompt: str, question: str) -> str:
    """Fallback: one plain LLM call with the same context and RAG chunks, no tools."""
    answer = message_text(llm.invoke([SystemMessage(content=system_prompt), HumanMessage(content=question)])).strip()
    if not answer:
        raise ValueError("Empty answer")
    return answer


def llm_answer(session: Session, items, chunks, language: str, question: str) -> tuple[str, list[str]]:
    llm = get_llm()
    system_prompt = build_system_prompt(session, items, chunks, language)
    try:
        return react_answer(llm, system_prompt, question)
    except Exception as e:
        logger.warning("Tool-calling agent failed, using a single grounded call: %s", e)
    try:
        return grounded_answer(llm, system_prompt, question), []
    except Exception as e:
        raise AdvisorLLMError(f"{settings.LLM_PROVIDER}/{settings.model_name}: {e}") from e


# =====================================================================
# Public API
# =====================================================================

def ask(session: Session, question: str) -> AskResult:
    language = session.profile.language
    masked, pii = mask_pii(question.strip())
    items = checklist.list_items(session.session_id)
    try:
        chunks = rag.retrieve(masked, k=4)
    except Exception as e:  # index missing or model not loaded: answer without schemes
        logger.warning("Scheme search failed for Q&A: %s", e)
        chunks = []

    checks: list[str] = []
    if is_mock():
        answer, used_tools, sources = mock_answer(masked, session, items, chunks, language)
    else:
        answer, used_tools = llm_answer(session, items, chunks, language, masked)
        # Wrong language? Ask once more, very clearly, without tools.
        if is_wrong_language([answer], language)[0]:
            note = f"IMPORTANT: reply ONLY in {LANGUAGES[language]}."
            try:
                answer = grounded_answer(get_llm(), build_system_prompt(session, items, chunks, language, note), masked)
                checks.append("LANGUAGE_RETRY")
            except Exception as e:
                logger.warning("Language retry failed: %s", e)
        sources = sources_in_answer(answer, chunks)

    if find_banned_phrases(answer):  # Phase 4 GUARANTEE_LANGUAGE check, reused
        answer = soften_text(answer)
        checks.append("GUARANTEE_LANGUAGE")
    if is_wrong_language([answer], language)[0]:
        checks.append("WRONG_LANGUAGE")
    if pii:
        answer = lang_templates("mock", language)["privacy"] + "\n" + answer
        checks.append("PRIVACY")

    _store_turn(session.session_id, masked, answer, sources)
    update_memory(session.session_id)
    nxt = checklist.next_step(items)
    return AskResult(answer=answer, sources=sources, used_tools=used_tools,
                     next_step_hint=nxt.title if nxt else None, checks=checks)


def guide(session: Session) -> GuideCard:
    """Proactive card: next unfinished step + one practical tip + an encouraging progress line."""
    language = session.profile.language
    items = checklist.list_items(session.session_id)
    progress = checklist.progress(items)
    lines = lang_templates("progress", language)
    if progress.total == 0:
        line = lines["none"]
    elif progress.done == progress.total:
        line = lines["all"].format(total=progress.total)
    elif progress.done == 0:
        line = lines["none"]
    else:
        line = lines["some"].format(done=progress.done, total=progress.total)

    nxt = checklist.next_step(items)
    tip = None
    if nxt:
        if is_mock():
            tip = lang_templates("guide_tip", language).format(detail=nxt.detail)
        else:
            prompt = ChatPromptTemplate.from_messages([("human", load_prompt(GUIDE_PROMPT))])
            try:
                tip = (prompt | get_llm() | StrOutputParser()).invoke({
                    "business": session.profile.business_idea, "step_title": nxt.title,
                    "step_detail": nxt.detail, "language_name": LANGUAGES.get(language, "English"),
                }).strip()
                if find_banned_phrases(tip):
                    tip = soften_text(tip)
            except Exception as e:  # the card still works without a tip
                logger.warning("Guide tip failed: %s", e)
    return GuideCard(next_step=nxt, tip=tip, progress_line=line, progress=progress)
