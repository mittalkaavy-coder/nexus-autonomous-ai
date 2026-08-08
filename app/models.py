"""
Pydantic models for NEXUS.

Minimal by design: one model per table row shape, plus the API wire shapes.
These are used for:
  - internal typing across the pipeline,
  - request/response validation in main.py (API contract models live here too).

No over-modelling — avoid adding fields until a phase actually needs them.
"""

from typing import Any, List, Optional
from pydantic import BaseModel


# ---------------------------------------------------------------------------
# posts table — internal row shape
# ---------------------------------------------------------------------------


class PostRecord(BaseModel):
    """Mirrors one row of the posts table. Used internally across the pipeline."""

    id: str
    agent_id: str
    topic: str
    summary: str
    created_at: str            # ISO 8601 UTC
    generated_text: Optional[str] = None
    sources: List[str] = []
    editorial_score: float
    decision: str              # 'PUBLISH' or 'REJECT'
    rationale: dict[str, Any] = {}


# ---------------------------------------------------------------------------
# topics_seen table — internal row shape
# ---------------------------------------------------------------------------


class TopicSeenRecord(BaseModel):
    """Mirrors one row of the topics_seen table. Used internally by memory/dedup."""

    id: str
    title: str
    summary: str
    source_url: str
    discovered_at: str         # ISO 8601 UTC
    similarity_ref: Optional[str] = None


# ---------------------------------------------------------------------------
# API wire shapes — used in main.py for request/response validation
# ---------------------------------------------------------------------------


class Persona(BaseModel):
    name: str
    domain: str


class AgentInitRequest(BaseModel):
    persona: Persona


class AgentInitResponse(BaseModel):
    agentId: str


class FeedPost(BaseModel):
    """One entry in the public feed — only PUBLISH decisions are returned."""

    id: str
    createdAt: str             # ISO 8601 UTC — matches PRD field name exactly
    text: str
    rationale: Any             # JSON object or string depending on the generator
    sources: List[str]


class FeedResponse(BaseModel):
    posts: List[FeedPost]
