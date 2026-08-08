"""
Failure-Case & Resilience Test Suite for NEXUS (PRD Section 17).

Tests:
1. No topics available (mock discovery returning []) -> pipeline completes cleanly with 0 items.
2. Unreachable discovery feed / network error -> discovery catches exception gracefully, returns valid subset.
3. LLM API failure during scoring -> topic marked skipped/unscoreable, pipeline does not crash.
4. LLM API failure during generation -> topic marked skipped, pipeline does not crash.
5. Invalid / malformed POST /api/agent/init request bodies -> HTTP 422.
6. Missing required query parameter on GET /api/agent/feed -> HTTP 422.
7. Hard evidence-floor (< 40) rejection edge case -> forced REJECT with distinct floor rationale.
8. Database graceful handling on malformed JSON data.
"""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.database import get_connection, get_posts_by_agent, init_db, insert_post
from app.discovery import _fetch_feed, discover_topics
from app.editor import ScoreResult, score_topic
from app.generator import GeneratedPost, generate_post
from app.main import app
from app.persona import PERSONA
from app.pipeline import run_pipeline_cycle
from app.scheduler import stop_scheduler


@pytest.fixture(autouse=True)
def setup_test_db(tmp_path):
    """Provide an isolated database and clean scheduler environment for each test."""
    db_file = str(tmp_path / "test_failures.db")
    os.environ["DATABASE_PATH"] = db_file
    from app.config import settings
    settings.DATABASE_PATH = db_file
    init_db()
    stop_scheduler()
    yield
    stop_scheduler()


@pytest.fixture
def client():
    """FastAPI TestClient fixture."""
    return TestClient(app)


# ---------------------------------------------------------------------------
# 1. No Topics Available
# ---------------------------------------------------------------------------

def test_pipeline_handles_empty_discovery_cleanly():
    """When discovery finds no items, pipeline finishes smoothly without errors."""
    with patch("app.pipeline.discover_topics", return_value=[]):
        summary = run_pipeline_cycle(agent_id="nexus-001")
        assert summary["total_candidates"] == 0
        assert summary["published"] == 0
        assert summary["rejected"] == 0
        assert summary["skipped"] == 0
        assert summary["results"] == []


# ---------------------------------------------------------------------------
# 2. Unreachable Discovery Source
# ---------------------------------------------------------------------------

def test_discovery_handles_unreachable_source_gracefully():
    """When an RSS feed raises a network/parsing error, _fetch_feed returns [] and does not crash."""
    with patch("requests.get", side_effect=Exception("Connection refused / Timeout")):
        result = _fetch_feed({"name": "Failing Feed", "url": "https://unreachable-feed-host.invalid/rss"})
        assert isinstance(result, list)
        assert len(result) == 0

    # Test full discovery when all live feeds fail
    with patch("app.discovery._fetch_feed", side_effect=Exception("Network error")):
        candidates = discover_topics(use_demo_fixtures=False)
        assert isinstance(candidates, list)
        assert len(candidates) == 0


# ---------------------------------------------------------------------------
# 3. LLM API Failure During Scoring
# ---------------------------------------------------------------------------

def test_scoring_api_failure_does_not_crash_pipeline():
    """When the LLM API fails or times out during scoring, the topic is skipped safely."""
    candidate = {
        "title": "Novel Agent Checkpointing Architecture",
        "summary": "Technical paper detailing memory persistence.",
        "source_url": "https://example.com/paper",
        "published_at": "2026-08-08T10:00:00Z",
        "raw_snippet": "Snippet content.",
    }

    # Verify score_topic returns None when LLM call fails
    with patch("app.editor._call_llm", side_effect=Exception("API key quota exhausted / 500 error")):
        scores = score_topic(candidate)
        assert scores is None

    # Verify pipeline skips failing topic without crashing
    with patch("app.pipeline.discover_topics", return_value=[candidate]), \
         patch("app.pipeline.score_topic", return_value=None):

        summary = run_pipeline_cycle(agent_id="nexus-001")
        assert summary["total_candidates"] == 1
        assert summary["published"] == 0
        assert summary["rejected"] == 0
        assert summary["skipped"] == 1
        assert summary["results"] == []


# ---------------------------------------------------------------------------
# 4. LLM API Failure During Generation
# ---------------------------------------------------------------------------

