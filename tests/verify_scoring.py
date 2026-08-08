"""
Verification script for Phase 7 editorial scoring.

Tests:
  1. Score a high-quality topic (primary-source technical release) -- should score well.
  2. Score a low-evidence hype topic (press release, no artifact) -- should score poorly
     on Evidence Quality due to the PRD guardrails.
  3. Simulate an LLM failure (bad API key) -- should return None without crashing.

Run from the project root:
    python tests/verify_scoring.py
"""

import json
import logging
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

from app.editor import score_topic, ScoreResult

# ---------------------------------------------------------------------------
# Test candidates
# Two of the real topics that came back from Phase 6's live discovery run,
# plus one that maps to the demo hype scenario.
# ---------------------------------------------------------------------------

# Candidate A: real InfoQ article on a specific, concrete agent infrastructure release
CANDIDATE_GOOD = {
    "title": "Cloudflare Launches Persistent, Stateful, Computer-like Environments for Agents",
    "summary": (
        "Cloudflare has launched a new product that gives AI agents persistent, stateful, "
        "computer-like environments. The product, built on Workers, allows agents to maintain "
        "state across calls, interact with file systems, run browsers, and execute long-running "
        "tasks — addressing a core limitation of stateless serverless functions for agentic workloads."
    ),
    "source_url": "https://www.infoq.com/news/2026/08/cloudflare-computer-agents/",
    "published_at": "2026-08-07T21:00:00+00:00",
    "raw_snippet": (
        "Cloudflare has launched a new product that gives AI agents persistent, stateful, "
        "computer-like environments built on Workers — allowing agents to maintain state across calls, "
        "interact with file systems, run browsers, and execute long-running tasks. "
        "This directly addresses stateless limitations in serverless agentic workloads."
    ),
}

# Candidate B: vague hype topic with no verifiable primary artifact
CANDIDATE_HYPE = {
    "title": "Startup claims 10x faster agent inference with 'NeuroFlow' architecture",
    "summary": (
        "A stealth startup announced 'NeuroFlow', a claimed novel agent inference architecture "
        "promising 10x throughput gains over existing frameworks. "
        "No paper, repository, benchmark methodology, or reproducible evaluation was provided "
        "— only a press release and a waitlist signup."
    ),
    "source_url": "https://techcrunch.com/2026/08/07/neuroflow-stealth-agent-startup/",
    "published_at": "2026-08-07T12:00:00+00:00",
    "raw_snippet": (
        "Stealth startup claims 10x agent inference gains via 'NeuroFlow'. "
        "No paper, no repo, no benchmark provided. Press release only with a waitlist link."
    ),
}

# Candidate C: a real InfoQ article that's relevant to NEXUS niche - AI Gateway and MCP
CANDIDATE_MCP = {
    "title": "Azure API Management Adds Dedicated AI Gateway Tier, Governing Models and MCP Tools",
    "summary": (
        "Microsoft Azure API Management has launched a dedicated AI gateway tier that provides "
        "unified governance over LLM model calls and Model Context Protocol (MCP) tool invocations. "
        "The tier adds rate limiting, semantic caching, token usage tracking, and policy enforcement "
        "across both REST APIs and MCP endpoints — filling a gap in enterprise agentic deployments."
    ),
    "source_url": "https://www.infoq.com/news/2026/08/azure-apim-ai-gateway-tier/",
    "published_at": "2026-08-07T06:35:00+00:00",
    "raw_snippet": (
        "Azure APIM launches dedicated AI gateway tier: unified governance over LLM calls and MCP tool "
        "invocations, with rate limiting, semantic caching, token tracking, and policy enforcement. "
        "Targets enterprise agentic deployment gaps."
    ),
}


def print_result(label: str, candidate: dict, result) -> None:
    print(f"\n{'='*65}")
    print(f"  {label}")
    print(f"  Title: {candidate['title'][:70]}")
    print(f"{'='*65}")
    if result is None:
        print("  RESULT: None (expected for failure simulation)")
        return
    d = result.to_dict()
    factors = d["factor_scores"]
    just    = d["justifications"]
    print(f"\n  Composite Score : {d['composite_score']:.1f} / 100")
    print(f"\n  Factor Scores:")
    print(f"    Relevance        ({20}%): {factors['relevance']:.0f}")
    print(f"    Novelty          ({15}%): {factors['novelty']:.0f}")
    print(f"    Technical Impact ({25}%): {factors['technical_impact']:.0f}")
    print(f"    Evidence Quality ({20}%): {factors['evidence_quality']:.0f}")
    print(f"    Timeliness       ({20}%): {factors['timeliness']:.0f}")
    print(f"\n  Justifications:")
    for k, v in just.items():
        print(f"    {k:20s}: {v}")
    print()


# ---------------------------------------------------------------------------
# Run tests
# ---------------------------------------------------------------------------

print("\n\n=== NEXUS Phase 7 — Editorial Scoring Verification ===\n")

# Test 1: Good candidate
print("[TEST 1] High-quality, primary-source topic ...")
result_good = score_topic(CANDIDATE_GOOD)
print_result("TEST 1 — Primary-source technical release (expect HIGH scores)", CANDIDATE_GOOD, result_good)

# Test 2: Hype / low-evidence candidate
print("[TEST 2] Hype/low-evidence topic ...")
result_hype = score_topic(CANDIDATE_HYPE)
print_result("TEST 2 — Press-release hype, no artifact (expect LOW Evidence Quality)", CANDIDATE_HYPE, result_hype)

# Test 3: MCP/infra topic
print("[TEST 3] MCP governance topic ...")
result_mcp = score_topic(CANDIDATE_MCP)
print_result("TEST 3 — Azure MCP gateway (expect HIGH relevance on niche match)", CANDIDATE_MCP, result_mcp)

# Test 4: LLM failure simulation
print("[TEST 4] Simulating LLM failure (bad API key) ...")
from app import config as cfg_module
original_key = cfg_module.settings.LLM_API_KEY
cfg_module.settings.LLM_API_KEY = "INVALID_KEY_NEXUS_TEST"

result_fail = score_topic(CANDIDATE_GOOD)
cfg_module.settings.LLM_API_KEY = original_key

print_result("TEST 4 — LLM failure simulation (expect None, no crash)", CANDIDATE_GOOD, result_fail)
assert result_fail is None, f"Expected None on LLM failure, got: {result_fail}"
print("  [PASS] LLM failure returned None without crashing.")

# Sanity checks
if result_good and result_hype:
    assert result_good.evidence_quality > result_hype.evidence_quality, (
        f"Sanity FAIL: good EQ ({result_good.evidence_quality}) should be > hype EQ ({result_hype.evidence_quality})"
    )
    print(f"\n  [PASS] Sanity check: EQ({result_good.evidence_quality:.0f}) > hype EQ({result_hype.evidence_quality:.0f})")

    assert result_hype.evidence_quality <= 45, (
        f"Sanity FAIL: hype EQ ({result_hype.evidence_quality}) must be <= 45 per PRD guardrail"
    )
    print(f"  [PASS] Evidence guardrail: hype EQ {result_hype.evidence_quality:.0f} <= 45")

print("\n=== Scoring verification complete ===\n")
