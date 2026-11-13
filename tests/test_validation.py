"""Phase 4 validation rules: each code is triggered by a crafted draft. Pure Python, offline."""
import copy

import pytest

from app.calculator import full_financials
from app.models import BusinessProfile
from app.plan_mock import VALID_PLAN
from app.plan_models import PlanDraft
from app.plan_validation import (
    auto_fix,
    find_banned_phrases,
    has_blocking,
    validate_plan,
)
from app.planner import financial_input
from app.rag import RetrievedChunk

FSSAI_URL = "https://fssai.gov.in/upload/uploadfiles/files/FAQs_Licensing_Registration_21_12_2022.pdf"
CHUNKS = [
    RetrievedChunk(text="FSSAI Registration ...", scheme="FSSAI Registration", category="license",
                   source_url=FSSAI_URL, score=0.6, chunk_id="fssai:c1"),
    RetrievedChunk(text="PM Mudra Yojana ...", scheme="PM Mudra Yojana", category="loan",
                   source_url="https://www.pib.gov.in/mudra", score=0.5, chunk_id="mudra:c1"),
]
PROFILE = BusinessProfile(business_idea="Healthy meal service", budget_inr=20000, location="Ghaziabad",
                          skills="Basic cooking", target_customers="Gym-goers")


def make_draft(**changes) -> PlanDraft:
    data = copy.deepcopy(VALID_PLAN)
    data["schemes"] = [{"scheme": "FSSAI Registration", "why_it_fits": "Needed to sell food.", "source_url": FSSAI_URL}]
    data.update(changes)
    return PlanDraft.model_validate(data)


def codes(draft: PlanDraft, budget: int = 20000, chunks=CHUNKS, financials="calc") -> list[str]:
    profile = PROFILE.model_copy(update={"budget_inr": budget})
    if financials == "calc":
        financials = full_financials(financial_input(draft, profile))
    return [i.code for i in validate_plan(draft, financials, chunks, budget)]


def test_clean_draft_passes_with_zero_issues():
    assert codes(make_draft()) == []


def test_budget_over():
    draft = make_draft(startup_costs=VALID_PLAN["startup_costs"] + [{"name": "Cart", "amount_inr": 30000, "kind": "one_time"}])
    issues = codes(draft)
    assert "BUDGET_OVER" in issues and "LOW_RESERVE" not in issues


def test_low_reserve():
    # 10,000 + 5,500 one-time + 3,000 first month = 18,500 -> only 1,500 (7.5%) left
    draft = make_draft(startup_costs=VALID_PLAN["startup_costs"] + [{"name": "Fridge", "amount_inr": 5500, "kind": "one_time"}])
    assert codes(draft) == ["LOW_RESERVE"]


def test_price_below_cost():
    assert "PRICE_BELOW_COST" in codes(make_draft(selling_price_inr=95))


def test_price_out_of_market():
    assert codes(make_draft(selling_price_inr=210)) == ["PRICE_OUT_OF_MARKET"]


def test_break_even_unrealistic():
    # break-even is 2 meals a day, but even a good day is only 1 meal
    assert "BREAK_EVEN_UNREALISTIC" in codes(make_draft(units_per_day_low=1, units_per_day_expected=1, units_per_day_high=1))


def test_hallucinated_scheme_name_and_url():
    fake = [{"scheme": "PM Free Money Yojana", "why_it_fits": "x", "source_url": "https://example.com"}]
    assert codes(make_draft(schemes=fake)) == ["HALLUCINATED_SCHEME"]
    wrong_url = [{"scheme": "FSSAI Registration", "why_it_fits": "x", "source_url": "https://fssai.example.com"}]
    assert codes(make_draft(schemes=wrong_url)) == ["HALLUCINATED_SCHEME"]


def test_any_scheme_is_hallucinated_without_retrieved_documents():
    assert codes(make_draft(), chunks=[]) == ["HALLUCINATED_SCHEME"]


@pytest.mark.parametrize("text", [
    "You will get guaranteed profit.", "This is risk-free.", "100% profit in a month",
    "Aapko pakka munafa hoga", "इसमें पक्का मुनाफा है", "You will definitely earn more",
])
def test_guarantee_language(text):
    assert codes(make_draft(risks=[text, "Prices can rise"])) == ["GUARANTEE_LANGUAGE"]


@pytest.mark.parametrize("text", [
    "Mudra gives loans bina guarantee ke", "Covered by the Credit Guarantee Fund", "बिना गारंटी लोन",
])
def test_allowed_guarantee_phrases(text):
    assert find_banned_phrases(text) == []
    assert codes(make_draft(assumptions=[text])) == []


def test_missing_section():
    assert codes(make_draft(marketing_ideas=[])) == ["MISSING_SECTION"]
    issues = codes(make_draft(launch_steps=[], assumptions=[]))
    assert issues.count("MISSING_SECTION") == 2 and "BAD_STEP_COUNT" not in issues


def test_bad_step_count():
    steps = VALID_PLAN["launch_steps"]
    assert codes(make_draft(launch_steps=steps[:3])) == ["BAD_STEP_COUNT"]
    assert codes(make_draft(launch_steps=steps + steps[:3])) == ["BAD_STEP_COUNT"]  # 9 steps


def test_invalid_numbers_when_calculator_fails():
    assert codes(make_draft(), financials=None) == ["INVALID_NUMBERS"]


def test_severity():
    draft = make_draft(selling_price_inr=210)
    issues = validate_plan(draft, full_financials(financial_input(draft, PROFILE)), CHUNKS, 20000)
    assert not has_blocking(issues)  # price outside market = warning only


def test_auto_fix_drops_fake_scheme_and_softens_words():
    fake = {"scheme": "PM Free Money Yojana", "why_it_fits": "x", "source_url": "https://example.com"}
    draft = make_draft(
        schemes=[{"scheme": "FSSAI Registration", "why_it_fits": "ok", "source_url": FSSAI_URL}, fake],
        business_summary="A tiffin service with guaranteed profit. Loans are given bina guarantee ke.",
    )
    fixed, fixes = auto_fix(draft, CHUNKS)
    assert [s.scheme for s in fixed.schemes] == ["FSSAI Registration"]
    assert "guaranteed" not in fixed.business_summary
    assert "bina guarantee" in fixed.business_summary  # allowed phrase untouched
    assert len(fixes) == 2
    assert codes(fixed) == []
