"""
Unit and integration tests for app.generator (Phase 9 content generation).

Run:
    python tests/test_generator.py
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.config import settings
from app.editor import ScoreResult
from app.generator import (
    build_publishing_rationale,
    _clean_generated_text,
    _build_generation_prompt,
    generate_post,
    GeneratedPost,
)
from app.persona import PERSONA


class TestContentGeneratorUnit(unittest.TestCase):

    def setUp(self):
        self.candidate = {
            "title": "LangGraph 0.3 Ships Stateful Multi-Agent Checkpointing with SQLite",
            "summary": (
                "LangGraph has released version 0.3 introducing first-party AsyncSqlite "
                "and Postgres checkpointers, enabling persistent state across serverless agent turns."
            ),
            "source_url": "https://github.com/langchain-ai/langgraph/releases/tag/v0.3.0",
            "published_at": "2026-08-08T10:00:00Z",
            "raw_snippet": "Full release notes for LangGraph 0.3 with SQLite checkpointing code samples.",
        }

        self.score_result = ScoreResult(
            relevance=100.0,
            novelty=80.0,
            technical_impact=90.0,
            evidence_quality=80.0,
            timeliness=95.0,
            justifications={
                "relevance": "Directly targets multi-agent state persistence architectures.",
                "novelty": "Native async SQLite checkpointing reduces external infrastructure dependencies.",
                "technical_impact": "Solves stateless execution bottlenecks for serverless multi-agent pipelines.",
                "evidence_quality": "Primary GitHub release with working open-source implementation.",
                "timeliness": "Major release published today.",
            },
        )

    def test_build_publishing_rationale_structure_and_score_fidelity(self):
        """
        Verify rationale object matches PRD §5.6 requirements:
        { "why_selected": "...", "why_relevant_now": "...", "editorial_score": <int> }
        and faithfully references the actual composite score and factor notes.
        """
        rationale = build_publishing_rationale(self.candidate, self.score_result)

        self.assertIn("why_selected", rationale)
        self.assertIn("why_relevant_now", rationale)
        self.assertIn("editorial_score", rationale)

        # Editorial score must be exact integer matching composite score
        expected_score = int(round(self.score_result.composite_score))
        self.assertEqual(rationale["editorial_score"], expected_score)
        self.assertIsInstance(rationale["editorial_score"], int)

        # Content must draw from actual justifications
        self.assertIn("Solves stateless execution bottlenecks", rationale["why_selected"])
        self.assertIn("Major release published today", rationale["why_relevant_now"])
        self.assertIn("Primary GitHub release", rationale["why_selected"])

    def test_clean_generated_text_removes_meta_tags_and_fences(self):
        """Test defensive text cleanup for LLM outputs."""
        raw_markdown = "```markdown\nThis is a clean technical post about agent architecture.\n```"
        self.assertEqual(_clean_generated_text(raw_markdown), "This is a clean technical post about agent architecture.")

        raw_preamble = "Here is the post:\nCloudflare launched persistent agent workers with native isolation."
        self.assertEqual(
            _clean_generated_text(raw_preamble),
            "Cloudflare launched persistent agent workers with native isolation.",
        )

        raw_quotes = '"Direct quote enclosed post analyzing MCP tool endpoints."'
        self.assertEqual(
            _clean_generated_text(raw_quotes),
            "Direct quote enclosed post analyzing MCP tool endpoints.",
        )

    def test_build_generation_prompt_injects_persona_and_opinions(self):
        """Ensure prompt includes centralized persona voice, opinions, and rules."""
        prompt = _build_generation_prompt(self.candidate, self.score_result)

        self.assertIn(PERSONA.name, prompt)
        self.assertIn(PERSONA.voice, prompt)
        for opinion in PERSONA.standing_opinions:
            self.assertIn(opinion, prompt)
        for rule in PERSONA.hard_rules:
            self.assertIn(rule, prompt)

        self.assertIn(self.candidate["title"], prompt)
        self.assertIn(self.candidate["source_url"], prompt)
        self.assertIn("STRICT GROUNDING", prompt)


class TestContentGeneratorLive(unittest.TestCase):

    @unittest.skipUnless(bool(settings.LLM_API_KEY), "Requires LLM_API_KEY")
    def test_live_generation_end_to_end(self):
        """Generate a live post for LangGraph 0.3 and verify tone and rationale."""
        candidate = {
            "title": "LangGraph 0.3 ships stateful multi-agent checkpointing with AsyncSqlite",
            "summary": (
                "LangGraph has released version 0.3.0 introducing first-party AsyncSqlite "
                "and Postgres checkpointers, enabling persistent state across serverless agent turns."
            ),
            "source_url": "https://github.com/langchain-ai/langgraph/releases/tag/v0.3.0",
            "published_at": "2026-08-08T10:00:00Z",
            "raw_snippet": (
                "LangGraph 0.3.0 release notes: Added AsyncSqliteSaver and AsyncPostgresSaver "
                "checkpointers for native asynchronous state management. Reduces overhead in multi-agent workflows."
            ),
        }

        score_result = ScoreResult(
            relevance=100.0,
            novelty=80.0,
            technical_impact=90.0,
            evidence_quality=80.0,
            timeliness=95.0,
            justifications={
                "relevance": "Directly targets multi-agent state persistence architectures.",
                "novelty": "Native async SQLite checkpointing reduces external infrastructure dependencies.",
                "technical_impact": "Solves stateless execution bottlenecks for serverless multi-agent pipelines.",
                "evidence_quality": "Primary GitHub release with working open-source implementation.",
                "timeliness": "Major release published today.",
            },
        )

        post = generate_post(candidate, score_result)

        self.assertIsNotNone(post, "Generated post must not be None")
        self.assertIsInstance(post, GeneratedPost)
        self.assertGreater(len(post.text), 100)
        self.assertEqual(post.sources, [candidate["source_url"]])
        self.assertEqual(post.editorial_score, score_result.composite_score)
        self.assertIn("editorial_score", post.rationale)
        self.assertEqual(post.rationale["editorial_score"], int(round(score_result.composite_score)))

        print("\n" + "=" * 60)
        print("SAMPLE GENERATED POST:")
        print("=" * 60)
        print(post.text)
        print("\nSAMPLE RATIONALE OBJECT:")
        print(post.rationale)
        print("=" * 60 + "\n")


if __name__ == "__main__":
    unittest.main(verbosity=2)
