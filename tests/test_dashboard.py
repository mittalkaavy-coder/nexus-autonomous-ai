"""
Unit and Integration Tests for NEXUS Demo Dashboard (Equal-Weight Published/Rejected Views).
"""

import os
import sys
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.config import settings
from app.database import init_db
from app.main import app
from app.persona import PERSONA
from app.scheduler import stop_scheduler


@pytest.fixture(autouse=True)
def setup_test_db(tmp_path):
    """Provide an isolated database and clean scheduler environment for each test."""
    db_file = str(tmp_path / "test_dashboard.db")
    os.environ["DATABASE_PATH"] = db_file
    settings.DATABASE_PATH = db_file
    init_db()
    stop_scheduler()
    yield
    stop_scheduler()


@pytest.fixture
def client():
    """FastAPI TestClient fixture."""
    return TestClient(app)


def test_dashboard_root_html_endpoint(client):
    """GET / returns 200 OK with HTML content containing core layout elements."""
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    html = response.text

    # Verify key dashboard brand and layout elements
    assert "NEXUS" in html
    assert "Autonomous AI Technology Analyst" in html
    assert "PUBLISHED TECHNICAL POSTS" in html
    assert "REJECTED CANDIDATES & REASONS" in html
    assert "Trigger Cycle" in html
    assert "Hard Evidence Floor" in html
    assert "Equal Visual Weight" in html


def test_dashboard_alias_endpoint(client):
    """GET /dashboard also serves the dashboard page."""
    response = client.get("/dashboard")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "REJECTED CANDIDATES & REASONS" in response.text


def test_dashboard_data_endpoint_structure(client):
    """GET /api/agent/dashboard-data returns structured JSON with all required fields."""
    init_res = client.post(
        "/api/agent/init",
        json={
            "persona": {
                "name": PERSONA.name,
                "domain": "AI Agent Infrastructure",
            }
        },
    )
    assert init_res.status_code == 200

    response = client.get("/api/agent/dashboard-data?agentId=nexus-001")
    assert response.status_code == 200
    data = response.json()

    assert data["agent_id"] == "nexus-001"
    assert "scheduler" in data
    assert "persona" in data
    assert "published_posts" in data
    assert "rejected_posts" in data
    assert "seen_topics" in data

    # Check persona details
    assert data["persona"]["name"] == PERSONA.name
    assert "standing_opinions" in data["persona"]
    assert "hard_rules" in data["persona"]

    # Check unknown agent returns 404
    unknown_res = client.get("/api/agent/dashboard-data?agentId=unknown-agent-999")
    assert unknown_res.status_code == 404


def test_dashboard_data_after_cycle(client):
    """Triggering a cycle populates both published and rejected items in dashboard data."""
    # 1. Initialize agent
    init_res = client.post(
        "/api/agent/init",
        json={
            "persona": {
                "name": PERSONA.name,
                "domain": "AI Agent Infrastructure",
            }
        },
    )
    assert init_res.status_code == 200
    agent_id = init_res.json()["agentId"]

    # 2. Trigger demo cycle
    trig_res = client.post(f"/api/agent/trigger-cycle?agentId={agent_id}&demo=true")
    assert trig_res.status_code == 200

    # 3. Query dashboard data
    dash_res = client.get(f"/api/agent/dashboard-data?agentId={agent_id}")
    assert dash_res.status_code == 200
    dash_data = dash_res.json()

    # Verify both published and rejected posts exist
    published = dash_data["published_posts"]
    rejected = dash_data["rejected_posts"]
    seen = dash_data["seen_topics"]

    assert len(published) > 0, "Expected at least one published post from demo fixtures"
    assert len(rejected) > 0, "Expected at least one rejected candidate from demo fixtures"
    assert len(seen) > 0, "Expected seen topics to be populated"

    # Check that published posts have scores and generated text
    first_pub = published[0]
    assert first_pub["decision"] == "PUBLISH"
    assert first_pub["editorial_score"] >= 70.0
    assert first_pub["generated_text"] is not None

    # Check that rejected posts have rejection rationale and structured reason
    first_rej = rejected[0]
    assert first_rej["decision"] == "REJECT"
    assert "rationale" in first_rej
    rat = first_rej["rationale"]
    assert "rejection_reason" in rat or "reason" in rat or first_rej["summary"] is not None
