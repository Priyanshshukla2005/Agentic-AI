"""Phase 7: automatic evaluation metrics on crafted plans (no LLM)."""
import copy
from datetime import datetime, timezone

import pytest

from app.calculator import full_financials
from app.evaluation.metrics import (
    compute_metrics,
    hallucinated_schemes,
    readability,
    structure_score,
)
from app.models import BusinessProfile
from app.plan_mock import VALID_PLAN, VALID_PLAN_HI
from app.plan_models import BusinessPlan, PlanDraft, ValidationIssue, ValidationReport
from app.planner import financial_input

PROFILE = BusinessProfile(business_idea="Healthy meal service", budget_inr=20000, location="Ghaziabad",
                          skills="Cooking", target_customers="Gym-goers")
FSSAI_URL = "https://fssai.gov.in/x.pdf"
KNOWN = [{"scheme": "FSSAI Registration", "source_url": FSSAI_URL},
         {"scheme": "PM Mudra Yojana", "source_url": "https://pib.gov.in/mudra"}]


def make_plan(draft_data=None, budget=20000, validation=None, language="en", raw_text=None) -> BusinessPlan:
    common = dict(profile=PROFILE.model_copy(update={"budget_inr": budget}), language=language, provider="mock",
                  model="mock", generated_at=datetime.now(timezone.utc), timings={"total": 1.5})
    if raw_text is not None:
        return BusinessPlan(raw_text=raw_text, prompt_version="plan_v1", **common)
    data = copy.deepcopy(draft_data or VALID_PLAN)
    data.setdefault("schemes", [{"scheme": "FSSAI Registration", "why_it_fits": "Needed.", "source_url": FSSAI_URL}])
    draft = PlanDraft.model_validate(data)
    financials = full_financials(financial_input(draft, common["profile"]))
    return BusinessPlan(draft=draft, financials=financials, prompt_version="plan_v5",
                        validation=validation or ValidationReport(passed=True, attempts=1), **common)


def test_clean_structured_plan():
    m = compute_metrics(make_plan(), "en", KNOWN)
    assert m["structure_score"] == 1.0
    assert m["budget_fit"] is True and m["price_above_cost"] is True and m["break_even_realistic"] is True
    assert m["hallucinated_schemes"] == 0 and m["guarantee_phrases"] == 0
    assert m["language_match"] == 100.0
    assert m["issues_before_repair"] == 0 and m["llm_repairs"] == 0 and m["final_passed"] is True
    assert m["latency_seconds"] == 1.5 and m["output_tokens_est"] > 100


def test_structure_score_missing_sections():
    plan = make_plan({**VALID_PLAN, "risks": [], "marketing_ideas": []})
    assert structure_score(plan) == round(5 / 7, 3)


def test_budget_price_and_break_even_failures():
    over = make_plan(budget=5000)
    assert compute_metrics(over, "en", KNOWN)["budget_fit"] is False
    cheap = make_plan({**VALID_PLAN, "selling_price_inr": 90})
    m = compute_metrics(cheap, "en", KNOWN)
    assert m["price_above_cost"] is False and m["break_even_realistic"] is False
    slow = make_plan({**VALID_PLAN, "units_per_day_low": 1, "units_per_day_expected": 1, "units_per_day_high": 1})
    assert compute_metrics(slow, "en", KNOWN)["break_even_realistic"] is False


def test_hallucinated_schemes_structured():
    fake = [{"scheme": "PM Free Money Yojana", "why_it_fits": "x", "source_url": "https://example.com"},
            {"scheme": "FSSAI Registration", "why_it_fits": "x", "source_url": "https://wrong.example.com"},
            {"scheme": "FSSAI Registration", "why_it_fits": "x", "source_url": FSSAI_URL}]
    assert hallucinated_schemes(make_plan({**VALID_PLAN, "schemes": fake}), KNOWN) == 2
    assert hallucinated_schemes(make_plan(), []) == 1  # no index: nothing can be verified


def test_guarantee_phrases_counted():
    plan = make_plan({**VALID_PLAN, "risks": ["Guaranteed profit, totally risk-free"], "business_summary": "Pakka munafa hoga"})
    assert compute_metrics(plan, "en", KNOWN)["guarantee_phrases"] == 3


def test_validation_fields():
    report = ValidationReport(passed=False, attempts=3, initial_issue_codes=["BUDGET_OVER", "GUARANTEE_LANGUAGE"],
                              repairs_made=["Softened promise words"],
                              issues=[ValidationIssue(code="BUDGET_OVER", message="x", severity="blocking")])
    m = compute_metrics(make_plan(validation=report), "en", KNOWN)
    assert (m["issues_before_repair"], m["llm_repairs"], m["auto_fixes"], m["final_passed"], m["final_issues"]) == (2, 2, 1, False, 1)


def test_language_match_hindi_and_wrong_language():
    assert compute_metrics(make_plan(VALID_PLAN_HI, language="hi"), "hi", KNOWN)["language_match"] > 95
    assert compute_metrics(make_plan(), "hi", KNOWN)["language_match"] == 0.0  # English text for a Hindi user


RAW_V1 = """Business Plan for a tiffin service in Pune.
Startup costs: stove Rs 3,000, utensils Rs 2,000. Total investment Rs 10,000.
Pricing: sell each meal at Rs 120. Profit: about Rs 40 per meal, guaranteed income every month.
Marketing: WhatsApp groups and flyers.
You can apply for the Pradhan Mantri Mudra Yojana and the Super Startup Scheme."""


def test_v1_raw_text_metrics():
    m = compute_metrics(make_plan(raw_text=RAW_V1), "en", KNOWN)
    assert m["structure_score"] == 0.8  # costs, pricing, profit, marketing found; no launch steps
    assert m["budget_fit"] is None and m["price_above_cost"] is None and m["break_even_realistic"] is None
    assert m["issues_before_repair"] is None and m["final_passed"] is None
    assert m["guarantee_phrases"] == 1
    assert m["hallucinated_schemes"] == 1  # "Super Startup Scheme" is not in our documents; Mudra is
    assert m["language_match"] == 100.0


def test_v1_raw_text_launch_steps_and_hindi_keywords():
    hindi = "शुरुआती खर्च ₹5,000। दाम ₹150। मुनाफा ₹50। प्रचार व्हाट्सऐप पर। पहला कदम: FSSAI रजिस्ट्रेशन।"
    assert structure_score(make_plan(raw_text=hindi)) == 1.0


def test_readability_english_only():
    pytest.importorskip("textstat")
    score = readability("Start small. Sell to people you know. Keep notes of your sales.", "en")
    assert score is None or score > 60  # None if textstat's data files are missing
    assert readability("कुछ हिंदी", "hi") is None
