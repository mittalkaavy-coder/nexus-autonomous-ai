"""
Unit tests for app.memory (Phase 10 memory, duplicate detection, and stance tracking).

Run:
    python tests/test_memory.py
"""

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.memory import (
    tokenize,
    compute_tfidf_vectors,
    compute_cosine_similarity,
    evaluate_material_novelty,
    check_duplicate,
    tag_topic_subject,
    record_stance,
    get_stance_reference,
    _STANCE_REGISTRY,
)


class TestMemoryUnit(unittest.TestCase):

    def setUp(self):
        _STANCE_REGISTRY.clear()

    def test_tokenize_cleans_and_filters_stopwords(self):
        text = "LangGraph has released a new SQLite checkpointer for multi-agent workflows."
        tokens = tokenize(text)
        self.assertIn("langgraph", tokens)
        self.assertIn("sqlite", tokens)
        self.assertIn("checkpointer", tokens)
        self.assertNotIn("has", tokens)
        self.assertNotIn("for", tokens)

    def test_tfidf_cosine_similarity_accuracy(self):
        doc1 = "LangGraph 0.3 ships stateful multi-agent SQLite checkpointing with AsyncSqlite"
        doc2 = "LangGraph 0.3 ships stateful multi-agent SQLite checkpointing with AsyncSqlite"
        doc3 = "LangGraph 0.3 Released with AsyncSqlite State Checkpointing for agents"
        doc4 = "Anthropic announces Claude 3.7 Sonnet hybrid reasoning architecture"

        vectors = compute_tfidf_vectors([doc1, doc2, doc3, doc4])

        # Exact match
        sim_exact = compute_cosine_similarity(vectors[0], vectors[1])
        self.assertAlmostEqual(sim_exact, 1.0, places=3)

        # High similarity (paraphrased/related)
        sim_high = compute_cosine_similarity(vectors[0], vectors[2])
        self.assertGreater(sim_high, 0.40)

        # Distinct topic
        sim_diff = compute_cosine_similarity(vectors[0], vectors[3])
        self.assertLess(sim_diff, 0.10)

    @patch("app.memory.get_recent_posts")
    @patch("app.memory.get_recent_topics")
    def test_check_duplicate_empty_history(self, mock_topics, mock_posts):
        mock_posts.return_value = []
        mock_topics.return_value = []

        candidate = {
            "title": "LangGraph 0.3 Checkpointer",
            "summary": "SQLite checkpointing for agents",
            "source_url": "https://example.com/1",
        }

        res = check_duplicate(candidate)
        self.assertFalse(res.is_duplicate)
        self.assertEqual(res.similarity_score, 0.0)

    @patch("app.memory.get_recent_posts")
    @patch("app.memory.get_recent_topics")
    def test_check_duplicate_detects_high_similarity(self, mock_topics, mock_posts):
        mock_posts.return_value = [
            {
                "id": "post-001",
                "topic": "LangGraph 0.3 ships stateful multi-agent checkpointing with AsyncSqlite",
                "summary": "LangGraph version 0.3 introduces AsyncSqlite and Postgres checkpointers for state persistence.",
                "sources": ["https://github.com/langchain-ai/langgraph/releases/tag/v0.3.0"],
            }
        ]
        mock_topics.return_value = []

        # Duplicate candidate (same release covered by another blog)
        candidate = {
            "title": "LangGraph 0.3 Released with AsyncSqlite State Checkpointing",
            "summary": "LangGraph released version 0.3.0 with AsyncSqlite and Postgres checkpointers for state persistence in agents.",
            "source_url": "https://techblog.example.com/langgraph-v0-3",
        }

        res = check_duplicate(candidate, threshold=0.70)
        self.assertTrue(res.is_duplicate)
        self.assertGreaterEqual(res.similarity_score, 0.70)
        self.assertEqual(res.matched_id, "post-001")
        self.assertIn("Rejected as duplicate", res.reason)

    def test_evaluate_material_novelty_recognizes_version_bump(self):
        candidate = {
            "title": "LangGraph 0.4.0 adds distributed fault tolerance",
            "summary": "LangGraph 0.4 introduces distributed consensus across agent clusters.",
            "source_url": "https://github.com/langchain-ai/langgraph/releases/tag/v0.4.0",
        }
        prior = {
            "title": "LangGraph 0.3.0 ships stateful multi-agent checkpointing",
            "summary": "LangGraph 0.3.0 introduces AsyncSqlite checkpointer.",
            "source_url": "https://github.com/langchain-ai/langgraph/releases/tag/v0.3.0",
        }

        is_new, note = evaluate_material_novelty(candidate, prior, sim_score=0.85)
        self.assertTrue(is_new)
        self.assertIn("version", note.lower())

    def test_stance_memory_lifecycle(self):
        # 1. Tagging
        tags = tag_topic_subject(
            "LangGraph SQLite Async Checkpointer",
            "Persistent state management for multi-agent loops",
        )
        self.assertIn("state-persistence", tags)

        # 2. Record stance
        record_stance(
            topic="LangGraph SQLite Checkpointer",
            decision="PUBLISH",
            rationale={"why_selected": "First-party asynchronous state persistence is an architectural requirement."},
            tags=tags,
        )

        # 3. Retrieve stance reference on a subsequent topic
        ref = get_stance_reference(
            topic="Temporal Serverless Agent Checkpointing",
            summary="Stateful execution and checkpointing in agent runtimes",
        )
        self.assertIsNotNone(ref)
        self.assertIn("Consistent with NEXUS's stance on 'state-persistence'", ref)


if __name__ == "__main__":
    unittest.main(verbosity=2)
