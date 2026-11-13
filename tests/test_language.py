"""Phase 6: script detection, WRONG_LANGUAGE -> pivot retry, NUMBER_MISMATCH, safe translation."""
import json

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel

from app import planner
from app.config import settings
from app.language import detect_script, is_wrong_language, rupee_numbers, script_ratio
from app.models import BusinessProfile
from app.plan_mock import VALID_PLAN
from app.plan_models import PlanDraft
from app.translation import check_number_mismatch, restore_fixed_fields, translate_draft

SAMPLES = {
    "en": ("Start a small tiffin service near the gym", "latin"),
    "hi": ("जिम के पास छोटी टिफिन सेवा शुरू करें", "devanagari"),
    "mr": ("जिमजवळ छोटी टिफिन सेवा सुरू करा", "devanagari"),
    "bn": ("জিমের কাছে ছোট টিফিন পরিষেবা শুরু করুন", "bengali"),
    "ta": ("ஜிம் அருகே சிறிய டிஃபின் சேவையைத் தொடங்குங்கள்", "tamil"),
    "te": ("జిమ్ దగ్గర చిన్న టిఫిన్ సేవ ప్రారంభించండి", "telugu"),
    "gu": ("જીમ પાસે નાની ટિફિન સેવા શરૂ કરો", "gujarati"),
}


@pytest.mark.parametrize("lang", list(SAMPLES))
def test_script_detection_all_languages(lang):
    text, script = SAMPLES[lang]
    assert detect_script(text) == script
    assert script_ratio(text, lang) == 1.0
    assert is_wrong_language([text], lang) == (False, 1.0)
    other = "ta" if lang != "ta" else "hi"
    assert is_wrong_language([text], other)[0] is True


def test_mixed_text():
    # Acronyms (FSSAI, UPI) and links are ignored; common English words still count.
    mixed = "FSSAI रजिस्ट्रेशन के लिए FoSCoS पर आवेदन करें, UPI से पैसे लें https://foscos.fssai.gov.in"
    assert script_ratio(mixed, "hi") > 0.8
    half = "Take orders on WhatsApp ऑर्डर लें"
    assert 0.2 < script_ratio(half, "hi") < 0.6
    assert is_wrong_language([half], "hi")[0] is True
    assert script_ratio("₹ 3,500 - 42%", "hi") is None  # no letters at all
    assert is_wrong_language(["12345"], "ta") == (False, None)


def test_rupee_numbers_with_native_digits():
    assert rupee_numbers("₹3,500 और रु ५०० ভাড়া ₹৫০, Rs. 1,50,000") == {3500: 1, 500: 1, 50: 1, 150000: 1}


# ---------- Translation keeps numbers and URLs ----------

def tamil(text: str) -> str:
    """Fake Tamil translation that keeps the rupee amounts of the text (as ₹ digits)."""
    amounts = " ".join(f"₹{n}" for n in rupee_numbers(text).elements())
    return f"தமிழில் எழுதிய உரை {amounts}".strip()


def fake_translation(english: PlanDraft, break_numbers=False) -> dict:
    data = english.model_dump()
    data["business_summary"] = tamil(data["business_summary"])
    data["unit_name"] = "சாப்பாடு"
    for c in data["startup_costs"] + data["fixed_monthly_costs"]:
        c["name"] = tamil(c["name"])
        c["amount_inr"] += 999 if break_numbers else 0  # a bad translator changing amounts
    for key in ("marketing_ideas", "assumptions", "risks"):
        data[key] = [tamil(t) for t in data[key]]
    for step in data["launch_steps"]:
        step["title"], step["detail"] = tamil(step["title"]), tamil(step["detail"])
    for s in data["schemes"]:
        s["why_it_fits"] = tamil(s["why_it_fits"])
        if break_numbers:
            s["source_url"] = "https://wrong.example.com"
            s["scheme"] = "தவறான பெயர்"
    if break_numbers:
        data["selling_price_inr"] = 1
    return data


