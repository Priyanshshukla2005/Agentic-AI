"""Phase 4: the plan-generation agent, built as a LangGraph state machine.

    retrieve -> draft -> calculate -> validate --passed--------------------------> finalize
                  ^                      |
                  |                      +--blocking issues, repairs left--> repair -+
                  +------------------------------------------------------------------+
                                         +--blocking issues, no repairs left--> auto_fix -> finalize
    (plan_v1 is free text: draft -> finalize, no calculation or validation)

Every node is a plain function: it reads the shared state and returns the keys it changed.
Core rule: the LLM only proposes INPUT numbers; calculate() computes every total with the
calculator, and the final plan shows only calculator numbers.

Run `python -m app.planner` to write the graph diagram to docs/plan_graph.md.
"""
import json
import logging
import os
import time
from datetime import datetime, timezone
from functools import wraps
from typing import Optional, TypedDict

from langchain_core.prompts import ChatPromptTemplate
from langgraph.graph import END, START, StateGraph

from app import checklist, rag
from app.calculator import FinancialInput, FinancialSummary, full_financials
from app.config import BASE_DIR, settings
from app.llm import get_plan_llm, load_prompt
from app.models import LANGUAGES, BusinessProfile
from app.plan_mock import MOCK_RAW_TEXT, mock_draft
from app.plan_models import BusinessPlan, PlanDraft, ValidationIssue, ValidationReport
from app.plan_validation import auto_fix, has_blocking, validate_plan
from app.rag import RetrievedChunk
from app.session_store import get_session, save_session
from app.structured import invoke_structured, message_text

logger = logging.getLogger(__name__)

MAX_REPAIRS = 2  # repair rounds after the first draft -> at most 3 LLM drafts per plan
INPUT_PROMPT = "plan_input_v1"
REPAIR_PROMPT = "plan_repair_v1"
SERVICE_WORDS = ["tailor", "boutique", "stitch", "silai", "repair", "salon", "parlour", "beauty",
                 "tuition", "coaching", "laundry", "service", "mehndi", "photography", "driver"]


class PlanLLMError(RuntimeError):
    """The LLM could not write a plan at all (network down, bad key...). API -> 502."""


class PlanState(TypedDict, total=False):
    # inputs
    profile: BusinessProfile
    language: str
    prompt_version: str
    session_id: Optional[str]
    mock_variant: str
    started_at: float
    # filled in by the nodes
    chunks: list[RetrievedChunk]
    warnings: list[str]
    draft: Optional[PlanDraft]
    raw_text: Optional[str]
    financials: Optional[FinancialSummary]
    issues: list[ValidationIssue]
    validation_feedback: str
    repairs_made: list[str]
    attempts: int
    timings: dict[str, float]
    plan: BusinessPlan


def timed(name: str):
    """Decorator: add the node's run time (seconds) to state["timings"]. Repeated nodes add up."""
    def decorator(func):
        @wraps(func)
        def wrapper(state: PlanState) -> dict:
            start = time.perf_counter()
            update = func(state)
            timings = dict(state.get("timings", {}))
            timings[name] = round(timings.get(name, 0) + time.perf_counter() - start, 3)
            return {**update, "timings": timings}
        return wrapper
    return decorator


def is_mock() -> bool:
    return settings.LLM_PROVIDER == "mock"


def profile_text(profile: BusinessProfile) -> str:
    return " ".join(str(v) for v in profile.model_dump(exclude={"language"}).values() if v).lower()


# =====================================================================
# Node 1: retrieve - find official scheme documents for this profile
# =====================================================================

@timed("retrieve")
def retrieve_node(state: PlanState) -> dict:
    """RAG search. If the index is missing (or the search fails) we continue without
    schemes and add a warning instead of crashing."""
    warnings = list(state.get("warnings", []))
    try:
        chunks = rag.retrieve_for_profile(state["profile"])
    except rag.IndexNotBuiltError as e:
        chunks = []
        warnings.append(f"Scheme documents were not searched: {e}")
    except Exception as e:  # e.g. the embedding model could not load
        chunks = []
        warnings.append(f"Scheme search failed, plan made without schemes: {e}")
    return {"chunks": chunks, "warnings": warnings}


# =====================================================================
# Node 2: draft - the LLM writes the plan (only input numbers)
# =====================================================================

def build_messages(state: PlanState):
    """System prompt = the chosen plan version; human message = profile (+ repair feedback)."""
    profile = state["profile"]
    prompt = ChatPromptTemplate.from_messages(
        [("system", load_prompt(state["prompt_version"])), ("human", load_prompt(INPUT_PROMPT))]
    )
    return prompt.format_messages(
        profile_json=json.dumps(profile.model_dump(exclude={"language"}), ensure_ascii=False, indent=2),
        scheme_context=rag.format_context(state.get("chunks", [])),
        language_name=LANGUAGES.get(state["language"], "English"),
        validation_feedback=state.get("validation_feedback", ""),
    )


