"""Phase 3: LangChain tools for the Phase 4 agent.

The agent reads each tool's docstring to decide WHEN to call it, and the typed arguments to
know WHAT to pass. Tools return plain dicts (JSON-friendly) so the LLM can read the results.
Rule: the agent must use these for every number and every scheme; it never guesses either.
"""
from typing import Optional

from langchain_core.tools import tool

from app import calculator, rag
from app.calculator import FinancialInput
from app.models import BusinessProfile


@tool
def search_schemes(query: str, category: Optional[str] = None) -> list[dict]:
    """Search official Indian government scheme documents (loans, subsidies, registrations,
    licences, GST). Use for any question about schemes, eligibility, loan limits or licences.
    category can be: loan, subsidy, registration, license, tax. Returns text chunks with the
    scheme name and official source_url; always cite the source_url to the user."""
    return [c.model_dump() for c in rag.retrieve(query, k=4, category=category)]


@tool
def search_schemes_for_profile(
    business_idea: str,
    budget_inr: Optional[int] = None,
    location: Optional[str] = None,
    skills: Optional[str] = None,
    target_customers: Optional[str] = None,
    sales_channel: Optional[str] = None,
) -> list[dict]:
    """Find the government schemes, loans and licences that fit one business profile
    (e.g. FSSAI for a food business, PM SVANidhi for a street vendor, Mudra for a small loan).
    Use this once when writing a business plan. Returns chunks with official source_url."""
    profile = BusinessProfile(
        business_idea=business_idea, budget_inr=budget_inr, location=location,
        skills=skills, target_customers=target_customers, sales_channel=sales_channel,
    )
    return [c.model_dump() for c in rag.retrieve_for_profile(profile)]


@tool(args_schema=FinancialInput)
def calculate_financials(**kwargs) -> dict:
    """Calculate the full money picture of a small business: budget check, suggested price,
    profit per unit, break-even sales, low/expected/high monthly profit, payback months and
    GST/FSSAI flags. Use this for EVERY number in a business plan; never do the maths yourself.
    All amounts are whole rupees. Results are estimates, not guarantees."""
    return calculator.full_financials(FinancialInput(**kwargs)).model_dump()


@tool
def calculate_break_even(fixed_monthly_costs: int, profit_per_unit: int, working_days: int = 26) -> dict:
    """How many units must be sold per month and per day to cover fixed monthly costs
    (rent, salary, gas). profit_per_unit = selling price - cost of one unit, in rupees."""
    return calculator.break_even(fixed_monthly_costs, profit_per_unit, working_days).model_dump()


@tool
def calculate_suggested_price(
    unit_cost: int,
    target_margin_percent: float = 40,
    market_low: Optional[int] = None,
    market_high: Optional[int] = None,
) -> dict:
    """Suggest a selling price (rounded to the nearest Rs 5) from the cost of one unit and a
    target profit margin, kept inside the local market price range if given."""
    return calculator.suggest_price(unit_cost, target_margin_percent, market_low, market_high).model_dump()


ALL_TOOLS = [
    search_schemes,
    search_schemes_for_profile,
    calculate_financials,
    calculate_break_even,
    calculate_suggested_price,
]
