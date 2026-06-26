"""Pydantic state definitions for LangGraph."""

from typing import Optional
from pydantic import BaseModel, Field


# ── Agent State (LangGraph) ─────────────────────────────────────────────

class AnalystState(BaseModel):
    """Shared state passed between graph nodes."""
    question: str = ""
    sql_query: Optional[str] = None
    query_result: Optional[str] = None
    rag_context: Optional[str] = None
    answer: Optional[str] = None
    error: Optional[str] = None
    iteration: int = Field(default=0, ge=0, le=5)


# ── Request / Response Schemas ──────────────────────────────────────────

class QueryRequest(BaseModel):
    question: str = Field(..., description="Natural‑language ops question")
    thread_id: Optional[str] = Field(None, description="Conversation thread ID")


class QueryResponse(BaseModel):
    answer: str
    sql_used: Optional[str] = None
    sources: Optional[list[str]] = None