@timed("draft")
def draft_node(state: PlanState) -> dict:
    attempts = state.get("attempts", 0) + 1
    version = state["prompt_version"]

    if is_mock():
        if version == "plan_v1":
            return {"raw_text": MOCK_RAW_TEXT, "attempts": attempts}
        return {"draft": mock_draft(state.get("mock_variant", "valid"), state.get("chunks", [])), "attempts": attempts}

    llm = get_plan_llm()
    messages = build_messages(state)
    try:
        if version == "plan_v1":  # baseline: free text, kept only for comparison
            return {"raw_text": message_text(llm.invoke(messages)), "attempts": attempts}
        return {"draft": invoke_structured(llm, messages, PlanDraft), "attempts": attempts}
    except Exception as e:
        raise PlanLLMError(f"{settings.LLM_PROVIDER}/{settings.model_name}: {e}") from e


def route_after_draft(state: PlanState) -> str:
    return "finalize" if state["prompt_version"] == "plan_v1" else "calculate"


# =====================================================================
# Node 3: calculate - the calculator computes every total
# =====================================================================

def financial_input(draft: PlanDraft, profile: BusinessProfile) -> FinancialInput:
    """Map the LLM's input numbers + the profile budget onto the calculator input."""
    startup = [c.model_copy(update={"kind": "one_time"}) for c in draft.startup_costs]
    monthly = [c.model_copy(update={"kind": "monthly"}) for c in draft.fixed_monthly_costs]
    low, high = sorted((draft.market_price_low_inr, draft.market_price_high_inr))
    text = profile_text(profile) + " " + draft.business_summary.lower()
    is_food = any(w in text for w in rag.FOOD_WORDS)
    return FinancialInput(
        budget_inr=profile.budget_inr,
        cost_items=startup + monthly,
        unit_cost=draft.unit_cost_inr,
        selling_price=draft.selling_price_inr,
        market_low=low,
        market_high=high,
        units_per_day_low=draft.units_per_day_low,
        units_per_day_expected=draft.units_per_day_expected,
        units_per_day_high=draft.units_per_day_high,
        is_food_business=is_food,
        # A "meal service" sells food (goods for GST), so food wins over the word "service".
        is_service=not is_food and any(w in text for w in SERVICE_WORDS),
    )


@timed("calculate")
def calculate_node(state: PlanState) -> dict:
    try:
        financials = full_financials(financial_input(state["draft"], state["profile"]))
    except ValueError as e:  # e.g. impossible numbers; validate() reports INVALID_NUMBERS
        logger.warning("Calculator rejected the draft numbers: %s", e)
        financials = None
    return {"financials": financials}


# =====================================================================
# Node 4: validate - plain Python rules, no LLM
# =====================================================================

@timed("validate")
def validate_node(state: PlanState) -> dict:
    issues = validate_plan(state["draft"], state.get("financials"), state.get("chunks", []), state["profile"].budget_inr)
    return {"issues": issues}


def route_after_validate(state: PlanState) -> str:
    if not has_blocking(state["issues"]):
        return "finalize"
    repairs_done = state.get("attempts", 1) - 1
    return "repair" if repairs_done < MAX_REPAIRS else "auto_fix"


# =====================================================================
# Node 5: repair - turn the issues into feedback for the next draft
# =====================================================================

@timed("repair")
def repair_node(state: PlanState) -> dict:
    lines = "\n".join(f"- [{i.code}] {i.message}" for i in state["issues"] if i.severity == "blocking")
    feedback = load_prompt(REPAIR_PROMPT).format(issues=lines) + "\n\n"
    return {"validation_feedback": feedback}


# =====================================================================
# Node 6: auto_fix - safe, rule-based fixes after the last attempt
# =====================================================================

@timed("auto_fix")
def auto_fix_node(state: PlanState) -> dict:
    """Drop invented schemes and soften promise words. Budget / price problems are NOT
    changed: they stay in the report and in the plan warnings, visible to the user."""
    draft, fixes = auto_fix(state["draft"], state.get("chunks", []))
    issues = validate_plan(draft, state.get("financials"), state.get("chunks", []), state["profile"].budget_inr)
    return {"draft": draft, "issues": issues, "repairs_made": list(state.get("repairs_made", [])) + fixes}


# =====================================================================
# Node 7: finalize - assemble the BusinessPlan and save it in the session
# =====================================================================

