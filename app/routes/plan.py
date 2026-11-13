"""Phase 4 API: business plan generation.

POST /api/plan           {session_id, prompt_version?}         -> BusinessPlan (saved in the session)
(prompt_version defaults to DEFAULT_PLAN_VERSION = plan_v5)
GET  /api/plan/{id}                                            -> last plan of that session
POST /api/plan/preview   {profile, language?, prompt_version?} -> BusinessPlan without a session
POST /api/plan/compare   {profile, versions}                   -> one plan per prompt version
"""
import time
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.models import BusinessProfile, LanguageCode
from app.plan_models import BusinessPlan, PromptVersion
from app.planner import PlanLLMError, generate_plan
from app.llm import LLMConfigError
from app.session_store import get_session

router = APIRouter(prefix="/api/plan", tags=["plan"])

ALL_VERSIONS = ["plan_v1", "plan_v2", "plan_v3", "plan_v4", "plan_v5"]


# ---------- Request / response models ----------

class PlanRequest(BaseModel):
    session_id: str
    prompt_version: Optional[PromptVersion] = Field(None, description="Empty = DEFAULT_PLAN_VERSION (plan_v5)")


class PreviewRequest(BaseModel):
    profile: BusinessProfile
    language: Optional[LanguageCode] = None
    prompt_version: Optional[PromptVersion] = Field(None, description="Empty = DEFAULT_PLAN_VERSION (plan_v5)")


class CompareRequest(BaseModel):
    profile: BusinessProfile
    language: Optional[LanguageCode] = None
    versions: list[PromptVersion] = Field(default_factory=lambda: list(ALL_VERSIONS), min_length=1)


class CompareResult(BaseModel):
    prompt_version: str
    seconds: float
    passed: Optional[bool] = Field(None, description="Validation result (None for plan_v1, which is not validated)")
    issue_codes: list[str] = Field(default_factory=list)
    plan: BusinessPlan


class CompareResponse(BaseModel):
    results: list[CompareResult]


# ---------- Helpers ----------

def ensure_complete(profile: BusinessProfile) -> None:
    """409 Conflict: the intake chat has not collected everything yet."""
    if not profile.is_complete:
        raise HTTPException(
            status_code=409,
            detail={"message": "The business profile is incomplete. Finish the intake chat first.",
                    "missing_fields": profile.missing_fields()},
        )


def run_plan(**kwargs) -> BusinessPlan:
    """Same error pattern as earlier phases: config problem -> 500, LLM call failed -> 502."""
    try:
        return generate_plan(**kwargs)
    except LLMConfigError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except PlanLLMError as e:
        raise HTTPException(status_code=502, detail=f"LLM call failed ({e})")


# ---------- Endpoints ----------

@router.post("", response_model=BusinessPlan)
def create_plan(body: PlanRequest):
    """Generate the plan for a finished intake session and save it in the session."""
    session = get_session(body.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session '{body.session_id}' not found.")
    ensure_complete(session.profile)
    return run_plan(profile=session.profile, language=session.profile.language,
                    prompt_version=body.prompt_version, session_id=session.session_id)


@router.get("/{session_id}", response_model=BusinessPlan)
def read_plan(session_id: str):
    """The last plan generated for this session."""
    session = get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")
    if session.plan is None:
        raise HTTPException(status_code=404, detail="No plan generated for this session yet. POST /api/plan first.")
    return BusinessPlan.model_validate(session.plan)


@router.post("/preview", response_model=BusinessPlan)
def preview_plan(body: PreviewRequest):
    """Generate a plan from a profile directly (no session). Used by evaluation and demos."""
    ensure_complete(body.profile)
    return run_plan(profile=body.profile, language=body.language, prompt_version=body.prompt_version)


@router.post("/compare", response_model=CompareResponse)
def compare_plans(body: CompareRequest):
    """Same profile through several prompt versions, side by side (prompt-iteration demo)."""
    ensure_complete(body.profile)
    results = []
    for version in body.versions:
        start = time.perf_counter()
        plan = run_plan(profile=body.profile, language=body.language, prompt_version=version)
        results.append(CompareResult(
            prompt_version=version,
            seconds=round(time.perf_counter() - start, 2),
            passed=plan.validation.passed if plan.validation else None,
            issue_codes=[i.code for i in plan.validation.issues] if plan.validation else [],
            plan=plan,
        ))
    return {"results": results}
