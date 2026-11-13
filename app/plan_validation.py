"""Phase 4: check a plan draft with plain Python rules (no LLM), and fix what can be fixed safely.

validate_plan()  -> list of issues, each with a code, a message and a severity:
    blocking = the plan is wrong or unsafe -> ask the LLM to repair it
    warning  = the plan works but the user should know (shown in the plan)
auto_fix()       -> deterministic fixes after the last LLM attempt: drop invented schemes and
                    soften promise words. Budget and price problems are NEVER hidden.
"""
import re
from typing import Optional

from app.calculator import FinancialSummary
from app.plan_models import PlanDraft, ValidationIssue
from app.rag import RetrievedChunk

RESERVE_PERCENT = 10
MIN_STEPS, MAX_STEPS = 5, 8

# code -> severity. Blocking issues trigger a repair round.
SEVERITY = {
    "BUDGET_OVER": "blocking",
    "LOW_RESERVE": "warning",
    "PRICE_BELOW_COST": "blocking",
    "PRICE_OUT_OF_MARKET": "warning",
    "BREAK_EVEN_UNREALISTIC": "blocking",
    "HALLUCINATED_SCHEME": "blocking",
    "GUARANTEE_LANGUAGE": "blocking",
    "MISSING_SECTION": "blocking",
    "BAD_STEP_COUNT": "blocking",
    "INVALID_NUMBERS": "blocking",
}

# ---------------------------------------------------------------------------
# Promise words. Profit is never certain, so a plan must not promise it.
# Each entry: (pattern, softer replacement used by auto_fix).
# ---------------------------------------------------------------------------
BANNED_PHRASES: list[tuple[str, str]] = [
    (r"100\s?% profit", "some profit"),
    (r"guaranteed (profit|income|returns?|earnings?|sales)", r"possible \1"),
    (r"(assured|sure|certain) (profit|income|returns?|earnings?)", r"possible \2"),
    (r"guaranteed", "possible"),
    (r"guarantees?", "chance"),
    (r"risk[- ]free|no risk", "lower risk"),
    (r"(?:will )?definitely (earn|make|get)", r"may \1"),
    (r"double your money", "grow your money"),
    (r"pakk[ae] (munafa|profit)|munafa pakka", "sambhavit munafa"),
    (r"100\s?% munafa", "kuch munafa"),
    (r"पक्का मुनाफा|मुनाफा पक्का", "संभावित मुनाफा"),
    (r"निश्चित (मुनाफा|कमाई|आय)", r"संभावित \1"),
    (r"100\s?% मुनाफा", "कुछ मुनाफा"),
    (r"गारंटी", "संभावना"),
    (r"बिना जोखिम|जोखिम[- ]मुक्त", "कम जोखिम"),
]
# Phrases that contain a banned word but are fine: "bina guarantee ke loan" means a loan
# WITHOUT collateral, and "Credit Guarantee Fund" is the real name of a government fund.
ALLOWED_PHRASES = [
    r"credit guarantee", r"without (any )?guarantee", r"no guarantee", r"bina guarantee",
    r"guarantee[- ]free", r"बिना गारंटी", r"क्रेडिट गारंटी",
]
_ALLOWED_RE = re.compile("|".join(ALLOWED_PHRASES), re.IGNORECASE)
_BANNED_RE = [(re.compile(p, re.IGNORECASE), repl) for p, repl in BANNED_PHRASES]


def issue(code: str, message: str) -> ValidationIssue:
    return ValidationIssue(code=code, message=message, severity=SEVERITY[code])


def iter_text_fields(draft: PlanDraft):
    """Every piece of text in the draft (summary, ideas, steps, schemes, assumptions, risks...)."""
    def walk(value):
        if isinstance(value, str):
            yield value
        elif isinstance(value, dict):
            for v in value.values():
                yield from walk(v)
        elif isinstance(value, list):
            for v in value:
                yield from walk(v)
    yield from walk(draft.model_dump())


def find_banned_phrases(text: str) -> list[str]:
    """Promise words found in one text (allowed phrases like 'credit guarantee' are skipped)."""
    cleaned = _ALLOWED_RE.sub(" ", text)
    found = []
    for pattern, _ in _BANNED_RE:
        for match in pattern.finditer(cleaned):
            found.append(match.group(0))
        cleaned = pattern.sub(" ", cleaned)  # do not report the same words twice
    return found


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9ऀ-ॿ]+", " ", text.lower()).strip()


def scheme_is_grounded(name: str, url: str, chunks: list[RetrievedChunk]) -> bool:
    """A scheme is real for us only if BOTH its name and its source_url appear in the retrieved chunks."""
    urls = {c.source_url.strip() for c in chunks}
    names = {_norm(c.scheme) for c in chunks}
    name_ok = any(_norm(name) == n or (n and n in _norm(name)) or (_norm(name) and _norm(name) in n) for n in names)
    return name_ok and url.strip() in urls


# =====================================================================
# validate_plan
# =====================================================================