ENGLISH = PlanDraft.model_validate({**VALID_PLAN, "schemes": [
    {"scheme": "FSSAI Registration", "why_it_fits": "Needed before selling food.", "source_url": "https://fssai.gov.in/x.pdf"}]})


def test_translation_keeps_urls_numbers_and_names():
    llm = FakeListChatModel(responses=[json.dumps(fake_translation(ENGLISH, break_numbers=True), ensure_ascii=False)])
    translated = translate_draft(llm, ENGLISH, "ta")
    assert translated.selling_price_inr == 170
    assert [c.amount_inr for c in translated.startup_costs] == [c.amount_inr for c in ENGLISH.startup_costs]
    assert translated.schemes[0].source_url == "https://fssai.gov.in/x.pdf"
    assert translated.schemes[0].scheme == "FSSAI Registration"
    assert translated.business_summary.startswith("தமிழில்")
    assert check_number_mismatch(translated, ENGLISH) == (False, "")  # ₹100 in assumptions kept
    assert is_wrong_language([translated.business_summary], "ta")[0] is False


def test_number_mismatch_detected():
    data = fake_translation(ENGLISH)
    data["assumptions"][0] = "ஒரு சாப்பாட்டின் செலவு ₹150"  # was ₹100 in English
    translated = restore_fixed_fields(PlanDraft.model_validate(data), ENGLISH)
    mismatch, message = check_number_mismatch(translated, ENGLISH)
    assert mismatch is True and "100" in message and "150" in message


# ---------- Planner: WRONG_LANGUAGE -> one pivot retry ----------

PROFILE = BusinessProfile(language="ta", business_idea="Healthy meal service", budget_inr=20000,
                          location="Chennai", skills="Cooking", target_customers="Gym-goers")


def use_fake_llm(monkeypatch, responses):
    llm = FakeListChatModel(responses=responses)
    monkeypatch.setattr(planner, "is_mock", lambda: False)
    monkeypatch.setattr(planner, "get_plan_llm", lambda: llm)


def test_wrong_language_triggers_pivot_retry(no_scheme_index, monkeypatch):
    monkeypatch.setattr(settings, "TRANSLATE_MODE", "direct")
    english = json.dumps(dict(VALID_PLAN, schemes=[]))
    tamil_json = json.dumps(fake_translation(PlanDraft.model_validate(dict(VALID_PLAN, schemes=[]))), ensure_ascii=False)
    # 1) direct draft comes back in English  2) English draft (pivot)  3) Tamil translation
    use_fake_llm(monkeypatch, [english, english, tamil_json])

    plan = planner.generate_plan(PROFILE)
    assert plan.translate_mode == "pivot"
    assert plan.validation.passed is True
    assert plan.script_match > 0.9
    assert "switch_to_pivot" in plan.timings and "translate" in plan.timings
    assert any("rewritten in English and translated" in w for w in plan.warnings)
    assert plan.financials.unit.selling_price == 170


def test_pivot_is_default_for_tamil_and_direct_for_hindi():
    assert settings.translate_mode("ta") == "pivot" and settings.translate_mode("gu") == "pivot"
    assert settings.translate_mode("hi") == "direct" and settings.translate_mode("en") == "direct"


def test_mock_hindi_plan_is_in_hindi(no_scheme_index):
    plan = planner.generate_plan(PROFILE.model_copy(update={"language": "hi"}))
    assert plan.validation.passed is True and plan.script_match > 0.9
    assert plan.draft.unit_name == "थाली"


def test_mock_tamil_plan_is_flagged_not_hidden(no_scheme_index):
    # Mock mode cannot translate: the English text must be reported as WRONG_LANGUAGE.
    plan = planner.generate_plan(PROFILE)
    assert plan.validation.passed is False
    assert [i.code for i in plan.validation.issues] == ["WRONG_LANGUAGE"]
