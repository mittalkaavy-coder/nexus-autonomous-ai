"""
End-to-end pipeline execution with content generation for NEXUS.

Executes:
  1. Discovery & Normalization (app.discovery)
  2. Editorial Scoring (app.editor)
  3. Editorial Decision & Evidence Floor check (app.editor)
  4. Content Generation for PUBLISHED topics (app.generator)
  5. Displays complete posts and publishing rationale objects

Run:
    python tests/demo_full_pipeline_with_generation.py
"""

import json
import logging
import os
import sys
import textwrap

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

from app.config import settings
from app.discovery import DEMO_FIXTURES
from app.editor import score_topic, make_editorial_decision, WEIGHTS
from app.generator import generate_post, GeneratedPost

CANDIDATES = [
    # Candidate 1: High quality release -> PUBLISH -> GENERATE
    DEMO_FIXTURES[0],

    # Candidate 2: Hype press release -> REJECT (Floor Triggered) -> NO GENERATION
    DEMO_FIXTURES[1],

    # Candidate 3: Enterprise Cloud infrastructure -> PUBLISH -> GENERATE
    {
        "title": "Azure API Management Adds Dedicated AI Gateway Tier, Governing Models and MCP Tools",
        "summary": (
            "Microsoft Azure API Management has launched a dedicated AI gateway tier providing "
            "unified governance, semantic caching, rate limiting, and policy enforcement across "
            "both LLM endpoints and Model Context Protocol (MCP) tool invocations."
        ),
        "source_url": "https://www.infoq.com/news/2026/08/azure-apim-ai-gateway-tier/",
        "published_at": "2026-08-07T06:35:00+00:00",
        "raw_snippet": (
            "Azure APIM adds dedicated AI gateway tier for unified governance over LLMs and "
            "Model Context Protocol (MCP) tool calls, with semantic caching and policy enforcement."
        ),
    },
]


def run_full_pipeline():
    print("\n" + "=" * 80)
    print("      NEXUS AUTONOMOUS PIPELINE (DISCOVERY -> SCORE -> DECIDE -> GENERATE)")
    print(f"      Threshold: {settings.PUBLISH_THRESHOLD} | Evidence Floor: {settings.EVIDENCE_FLOOR} | Model: {settings.LLM_MODEL}")
    print("=" * 80 + "\n")

    published_posts: list[GeneratedPost] = []

    for i, cand in enumerate(CANDIDATES, start=1):
        title = cand.get("title", "")
        print(f"\n[{i}/{len(CANDIDATES)}] CANDIDATE: {title}")
        print(f"    Source: {cand.get('source_url')}")

        # Step 1: Score
        score_res = score_topic(cand)
        if score_res is None:
            print("    [SKIPPED] Scoring failed.")
            continue

        # Step 2: Decide
        decision = make_editorial_decision(cand, score_res)
        print(f"    Scores: Composite={score_res.composite_score:.1f} | EQ={score_res.evidence_quality:.0f} (Floor: {'FAIL' if decision.evidence_floor_triggered else 'PASS'})")
        print(f"    Editorial Decision: [{decision.decision}]")
        print(f"    Reason: {decision.summary_reason}")

        # Step 3: Generate (Only if PUBLISH)
        if decision.decision == "PUBLISH":
            print("\n    >>> Triggering Content Generation in NEXUS Voice...")
            post = generate_post(cand, score_res)
            if post:
                published_posts.append(post)
                print("    >>> Generation Succeeded.")
            else:
                print("    >>> [WARNING] Generation failed — skipping post persistence.")
        else:
            print("    >>> Skipped Content Generation (Topic Rejected by Editorial Engine).")

        print("-" * 80)

    # -----------------------------------------------------------------------
    # Output Generated Posts
    # -----------------------------------------------------------------------
    print("\n" + "=" * 80)
    print(f"                 FINAL GENERATED POSTS ({len(published_posts)} PUBLISHED)")
    print("=" * 80)

    for idx, p in enumerate(published_posts, start=1):
        print(f"\n==================== [POST {idx}] ====================")
        print(f"TOPIC: {p.topic}")
        print(f"SCORE: {p.editorial_score:.1f}/100 | SOURCES: {p.sources}")
        print("-" * 60)
        print("TEXT:")
        print(p.text)
        print("-" * 60)
        print("PRD RATIONALE OBJECT:")
        print(json.dumps(p.rationale, indent=2))
        print("=" * 60)

    print("\n[OK] End-to-end pipeline run completed successfully.\n")


if __name__ == "__main__":
    run_full_pipeline()
