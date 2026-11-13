"""Turn a BusinessPlan into plain readable text (for the LLM judge and the human review pack).

The text never says which prompt version made the plan, so judging stays blind.
"""
from app.calculator import _inr
from app.plan_models import BusinessPlan


def plan_to_text(plan: BusinessPlan) -> str:
    if plan.raw_text is not None:  # plan_v1: free text as written
        return plan.raw_text.strip()
    d, f = plan.draft, plan.financials
    lines = ["SUMMARY", d.business_summary, "", "STARTUP COSTS"]
    lines += [f"- {c.name}: {_inr(c.amount_inr)}" for c in d.startup_costs]
    lines += ["MONTHLY COSTS"] + [f"- {c.name}: {_inr(c.amount_inr)}" for c in d.fixed_monthly_costs]
    if f:
        b, u, be = f.budget, f.unit, f.break_even
        lines += [
            "", "MONEY (calculated)",
            f"- Budget {_inr(b.budget_inr)}, needed to start {_inr(b.startup_need)}, left {_inr(b.remaining)}",
            f"- Cost per {d.unit_name} {_inr(u.unit_cost)}, price {_inr(u.selling_price)}, profit per unit {_inr(u.profit_per_unit)}",
            f"- Break-even: {be.message}",
        ]
        lines += [f"- {s.label} month: revenue {_inr(s.revenue)}, profit {_inr(s.profit)}" for s in f.scenarios.scenarios]
        lines += [f"- {flag}" for flag in f.compliance.flags]
    lines += ["", "MARKETING"] + [f"- {m}" for m in d.marketing_ideas]
    lines += ["", "LAUNCH STEPS"] + [f"{i}. {s.title}: {s.detail} ({s.estimated_days} days)" for i, s in enumerate(d.launch_steps, 1)]
    lines += ["", "GOVERNMENT SCHEMES"] + ([f"- {s.scheme}: {s.why_it_fits} ({s.source_url})" for s in d.schemes] or ["- none"])
    lines += ["", "ASSUMPTIONS"] + [f"- {a}" for a in d.assumptions]
    lines += ["", "RISKS"] + [f"- {r}" for r in d.risks]
    return "\n".join(lines)