def test_generation_api_failure_does_not_crash_pipeline():
    """When the LLM API fails during post synthesis, the candidate is skipped without crashing."""
    candidate = {
        "title": "Novel Agent Framework Release",
        "summary": "High technical impact release with empirical benchmarks.",
        "source_url": "https://example.com/release",
        "published_at": "2026-08-08T10:00:00Z",
        "raw_snippet": "Full benchmarks.",
    }

    mock_scoring = ScoreResult(
        relevance=90.0,
        novelty=90.0,
        technical_impact=90.0,
        evidence_quality=90.0,
        timeliness=90.0,
        justifications={
            "relevance": "Relevant.",
            "novelty": "Novel.",
            "technical_impact": "High impact.",
            "evidence_quality": "Solid benchmarks.",
            "timeliness": "Recent.",
        },
    )

    # Mock score passing, but generation returning None (failed LLM call)
    with patch("app.pipeline.discover_topics", return_value=[candidate]), \
         patch("app.pipeline.score_topic", return_value=mock_scoring), \
         patch("app.pipeline.generate_post", return_value=None):

        summary = run_pipeline_cycle(agent_id="nexus-001")
        assert summary["total_candidates"] == 1
        assert summary["published"] == 0
        assert summary["skipped"] == 1


# ---------------------------------------------------------------------------
# 5. Invalid / Malformed POST /api/agent/init Request Bodies
# ---------------------------------------------------------------------------

def test_init_rejects_empty_payload(client):
    """POST /api/agent/init with empty payload returns HTTP 422."""
    response = client.post("/api/agent/init", json={})
    assert response.status_code == 422


def test_init_rejects_missing_persona_name(client):
    """POST /api/agent/init missing persona.name returns HTTP 422."""
    response = client.post("/api/agent/init", json={"persona": {"domain": "AI Infra"}})
    assert response.status_code == 422


def test_init_rejects_non_dict_persona(client):
    """POST /api/agent/init with invalid type returns HTTP 422."""
    response = client.post("/api/agent/init", json={"persona": "invalid_string_not_dict"})
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# 6. Missing / Invalid Query Parameter on GET /api/agent/feed
# ---------------------------------------------------------------------------

def test_feed_rejects_missing_agent_id(client):
    """GET /api/agent/feed with missing agentId query parameter returns HTTP 422."""
    response = client.get("/api/agent/feed")
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# 7. Hard Evidence-Floor Rule Failure Case
# ---------------------------------------------------------------------------

def test_evidence_floor_forces_rejection_despite_high_composite_score(client):
    """If Evidence Quality < 40, topic is rejected even if composite score would be >= 70."""
    init_res = client.post("/api/agent/init", json={"persona": {"name": PERSONA.name, "domain": "AI Infrastructure"}})
    agent_id = init_res.json()["agentId"]

    candidate = [{
        "title": "Anonymous Leak: Revolutionary AGI Architecture Next Month",
        "summary": "Unverified rumors from anonymous social media posts claim 1000x gain without evidence.",
        "source_url": "https://example.com/rumor",
        "published_at": "2026-08-08T10:00:00Z",
        "raw_snippet": "No data, purely speculative leak.",
    }]

    # Composite = 0.2*95 + 0.15*95 + 0.25*95 + 0.2*25 + 0.2*95 = 81.0 (>= 70)
    low_evidence_scores = ScoreResult(
        relevance=95.0,
        novelty=95.0,
        technical_impact=95.0,
        evidence_quality=25.0,
        timeliness=95.0,
        justifications={
            "relevance": "Very relevant topic.",
            "novelty": "Super novel claim.",
            "technical_impact": "Huge if true.",
            "evidence_quality": "Zero benchmarks or verifiable data.",
            "timeliness": "Breaking news.",
        },
    )

    with patch("app.pipeline.discover_topics", return_value=candidate), \
         patch("app.pipeline.score_topic", return_value=low_evidence_scores):

        res = client.post(f"/api/agent/trigger-cycle?agentId={agent_id}")
        summary = res.json()["summary"]
        assert summary["published"] == 0
        assert summary["rejected"] == 1

        result_item = summary["results"][0]
        assert result_item["decision"] == "REJECT"
        assert "Stage A" in result_item["stage"]
        assert "evidence quality" in result_item["reason"].lower()
        assert "floor" in result_item["reason"].lower()


# ---------------------------------------------------------------------------
# 8. Database Resilience with Corrupted / Partial JSON
# ---------------------------------------------------------------------------

def test_database_gracefully_handles_malformed_json_fields():
    """get_posts_by_agent recovers gracefully if stored JSON fields in DB are corrupted/invalid JSON strings."""
    init_db()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO posts
                (id, agent_id, topic, summary, created_at,
                 generated_text, sources, editorial_score, decision, rationale)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "post-corrupt-001",
                "nexus-001",
                "Corrupt Data Test",
                "Testing fallback on non-json string",
                "2026-08-08T10:00:00Z",
                "Valid text",
                "not-a-valid-json-array",
                85.0,
                "PUBLISH",
                "not-a-valid-json-dict",
            ),
        )

    posts = get_posts_by_agent("nexus-001", decision="PUBLISH")
    assert len(posts) == 1
    # Check that sources and rationale fell back safely to list and dict
    assert isinstance(posts[0]["sources"], list)
    assert isinstance(posts[0]["rationale"], dict)
