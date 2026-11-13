"""Phase 6: "pivot" mode - the plan is written in English, then its text is translated.

Why: smaller open models write better plans in English than in Tamil or Gujarati.
Safety: after translation, restore_fixed_fields() copies every number, "kind", scheme name and
URL back from the English draft, so the translator can never change the money or the links.
check_number_mismatch() then compares the ₹ amounts written inside the text.
"""
import json

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate

from app.language import plan_texts, rupee_numbers
from app.llm import load_prompt
from app.models import LANGUAGES
from app.plan_models import PlanDraft
from app.structured import invoke_structured

TRANSLATE_PROMPT = "translate_v1"


def restore_fixed_fields(translated: PlanDraft, english: PlanDraft) -> PlanDraft:
    """Take the TEXT from the translation and EVERYTHING ELSE from the English draft.
    If a list has a different length after translation, the English list is kept."""
    data = translated.model_dump()
    src = english.model_dump()
    for key, value in src.items():
        if isinstance(value, (int, float)):
            data[key] = value  # unit cost, price, market range, sales per day

    def merge(items, originals, text_keys):
        if len(items) != len(originals):
            return originals
        return [{**orig, **{k: item[k] for k in text_keys}} for item, orig in zip(items, originals)]

    data["startup_costs"] = merge(data["startup_costs"], src["startup_costs"], ["name"])
    data["fixed_monthly_costs"] = merge(data["fixed_monthly_costs"], src["fixed_monthly_costs"], ["name"])
    data["launch_steps"] = merge(data["launch_steps"], src["launch_steps"], ["title", "detail"])
    data["schemes"] = merge(data["schemes"], src["schemes"], ["why_it_fits"])  # name + URL stay
    for key in ("marketing_ideas", "assumptions", "risks"):
        if len(data[key]) != len(src[key]):
            data[key] = src[key]
    return PlanDraft.model_validate(data)


def translate_draft(llm: BaseChatModel, english: PlanDraft, language: str) -> PlanDraft:
    """Translate the text fields of an English PlanDraft into `language` with the LLM."""
    prompt = ChatPromptTemplate.from_messages([("human", load_prompt(TRANSLATE_PROMPT))])
    messages = prompt.format_messages(
        language_name=LANGUAGES.get(language, language),
        plan_json=json.dumps(english.model_dump(), ensure_ascii=False, indent=1),
    )
    translated = invoke_structured(llm, messages, PlanDraft)
    return restore_fixed_fields(translated, english)


def check_number_mismatch(translated: PlanDraft, english: PlanDraft) -> tuple[bool, str]:
    """(True, explanation) if the ₹ amounts written in the text differ after translation."""
    before = sum((rupee_numbers(t) for t in plan_texts(english)), start=rupee_numbers(""))
    after = sum((rupee_numbers(t) for t in plan_texts(translated)), start=rupee_numbers(""))
    if before == after:
        return False, ""
    missing = sorted((before - after).elements())
    extra = sorted((after - before).elements())
    return True, f"Rupee amounts changed in translation (missing: {missing or 'none'}, new: {extra or 'none'})."
