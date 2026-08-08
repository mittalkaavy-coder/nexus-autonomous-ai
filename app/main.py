"""
NEXUS — Autonomous AI Technology Analyst
FastAPI application entrypoint.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.database import init_db
import app.agent as agent_module

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
# Request / Response models
# ---------------------------------------------------------------------------

class Persona(BaseModel):
    name: str
    domain: str


class AgentInitRequest(BaseModel):
    persona: Persona


class AgentInitResponse(BaseModel):
    agentId: str


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
