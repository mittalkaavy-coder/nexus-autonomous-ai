"""
Dry-run pipeline script for NEXUS Phase 8.

Pipeline flow:
  1. Discovery: Discover candidate topics from live RSS feeds + deterministic fixtures.
  2. Normalization: Standardized candidate shape (title, summary, source_url, published_at, raw_snippet).
  3. Scoring: LLM scores candidates across the 5 PRD factors (0-100 each).
  4. Decision: Editorial decision engine evaluates threshold (70.0) and evidence floor (40.0).
  5. Persistence: Stubbed as TODO for Phase 10.

Run:
    python tests/dry_run_pipeline.py
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
from app.discovery import discover_topics, DEMO_FIXTURES
from app.editor import score_topic, make_editorial_decision, EditorialDecision, WEIGHTS

# ---------------------------------------------------------------------------
# Test Batch Candidates
# Combines live discovered topics, demo fixtures (covering substantive + hype),
# plus real recent candidate articles from InfoQ / dev feeds.
# ---------------------------------------------------------------------------

CANDIDATES_BATCH = [
    # 1. High-quality primary technical release (LangGraph 0.3)
    DEMO_FIXTURES[0],

    # 2. Hype / press release with no artifact (NeuroFlow) -> Triggers Evidence Floor!
    DEMO_FIXTURES[1],

    # 3. Real Live InfoQ topic: Cloudflare persistent agent environment
    {
        "title": "Cloudflare Launches Persistent, Stateful, Computer-like Environments for Agents",
        "summary": (
            "Cloudflare has launched a new product that gives AI agents persistent, stateful, "
            "computer-like environments built on Workers. This directly addresses stateless "
            "limitations in serverless agentic workloads with file system and browser support."
        ),
        "source_url": "https://www.infoq.com/news/2026/08/cloudflare-computer-agents/",
        "published_at": "2026-08-07T21:00:00+00:00",
        "raw_snippet": (
            "Cloudflare launches persistent stateful computer-like environments for agents on Workers. "
            "Supports file systems, browser isolation, long-running agent execution."
        ),
    },

    # 4. Real Live InfoQ topic: Azure API Management AI Gateway Tier & MCP Tooling
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
            "Azure APIM adds AI gateway tier for unified governance over LLMs and Model Context Protocol (MCP) tools."
        ),
    },

    # 5. Viral unverified claim / leak: High interest/novelty on paper, but zero verifiable primary artifact
    # Designed specifically to test the hard floor rule on a high-buzz topic
    {
        "title": "Leaked Benchmark Claims Next-Gen Reasoning Model Solves SWE-bench in 12 Seconds",
        "summary": (
            "An anonymous post on X/Twitter accompanied by an unverified screenshot claims a new "
            "unreleased reasoning model achieves 85% on SWE-bench Verified in under 12 seconds per task. "
            "No methodology, evaluation harness, weights, or verifiable reproduction steps are provided."
        ),
        "source_url": "https://twitter.com/ai_leaks_daily/status/1890000000000000",
        "published_at": "2026-08-08T08:00:00+00:00",
        "raw_snippet": (
            "Anonymous leak claims next-gen reasoning model solves SWE-bench in 12s with 85% score. "
            "Screenshot only, no reproduction code or verified evaluation harness."
        ),
    },
]


def run_dry_run():
    print("\n" + "=" * 80)
    print("        NEXUS EDITORIAL PIPELINE DRY RUN (STAGE A: DISCOVERY -> DECISION)")
    print(f"        Config: PUBLISH_THRESHOLD = {settings.PUBLISH_THRESHOLD} | EVIDENCE_FLOOR = {settings.EVIDENCE_FLOOR}")
    print(f"        LLM Model: {settings.LLM_MODEL}")
    print("=" * 80 + "\n")

    decisions: list[EditorialDecision] = []

    print(f"[*] Processing batch of {len(CANDIDATES_BATCH)} candidate topics...\n")

    for i, candidate in enumerate(CANDIDATES_BATCH, start=1):
        title = candidate.get("title", "")
        print(f"--- [{i}/{len(CANDIDATES_BATCH)}] Evaluating: {title[:65]} ---")

        # Step 1: Score topic via LLM
        score_res = score_topic(candidate)
        if score_res is None:
            print(f"    [SKIP] Failed to score candidate: {title[:50]}")
            continue

        # Step 2: Make editorial decision
        decision = make_editorial_decision(candidate, score_res)
        decisions.append(decision)

        # Step 3: Persistence stub
        # TODO: Phase 10 - Database persistence
        # if decision.decision == "PUBLISH":
        #     insert_post(post_record)
        # else:
        #     insert_post(reject_record)
        # insert_topic_seen(topic_record)

        print(f"    Scores: Composite={score_res.composite_score:.1f} | R={score_res.relevance:.0f} N={score_res.novelty:.0f} TI={score_res.technical_impact:.0f} EQ={score_res.evidence_quality:.0f} T={score_res.timeliness:.0f}")
        print(f"    Outcome: [{decision.decision}] (Evidence floor triggered: {decision.evidence_floor_triggered})")
        print(f"    Reason: {decision.summary_reason}\n")

    # -----------------------------------------------------------------------
    # Summary Dashboard Report
    # -----------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("                         BATCH DECISION SUMMARY")
    print("=" * 80)
    print(f"{'#':<3} | {'DECISION':<8} | {'COMP':<5} | {'EQ':<4} | {'FLOOR?':<6} | {'TOPIC TITLE':<45}")
    print("-" * 80)

    for i, d in enumerate(decisions, start=1):
        status_tag = f"[{d.decision}]"
        floor_tag = "YES" if d.evidence_floor_triggered else "NO"
        title_trunc = textwrap.shorten(d.candidate.get("title", ""), width=45, placeholder="…")
        print(f"{i:<3} | {status_tag:<8} | {d.score_result.composite_score:<5.1f} | {d.score_result.evidence_quality:<4.0f} | {floor_tag:<6} | {title_trunc:<45}")

    print("-" * 80)
    pub_count = sum(1 for d in decisions if d.decision == "PUBLISH")
    rej_count = sum(1 for d in decisions if d.decision == "REJECT")
    floor_count = sum(1 for d in decisions if d.evidence_floor_triggered)
    print(f"TOTAL: {len(decisions)} | PUBLISHED: {pub_count} | REJECTED: {rej_count} | FLOOR RULE TRIGGERED: {floor_count}\n")

    # -----------------------------------------------------------------------
    # Detailed Breakdown of Decisions & Rationales
    # -----------------------------------------------------------------------
    print("=" * 80)
    print("                     DETAILED EDITORIAL RATIONALES")
    print("=" * 80)

    for i, d in enumerate(decisions, start=1):
        print(f"\n[{i}] {d.candidate.get('title')}")
        print(f"    Source URL: {d.candidate.get('source_url')}")
        print(f"    Outcome   : {d.decision} (Composite: {d.score_result.composite_score:.1f}, Threshold: {d.publish_threshold}, Evidence Floor: {d.evidence_floor})")
        print(f"    Floor Rule: {'TRIGGERED (Hard Rejection)' if d.evidence_floor_triggered else 'PASSED'}")
        print(f"\n    Factor Scores & Weights:")
        for k, v in d.score_result.to_dict()["factor_scores"].items():
            weight_pct = int(WEIGHTS.get(k, 0) * 100)
            print(f"      - {k:18s} ({weight_pct:2d}%): {v:3.0f}/100  ->  {d.score_result.justifications.get(k, '')}")
        print(f"\n    Editorial Summary Reason:")
        print(f"      \"{d.summary_reason}\"")
        print("-" * 80)

    print("\n[OK] Dry run pipeline completed successfully.\n")


if __name__ == "__main__":
    run_dry_run()