def validate_plan(
    draft: PlanDraft,
    financials: Optional[FinancialSummary],
    chunks: list[RetrievedChunk],
    budget_inr: int,
) -> list[ValidationIssue]:
    """Run every rule. `financials` comes from the calculator (None if the numbers were unusable)."""
    issues: list[ValidationIssue] = []

    # --- Money rules (use calculator numbers only) ---
    if financials is None:
        issues.append(issue("INVALID_NUMBERS", "The plan numbers could not be calculated. Check all amounts are whole numbers."))
    else:
        b = financials.budget
        if b.over_budget:
            issues.append(issue(
                "BUDGET_OVER",
                f"Startup costs plus the first month (Rs {b.startup_need}) are more than the budget "
                f"(Rs {budget_inr}) by Rs {-b.remaining}.",
            ))
        elif b.remaining < budget_inr * RESERVE_PERCENT / 100:
            issues.append(issue(
                "LOW_RESERVE",
                f"Only Rs {b.remaining} of the budget is left; keep at least {RESERVE_PERCENT}% "
                f"(Rs {budget_inr * RESERVE_PERCENT // 100}) as a reserve.",
            ))
        be = financials.break_even
        if be.possible and be.units_per_day > draft.units_per_day_high:
            issues.append(issue(
                "BREAK_EVEN_UNREALISTIC",
                f"Break-even needs {be.units_per_day} {draft.unit_name} a day, more than even a good day "
                f"({draft.units_per_day_high}). Lower the fixed costs or rethink the price.",
            ))

    if draft.selling_price_inr <= draft.unit_cost_inr:
        issues.append(issue(
            "PRICE_BELOW_COST",
            f"Selling price Rs {draft.selling_price_inr} is not more than the unit cost Rs {draft.unit_cost_inr}.",
        ))
    low, high = sorted((draft.market_price_low_inr, draft.market_price_high_inr))
    if not low <= draft.selling_price_inr <= high:
        issues.append(issue(
            "PRICE_OUT_OF_MARKET",
            f"Selling price Rs {draft.selling_price_inr} is outside the market range Rs {low} to Rs {high}.",
        ))

    # --- Only real schemes (must come from the retrieved documents) ---
    for s in draft.schemes:
        if not scheme_is_grounded(s.scheme, s.source_url, chunks):
            issues.append(issue(
                "HALLUCINATED_SCHEME",
                f"Scheme '{s.scheme}' ({s.source_url}) is not in the official documents found for this plan.",
            ))

    # --- No profit promises ---
    found = sorted({p.lower() for text in iter_text_fields(draft) for p in find_banned_phrases(text)})
    if found:
        issues.append(issue("GUARANTEE_LANGUAGE", f"Remove promise words: {', '.join(found)}. Profit is never certain."))

    # --- Completeness ---
    for section in ("marketing_ideas", "launch_steps", "assumptions"):
        if not getattr(draft, section):
            issues.append(issue("MISSING_SECTION", f"The '{section}' section is empty."))
    if draft.launch_steps and not MIN_STEPS <= len(draft.launch_steps) <= MAX_STEPS:
        issues.append(issue(
            "BAD_STEP_COUNT", f"There are {len(draft.launch_steps)} launch steps; give {MIN_STEPS} to {MAX_STEPS}."
        ))
    return issues


def has_blocking(issues: list[ValidationIssue]) -> bool:
    return any(i.severity == "blocking" for i in issues)


# =====================================================================
# auto_fix (deterministic, after the last LLM attempt)
# =====================================================================

def soften_text(text: str) -> str:
    """Replace promise words with softer ones, keeping allowed phrases untouched."""
    # Protect allowed phrases by swapping them for placeholders first.
    protected: list[str] = []

    def protect(match: re.Match) -> str:
        protected.append(match.group(0))
        return f"\x00{len(protected) - 1}\x00"

    text = _ALLOWED_RE.sub(protect, text)
    for pattern, replacement in _BANNED_RE:
        text = pattern.sub(replacement, text)
    return re.sub(r"\x00(\d+)\x00", lambda m: protected[int(m.group(1))], text)


def auto_fix(draft: PlanDraft, chunks: list[RetrievedChunk]) -> tuple[PlanDraft, list[str]]:
    """Return (fixed copy of the draft, list of fixes made). Only safe, rule-based fixes."""
    fixes: list[str] = []
    data = draft.model_dump()

    kept = []
    for s in data["schemes"]:
        if scheme_is_grounded(s["scheme"], s["source_url"], chunks):
            kept.append(s)
        else:
            fixes.append(f"Removed scheme '{s['scheme']}': not found in the official documents.")
    data["schemes"] = kept

    def walk(value):
        if isinstance(value, str):
            for phrase in find_banned_phrases(value):
                fixes.append(f"Softened promise words: '{phrase}' -> '{soften_text(phrase)}'")
            return soften_text(value)
        if isinstance(value, dict):
            return {k: walk(v) for k, v in value.items()}
        if isinstance(value, list):
            return [walk(v) for v in value]
        return value

    data = walk(data)
    return PlanDraft.model_validate(data), fixes