@timed("finalize")
def finalize_node(state: PlanState) -> dict:
    warnings = list(state.get("warnings", []))
    timings = dict(state.get("timings", {}))
    timings["total"] = round(time.perf_counter() - state.get("started_at", time.perf_counter()), 3)
    validation = None
    if state["prompt_version"] != "plan_v1":
        issues = state.get("issues", [])
        validation = ValidationReport(
            passed=not has_blocking(issues),
            issues=issues,
            repairs_made=state.get("repairs_made", []),
            attempts=state.get("attempts", 0),
        )
        # Problems that are still there are shown to the user, never hidden.
        warnings += [f"{i.code}: {i.message}" for i in issues]
    else:
        warnings.append("plan_v1 is free text for comparison only: it was not calculated or validated.")

    plan = BusinessPlan(
        profile=state["profile"],
        draft=state.get("draft"),
        raw_text=state.get("raw_text"),
        financials=state.get("financials"),
        validation=validation,
        sources=state.get("chunks", []),
        warnings=warnings,
        language=state["language"],
        prompt_version=state["prompt_version"],
        provider=settings.LLM_PROVIDER,
        model=settings.model_name,
        generated_at=datetime.now(timezone.utc),
        timings=timings,
    )
    if state.get("session_id"):
        session = get_session(state["session_id"])
        if session is not None:
            session.plan = plan.model_dump(mode="json")
            save_session(session)
            # Phase 6: the plan's launch steps become the session's checklist on the server.
            if plan.draft is not None:
                checklist.sync_from_plan(session.session_id, plan.draft.launch_steps)
    return {"plan": plan}


# =====================================================================
# The graph
# =====================================================================

def build_graph():
    graph = StateGraph(PlanState)
    graph.add_node("retrieve", retrieve_node)
    graph.add_node("draft", draft_node)
    graph.add_node("calculate", calculate_node)
    graph.add_node("validate", validate_node)
    graph.add_node("repair", repair_node)
    graph.add_node("auto_fix", auto_fix_node)
    graph.add_node("finalize", finalize_node)

    graph.add_edge(START, "retrieve")
    graph.add_edge("retrieve", "draft")
    graph.add_conditional_edges("draft", route_after_draft, {"calculate": "calculate", "finalize": "finalize"})
    graph.add_edge("calculate", "validate")
    graph.add_conditional_edges(
        "validate", route_after_validate, {"finalize": "finalize", "repair": "repair", "auto_fix": "auto_fix"}
    )
    graph.add_edge("repair", "draft")
    graph.add_edge("auto_fix", "finalize")
    graph.add_edge("finalize", END)
    return graph.compile()


_graph = None


def get_graph():
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph


def generate_plan(
    profile: BusinessProfile,
    language: Optional[str] = None,
    prompt_version: str = "plan_v4",
    session_id: Optional[str] = None,
    mock_variant: Optional[str] = None,
) -> BusinessPlan:
    """Run the whole graph for one complete profile and return the final BusinessPlan.
    If session_id is given, the plan is also saved in that session."""
    if not profile.is_complete:
        raise ValueError(f"Profile is incomplete. Missing: {', '.join(profile.missing_fields())}")
    state = get_graph().invoke({
        "profile": profile,
        "language": language or profile.language,
        "prompt_version": prompt_version,
        "session_id": session_id,
        "mock_variant": mock_variant or os.getenv("MOCK_PLAN_VARIANT", "valid"),
        "started_at": time.perf_counter(),
    })
    return state["plan"]


def export_mermaid(path=BASE_DIR / "docs" / "plan_graph.md") -> str:
    """Write the graph as a Mermaid diagram (GitHub renders it) for the report."""
    mermaid = get_graph().get_graph().draw_mermaid()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# Plan generation graph (Phase 4)\n\n"
        "Generated from `app/planner.py` with `python -m app.planner`. Do not edit by hand.\n\n"
        "```mermaid\n" + mermaid.strip() + "\n```\n\n"
        "| Node | What it does |\n|---|---|\n"
        "| retrieve | Searches the official scheme documents for this profile (RAG). Missing index -> warning, not a crash |\n"
        "| draft | The LLM writes a PlanDraft with INPUT numbers only (plan_v1: free text, goes straight to finalize) |\n"
        "| calculate | The calculator computes every total, profit, break-even and payback |\n"
        "| validate | Plain Python rules: budget, reserve, price, break-even, real schemes, no promises, sections |\n"
        "| repair | Sends the blocking issues back to the LLM as feedback (at most 2 rounds) |\n"
        "| auto_fix | After the last round: drops invented schemes and softens promise words; budget/price problems stay visible |\n"
        "| finalize | Builds the BusinessPlan, records timings and saves it in the session |\n",
        encoding="utf-8",
    )
    return mermaid


if __name__ == "__main__":
    export_mermaid()
    print("Wrote docs/plan_graph.md")
