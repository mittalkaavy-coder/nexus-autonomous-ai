"""
Live topic discovery for NEXUS.

Pulls candidate topics from curated RSS feeds relevant to the persona niche
(AI agents, agent infrastructure, developer tooling, MCP/RAG, AI deployment/ops).

Pipeline contract:
  - discover_topics() is the single public entry point.
  - Returns a list of normalized candidate dicts — no scores, no decisions.
  - Individual feed failures are logged and skipped; the run continues.
  - If ALL feeds fail, returns [] — never raises.
  - A separate DEMO_FIXTURES list provides a clearly labeled fallback for
    deterministic demo runs when live sources are slow/empty (PRD §8).

Normalized shape per candidate:
    {
        "title":        str,   -- headline as-is from the feed
        "summary":      str,   -- cleaned plain-text snippet / description
        "source_url":   str,   -- canonical link to the article
        "published_at": str,   -- ISO 8601 UTC; falls back to discovery time
        "raw_snippet":  str,   -- first ~400 chars of raw description for scoring
    }
"""

import logging
import re
import textwrap
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import feedparser

logger = logging.getLogger(__name__)

# RSS request timeout (PRD §5.1 mandates 5–10 s)
_FEED_TIMEOUT_SECONDS: int = 8

# How many items to pull per feed (keeps cycle latency bounded)
_MAX_ITEMS_PER_FEED: int = 10

# Recency filter — ignore items older than this many hours in LIVE mode.
# Demo fixtures are exempt (PRD §5.1).
_MAX_AGE_HOURS: int = 72


# ---------------------------------------------------------------------------
# Curated feed list — all relevant to NEXUS niche
# ---------------------------------------------------------------------------

LIVE_FEEDS: list[dict[str, str]] = [
    {
        "name": "The Sequence (AI research & infrastructure)",
        "url": "https://thesequence.substack.com/feed",
    },
    {
        "name": "Towards Data Science",
        "url": "https://towardsdatascience.com/feed",
    },
    {
        "name": "Last Week in AI",
        "url": "https://lastweekin.ai/feed",
    },
    {
        "name": "The Gradient (AI research deep dives)",
        "url": "https://thegradient.pub/rss/",
    },
    {
        "name": "InfoQ AI/ML",
        "url": "https://feed.infoq.com/ai-ml-data-eng",
    },
]


# ---------------------------------------------------------------------------
# Demo fixtures — PRD §8 determinism requirement
#
# These three candidates cover the three mandatory demo scenarios:
#   1. A clearly substantive / high-quality candidate (should PUBLISH).
#   2. A clearly low-evidence / hype candidate (should REJECT via evidence floor).
#   3. A near-duplicate of an already-published topic (should REJECT via dedup).
#
# Fixtures pass through the EXACT same pipeline as live topics — no pre-set
# scores, decisions, or dashboard output are embedded here.
# ---------------------------------------------------------------------------

DEMO_FIXTURES: list[dict[str, Any]] = [
    {
        # Scenario 1 — substantive: primary-source technical release
        "title": "LangGraph 0.3 ships stateful multi-agent checkpointing with SQLite backend",
        "summary": (
            "LangGraph 0.3 adds a first-party checkpointing layer backed by SQLite, "
            "letting multi-agent graphs persist and resume state across process restarts "
            "without an external store. The release includes a reference architecture for "
            "human-in-the-loop approval nodes and a revised streaming API."
        ),
        "source_url": "https://github.com/langchain-ai/langgraph/releases/tag/0.3.0",
        "published_at": datetime.now(timezone.utc).isoformat(),
        "raw_snippet": (
            "LangGraph 0.3 adds a first-party checkpointing layer backed by SQLite, "
            "letting multi-agent graphs persist and resume state across process restarts "
            "without an external store. The release includes a reference architecture for "
            "human-in-the-loop approval nodes and a revised streaming API. "
            "Source: github.com/langchain-ai/langgraph/releases/tag/0.3.0"
        ),
        "_demo": True,
    },
    {
        # Scenario 2 — low-evidence hype: no verifiable artifact
        "title": "Startup claims 10x faster agent inference with 'NeuroFlow' architecture",
        "summary": (
            "A stealth startup announced 'NeuroFlow', a claimed novel agent inference "
            "architecture promising 10x throughput gains over existing frameworks. "
            "No paper, repository, benchmark methodology, or reproducible evaluation "
            "was provided — only a press release and a waitlist."
        ),
        "source_url": "https://techcrunch.com/2026/08/07/neuroflow-stealth-agent-startup/",
        "published_at": datetime.now(timezone.utc).isoformat(),
        "raw_snippet": (
            "A stealth startup announced 'NeuroFlow', claiming 10x agent inference gains. "
            "No paper, no repo, no benchmark — press release only with a waitlist link."
        ),
        "_demo": True,
    },
    {
        # Scenario 3 — duplicate: closely related to scenario 1
        "title": "LangGraph adds persistent state to multi-agent workflows",
        "summary": (
            "LangGraph has introduced persistent state management for multi-agent systems, "
            "allowing agents to resume from checkpoints after interruption. "
            "The feature uses a local SQLite store and is documented in the project README."
        ),
        "source_url": "https://blog.langchain.dev/langgraph-persistent-state/",
        "published_at": datetime.now(timezone.utc).isoformat(),
        "raw_snippet": (
            "LangGraph now supports persistent state in multi-agent graphs via a local "
            "SQLite checkpoint store. Agents can resume after interruption. See README."
        ),
        "_demo": True,
    },
]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _strip_html(text: str) -> str:
    """Remove HTML tags and collapse whitespace."""
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _to_iso8601(entry: feedparser.FeedParserDict) -> str:
    """
    Extract a UTC ISO 8601 timestamp from a feedparser entry.
    Tries published_parsed, updated_parsed, then falls back to now().
    """
    for attr in ("published_parsed", "updated_parsed"):
        struct = getattr(entry, attr, None)
        if struct:
            try:
                # feedparser gives us a time.struct_time in UTC
                dt = datetime(*struct[:6], tzinfo=timezone.utc)
                return dt.isoformat()
            except Exception:
                pass

    # Last resort: use the raw string if parseable
    for attr in ("published", "updated"):
        raw = getattr(entry, attr, None)
        if raw:
            try:
                dt = parsedate_to_datetime(raw).astimezone(timezone.utc)
                return dt.isoformat()
            except Exception:
                pass

    return datetime.now(timezone.utc).isoformat()


