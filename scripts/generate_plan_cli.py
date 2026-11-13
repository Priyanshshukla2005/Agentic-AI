"""Phase 4 check from the terminal: generate a business plan for a sample profile.

Run from the project folder:
    python scripts/generate_plan_cli.py --profile 0                    # plan_v5 (default)
    python scripts/generate_plan_cli.py --profile 2 --version plan_v2
    python scripts/generate_plan_cli.py --profile 0 --all-versions     # compare v1..v5
    LLM_PROVIDER=mock python scripts/generate_plan_cli.py --profile 0 --mock-variant invalid

Profiles come from data/eval/sample_profiles.json (index 0-4).
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.calculator import _inr  # noqa: E402
from app.config import BASE_DIR, settings  # noqa: E402
from app.llm import LLMConfigError  # noqa: E402
from app.models import BusinessProfile  # noqa: E402
from app.planner import PlanLLMError, generate_plan  # noqa: E402

VERSIONS = ["plan_v1", "plan_v2", "plan_v3", "plan_v4", "plan_v5"]
PROFILES_FILE = BASE_DIR / "data" / "eval" / "sample_profiles.json"


def line(char="-"):
    print(char * 72)


def print_plan(plan, seconds: float) -> None:
    line("=")
    script = f" | script match {plan.script_match:.0%}" if plan.script_match is not None else ""
    print(f"{plan.prompt_version} | {plan.provider}/{plan.model} | language {plan.language} "
          f"({plan.translate_mode}){script} | {seconds:.1f}s")
    line("=")
    if plan.raw_text is not None:  # plan_v1: free text
        print(plan.raw_text)
    if plan.draft:
        d = plan.draft
        print(d.business_summary, "\n")
        print("Startup costs:")
        for c in d.startup_costs:
            print(f"  {c.name:<45} {_inr(c.amount_inr):>12}")
        print("Fixed monthly costs:")
        for c in d.fixed_monthly_costs:
            print(f"  {c.name:<45} {_inr(c.amount_inr):>12}")
        print("\nMarketing ideas:", *[f"  - {m}" for m in d.marketing_ideas], sep="\n")
        print("\nLaunch steps:")
        for i, s in enumerate(d.launch_steps, 1):
            cost = f", {_inr(s.estimated_cost_inr)}" if s.estimated_cost_inr else ""
            print(f"  {i}. {s.title} ({s.estimated_days} days{cost}): {s.detail}")
        print("\nSchemes:", *([f"  - {s.scheme}: {s.why_it_fits} [{s.source_url}]" for s in d.schemes] or ["  (none)"]), sep="\n")
        print("\nRisks:", *[f"  - {r}" for r in d.risks], sep="\n")

    f = plan.financials
    if f:
        line()
        print("FINANCIALS (calculator numbers, not the LLM's)")
        print(f"  Budget {_inr(f.budget.budget_inr)} | needed to start {_inr(f.budget.startup_need)} "
              f"| left {_inr(f.budget.remaining)} ({100 - f.budget.percent_used:.1f}%)")
        print(f"  Price {_inr(f.unit.selling_price)} - cost {_inr(f.unit.unit_cost)} = "
              f"profit {_inr(f.unit.profit_per_unit)} per {plan.draft.unit_name} ({f.unit.margin_percent}% margin)")
        print(f"  Break-even: {f.break_even.message}")
        print(f"  {'month':<9}{'units':>7}{'revenue':>14}{'total cost':>14}{'profit':>14}")
        for s in f.scenarios.scenarios:
            print(f"  {s.label:<9}{s.units_per_month:>7}{_inr(s.revenue):>14}{_inr(s.total_cost):>14}{_inr(s.profit):>14}")
        print(f"  Payback: {f.payback_months if f.payback_months is not None else 'not reached'} months")
        for flag in f.compliance.flags:
            print(f"  - {flag}")
        print(f"  {f.disclaimer}")

    v = plan.validation
    if v:
        line()
        print(f"VALIDATION: {'PASSED' if v.passed else 'NOT PASSED'} after {v.attempts} attempt(s)")
        for i in v.issues:
            print(f"  [{i.severity}] {i.code}: {i.message}")
        for r in v.repairs_made:
            print(f"  auto-fix: {r}")
    if plan.warnings:
        print("Warnings:", *[f"  ! {w}" for w in plan.warnings], sep="\n")
    print(f"Sources used: {len(plan.sources)} chunks | timings: {plan.timings}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a business plan for a sample profile.")
    parser.add_argument("--profile", type=int, default=0, help="index in data/eval/sample_profiles.json")
    parser.add_argument("--version", default=settings.DEFAULT_PLAN_VERSION, choices=VERSIONS)
    parser.add_argument("--all-versions", action="store_true", help="run plan_v1 to plan_v5 and compare")
    parser.add_argument("--mock-variant", default=None, choices=["valid", "invalid"], help="mock mode only")
    args = parser.parse_args()

    profiles = json.loads(PROFILES_FILE.read_text(encoding="utf-8"))
    if not 0 <= args.profile < len(profiles):
        print(f"--profile must be between 0 and {len(profiles) - 1}")
        return 1
    profile = BusinessProfile(**profiles[args.profile])
    print(f"Provider: {settings.LLM_PROVIDER} | Model: {settings.model_name}")
    print(f"Profile {args.profile}: {profile.business_idea} | {_inr(profile.budget_inr)} | {profile.location}")

    summary = []
    for version in (VERSIONS if args.all_versions else [args.version]):
        start = time.perf_counter()
        try:
            plan = generate_plan(profile, prompt_version=version, mock_variant=args.mock_variant)
        except (LLMConfigError, PlanLLMError) as e:
            print(f"ERROR ({version}): {e}")
            return 1
        seconds = time.perf_counter() - start
        print_plan(plan, seconds)
        passed = "n/a (free text)" if plan.validation is None else ("passed" if plan.validation.passed else "NOT passed")
        codes = ", ".join(i.code for i in plan.validation.issues) if plan.validation else "-"
        summary.append((version, passed, codes or "none", seconds))

    if len(summary) > 1:
        line("=")
        print(f"{'version':<10}{'validation':<18}{'issues':<36}{'seconds':>8}")
        for version, passed, codes, seconds in summary:
            print(f"{version:<10}{passed:<18}{codes[:34]:<36}{seconds:>8.1f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
