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
from app.discovery import discover_topics
from app.models import (
    AgentInitRequest,
    AgentInitResponse,
    FeedPost,
    FeedResponse,
)
from app.scheduler import (
    get_scheduler_status,
    start_scheduler,
    stop_scheduler,
    trigger_cycle_now,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


# ---------------------------------------------------------------------------
# Lifespan — runs init_db() on startup and stops background scheduler on shutdown
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield
    stop_scheduler()


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
    existing agentId with 200. Starts the background autonomous scheduler
    on first call; ignores subsequent start attempts without double-scheduling.

    Malformed request bodies are rejected automatically by Pydantic with 422.
    """
    agent_id = agent_module.initialize_agent(body.persona.model_dump())
    start_scheduler(agent_id)
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


# ---------------------------------------------------------------------------
# POST /api/agent/trigger-cycle — DEBUG ONLY, for demo pacing and manual testing
# ---------------------------------------------------------------------------

@app.post(
    "/api/agent/trigger-cycle",
    tags=["debug"],
    summary="Trigger an immediate editorial cycle (Debug / Demo convenience)",
)
def agent_trigger_cycle(
    agentId: str = Query(default="nexus-001", description="Agent ID to run cycle for"),
    demo: bool = Query(default=False, description="If true, use demo fixtures instead of live RSS"),
):
    """
    Manually force an immediate editorial cycle right now for demo pacing.

    NOTE: This is purely a convenience mechanism for interactive hackathon
    demonstrations and testing; it is NOT part of the required public API contract.
    """
    summary = trigger_cycle_now(agent_id=agentId, use_demo_fixtures=demo)
    return {
        "status": "ok",
        "message": "Editorial cycle triggered and completed.",
        "summary": summary,
    }


# ---------------------------------------------------------------------------
# GET /api/agent/scheduler-status — DEBUG ONLY
# ---------------------------------------------------------------------------

@app.get(
    "/api/agent/scheduler-status",
    tags=["debug"],
    summary="Fetch autonomous scheduler telemetry and health status",
)
def agent_scheduler_status():
    """
    Return the current state of the autonomous background scheduler.
    """
    return get_scheduler_status()


# ---------------------------------------------------------------------------
# GET /debug/discover  — DEBUG ONLY, not part of the frozen API contract
# ---------------------------------------------------------------------------

@app.get(
    "/debug/discover",
    tags=["debug"],
    summary="Run one discovery cycle and return raw normalized candidates",
)
def debug_discover(
    demo: bool = Query(
        default=False,
        description="If true, return demo fixtures instead of hitting live feeds.",
    ),
):
    """
    Trigger one discovery cycle right now and return the raw candidate list.

    This endpoint exists to prove live sources work during development.
    It does NOT score, deduplicate, or persist anything.
    It is NOT part of the frozen public API and MUST NOT be called by
    autonomous pipeline logic.
    """
    candidates = discover_topics(use_demo_fixtures=demo)
    return {
        "source": "demo_fixtures" if demo else "live_rss",
        "count": len(candidates),
        "candidates": candidates,
    }

