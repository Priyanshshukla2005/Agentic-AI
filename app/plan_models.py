"""Phase 4 data models: what the LLM writes (PlanDraft) and what the user gets (BusinessPlan).

Core rule: the LLM only proposes INPUT numbers (costs, unit cost, price, expected sales).
Every total, profit, break-even and payback in BusinessPlan.financials comes from
app/calculator.py, never from the LLM.
"""
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.calculator import CostItem, FinancialSummary
from app.models import BusinessProfile
from app.rag import RetrievedChunk

PromptVersion = Literal["plan_v1", "plan_v2", "plan_v3", "plan_v4"]

__all__ = [
    "CostItem", "LaunchStep", "SchemeSuggestion", "PlanDraft", "ValidationIssue",
    "ValidationReport", "BusinessPlan", "PromptVersion",
]


class LaunchStep(BaseModel):
    title: str = Field(..., description="Short name of the step, e.g. 'Get FSSAI registration'")
    detail: str = Field(..., description="What exactly to do, in simple words")
    estimated_days: int = Field(..., ge=0, description="Days this step takes")
    estimated_cost_inr: Optional[int] = Field(None, ge=0, description="Cost in whole rupees, if any")


class SchemeSuggestion(BaseModel):
    scheme: str = Field(..., description="Scheme name exactly as in the context")
    why_it_fits: str = Field(..., description="One line: why this scheme suits this business")
    source_url: str = Field(..., description="Official link, copied exactly from the context")


class PlanDraft(BaseModel):
    """The LLM's plan. Numbers here are INPUTS for the calculator, never totals."""

    business_summary: str = Field(..., description="2-3 lines describing the business")
    unit_name: str = Field(..., description="What one sale is, e.g. 'meal', 'jar', 'kg'")
    startup_costs: list[CostItem] = Field(default_factory=list, description="One-time costs to start")
    fixed_monthly_costs: list[CostItem] = Field(
        default_factory=list, description="Costs paid every month whatever the sales (rent, gas, phone)"
    )
    unit_cost_inr: int = Field(..., ge=0, description="Cost to make or buy ONE unit")
    selling_price_inr: int = Field(..., ge=0, description="Price of ONE unit")
    market_price_low_inr: int = Field(..., ge=0, description="Lowest price similar sellers charge nearby")
    market_price_high_inr: int = Field(..., ge=0, description="Highest price similar sellers charge nearby")
    units_per_day_low: int = Field(..., ge=0, description="Units sold on a slow day")
    units_per_day_expected: int = Field(..., ge=0, description="Units sold on a normal day")
    units_per_day_high: int = Field(..., ge=0, description="Units sold on a good day")
    marketing_ideas: list[str] = Field(default_factory=list, description="3-5 low-cost, local ideas")
    launch_steps: list[LaunchStep] = Field(default_factory=list, description="5-8 steps in order")
    schemes: list[SchemeSuggestion] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list, description="2-4 main risks")


class ValidationIssue(BaseModel):
    code: str = Field(..., examples=["BUDGET_OVER"])
    message: str
    severity: Literal["blocking", "warning"]


class ValidationReport(BaseModel):
    passed: bool = Field(..., description="True when no blocking issue is left")
    issues: list[ValidationIssue] = Field(default_factory=list)
    repairs_made: list[str] = Field(default_factory=list)
    attempts: int = Field(0, description="How many times the LLM wrote the plan")


class BusinessPlan(BaseModel):
    profile: BusinessProfile
    draft: Optional[PlanDraft] = None
    raw_text: Optional[str] = Field(None, description="Only for plan_v1 (free text, not validated)")
    financials: Optional[FinancialSummary] = None
    validation: Optional[ValidationReport] = None
    sources: list[RetrievedChunk] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list, description="Problems the user must see")
    language: str
    prompt_version: PromptVersion
    provider: str
    model: str
    generated_at: datetime
    timings: dict[str, float] = Field(default_factory=dict, description="Seconds per graph node")
