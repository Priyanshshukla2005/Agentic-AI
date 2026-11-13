"""Phase 3 API: scheme search (RAG) and the money calculator.

POST /api/rag/search       {query, k?, category?} -> chunks with sources
POST /api/rag/for-session  {session_id}           -> schemes for that session's profile
GET  /api/rag/sources                             -> schemes + source URLs in the index
POST /api/calculate        FinancialInput         -> FinancialSummary
"""
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app import rag
from app.calculator import FinancialInput, FinancialSummary, full_financials
from app.rag import IndexNotBuiltError, RetrievedChunk
from app.session_store import get_session

router = APIRouter(prefix="/api", tags=["tools"])

Category = Literal["loan", "subsidy", "registration", "license", "tax"]


# ---------- Request / response models ----------

class SearchRequest(BaseModel):
    query: str = Field(..., examples=["Thele par sabzi bechta hoon, loan milega?"])
    k: int = Field(4, ge=1, le=20)
    category: Optional[Category] = None


class SessionSearchRequest(BaseModel):
    session_id: str


class SearchResponse(BaseModel):
    chunks: list[RetrievedChunk]
    context: str = Field(..., description="Ready-to-use numbered context block for an LLM prompt")


class SessionSearchResponse(SearchResponse):
    queries: list[str]


# ---------- Helpers ----------

def rag_call(func, *args, **kwargs):
    """Index not built -> 503 (server not ready), bad input -> 400."""
    try:
        return func(*args, **kwargs)
    except IndexNotBuiltError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---------- Endpoints ----------

@router.post("/rag/search", response_model=SearchResponse)
def rag_search(body: SearchRequest):
    """Search the official scheme documents. Works with English, Hindi and Hinglish questions."""
    chunks = rag_call(rag.retrieve, body.query, k=body.k, category=body.category)
    return {"chunks": chunks, "context": rag.format_context(chunks)}


@router.post("/rag/for-session", response_model=SessionSearchResponse)
def rag_for_session(body: SessionSearchRequest):
    """Schemes, loans and licences that fit the profile collected in an intake chat."""
    session = get_session(body.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session '{body.session_id}' not found.")
    if not session.profile.business_idea:
        raise HTTPException(status_code=400, detail="The profile has no business idea yet. Finish the intake chat first.")
    chunks = rag_call(rag.retrieve_for_profile, session.profile)
    return {
        "chunks": chunks,
        "context": rag.format_context(chunks),
        "queries": rag.build_query_from_profile(session.profile),
    }


@router.get("/rag/sources")
def rag_sources():
    """Every scheme in the index with its category and official source URL."""
    return {"sources": rag_call(rag.list_sources)}


@router.post("/calculate", response_model=FinancialSummary)
def calculate(body: FinancialInput):
    """Budget, price, profit, break-even, scenarios, payback and GST/FSSAI flags. No LLM involved."""
    try:
        return full_financials(body)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
