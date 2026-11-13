"""Phase 6 API: "Ask a question" (Q&A agent with memory) and the "Your next step" card.

POST /api/ask                    {session_id, question} -> {answer, sources, used_tools, next_step_hint, checks}
GET  /api/ask/{session_id}/history                      -> the whole Q&A thread
GET  /api/guide/{session_id}                            -> next step + tip + progress line
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app import advisor
from app.advisor import AdvisorLLMError, AskResult, GuideCard, QAMessage
from app.llm import LLMConfigError
from app.session_store import Session, get_session

router = APIRouter(prefix="/api", tags=["advisor"])


class AskRequest(BaseModel):
    session_id: str
    question: str = Field(..., min_length=1, max_length=1000, examples=["What if I sell at ₹150?"])


class HistoryResponse(BaseModel):
    messages: list[QAMessage]


def load_or_404(session_id: str) -> Session:
    session = get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")
    return session


@router.post("/ask", response_model=AskResult)
def ask(body: AskRequest):
    """Answer a question about the user's business, in their language."""
    session = load_or_404(body.session_id)
    if not body.question.strip():
        raise HTTPException(status_code=400, detail="Question must not be empty.")
    try:
        return advisor.ask(session, body.question)
    except LLMConfigError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except AdvisorLLMError as e:
        raise HTTPException(status_code=502, detail=f"LLM call failed ({e})")


@router.get("/ask/{session_id}/history", response_model=HistoryResponse)
def ask_history(session_id: str):
    load_or_404(session_id)
    return {"messages": advisor.history(session_id)}


@router.get("/guide/{session_id}", response_model=GuideCard)
def guide(session_id: str):
    """The "Your next step" card shown at the top of the plan."""
    return advisor.guide(load_or_404(session_id))
