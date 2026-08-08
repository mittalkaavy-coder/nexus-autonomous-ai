"""
End-to-End Lifecycle Test Suite for NEXUS (PRD §5 & §17).

Tests:
1. POST /api/agent/init returns a valid agentId.
2. Calling init twice is idempotent (returns same agentId, no duplicate agent, no duplicate scheduler).
3. GET /api/agent/feed with a fresh agent returns {"posts": []}.
4. GET /api/agent/feed with an unknown agentId returns 404.
5. After a forced cycle (POST /api/agent/trigger-cycle), feed returns:
   - Newest-first ordering.
   - Unique IDs.
   - Valid ISO 8601 UTC timestamps.
   - All required PRD fields (rationale, sources, editorialScore, generatedText).
6. A duplicate topic run through the pipeline twice is correctly rejected the second time.
7. Previously returned posts remain available after a second cycle runs (additive feed).
"""

import os
import sys
from datetime import datetime
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.database import get_recent_posts, init_db
from app.editor import ScoreResult
from app.generator import GeneratedPost
from app.main import app
from app.persona import PERSONA
from app.scheduler import is_scheduler_running, stop_scheduler


@pytest.fixture(autouse=True)
def setup_test_db(tmp_path):
    """Provide an isolated database and clean scheduler environment for each test."""
    db_file = str(tmp_path / "test_lifecycle.db")
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


