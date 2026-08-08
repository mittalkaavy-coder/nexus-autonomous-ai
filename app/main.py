"""
NEXUS — Autonomous AI Technology Analyst
FastAPI application entrypoint.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from app.database import init_db
import app.agent as agent_module
from app.models import (
    AgentInitRequest,
    AgentInitResponse,
    FeedPost,
    FeedResponse,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


# ---------------------------------------------------------------------------
# Lifespan — runs init_db() once on startup before accepting requests
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


# ---------------------------------------------------------------------------
# App instance
# ---------------------------------------------------------------------------

app = FastAPI(
    title="NEXUS API",
    version="0.1.0",
    description="Autonomous AI Technology Analyst",
    lifespan=lifespan,
)

# Permissive CORS — hackathon demo, no auth required
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------

@app.get("/health", tags=["meta"])
def health_check():
    """Liveness probe — returns 200 when the server is up."""
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# POST /api/agent/init
# ---------------------------------------------------------------------------

@app.post(
    "/api/agent/init",
    response_model=AgentInitResponse,
    status_code=200,
    tags=["agent"],
    summary="Initialize the NEXUS agent",
)
def agent_init(body: AgentInitRequest):
    """
    Initialize NEXUS with a persona config and persist it to the database.

    Idempotent — if the agent has already been initialized, returns the
    existing agentId with 200. No duplicate rows, no double-scheduling.

    Malformed request bodies are rejected automatically by Pydantic with 422.
    """
    agent_id = agent_module.initialize_agent(body.persona.model_dump())
    return AgentInitResponse(agentId=agent_id)


# ---------------------------------------------------------------------------
# GET /api/agent/feed
# ---------------------------------------------------------------------------

@app.get(
    "/api/agent/feed",
    response_model=FeedResponse,
    status_code=200,
    tags=["agent"],
    summary="Fetch the agent's published post feed",
)
def agent_feed(
    agentId: str = Query(..., description="The agent ID returned by /api/agent/init"),
):
    """
    Return all PUBLISH-decision posts for the given agent, newest-first.

    - 404 if the agentId is unknown — do not silently return an empty feed.
    - 200 { "posts": [] } if the agent exists but has no published posts yet.
    - Rejected decisions are never included in the public feed.
    """
    agent = agent_module.get_agent(agentId)
    if agent is None:
        raise HTTPException(
            status_code=404,
            detail=f"Agent '{agentId}' not found. Initialize the agent first via POST /api/agent/init.",
        )

    raw_posts = agent_module.get_feed(agentId)
    posts = [FeedPost(**p) for p in raw_posts]
    return FeedResponse(posts=posts)
