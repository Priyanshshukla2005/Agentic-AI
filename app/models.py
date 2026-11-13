"""Data models for Phase 2 (intake chat).

BusinessProfile = everything we know about the user's business so far.
ProfileUpdate   = what the LLM (or the rule-based fallback) pulled out of ONE user message.

Which fields are "missing" is decided here, in plain Python - never by the LLM -
so the order of questions is predictable and easy to test.
"""
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

# Supported languages: code -> name we put into prompts ("reply ONLY in ...").
LANGUAGES: dict[str, str] = {
    "en": "English",
    "hi": "Hindi (हिन्दी)",
    "bn": "Bengali (বাংলা)",
    "mr": "Marathi (मराठी)",
    "ta": "Tamil (தமிழ்)",
    "te": "Telugu (తెలుగు)",
    "gu": "Gujarati (ગુજરાતી)",
}
LanguageCode = Literal["en", "hi", "bn", "mr", "ta", "te", "gu"]

# The agent asks for these, in THIS order. All five are needed before we can make a plan.
REQUIRED_FIELDS: list[str] = [
    "business_idea",
    "budget_inr",
    "location",
    "skills",
    "target_customers",
]
# Nice to have. Saved if the user mentions them, but never asked for.
OPTIONAL_FIELDS: list[str] = ["time_available", "sales_channel", "experience", "extra_notes"]
PROFILE_FIELDS: list[str] = REQUIRED_FIELDS + OPTIONAL_FIELDS


class BusinessProfile(BaseModel):
    language: LanguageCode = "en"

    # Required for completion
    business_idea: Optional[str] = None
    budget_inr: Optional[int] = Field(None, gt=0, description="Budget in rupees")
    location: Optional[str] = None
    skills: Optional[str] = None
    target_customers: Optional[str] = None

    # Optional extras
    time_available: Optional[str] = None
    sales_channel: Optional[str] = None
    experience: Optional[str] = None
    extra_notes: Optional[str] = None

    def missing_fields(self) -> list[str]:
        """Required fields that are still empty, in the order we ask for them."""
        return [f for f in REQUIRED_FIELDS if getattr(self, f) in (None, "")]

    @property
    def is_complete(self) -> bool:
        return not self.missing_fields()


class ProfileUpdate(BaseModel):
    """Details found in one user message. Everything is optional: null = "not mentioned".

    budget_inr is kept as TEXT on purpose (e.g. "1.5 lakh", "bees hazaar"):
    the LLM copies what the user said and our own code (parse_budget_inr) turns it
    into a number. LLMs are not reliable at "1.5 lakh = 150000" style maths.
    """

    business_idea: Optional[str] = Field(None, description="What the user wants to sell or do")
    budget_inr: Optional[str] = Field(
        None, description="Money the user can invest, exactly as they said it, e.g. '20k', '1.5 lakh'"
    )
    location: Optional[str] = Field(None, description="City, town or village where the business will run")
    skills: Optional[str] = Field(None, description="What the user is good at / knows how to do")
    target_customers: Optional[str] = Field(None, description="Who will buy from them")
    time_available: Optional[str] = Field(None, description="Hours or days the user can give")
    sales_channel: Optional[str] = Field(None, description="How they will sell: stall, home delivery, online...")
    experience: Optional[str] = Field(None, description="Past work or business experience")
    extra_notes: Optional[str] = Field(None, description="Any other useful detail")
    user_question: Optional[str] = Field(
        None, description="If the user asked a general question instead of answering, copy it here"
    )

    @field_validator("*", mode="before")
    @classmethod
    def numbers_to_text(cls, value):
        # LLMs sometimes return budget as 20000 instead of "20000". Accept both.
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return str(value)
        return value


class ProfilePatch(BaseModel):
    """Body of PATCH /api/session/{id}/profile: send only the fields you want to change.
    null or "" clears a field. budget_inr may be a number (20000) or text ("1.5 lakh")."""

    model_config = {"extra": "forbid"}  # a typo like "budjet" gives a clear 422 error

    language: Optional[LanguageCode] = None
    business_idea: Optional[str] = None
    budget_inr: Optional[int | str] = None
    location: Optional[str] = None
    skills: Optional[str] = None
    target_customers: Optional[str] = None
    time_available: Optional[str] = None
    sales_channel: Optional[str] = None
    experience: Optional[str] = None
    extra_notes: Optional[str] = None
