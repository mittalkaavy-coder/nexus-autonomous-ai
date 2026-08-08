"""
Unit and integration tests for Phase 8: Editorial Decision Engine.

Tests:
  1. Standard PUBLISH decision: composite >= 70, EQ >= 40.
  2. Standard REJECT decision: composite < 70, EQ >= 40 (drag factors identified).
  3. Evidence floor forced REJECT: composite >= 70, but EQ < 40 (distinct floor messaging).
  4. Both low score and floor breach: composite < 70 and EQ < 40.
  5. Configurable thresholds: custom threshold (80.0) and floor (50.0).
  6. Structured rationale contains all required fields for database/API wire models.

Run:
    python tests/test_phase8_decisions.py
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.config import settings
from app.editor import (
    ScoreResult,
    EditorialDecision,
    make_editorial_decision,
    WEIGHTS,
)


class TestEditorialDecisionEngine(unittest.TestCase):

    def setUp(self):
        self.candidate = {
            "title": "Test Framework Release with Verified Repository",
            "summary": "Official release notes with reproducible benchmarks and GitHub repo.",
            "source_url": "https://github.com/example/test-framework/releases/tag/v1.0",
            "published_at": "2026-08-08T12:00:00Z",
            "raw_snippet": "Full release details with benchmarks.",
        }

    def test_standard_publish(self):
        """High-scoring topic with strong evidence should PUBLISH."""
        scores = ScoreResult(
            relevance=95,
            novelty=80,
            technical_impact=85,
            evidence_quality=75,
            timeliness=90,
            justifications={
                "relevance": "Directly in agent infrastructure niche.",
                "novelty": "Novel checkpointing mechanism.",
                "technical_impact": "Solves serverless state persistence.",
                "evidence_quality": "Primary GitHub release with working code.",
                "timeliness": "Released today.",
            },
        )
        # Expected composite: 95*0.20 + 80*0.15 + 85*0.25 + 75*0.20 + 90*0.20 = 19 + 12 + 21.25 + 15 + 18 = 85.25
        self.assertGreaterEqual(scores.composite_score, 70.0)
        self.assertGreaterEqual(scores.evidence_quality, 40.0)

        decision = make_editorial_decision(self.candidate, scores, threshold=70.0, evidence_floor=40.0)

        self.assertEqual(decision.decision, "PUBLISH")
        self.assertFalse(decision.evidence_floor_triggered)
        self.assertIn("Published:", decision.summary_reason)
        self.assertIn("Key strengths", decision.summary_reason)
        self.assertIn("key_strengths", decision.rationale)
        self.assertGreaterEqual(len(decision.rationale["key_strengths"]), 1)

    def test_standard_low_score_reject(self):
        """Topic with composite < 70 but EQ >= 40 rejected with drag factors."""
        scores = ScoreResult(
            relevance=50,
            novelty=40,
            technical_impact=45,
            evidence_quality=50,
            timeliness=60,
            justifications={
                "relevance": "Peripheral relevance.",
                "novelty": "Incremental tutorial.",
                "technical_impact": "Low impact.",
                "evidence_quality": "Decent primary source tutorial.",
                "timeliness": "Recent.",
            },
        )
        # Expected composite: 50*0.2 + 40*0.15 + 45*0.25 + 50*0.2 + 60*0.2 = 10 + 6 + 11.25 + 10 + 12 = 49.25
        self.assertLess(scores.composite_score, 70.0)
        self.assertGreaterEqual(scores.evidence_quality, 40.0)

        decision = make_editorial_decision(self.candidate, scores, threshold=70.0, evidence_floor=40.0)

        self.assertEqual(decision.decision, "REJECT")
        self.assertFalse(decision.evidence_floor_triggered)
        self.assertIn("Rejected: composite score", decision.summary_reason)
        self.assertIn("fell short of publish threshold", decision.summary_reason)
        self.assertIn("Dragged down by:", decision.summary_reason)
        self.assertIn("drag_factors", decision.rationale)

    def test_hard_evidence_floor_rule_triggers_despite_high_composite(self):
        """
        CRITICAL TEST: When composite score is >= 70 (qualifies on paper),
        but Evidence Quality < 40, the hard floor rule MUST force REJECT
        with visibly distinct messaging.
        """
        # Fabricate scores where R=100, N=90, TI=90, T=90, but EQ=20 (e.g. unverified rumor/leak)
        # Composite = 100*0.2 + 90*0.15 + 90*0.25 + 20*0.20 + 90*0.20 = 20 + 13.5 + 22.5 + 4 + 18 = 78.0
        scores = ScoreResult(
            relevance=100,
            novelty=90,
            technical_impact=90,
            evidence_quality=20,  # Below 40 floor!
            timeliness=90,
            justifications={
                "relevance": "Core agent tooling niche.",
                "novelty": "Claimed breakthrough.",
                "technical_impact": "Massive claimed architecture shift.",
                "evidence_quality": "Anonymous tweet with zero source repo or paper.",
                "timeliness": "Breaking rumor.",
            },
        )
        self.assertGreaterEqual(scores.composite_score, 70.0, "Composite should exceed 70 on paper")
        self.assertLess(scores.evidence_quality, 40.0, "EQ must be strictly below 40 floor")

        decision = make_editorial_decision(self.candidate, scores, threshold=70.0, evidence_floor=40.0)

        # Must be REJECT
        self.assertEqual(decision.decision, "REJECT")
        self.assertTrue(decision.evidence_floor_triggered)

        # Must produce visibly distinct reason noting the floor breach despite qualifying composite
        self.assertIn("below the minimum floor", decision.summary_reason)
        self.assertIn("despite a qualifying composite score", decision.summary_reason)
        self.assertIn("78.0", decision.summary_reason)
        self.assertIn("20", decision.summary_reason)
        self.assertIn("Anonymous tweet", decision.summary_reason)

        # Check structured rationale
        self.assertTrue(decision.rationale["evidence_floor_triggered"])
        self.assertIn("primary_violation", decision.rationale)
        self.assertIn("failed mandatory floor", decision.rationale["primary_violation"])

    def test_low_score_and_low_evidence(self):
        """When both composite < 70 and EQ < 40, evidence floor is still triggered."""
        scores = ScoreResult(
            relevance=40,
            novelty=30,
            technical_impact=20,
            evidence_quality=25,
            timeliness=50,
            justifications={
                "relevance": "Marginal.",
                "novelty": "Hype rehash.",
                "technical_impact": "No substance.",
                "evidence_quality": "Press release only.",
                "timeliness": "Standard.",
            },
        )
        decision = make_editorial_decision(self.candidate, scores, threshold=70.0, evidence_floor=40.0)

        self.assertEqual(decision.decision, "REJECT")
        self.assertTrue(decision.evidence_floor_triggered)
        self.assertIn("below the minimum floor", decision.summary_reason)

    def test_tunable_threshold_and_floor_from_config(self):
        """Test custom threshold (80.0) and floor (50.0) values."""
        scores = ScoreResult(
            relevance=80,
            novelty=70,
            technical_impact=75,
            evidence_quality=45,  # Passes default 40 floor, but fails custom 50 floor!
            timeliness=80,
            justifications={
                "relevance": "Niche.",
                "novelty": "Interesting.",
                "technical_impact": "Solid.",
                "evidence_quality": "Secondary summary with partial code.",
                "timeliness": "Recent.",
            },
        )
        # Default settings (70 / 40): passes floor (45 >= 40) and passes threshold (70.25 >= 70) -> PUBLISH
        dec_default = make_editorial_decision(self.candidate, scores, threshold=70.0, evidence_floor=40.0)
        self.assertEqual(dec_default.decision, "PUBLISH")

        # Custom strict settings (80 / 50): fails floor (45 < 50) -> REJECT
        dec_strict = make_editorial_decision(self.candidate, scores, threshold=80.0, evidence_floor=50.0)
        self.assertEqual(dec_strict.decision, "REJECT")
        self.assertTrue(dec_strict.evidence_floor_triggered)

    def test_editorial_decision_to_dict_structure(self):
        """Ensure to_dict returns the expected wire/persistence shape."""
        scores = ScoreResult(
            relevance=90,
            novelty=85,
            technical_impact=90,
            evidence_quality=80,
            timeliness=85,
            justifications={"relevance": "R", "novelty": "N", "technical_impact": "TI", "evidence_quality": "EQ", "timeliness": "T"},
        )
        decision = make_editorial_decision(self.candidate, scores)
        d = decision.to_dict()

        self.assertEqual(d["title"], self.candidate["title"])
        self.assertEqual(d["decision"], "PUBLISH")
        self.assertIsInstance(d["composite_score"], float)
        self.assertIsInstance(d["publish_threshold"], float)
        self.assertIsInstance(d["evidence_floor"], float)
        self.assertIsInstance(d["evidence_floor_triggered"], bool)
        self.assertIsInstance(d["summary_reason"], str)
        self.assertIn("factor_scores", d)
        self.assertIn("rationale", d)


if __name__ == "__main__":
    unittest.main(verbosity=2)
