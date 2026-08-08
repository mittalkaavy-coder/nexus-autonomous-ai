"""
NEXUS — Autonomous AI Technology Analyst
FastAPI application entrypoint.
"""

from fastapi import FastAPI

app = FastAPI(title="NEXUS", description="Autonomous AI Technology Analyst")


@app.get("/")
def root():
    return {"message": "Hello from NEXUS"}
