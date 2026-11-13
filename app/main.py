"""FastAPI backend - Phase 1.

Run:  uvicorn app.main:app --reload
Docs: http://127.0.0.1:8000/docs   (try the endpoints from your browser)
"""
import time

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.config import settings
from app.llm import LLMConfigError, get_llm, load_prompt

app = FastAPI(
    title="AI Business Starter Agent",
    description="Agentic AI that helps aspiring entrepreneurs plan and launch a small business.",
    version="0.1.0",
)

# Allow the frontend (Phase 5) to call this API from the browser.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- Request / response models ----------

class BusinessInput(BaseModel):
    business_idea: str = Field(..., examples=["Healthy meal service for fitness enthusiasts"])
    budget: str = Field(..., examples=["Rs 20,000"])
    location: str = Field(..., examples=["Ghaziabad"])
    skills: str = Field(..., examples=["Basic cooking"])
    target_customers: str = Field(
        ..., examples=["Gym-goers and fitness enthusiasts seeking high-protein meals and diet plans"]
    )
    prompt_version: str = Field("baseline_v1", description="File name in app/prompts/ (without .txt)")


class LLMResponse(BaseModel):
    output: str
    provider: str
    model: str
    prompt_version: str
    latency_seconds: float


# ---------- Helpers ----------

def format_user_input(data: BusinessInput) -> str:
    return (
        f"Business idea: {data.business_idea}\n"
        f"Budget: {data.budget}\n"
        f"Location: {data.location}\n"
        f"Skills: {data.skills}\n"
        f"Target customers: {data.target_customers}"
    )


def run_llm(system_prompt: str, user_message: str) -> str:
    try:
        llm = get_llm()
        result = llm.invoke([SystemMessage(content=system_prompt), HumanMessage(content=user_message)])
    except LLMConfigError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:  # network errors, bad model name, Ollama not running, rate limits...
        raise HTTPException(
            status_code=502,
            detail=f"LLM call failed ({settings.LLM_PROVIDER}/{settings.model_name}): {e}",
        )
    return result.content if isinstance(result.content, str) else str(result.content)


# ---------- Endpoints ----------

@app.get("/health")
def health():
    """Quick check that the server is running and which LLM it is configured for."""
    return {"status": "ok", "provider": settings.LLM_PROVIDER, "model": settings.model_name}


@app.post("/api/test-prompt", response_model=LLMResponse)
def test_prompt(data: BusinessInput):
    """Phase 1 test: send a business profile through a prompt and return the LLM's plan."""
    try:
        system_prompt = load_prompt(data.prompt_version)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    start = time.perf_counter()
    output = run_llm(system_prompt, format_user_input(data))
    return LLMResponse(
        output=output,
        provider=settings.LLM_PROVIDER,
        model=settings.model_name,
        prompt_version=data.prompt_version,
        latency_seconds=round(time.perf_counter() - start, 2),
    )