def test_agent_init_returns_valid_id(client):
    """POST /api/agent/init returns 200 and a non-empty agentId string."""
    payload = {
        "persona": {
            "name": PERSONA.name,
            "domain": "AI Agent Infrastructure",
        }
    }
    response = client.post("/api/agent/init", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "agentId" in data
    assert isinstance(data["agentId"], str)
    assert len(data["agentId"]) > 0
    assert data["agentId"] == "nexus-001"


def test_agent_init_is_idempotent(client):
    """Calling init multiple times is idempotent with no duplicate agent or scheduler."""
    payload = {
        "persona": {
            "name": PERSONA.name,
            "domain": "AI Agent Infrastructure",
        }
    }

    # First initialization
    res1 = client.post("/api/agent/init", json=payload)
    assert res1.status_code == 200
    agent_id1 = res1.json()["agentId"]
    assert is_scheduler_running() is True

    # Second initialization
    res2 = client.post("/api/agent/init", json=payload)
    assert res2.status_code == 200
    agent_id2 = res2.json()["agentId"]
    assert agent_id1 == agent_id2
    assert is_scheduler_running() is True


def test_fresh_agent_feed_returns_empty_list(client):
    """GET /api/agent/feed on a newly initialized agent returns 200 with an empty list."""
    payload = {
        "persona": {
            "name": PERSONA.name,
            "domain": "AI Agent Infrastructure",
        }
    }
    init_res = client.post("/api/agent/init", json=payload)
    agent_id = init_res.json()["agentId"]

    feed_res = client.get(f"/api/agent/feed?agentId={agent_id}")
    assert feed_res.status_code == 200
    data = feed_res.json()
    assert "posts" in data
    assert data["posts"] == []


def test_unknown_agent_feed_returns_404(client):
    """GET /api/agent/feed for a non-existent agent returns 404 Not Found."""
    response = client.get("/api/agent/feed?agentId=non-existent-agent-999")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_feed_contract_after_forced_cycle(client):
    """
    After triggering a cycle, verify feed schema:
    - Newest-first ordering
    - Unique post IDs
    - Valid ISO 8601 UTC timestamps
    - All required fields: id, agentId, topic, summary, createdAt, generatedText, sources, editorialScore, decision, rationale
    """
    # 1. Initialize
    init_res = client.post("/api/agent/init", json={"persona": {"name": PERSONA.name, "domain": "AI Infrastructure"}})
    agent_id = init_res.json()["agentId"]

    # 2. Mock high-scoring items to guarantee published posts
    mock_candidates = [
        {
            "title": "Post Alpha: Memory Checkpointing in Distributed Agents",
            "summary": "Technical deep dive into SQLite WAL checkpointing for autonomous agent memory state.",
            "source_url": "https://example.com/alpha",
            "published_at": "2026-08-08T10:00:00Z",
            "raw_snippet": "Memory checkpointing architecture details.",
        },
        {
            "title": "Post Beta: Zero-Copy Serialization in LangGraph 0.3",
            "summary": "Benchmarking serialization latency reductions in multi-agent graph workflows.",
            "source_url": "https://example.com/beta",
            "published_at": "2026-08-08T10:05:00Z",
            "raw_snippet": "Zero copy benchmarks and graphs.",
        },
    ]

    mock_score = ScoreResult(
        relevance=90.0,
        novelty=85.0,
        technical_impact=95.0,
        evidence_quality=90.0,
        timeliness=85.0,
        justifications={
            "relevance": "Direct agent infra relevance.",
            "novelty": "New checkpointing benchmark.",
            "technical_impact": "Significant architectural leap.",
            "evidence_quality": "Empirical benchmarks included.",
            "timeliness": "Fresh release this morning.",
        },
    )

    def mock_gen(cand, score_res, **kwargs):
        return GeneratedPost(
            topic=cand["title"],
            summary=cand["summary"],
            text=f"Technical analysis of {cand['title']}: {cand['summary']}",
            rationale={
                "why_selected": "High technical impact and robust empirical evidence.",
                "why_relevant_now": "Immediate relevance to production agent architectures.",
                "editorial_score": int(round(score_res.composite_score)),
            },
            sources=[cand["source_url"]],
            editorial_score=score_res.composite_score,
        )

    with patch("app.pipeline.discover_topics", return_value=mock_candidates), \
         patch("app.pipeline.score_topic", return_value=mock_score), \
         patch("app.pipeline.generate_post", side_effect=mock_gen):

        trigger_res = client.post(f"/api/agent/trigger-cycle?agentId={agent_id}")
        assert trigger_res.status_code == 200
        summary = trigger_res.json()["summary"]
        assert summary["published"] == 2

    # 3. Query Feed
    feed_res = client.get(f"/api/agent/feed?agentId={agent_id}")
    assert feed_res.status_code == 200
    posts = feed_res.json()["posts"]
    assert len(posts) == 2

    # Verify unique IDs
    post_ids = [p["id"] for p in posts]
    assert len(post_ids) == len(set(post_ids))

    # Verify required fields and types according to FeedPost PRD schema
    for p in posts:
        assert isinstance(p["id"], str) and len(p["id"]) > 0
        assert isinstance(p["text"], str) and len(p["text"]) > 0
        assert isinstance(p["sources"], list) and len(p["sources"]) >= 1

        # Rationale structure validation
        assert isinstance(p["rationale"], dict)
        assert "why_selected" in p["rationale"]
        assert "why_relevant_now" in p["rationale"]
        assert "editorial_score" in p["rationale"]

        # Valid ISO 8601 UTC timestamp check
        ts = p["createdAt"]
        assert isinstance(ts, str)
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        assert dt is not None


def test_duplicate_topic_rejected_on_second_run(client):
    """A topic run through the pipeline twice is rejected as a duplicate on the second cycle."""
    init_res = client.post("/api/agent/init", json={"persona": {"name": PERSONA.name, "domain": "AI Infrastructure"}})
    agent_id = init_res.json()["agentId"]

    duplicate_candidate = [
        {
            "title": "vLLM 0.6.0 Kernel Optimizations for Agent Batching",
            "summary": "vLLM introduces PagedAttention v3 with 3x higher throughput for concurrent agent loops.",
            "source_url": "https://example.com/vllm-060",
            "published_at": "2026-08-08T10:00:00Z",
            "raw_snippet": "Comprehensive throughput benchmarks on H100 clusters.",
        }
    ]

    mock_score = ScoreResult(
        relevance=90.0,
        novelty=85.0,
        technical_impact=95.0,
        evidence_quality=90.0,
        timeliness=80.0,
        justifications={
            "relevance": "Core agent serving infra.",
            "novelty": "PagedAttention v3.",
            "technical_impact": "3x throughput.",
            "evidence_quality": "Empirical benchmarks.",
            "timeliness": "Today's release.",
        },
    )

    mock_gen = GeneratedPost(
        topic=duplicate_candidate[0]["title"],
        summary=duplicate_candidate[0]["summary"],
        text="vLLM 0.6.0 brings decisive throughput gains for concurrent agent architectures.",
        rationale={
            "why_selected": "Exceptional technical impact on serving latency.",
            "why_relevant_now": "Critical for production agent infrastructure scaling.",
            "editorial_score": 88,
        },
        sources=[duplicate_candidate[0]["source_url"]],
        editorial_score=89.25,
    )

    # Cycle 1: First time candidate is processed -> PUBLISH
    with patch("app.pipeline.discover_topics", return_value=duplicate_candidate), \
         patch("app.pipeline.score_topic", return_value=mock_score), \
         patch("app.pipeline.generate_post", return_value=mock_gen):

        res1 = client.post(f"/api/agent/trigger-cycle?agentId={agent_id}")
        assert res1.json()["summary"]["published"] == 1
        assert res1.json()["summary"]["rejected"] == 0

    # Cycle 2: Candidate is submitted again -> REJECT (duplicate)
    with patch("app.pipeline.discover_topics", return_value=duplicate_candidate), \
         patch("app.pipeline.score_topic", return_value=mock_score), \
         patch("app.pipeline.generate_post", return_value=mock_gen):

        res2 = client.post(f"/api/agent/trigger-cycle?agentId={agent_id}")
        assert res2.json()["summary"]["published"] == 0
        assert res2.json()["summary"]["rejected"] == 1

        # Verify rejection reason in cycle result
        dup_result = res2.json()["summary"]["results"][0]
        assert dup_result["decision"] == "REJECT"
        assert "Duplicate" in dup_result["stage"]
        assert "duplicate" in dup_result["reason"].lower()


def test_previously_returned_posts_remain_available_after_second_cycle(client):
    """Posts published in Cycle 1 remain in the feed when Cycle 2 runs."""
    init_res = client.post("/api/agent/init", json={"persona": {"name": PERSONA.name, "domain": "AI Infrastructure"}})
    agent_id = init_res.json()["agentId"]

    item1 = [{
        "title": "Topic One: MCP Specification Finalized",
        "summary": "Model Context Protocol reaches 1.0 specification with universal tool calling standards.",
        "source_url": "https://example.com/item-1",
        "published_at": "2026-08-08T09:00:00Z",
        "raw_snippet": "Spec details.",
    }]

    item2 = [{
        "title": "Topic Two: Formal Verification of Agent Sandboxes",
        "summary": "Proving isolation guarantees for autonomous code execution environments using Lean 4.",
        "source_url": "https://example.com/item-2",
        "published_at": "2026-08-08T11:00:00Z",
        "raw_snippet": "Sandbox proof details.",
    }]

    scoring = ScoreResult(
        relevance=90.0,
        novelty=90.0,
        technical_impact=90.0,
        evidence_quality=90.0,
        timeliness=90.0,
        justifications={
            "relevance": "Relevant.",
            "novelty": "Novel.",
            "technical_impact": "High impact.",
            "evidence_quality": "Formal proofs.",
            "timeliness": "Current.",
        },
    )

    def gen(cand, score_res, **kwargs):
        return GeneratedPost(
            topic=cand["title"],
            summary=cand["summary"],
            text=f"Analysis of {cand['title']}",
            rationale={"why_selected": "Key infra", "why_relevant_now": "Now", "editorial_score": 90},
            sources=[cand["source_url"]],
            editorial_score=90.0,
        )

    with patch("app.pipeline.score_topic", return_value=scoring), \
         patch("app.pipeline.generate_post", side_effect=gen):

        # Cycle 1
        with patch("app.pipeline.discover_topics", return_value=item1):
            client.post(f"/api/agent/trigger-cycle?agentId={agent_id}")

        feed1 = client.get(f"/api/agent/feed?agentId={agent_id}").json()["posts"]
        assert len(feed1) == 1
        assert "Topic One" in feed1[0]["text"]

        # Cycle 2
        with patch("app.pipeline.discover_topics", return_value=item2):
            client.post(f"/api/agent/trigger-cycle?agentId={agent_id}")

        feed2 = client.get(f"/api/agent/feed?agentId={agent_id}").json()["posts"]
        assert len(feed2) == 2
        texts = [p["text"] for p in feed2]
        assert any("Topic One" in t for t in texts)
        assert any("Topic Two" in t for t in texts)
