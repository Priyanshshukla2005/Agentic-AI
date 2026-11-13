"""Phase 4 graph tests (offline). Mock mode by default; a recording fake LLM tests the real LLM path."""
import json

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel

from app import planner
from app.calculator import FinancialInput, full_financials
from app.models import BusinessProfile
from app.plan_mock import FAKE_SCHEME, VALID_PLAN
from app.session_store import create_session, get_session

PROFILE = BusinessProfile(
    business_idea="Healthy meal service for gym-goers", budget_inr=20000, location="Ghaziabad",
    skills="Basic cooking", target_customers="Gym-goers",
)


def test_valid_mock_plan(fake_scheme_index):
    plan = planner.generate_plan(PROFILE)
    assert plan.prompt_version == "plan_v4" and plan.provider == "mock"
    assert plan.validation.passed is True
    assert plan.validation.attempts == 1 and plan.validation.issues == []
    assert plan.warnings == []
    # Financial numbers are the CALCULATOR's
    f = plan.financials
    assert f.unit.profit_per_unit == 70 and f.unit.margin_percent == 41.2
    assert f.break_even.units_per_month == 43 and f.break_even.units_per_day == 2
    assert f.budget.startup_need == 13000 and f.budget.remaining == 7000
    # Suggested schemes are exactly ones that were retrieved
    source_urls = {c.source_url for c in plan.sources}
    assert plan.draft.schemes and all(s.source_url in source_urls for s in plan.draft.schemes)
    # finalize builds the plan itself, so its own time is only included in "total"
    assert {"retrieve", "draft", "calculate", "validate", "total"} <= set(plan.timings)


def test_financials_match_calculator_directly(fake_scheme_index):
    plan = planner.generate_plan(PROFILE)
    d = plan.draft
    expected = full_financials(FinancialInput(
        budget_inr=20000, cost_items=d.startup_costs + d.fixed_monthly_costs, unit_cost=d.unit_cost_inr,
        selling_price=d.selling_price_inr, market_low=d.market_price_low_inr, market_high=d.market_price_high_inr,
        units_per_day_low=d.units_per_day_low, units_per_day_expected=d.units_per_day_expected,
        units_per_day_high=d.units_per_day_high, is_food_business=True,
    ))
    assert plan.financials == expected


def test_invalid_mock_is_repaired_then_auto_fixed(fake_scheme_index):
    plan = planner.generate_plan(PROFILE, mock_variant="invalid")
    v = plan.validation
    assert v.attempts == 1 + planner.MAX_REPAIRS  # first draft + 2 repair rounds
    assert "repair" in plan.timings and "auto_fix" in plan.timings
    # auto_fix: fake scheme dropped, promise words removed
    assert FAKE_SCHEME["scheme"] not in [s.scheme for s in plan.draft.schemes]
    assert "guaranteed" not in plan.draft.business_summary.lower()
    assert any("Removed scheme 'PM Free Money Yojana'" in r for r in v.repairs_made)
    assert any("guaranteed profit" in r for r in v.repairs_made)
    # the budget problem is NOT hidden
    assert v.passed is False
    assert [i.code for i in v.issues] == ["BUDGET_OVER"]
    assert any(w.startswith("BUDGET_OVER") for w in plan.warnings)
    assert plan.financials.budget.over_budget is True


def test_invalid_variant_from_env(fake_scheme_index, monkeypatch):
    monkeypatch.setenv("MOCK_PLAN_VARIANT", "invalid")
    assert planner.generate_plan(PROFILE).validation.passed is False


def test_missing_index_gives_warning_not_crash(no_scheme_index):
    plan = planner.generate_plan(PROFILE)
    assert plan.sources == [] and plan.draft.schemes == []
    assert any("ingest_docs.py" in w for w in plan.warnings)
    assert plan.validation.passed is True


def test_plan_v1_returns_raw_text(fake_scheme_index):
    plan = planner.generate_plan(PROFILE, prompt_version="plan_v1")
    assert plan.raw_text and plan.draft is None
    assert plan.financials is None and plan.validation is None
    assert any("plan_v1" in w for w in plan.warnings)


def test_incomplete_profile_is_rejected():
    with pytest.raises(ValueError, match="incomplete"):
        planner.generate_plan(BusinessProfile(business_idea="Tea stall"))


def test_plan_is_saved_in_session(fake_scheme_index):
    session = create_session("en")
    session.profile = PROFILE
    from app.session_store import save_session
    save_session(session)
    plan = planner.generate_plan(PROFILE, session_id=session.session_id)
    assert get_session(session.session_id).plan["generated_at"] == plan.model_dump(mode="json")["generated_at"]


def test_mermaid_export(tmp_path):
    mermaid = planner.export_mermaid(tmp_path / "graph.md")
    for node in ["retrieve", "draft", "calculate", "validate", "repair", "auto_fix", "finalize"]:
        assert node in mermaid
    assert "```mermaid" in (tmp_path / "graph.md").read_text()


# ---------- Real LLM path with a fake model (still offline) ----------

class RecordingLLM(FakeListChatModel):
    """Fake chat model that remembers every prompt it received."""
    calls: list = []

    def _call(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls.append(messages)
        return super()._call(messages, stop=stop, run_manager=run_manager, **kwargs)


def use_fake_llm(monkeypatch, responses):
    llm = RecordingLLM(responses=responses, calls=[])
    monkeypatch.setattr(planner, "is_mock", lambda: False)
    monkeypatch.setattr(planner, "get_plan_llm", lambda: llm)
    return llm


def test_llm_repair_loop_sends_feedback(fake_scheme_index, monkeypatch):
    bad = dict(VALID_PLAN, schemes=[FAKE_SCHEME], selling_price_inr=90)  # fake scheme + price below cost
    good = dict(VALID_PLAN, schemes=[])
    llm = use_fake_llm(monkeypatch, [json.dumps(bad), json.dumps(good)])

    plan = planner.generate_plan(PROFILE, language="hi")
    assert plan.validation.passed is True and plan.validation.attempts == 2
    assert len(llm.calls) == 2

    first_prompt = "\n".join(m.content for m in llm.calls[0])
    assert "Hindi" in first_prompt               # {language_name} filled in (plan_v4)
    assert "[1] [source:" in first_prompt        # {scheme_context} filled in
    second_prompt = "\n".join(m.content for m in llm.calls[1])
    assert "HALLUCINATED_SCHEME" in second_prompt and "PRICE_BELOW_COST" in second_prompt


def test_llm_failure_raises_plan_error(fake_scheme_index, monkeypatch):
    class BrokenLLM(FakeListChatModel):
        def _call(self, *args, **kwargs):
            raise ConnectionError("network down")

    monkeypatch.setattr(planner, "is_mock", lambda: False)
    monkeypatch.setattr(planner, "get_plan_llm", lambda: BrokenLLM(responses=["x"]))
    with pytest.raises(planner.PlanLLMError, match="network down"):
        planner.generate_plan(PROFILE)
