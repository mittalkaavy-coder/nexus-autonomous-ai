"""
End-to-end integration tests for Phase 10: Memory, Duplicate Detection, and Persistence.

Validates:
1. First run persists all discovered topics to `topics_seen`.
2. First run persists BOTH PUBLISH and REJECT decisions to `posts` table.
3. Second run with duplicate topic catches and rejects candidate as duplicate.
4. Second run persists duplicate rejection to `posts` table.
5. GET /api/agent/feed returns ONLY PUBLISH decisions (never REJECT or duplicate REJECT).

Run:
    python tests/test_pipeline_persistence.py
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.agent import initialize_agent, get_feed
from app.database import get_connection, init_db, get_recent_posts, get_recent_topics
from app.editor import ScoreResult
from app.generator import GeneratedPost
from app.persona import PERSONA
from app.pipeline import run_pipeline_cycle


class TestPipelinePersistenceAndMemory(unittest.TestCase):

    def setUp(self):
        # Fresh in-memory DB or temporary file for clean test isolation
        self.test_db = f"./data/test_memory_{self._testMethodName}.db"
        os.environ["DATABASE_PATH"] = self.test_db
        from app.config import settings
        settings.DATABASE_PATH = self.test_db
        init_db()

        # Initialize agent
        self.agent_id = initialize_agent({"name": PERSONA.name, "domain": "AI Agent Infrastructure"})

    def tearDown(self):
        if os.path.exists(self.test_db):
            try:
                os.remove(self.test_db)
            except Exception:
                pass

    @patch("app.pipeline.score_topic")
    @patch("app.pipeline.generate_post")
    def test_full_pipeline_persistence_and_duplicate_rejection(
        self, mock_generate, mock_score
    ):
        # -------------------------------------------------------------------
        # Fixtures for Run 1:
        # Candidate 1: High quality AI Agent topic (Will PASS and PUBLISH)
        # Candidate 2: Low evidence topic (Evidence Floor < 40 -> REJECT)
        # Candidate 3: Low relevance/score topic (Composite < 70 -> REJECT)
        # -------------------------------------------------------------------
        cand_publish = {
            "title": "LangGraph 0.3 Ships AsyncSqlite State Checkpointing for Multi-Agent Loops",
            "summary": "LangGraph 0.3 introduces asynchronous SQLite and PostgreSQL checkpointers for robust fault-tolerant agent state management.",
            "source_url": "https://github.com/langchain-ai/langgraph/releases/tag/v0.3.0",
            "published_at": "2026-03-01T12:00:00Z",
            "raw_snippet": "LangGraph v0.3.0 released with AsyncSqlite saver.",
        }

        cand_low_evidence = {
            "title": "Anonymous Rumor: Next-Gen Model Might Be 100x Faster",
            "summary": "Unverified claims on social media suggest an upcoming model will achieve 100x speedup with zero benchmarks.",
            "source_url": "https://rumor.example.com/unverified-claim",
            "published_at": "2026-03-01T13:00:00Z",
            "raw_snippet": "Rumors swirl about unreleased speedups.",
        }

        cand_low_score = {
            "title": "Generic CSS Tips for Frontend Buttons",
            "summary": "A basic guide on how to style CSS buttons with border-radius and box-shadow.",
            "source_url": "https://css.example.com/buttons",
            "published_at": "2026-03-01T14:00:00Z",
            "raw_snippet": "How to make buttons rounded.",
        }

        # Mock Scoring Results
        score_pub = ScoreResult(
            relevance=92.0, novelty=85.0, technical_impact=90.0, evidence_quality=95.0, timeliness=88.0,
            justifications={"relevance": "Direct match for agent infra", "evidence_quality": "Official release"}
        )
        score_low_ev = ScoreResult(
            relevance=80.0, novelty=75.0, technical_impact=70.0, evidence_quality=25.0, timeliness=80.0,
            justifications={"evidence_quality": "Unverified rumor without benchmark proof"}
        )
        score_low_sc = ScoreResult(
            relevance=10.0, novelty=20.0, technical_impact=15.0, evidence_quality=80.0, timeliness=40.0,
            justifications={"relevance": "Unrelated to AI infra"}
        )

        def mock_score_side_effect(cand):
            if "LangGraph" in cand["title"]:
                return score_pub
            elif "Rumor" in cand["title"]:
                return score_low_ev
            else:
                return score_low_sc

        mock_score.side_effect = mock_score_side_effect

        # Mock Generator
        mock_generate.return_value = GeneratedPost(
            text="LangGraph 0.3 establishes persistent agent state via AsyncSqlite checkpointers. Critical infrastructure for multi-step agent reliability.",
            rationale={
                "why_selected": "First-party asynchronous state checkpointing is foundational for reliable agent runtimes.",
                "why_relevant_now": "LangGraph v0.3 release brings SQLite and Postgres checkpointers to production workflows.",
                "editorial_score": 90,
            },
            topic=cand_publish["title"],
            summary=cand_publish["summary"],
            sources=[cand_publish["source_url"]],
            editorial_score=90.3,
        )

        # ===================================================================
        # EXECUTE CYCLE 1
        # ===================================================================
        run1_candidates = [cand_publish, cand_low_evidence, cand_low_score]
        summary1 = run_pipeline_cycle(
            agent_id=self.agent_id,
            candidates_override=run1_candidates,
        )

        self.assertEqual(summary1["total_candidates"], 3)
        self.assertEqual(summary1["published"], 1)
        self.assertEqual(summary1["rejected"], 2)

        # Check topics_seen table has all 3 discovered topics
        all_topics_seen = get_recent_topics(limit=50)
        self.assertEqual(len(all_topics_seen), 3)

        # Check posts table has 3 records (1 PUBLISH, 2 REJECT)
        all_posts = get_recent_posts(limit=50)
        self.assertEqual(len(all_posts), 3)

        published_posts = [p for p in all_posts if p["decision"] == "PUBLISH"]
        rejected_posts = [p for p in all_posts if p["decision"] == "REJECT"]

        self.assertEqual(len(published_posts), 1)
        self.assertEqual(len(rejected_posts), 2)
        self.assertIsNotNone(published_posts[0]["generated_text"])
        self.assertIsNone(rejected_posts[0]["generated_text"])

        # Check feed endpoint returns ONLY the PUBLISH post
        feed = get_feed(self.agent_id)
        self.assertEqual(len(feed), 1)
        self.assertEqual(feed[0]["id"], published_posts[0]["id"])
        self.assertIn("LangGraph 0.3", feed[0]["text"])

        # ===================================================================
        # EXECUTE CYCLE 2: Near-duplicate of cand_publish arrives
        # ===================================================================
        cand_duplicate = {
            "title": "LangGraph 0.3 Released with AsyncSqlite State Checkpointing",
            "summary": "LangGraph released version 0.3.0 with AsyncSqlite and Postgres checkpointers for state persistence in agents.",
            "source_url": "https://tech-news-aggregator.example.com/langgraph-v03",
            "published_at": "2026-03-01T15:00:00Z",
            "raw_snippet": "Summary of LangGraph 0.3 checkpointing.",
        }

        # Candidate is high quality, so Stage A score passes
        # But Stage B duplicate check must catch it!
        summary2 = run_pipeline_cycle(
            agent_id=self.agent_id,
            candidates_override=[cand_duplicate],
        )

        self.assertEqual(summary2["total_candidates"], 1)
        self.assertEqual(summary2["published"], 0)
        self.assertEqual(summary2["rejected"], 1)

        dup_result = summary2["results"][0]
        self.assertEqual(dup_result["decision"], "REJECT")
        self.assertEqual(dup_result["stage"], "Stage B (Duplicate Check)")
        self.assertIn("Rejected as duplicate", dup_result["reason"])

        # Confirm posts table now has 4 rows total (1 PUBLISH, 3 REJECT)
        all_posts_after = get_recent_posts(limit=50)
        self.assertEqual(len(all_posts_after), 4)

        # Confirm feed still has ONLY the 1 original PUBLISH post
        feed_after = get_feed(self.agent_id)
        self.assertEqual(len(feed_after), 1)
        self.assertEqual(feed_after[0]["id"], published_posts[0]["id"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
