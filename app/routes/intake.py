"""Phase 2 API: the intake chat.

POST  /api/session               start a chat in a language -> greeting + first question
POST  /api/chat                  send one message           -> reply + updated profile
GET   /api/session/{id}          full session (profile + messages)
PATCH /api/session/{id}/profile  edit profile fields directly (for the UI)
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.config import settings
from app.intake import IntakeLLMError, apply_patch, process_message, start_session
from app.llm import LLMConfigError
from app.models import BusinessProfile, LanguageCode, ProfilePatch
from app.session_store import Session, get_session, save_session

router = APIRouter(prefix="/api", tags=["intake"])


# ---------- Request / response models ----------

class NewSessionRequest(BaseModel):
    # Literal type -> FastAPI answers 422 automatically for an unsupported language.
    language: LanguageCode = Field("en", examples=["hi"])


class ChatRequest(BaseModel):
    session_id: str
    message: str = Field(..., min_length=1, max_length=2000, examples=["Main Lucknow mein achar bechna chahta hoon"])


class ChatResponse(BaseModel):
    reply: str
    profile: BusinessProfile
    missing_fields: list[str]
    is_complete: bool


class NewSessionResponse(ChatResponse):
    session_id: str


# ---------- Helpers ----------

def load_or_404(session_id: str) -> Session:
    session = get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")
    return session


def llm_errors_to_http(func, *args):
    """Same error pattern as Phase 1: config problem -> 500, LLM call failed -> 502."""
    try:
        return func(*args)
    except LLMConfigError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except IntakeLLMError as e:
        raise HTTPException(
            status_code=502,
            detail=f"LLM call failed ({settings.LLM_PROVIDER}/{settings.model_name}): {e}",
        )


def chat_response(session: Session, reply: str) -> dict:
    return {
        "reply": reply,
        "profile": session.profile,
        "missing_fields": session.profile.missing_fields(),
        "is_complete": session.profile.is_complete,
    }


# ---------- Endpoints ----------

@router.post("/session", response_model=NewSessionResponse)
def new_session(body: NewSessionRequest):
    """Start an intake chat. The reply is a greeting + the first question."""
    session, reply = llm_errors_to_http(start_session, body.language)
    return {"session_id": session.session_id, **chat_response(session, reply)}


@router.post("/chat", response_model=ChatResponse)
def chat(body: ChatRequest):
    """Send one user message; get the next question (or the summary when complete)."""
    session = load_or_404(body.session_id)
    reply = llm_errors_to_http(process_message, session, body.message)
    save_session(session)  # only saved if the turn succeeded
    return chat_response(session, reply)


@router.get("/session/{session_id}", response_model=Session)
def read_session(session_id: str):
    """Full session: profile + every message (personal numbers already masked)."""
    return load_or_404(session_id)


@router.patch("/session/{session_id}/profile", response_model=ChatResponse)
def edit_profile(session_id: str, body: ProfilePatch):
    """Edit fields directly, e.g. {"budget_inr": "1.5 lakh"}. null or "" clears a field."""
    session = load_or_404(session_id)
    try:
        apply_patch(session.profile, body.model_dump(exclude_unset=True))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    save_session(session)
    return chat_response(session, reply="Profile updated.")
