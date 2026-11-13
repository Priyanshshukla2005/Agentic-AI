"""Phase 7: automatic metrics for one generated plan (pure code, no LLM).

compute_metrics(plan, profile_language, known_sources) -> dict with:
  structure_score       0-1, required sections present (plan_v1: keyword detection in the free text)
  budget_fit            startup costs + first month fit the budget        (None for plan_v1)
  price_above_cost      selling price > unit cost                          (None for plan_v1)
  break_even_realistic  break-even sales/day <= the plan's good-day sales  (None for plan_v1)
  hallucinated_schemes  schemes not found in the RAG index sources
  guarantee_phrases     promise words ("guaranteed", "pakka munafa"...)
  language_match        % of letters in the expected script
  issues_before_repair, llm_repairs, auto_fixes, final_passed   (None for plan_v1)
  latency_seconds, output_tokens_est (characters / 4, a rough estimate), readability (English only)
"""
import re
from typing import Optional

from app.language import plan_texts, script_ratio
from app.plan_models import BusinessPlan
from app.plan_validation import find_banned_phrases

SECTIONS = ["business_summary", "startup_costs", "fixed_monthly_costs", "marketing_ideas",
            "launch_steps", "assumptions", "risks"]

# Keywords per section for the free-text baseline (English + Hindi).
RAW_SECTION_KEYWORDS = {
    "costs": r"cost|budget|investment|expense|खर्च|लागत|बजट",
    "pricing": r"pric|selling|rate|दाम|कीमत|मूल्य",
    "profit": r"profit|margin|earning|income|मुनाफ|लाभ|कमाई",
    "marketing": r"marketing|promot|advertis|social media|whatsapp|प्रचार|मार्केटिंग",
    "launch_steps": r"step|launch|timeline|week|कदम|शुरू|चरण",
}

# "Something Yojana / Scheme / Mission" mentioned in free text.
SCHEME_MENTION_RE = re.compile(
    r"((?:[A-Z][\w-]*\.?\s){0,5}(?:Yojana|Scheme|Programme|Program|Mission|Abhiyan|Nidhi|योजना))", re.UNICODE
)


def _norm(text: str) -> str:
    # "Pradhan Mantri Mudra Yojana" and "PM Mudra Yojana" are the same scheme.
    text = re.sub(r"pradhan\s*mantri|prime\s*minister'?s?|प्रधानमंत्री|प्रधान मंत्री", "pm", text.lower())
    return re.sub(r"[^a-z0-9ऀ-ॿ]+", " ", text.lower()).strip()


def structure_score(plan: BusinessPlan) -> float:
    if plan.raw_text is not None:
        text = plan.raw_text.lower()
        found = sum(bool(re.search(pattern, text)) for pattern in RAW_SECTION_KEYWORDS.values())
        return round(found / len(RAW_SECTION_KEYWORDS), 3)
    if plan.draft is None:
        return 0.0
    present = sum(bool(getattr(plan.draft, s)) for s in SECTIONS)
    return round(present / len(SECTIONS), 3)


def _is_known(name: str, url: str, known_sources: list[dict]) -> bool:
    names = [_norm(s["scheme"]) for s in known_sources]
    urls = {s["source_url"] for s in known_sources}
    n = _norm(name)
    name_ok = any(n and (n == k or k in n or n in k) for k in names)
    return name_ok and (not url or url in urls)


def hallucinated_schemes(plan: BusinessPlan, known_sources: list[dict]) -> int:
    """Schemes that are not in our official documents. With no index, every scheme counts."""
    if plan.raw_text is not None:
        mentions = {m.strip() for m in SCHEME_MENTION_RE.findall(plan.raw_text)}
        return sum(not _is_known(m, "", known_sources) for m in mentions)
    if plan.draft is None:
        return 0
    return sum(not _is_known(s.scheme, s.source_url, known_sources) for s in plan.draft.schemes)


def all_text(plan: BusinessPlan) -> str:
    if plan.raw_text is not None:
        return plan.raw_text
    return "\n".join(plan_texts(plan.draft)) if plan.draft else ""


def readability(text: str, language: str) -> Optional[float]:
    """Flesch reading ease (higher = easier) for English only; None if textstat is missing."""
    if language != "en" or not text.strip():
        return None
    try:
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")  # textstat 0.7.3 imports the old pkg_resources
            import textstat

            return round(float(textstat.flesch_reading_ease(text)), 1)
    except Exception:  # not installed, or its data files are missing
        return None


def compute_metrics(plan: BusinessPlan, language: str, known_sources: list[dict]) -> dict:
    text = all_text(plan)
    v, f = plan.validation, plan.financials
    ratio = script_ratio(text, language)
    return {
        "structure_score": structure_score(plan),
        "budget_fit": None if f is None else not f.budget.over_budget,
        "price_above_cost": None if f is None else f.unit.selling_price > f.unit.unit_cost,
        "break_even_realistic": None if f is None or plan.draft is None else (
            f.break_even.possible and f.break_even.units_per_day <= plan.draft.units_per_day_high),
        "hallucinated_schemes": hallucinated_schemes(plan, known_sources),
        "guarantee_phrases": len(find_banned_phrases(text)),
        "language_match": None if ratio is None else round(ratio * 100, 1),
        "issues_before_repair": None if v is None else len(v.initial_issue_codes),
        "llm_repairs": None if v is None else max(v.attempts - 1, 0),
        "auto_fixes": None if v is None else len(v.repairs_made),
        "final_passed": None if v is None else v.passed,
        "final_issues": None if v is None else len(v.issues),
        "latency_seconds": plan.timings.get("total"),
        "output_tokens_est": round(len(text) / 4),
        "readability": readability(text, language),
    }
