"""
NEXUS — Autonomous AI Technology Analyst
FastAPI application entrypoint.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title="NEXUS API",
    version="0.1.0",
    description="Autonomous AI Technology Analyst",
)

# Permissive CORS — hackathon demo, no auth required
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["meta"])
def health_check():
    """Liveness probe — returns 200 when the server is up."""
    return {"status": "ok"}
