"""Phase 7: LLM-as-judge. Scores a plan 1-5 on five criteria with a one-line reason each.

* Blind: the judge sees only the profile and the plan text, never the prompt version.
* Temperature 0 and JSON output through invoke_structured (json_schema -> function calling -> raw).
* JUDGE_MODEL in .env picks the model.
Limitation: an LLM judge can be biased (for example towards longer answers or its own style), so we
also run a blind human review (app/evaluation/human.py).

Mock mode: a deterministic stand-in judge derived from the automatic metrics, so the pipeline can be
checked offline. Its numbers are NOT real results.
"""
import hashlib
import json

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from app.config import settings
from app.evaluation.render import plan_to_text
from app.llm import get_judge_llm, load_prompt
from app.models import BusinessProfile
from app.plan_models import BusinessPlan
from app.structured import invoke_structured

JUDGE_PROMPT = "eval_judge_v1"
CRITERIA = ["personalisation", "practicality", "simplicity", "grounding", "completeness"]


class Criterion(BaseModel):
    score: int = Field(..., ge=1, le=5)
    reason: str


class JudgeScores(BaseModel):
    personalisation: Criterion
    practicality: Criterion
    simplicity: Criterion
    grounding: Criterion
    completeness: Criterion

    def average(self) -> float:
        return round(sum(getattr(self, c).score for c in CRITERIA) / len(CRITERIA), 2)

    def flat(self) -> dict:
        """{"judge_personalisation": 4, ..., "judge_avg": 3.8}"""
        data = {f"judge_{c}": getattr(self, c).score for c in CRITERIA}
        data["judge_avg"] = self.average()
        return data


def judge_plan(profile: BusinessProfile, plan: BusinessPlan, metrics: dict) -> JudgeScores:
    if settings.LLM_PROVIDER == "mock":
        return mock_judge(profile, plan, metrics)
    prompt = ChatPromptTemplate.from_messages([("human", load_prompt(JUDGE_PROMPT))])
    messages = prompt.format_messages(
        profile_json=json.dumps(profile.model_dump(exclude={"language"}), ensure_ascii=False, indent=1),
        plan_text=plan_to_text(plan),
    )
    return invoke_structured(get_judge_llm(), messages, JudgeScores)


def mock_judge(profile: BusinessProfile, plan: BusinessPlan, metrics: dict) -> JudgeScores:
    """Offline stand-in: scores follow the automatic metrics (+ a small fixed wobble per plan)."""
    wobble = int(hashlib.md5((profile.model_dump_json() + str(plan.prompt_version)).encode()).hexdigest(), 16) % 2

    def clamp(x: float) -> int:
        return max(1, min(5, round(x)))

    structured = plan.draft is not None
    passed = bool(metrics.get("final_passed"))
    base = 2 + (1 if structured else 0) + (1 if passed else 0)
    reason = "Mock judge (offline): derived from the automatic metrics, not a real assessment."
    return JudgeScores(
        personalisation=Criterion(score=clamp(base + wobble - (0 if structured else 1)), reason=reason),
        practicality=Criterion(score=clamp(base + (1 if metrics.get("budget_fit") else -1)), reason=reason),
        simplicity=Criterion(score=clamp(base + wobble), reason=reason),
        grounding=Criterion(score=clamp(5 - metrics.get("hallucinated_schemes", 0) - metrics.get("guarantee_phrases", 0)
                                        - (0 if structured else 1)), reason=reason),
        completeness=Criterion(score=clamp(1 + 4 * metrics.get("structure_score", 0)), reason=reason),
    )