def _is_recent(iso_str: str, max_age_hours: int = _MAX_AGE_HOURS) -> bool:
    """Return True if the timestamp is within max_age_hours of now."""
    try:
        dt = datetime.fromisoformat(iso_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        age = datetime.now(timezone.utc) - dt
        return age.total_seconds() < max_age_hours * 3600
    except Exception:
        return True  # if we can't parse, don't filter it out


def _normalize_entry(entry: feedparser.FeedParserDict, feed_name: str) -> dict[str, Any]:
    """Convert a single feedparser entry into the normalized candidate shape."""
    title = _strip_html(getattr(entry, "title", "") or "")
    raw_desc = getattr(entry, "summary", "") or getattr(entry, "description", "") or ""
    summary = _strip_html(raw_desc)
    source_url = getattr(entry, "link", "") or ""
    published_at = _to_iso8601(entry)
    raw_snippet = textwrap.shorten(summary, width=400, placeholder="…")

    return {
        "title": title,
        "summary": summary,
        "source_url": source_url,
        "published_at": published_at,
        "raw_snippet": raw_snippet,
    }


def _fetch_feed(feed: dict[str, str]) -> list[dict[str, Any]]:
    """
    Fetch and parse one RSS feed.

    Returns a list of normalized candidates, or [] on any failure.
    Exceptions are caught and logged so callers always get a list back.
    """
    name = feed["name"]
    url = feed["url"]

    logger.info("Fetching feed: %s (%s)", name, url)
    try:
        # feedparser uses urllib internally; we set the request_headers and
        # socket timeout via the agent kwarg.  The socket-level timeout is
        # handled by passing a custom opener is complex — instead we use
        # feedparser's built-in `agent` kwarg for identification and rely on
        # requests for the actual HTTP fetch so we can enforce a hard timeout.
        import requests

        response = requests.get(
            url,
            timeout=_FEED_TIMEOUT_SECONDS,
            headers={"User-Agent": "NEXUS-discovery/1.0 (+https://github.com/nexus-ai)"},
        )
        response.raise_for_status()
        parsed = feedparser.parse(response.text)
    except Exception as exc:
        logger.warning("Feed '%s' failed: %s — skipping.", name, exc)
        return []

    entries = parsed.get("entries", [])
    if not entries:
        logger.info("Feed '%s' returned 0 entries.", name)
        return []

    candidates = []
    for entry in entries[:_MAX_ITEMS_PER_FEED]:
        try:
            candidate = _normalize_entry(entry, name)
            if not candidate["title"] or not candidate["source_url"]:
                continue  # skip malformed entries silently
            if not _is_recent(candidate["published_at"]):
                logger.debug(
                    "Skipping stale item '%s' from '%s' (older than %dh).",
                    candidate["title"][:60],
                    name,
                    _MAX_AGE_HOURS,
                )
                continue
            candidates.append(candidate)
        except Exception as exc:
            logger.warning("Failed to normalize entry from '%s': %s", name, exc)
            continue

    logger.info("Feed '%s' yielded %d fresh candidates.", name, len(candidates))
    return candidates


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def discover_topics(use_demo_fixtures: bool = False) -> list[dict[str, Any]]:
    """
    Pull and normalize candidate topics from all configured live RSS feeds.

    Args:
        use_demo_fixtures:
            If True, return DEMO_FIXTURES instead of hitting live sources.
            Intended only for deterministic demo runs (PRD §8).
            DEMO_FIXTURES are still exempt from the recency filter.

    Returns:
        List of normalized candidate dicts — each with keys:
            title, summary, source_url, published_at, raw_snippet.
        Returns [] if all live sources fail; never raises.
    """
    if use_demo_fixtures:
        logger.info(
            "[DEMO MODE] Returning %d demo fixtures — live sources not contacted.",
            len(DEMO_FIXTURES),
        )
        # Strip the internal _demo marker before returning
        return [
            {k: v for k, v in fixture.items() if k != "_demo"}
            for fixture in DEMO_FIXTURES
        ]

    logger.info(
        "Starting live discovery from %d configured feed(s).", len(LIVE_FEEDS)
    )

    all_candidates: list[dict[str, Any]] = []
    success_count = 0

    for feed in LIVE_FEEDS:
        results = _fetch_feed(feed)
        if results is not None:  # _fetch_feed always returns a list, even on failure
            all_candidates.extend(results)
            if results:
                success_count += 1

    if not all_candidates:
        logger.warning(
            "All %d feed(s) returned no candidates. "
            "Discovery returning empty list — cycle will be skipped.",
            len(LIVE_FEEDS),
        )
    else:
        logger.info(
            "Discovery complete: %d candidates from %d/%d feed(s).",
            len(all_candidates),
            success_count,
            len(LIVE_FEEDS),
        )

    return all_candidates
