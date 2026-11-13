"""Phase 3 (B): money calculator. Pure Python, no LLM.

Language models are bad at arithmetic, so the agent NEVER does money maths itself: it calls
these functions and only explains the results. All money is in whole rupees (int).

Every result says it is an ESTIMATE. Real sales and costs will differ.
"""
import math
from typing import Literal, Optional

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Official limits used by compliance_flags(). Re-check these every year.
# ---------------------------------------------------------------------------
THRESHOLDS = {
    # GST registration, from 1 April 2019 (GST Council, 32nd meeting).
    # Goods: two limits (40 lakh and 20 lakh); each State chooses which one applies.
    # Services: 20 lakh, or 10 lakh in Special Category States.
    # Source: https://www.pib.gov.in/Pressreleaseshare.aspx?PRID=1567975&reg=48&lang=2
    # Confirmed as still current in "Nine Years of GST" (30 June 2026):
    # https://www.pib.gov.in/PressReleasePage.aspx?PRID=2279318&reg=3&lang=1
    "gst_goods_high_inr": 40_00_000,
    "gst_goods_low_inr": 20_00_000,
    "gst_services_inr": 20_00_000,
    "gst_services_special_category_inr": 10_00_000,
    # FSSAI: "petty" food businesses with annual turnover up to Rs 12 lakh need a Registration
    # Certificate; above that, an FSSAI License.
    # Source: https://fssai.gov.in/upload/uploadfiles/files/FAQs_Licensing_Registration_21_12_2022.pdf
    "fssai_registration_max_inr": 12_00_000,
}

ESTIMATE_NOTE = "These are ESTIMATES based on your numbers, not guarantees. Real sales and costs will differ."
RESERVE_PERCENT = 10  # keep at least this much of the budget unspent, for surprises


def _round_to_5(value: float) -> int:
    """Round to the nearest Rs 5 (2.5 rounds up). Shop prices usually end in 0 or 5."""
    return int(math.floor(value / 5 + 0.5) * 5)


def _inr(amount: int) -> str:
    """150000 -> 'Rs 1,50,000' (Indian digit grouping), for warning messages."""
    sign = "-" if amount < 0 else ""
    digits = str(abs(int(amount)))
    if len(digits) > 3:
        head, tail = digits[:-3], digits[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        digits = ",".join(groups) + "," + tail
    return f"{sign}Rs {digits}"


# =====================================================================
# 1. Budget
# =====================================================================

class CostItem(BaseModel):
    name: str = Field(..., examples=["Gas stove"])
    amount_inr: int = Field(..., ge=0, examples=[3000])
    kind: Literal["one_time", "monthly"] = "one_time"


class BudgetSummary(BaseModel):
    budget_inr: int
    one_time_total: int
    monthly_total: int
    startup_need: int = Field(..., description="One-time costs + the first month's running costs")
    remaining: int
    percent_used: float
    over_budget: bool
    warnings: list[str] = Field(default_factory=list)


def budget_summary(items: list[CostItem], budget_inr: int) -> BudgetSummary:
    """Add up the costs and compare them with the budget.

    The money needed to START = all one-time costs + one month of monthly costs (rent,
    ingredients...), because the first month must be paid before sales come in.
    Warns when over budget, or when less than 10% of the budget is left as a reserve.
    """
    if budget_inr <= 0:
        raise ValueError("Budget must be more than 0.")
    one_time = sum(i.amount_inr for i in items if i.kind == "one_time")
    monthly = sum(i.amount_inr for i in items if i.kind == "monthly")
    need = one_time + monthly
    remaining = budget_inr - need

    warnings = []
    if remaining < 0:
        warnings.append(f"Over budget by {_inr(-remaining)}. Cut some costs or start smaller.")
    elif remaining < budget_inr * RESERVE_PERCENT / 100:
        warnings.append(
            f"Only {_inr(remaining)} left. Try to keep at least {RESERVE_PERCENT}% of the budget "
            f"({_inr(budget_inr * RESERVE_PERCENT // 100)}) as a reserve for surprises."
        )
    return BudgetSummary(
        budget_inr=budget_inr,
        one_time_total=one_time,
        monthly_total=monthly,
        startup_need=need,
        remaining=remaining,
        percent_used=round(need / budget_inr * 100, 1),
        over_budget=remaining < 0,
        warnings=warnings,
    )


# =====================================================================
# 2. Price and profit per item
# =====================================================================

class UnitEconomics(BaseModel):
    unit_cost: int
    selling_price: int
    profit_per_unit: int
    margin_percent: float = Field(..., description="Profit as a % of the selling price")
    warnings: list[str] = Field(default_factory=list)


def unit_economics(unit_cost: int, selling_price: int) -> UnitEconomics:
    """Profit on ONE item. Margin = profit / selling price x 100.
    Example: cost 100, price 170 -> profit 70, margin 41.2%."""
    if unit_cost < 0 or selling_price < 0:
        raise ValueError("Cost and price cannot be negative.")
    profit = selling_price - unit_cost
    margin = round(profit / selling_price * 100, 1) if selling_price > 0 else 0.0
    warnings = []
    if selling_price <= unit_cost:
        warnings.append(
            f"Selling price ({_inr(selling_price)}) is not more than the cost ({_inr(unit_cost)}). "
            "You lose money on every sale. Raise the price or lower the cost."
        )
    return UnitEconomics(
        unit_cost=unit_cost, selling_price=selling_price,
        profit_per_unit=profit, margin_percent=margin, warnings=warnings,
    )


class PriceSuggestion(BaseModel):
    suggested_price: int
    unit_cost: int
    margin_percent: float
    reason: str
    warnings: list[str] = Field(default_factory=list)


def suggest_price(
    unit_cost: int,
    target_margin_percent: float = 40,
    market_low: Optional[int] = None,
    market_high: Optional[int] = None,
) -> PriceSuggestion:
    """Price that gives the target margin, rounded to the nearest Rs 5, and kept inside the
    market range (what nearby sellers charge) if one is given.

    Margin is on the selling price: price = cost / (1 - margin/100).
    Example: cost 100, margin 40% -> 166.67 -> Rs 165.
    """
    if unit_cost < 0:
        raise ValueError("Cost cannot be negative.")
    if not 0 <= target_margin_percent < 100:
        raise ValueError("Target margin must be between 0 and 99 percent.")
    if market_low is not None and market_high is not None and market_low > market_high:
        raise ValueError("market_low cannot be more than market_high.")

    price = _round_to_5(unit_cost / (1 - target_margin_percent / 100))
    reason = f"Cost {_inr(unit_cost)} + {target_margin_percent:g}% margin, rounded to the nearest Rs 5."
    if market_low is not None and price < market_low:
        price = market_low
        reason = f"Your target price is below the market range, so we use the market low of {_inr(market_low)}."
    elif market_high is not None and price > market_high:
        price = market_high
        reason = (
            f"Your target price is above what the market pays, so it is capped at the market high "
            f"of {_inr(market_high)}."
        )

    warnings = []
    if price <= unit_cost:
        warnings.append("At this price you make no profit. Find a cheaper supplier or a smaller pack size.")
    margin = round((price - unit_cost) / price * 100, 1) if price > 0 else 0.0
    return PriceSuggestion(
        suggested_price=price, unit_cost=unit_cost, margin_percent=margin, reason=reason, warnings=warnings
    )


# =====================================================================
# 3. Break-even: how many sales to cover the fixed monthly costs
# =====================================================================

class BreakEven(BaseModel):
    possible: bool
    units_per_month: Optional[int] = None
    units_per_day: Optional[int] = None
    message: str


def break_even(fixed_monthly_costs: int, profit_per_unit: int, working_days: int = 26) -> BreakEven:
    """Sales needed each month (and day) so that profit covers rent, salary etc.
    Both numbers are rounded UP: you cannot sell 42.9 plates.
    Example: fixed Rs 3,000, profit Rs 70 per unit, 26 days -> 43 a month, 2 a day."""
    if working_days <= 0:
        raise ValueError("Working days must be more than 0.")
    if fixed_monthly_costs < 0:
        raise ValueError("Fixed costs cannot be negative.")
    if profit_per_unit <= 0:
        return BreakEven(
            possible=False,
            message="Break-even is not possible at this price: each sale makes no profit. Raise the price or lower the cost.",
        )
    per_month = math.ceil(fixed_monthly_costs / profit_per_unit)
    per_day = math.ceil(per_month / working_days)
    return BreakEven(
        possible=True,
        units_per_month=per_month,
        units_per_day=per_day,
        message=f"Sell at least {per_month} units a month (about {per_day} a day over {working_days} working days) to cover fixed costs.",
    )


# =====================================================================
# 4. Monthly scenarios and payback
# =====================================================================

class Scenario(BaseModel):
    label: Literal["low", "expected", "high"]
    units_per_day: int
    units_per_month: int
    revenue: int
    total_cost: int
    profit: int


class MonthlyScenarios(BaseModel):
    scenarios: list[Scenario]
    note: str = ESTIMATE_NOTE


def monthly_scenarios(
    unit_cost: int,
    selling_price: int,
    fixed_monthly_costs: int,
    units_per_day_low: int,
    units_per_day_expected: int,
    units_per_day_high: int,
    working_days: int = 26,
) -> MonthlyScenarios:
    """Revenue, cost and profit for a slow, normal and good month. ESTIMATES only.
    total cost = (unit cost x units) + fixed monthly costs."""
    if working_days <= 0:
        raise ValueError("Working days must be more than 0.")
    scenarios = []
    for label, per_day in (("low", units_per_day_low), ("expected", units_per_day_expected), ("high", units_per_day_high)):
        if per_day < 0:
            raise ValueError("Units per day cannot be negative.")
        units = per_day * working_days
        revenue = units * selling_price
        total_cost = units * unit_cost + fixed_monthly_costs
        scenarios.append(Scenario(
            label=label, units_per_day=per_day, units_per_month=units,
            revenue=revenue, total_cost=total_cost, profit=revenue - total_cost,
        ))
    return MonthlyScenarios(scenarios=scenarios)


def payback_months(startup_cost: int, monthly_profit: int) -> Optional[float]:
    """Months to earn back the starting investment. None if there is no monthly profit."""
    if monthly_profit <= 0:
        return None
    return round(startup_cost / monthly_profit, 1)


# =====================================================================
# 5. Compliance (GST / FSSAI) from yearly sales
# =====================================================================

class ComplianceFlags(BaseModel):
    annual_revenue_estimate: int
    flags: list[str]


def compliance_flags(annual_revenue_estimate: int, is_food_business: bool, is_service: bool) -> ComplianceFlags:
    """Plain-language hints about GST and FSSAI based on expected yearly sales.
    Limits come from THRESHOLDS at the top of this file. Always says "(verify)": State rules differ."""
    t = THRESHOLDS
    revenue = annual_revenue_estimate
    flags = []

    if is_service:
        if revenue <= t["gst_services_special_category_inr"]:
            flags.append("GST: below the GST registration limit for services, not needed yet (verify).")
        elif revenue <= t["gst_services_inr"]:
            flags.append(
                f"GST: below the {_inr(t['gst_services_inr'])} limit for services, but Special Category "
                f"States use {_inr(t['gst_services_special_category_inr'])}. Check your State (verify)."
            )
        else:
            flags.append(f"GST: yearly sales above {_inr(t['gst_services_inr'])}, GST registration is needed (verify).")
    else:
        if revenue <= t["gst_goods_low_inr"]:
            flags.append("GST: below the GST registration limit, not needed yet (verify).")
        elif revenue <= t["gst_goods_high_inr"]:
            flags.append(
                f"GST: between {_inr(t['gst_goods_low_inr'])} and {_inr(t['gst_goods_high_inr'])}. "
                "Whether you need GST depends on which limit your State uses (verify)."
            )
        else:
            flags.append(f"GST: yearly sales above {_inr(t['gst_goods_high_inr'])}, GST registration is needed (verify).")

    if is_food_business:
        if revenue <= t["fssai_registration_max_inr"]:
            flags.append(
                f"FSSAI: basic FSSAI Registration is needed before selling food (turnover up to "
                f"{_inr(t['fssai_registration_max_inr'])}) (verify)."
            )
        else:
            flags.append(
                f"FSSAI: turnover above {_inr(t['fssai_registration_max_inr'])}, you need an FSSAI License, "
                "not just a registration (verify)."
            )

    flags.append("Udyam: free MSME registration, useful for loans and schemes (recommended).")
    return ComplianceFlags(annual_revenue_estimate=revenue, flags=flags)


# =====================================================================
# 6. Everything at once (what Phase 4 puts into the plan)
# =====================================================================

class FinancialInput(BaseModel):
    budget_inr: int = Field(..., gt=0, examples=[20000])
    cost_items: list[CostItem] = Field(default_factory=list)
    unit_cost: int = Field(..., ge=0, description="Cost to make/buy ONE unit", examples=[100])
    selling_price: Optional[int] = Field(None, ge=0, description="Leave empty to get a suggested price", examples=[170])
    target_margin_percent: float = Field(40, ge=0, lt=100)
    market_low: Optional[int] = Field(None, ge=0)
    market_high: Optional[int] = Field(None, ge=0)
    fixed_monthly_costs: Optional[int] = Field(
        None, ge=0, description="Rent, salary, gas... per month. Empty = total of monthly cost_items"
    )
    units_per_day_low: int = Field(..., ge=0, examples=[5])
    units_per_day_expected: int = Field(..., ge=0, examples=[10])
    units_per_day_high: int = Field(..., ge=0, examples=[15])
    working_days: int = Field(26, gt=0, le=31)
    is_food_business: bool = False
    is_service: bool = False


class FinancialSummary(BaseModel):
    budget: BudgetSummary
    price: PriceSuggestion
    unit: UnitEconomics
    break_even: BreakEven
    scenarios: MonthlyScenarios
    payback_months: Optional[float]
    compliance: ComplianceFlags
    warnings: list[str]
    disclaimer: str = ESTIMATE_NOTE


def full_financials(data: FinancialInput) -> FinancialSummary:
    """Run every calculation and return one summary. If no selling price is given, the
    suggested price is used. Payback and compliance use the EXPECTED scenario."""
    budget = budget_summary(data.cost_items, data.budget_inr)
    price = suggest_price(data.unit_cost, data.target_margin_percent, data.market_low, data.market_high)
    selling_price = data.selling_price if data.selling_price is not None else price.suggested_price
    unit = unit_economics(data.unit_cost, selling_price)

    fixed = data.fixed_monthly_costs if data.fixed_monthly_costs is not None else budget.monthly_total
    be = break_even(fixed, unit.profit_per_unit, data.working_days)
    scenarios = monthly_scenarios(
        data.unit_cost, selling_price, fixed,
        data.units_per_day_low, data.units_per_day_expected, data.units_per_day_high, data.working_days,
    )
    expected = next(s for s in scenarios.scenarios if s.label == "expected")
    payback = payback_months(budget.one_time_total, expected.profit)
    compliance = compliance_flags(expected.revenue * 12, data.is_food_business, data.is_service)

    warnings = budget.warnings + unit.warnings + price.warnings
    if be.possible and be.units_per_day > data.units_per_day_expected:
        warnings.append(
            f"You expect {data.units_per_day_expected} sales a day, but need {be.units_per_day} a day "
            "just to cover fixed costs."
        )
    if payback is None:
        warnings.append("No profit in the expected month, so the starting money is never earned back at these numbers.")

    return FinancialSummary(
        budget=budget, price=price, unit=unit, break_even=be, scenarios=scenarios,
        payback_months=payback, compliance=compliance, warnings=warnings,
    )
