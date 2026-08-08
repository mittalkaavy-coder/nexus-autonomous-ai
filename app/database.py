"""
Handles SQLite database setup and connection.
Plain sqlite3 (stdlib) chosen over SQLAlchemy Core — zero extra dependencies,
no ORM overhead, and NEXUS is a single-node app with simple flat tables.
"""

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from app.config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Connection helper
# ---------------------------------------------------------------------------


@contextmanager
def get_connection():
    """
    Yield a sqlite3 connection with row_factory set to sqlite3.Row.
    Commits on clean exit, rolls back on exception, always closes.
    """
    conn = sqlite3.connect(settings.DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Schema creation
# ---------------------------------------------------------------------------


def init_db() -> None:
    """Create all tables if they don't already exist. Called once on server startup."""
    # Ensure the data directory exists
    Path(settings.DATABASE_PATH).parent.mkdir(parents=True, exist_ok=True)

    with get_connection() as conn:
        # ---- agent ----
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS agent (
                agent_id        TEXT PRIMARY KEY,
                persona_config  TEXT NOT NULL,           -- JSON-encoded dict
                initialized_at  TEXT NOT NULL,           -- ISO 8601 UTC
                status          TEXT NOT NULL DEFAULT 'active'
            )
            """
        )

        # ---- posts ----
        # Stores every editorial decision — both PUBLISH and REJECT.
        # generated_text is NULL for REJECT rows (generation never runs for rejects).
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS posts (
                id              TEXT PRIMARY KEY,
                agent_id        TEXT NOT NULL,
                topic           TEXT NOT NULL,
                summary         TEXT NOT NULL,
                created_at      TEXT NOT NULL,           -- ISO 8601 UTC
                generated_text  TEXT,                    -- NULL for REJECT decisions
                sources         TEXT NOT NULL DEFAULT '[]', -- JSON array of URLs
                editorial_score REAL NOT NULL,
                decision        TEXT NOT NULL,           -- 'PUBLISH' or 'REJECT'
                rationale       TEXT NOT NULL DEFAULT '{}' -- JSON object
            )
            """
        )

        # ---- topics_seen ----
        # Every discovered candidate is logged here — even those that are rejected —
        # so duplicate detection has a full history to compare against.
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS topics_seen (
                id              TEXT PRIMARY KEY,
                title           TEXT NOT NULL,
                summary         TEXT NOT NULL,
                source_url      TEXT NOT NULL,
                discovered_at   TEXT NOT NULL,           -- ISO 8601 UTC
                similarity_ref  TEXT                     -- nullable: ID of a related post/topic
            )
            """
        )

    logger.info("Database ready at '%s'", settings.DATABASE_PATH)


# ---------------------------------------------------------------------------
# posts — data-access functions
# ---------------------------------------------------------------------------


def insert_post(
    *,
    id: str,
    agent_id: str,
    topic: str,
    summary: str,
    created_at: str,
    generated_text: Optional[str],
    sources: list[str],
    editorial_score: float,
    decision: str,
    rationale: dict[str, Any],
) -> None:
    """
    Persist one editorial decision (PUBLISH or REJECT) to the posts table.

    Args:
        id:              Unique post ID (e.g. 'post-001').
        agent_id:        Owning agent (e.g. 'nexus-001').
        topic:           Short topic title from discovery.
        summary:         One-sentence summary of the candidate.
        created_at:      ISO 8601 UTC timestamp string.
        generated_text:  Final post body; None/empty for REJECT decisions.
        sources:         List of source URLs used as evidence.
        editorial_score: Composite float score (0–100).
        decision:        'PUBLISH' or 'REJECT'.
        rationale:       Dict explaining the decision (why_selected, etc.).
    """
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO posts
                (id, agent_id, topic, summary, created_at,
                 generated_text, sources, editorial_score, decision, rationale)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                id,
                agent_id,
                topic,
                summary,
                created_at,
                generated_text,
                json.dumps(sources),
                editorial_score,
                decision,
                json.dumps(rationale),
            ),
        )
    logger.debug("Inserted post '%s' (decision=%s) for agent '%s'.", id, decision, agent_id)


def _safe_json_loads(value: Any, default: Any) -> Any:
    """Safely parse JSON or return default if corrupted / invalid."""
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        value_str = value.strip()
        if not value_str:
            return default
        try:
            return json.loads(value_str)
        except Exception:
            return default
    return default


def get_posts_by_agent(agent_id: str, decision: Optional[str] = None) -> list[dict[str, Any]]:
    """
    Return all posts for the given agent, newest-first.

    Args:
        agent_id: Owning agent ID.
        decision: Optional filter ('PUBLISH' or 'REJECT'). If None, returns all.

    Returns:
        List of dicts with keys matching the posts table columns.
        sources and rationale are safely deserialized from JSON to Python objects.
    """
    query = """
        SELECT id, agent_id, topic, summary, created_at,
               generated_text, sources, editorial_score, decision, rationale
        FROM   posts
        WHERE  agent_id = ?
    """
    params: list[Any] = [agent_id]
    if decision is not None:
        query += " AND decision = ?"
        params.append(decision)
    query += " ORDER BY created_at DESC"

    with get_connection() as conn:
        rows = conn.execute(query, tuple(params)).fetchall()

    result = []
    for row in rows:
        d = dict(row)
        d["sources"] = _safe_json_loads(d.get("sources"), [])
        d["rationale"] = _safe_json_loads(d.get("rationale"), {})
        result.append(d)
    return result


def get_recent_posts(limit: int = 50, published_only: bool = False) -> list[dict[str, Any]]:
    """
    Return recent posts across all agents, newest-first.

    Args:
        limit: Maximum number of posts to return.
        published_only: If True, filters only rows where decision == 'PUBLISH'.

    Returns:
        List of dicts with deserialized sources and rationale.
    """
    query = """
        SELECT id, agent_id, topic, summary, created_at,
               generated_text, sources, editorial_score, decision, rationale
        FROM   posts
    """
    params: list[Any] = []
    if published_only:
        query += " WHERE decision = 'PUBLISH'"
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)

    with get_connection() as conn:
        rows = conn.execute(query, tuple(params)).fetchall()

    result = []
    for row in rows:
        d = dict(row)
        d["sources"] = _safe_json_loads(d.get("sources"), [])
        d["rationale"] = _safe_json_loads(d.get("rationale"), {})
        result.append(d)
    return result


# ---------------------------------------------------------------------------
# topics_seen — data-access functions
# ---------------------------------------------------------------------------


def insert_topic_seen(
    *,
    id: str,
    title: str,
    summary: str,
    source_url: str,
    discovered_at: str,
    similarity_ref: Optional[str] = None,
) -> None:
    """
    Log a discovered topic candidate to topics_seen.

    Called for every candidate that enters the pipeline, regardless of whether
    it is later published or rejected, so the duplicate-detection window is
    always accurate.

    Args:
        id:             Unique ID for this seen-topic record.
        title:          Topic headline from discovery.
        summary:        Short summary / snippet.
        source_url:     Canonical URL of the source article.
        discovered_at:  ISO 8601 UTC timestamp string.
        similarity_ref: Optional ID of an existing post or topic that this
                        candidate was found to be similar to.
    """
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO topics_seen
                (id, title, summary, source_url, discovered_at, similarity_ref)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (id, title, summary, source_url, discovered_at, similarity_ref),
        )
    logger.debug("Logged topic_seen '%s' ('%s').", id, title[:60])


def get_recent_topics(limit: int = 50) -> list[dict[str, Any]]:
    """
    Return the most recently discovered topics, newest-first.

    Used by duplicate detection to bound the comparison window to a practical
    recent set rather than scanning the entire lifetime database.

    Args:
        limit: Maximum number of rows to return (default 50).

    Returns:
        List of dicts with all topics_seen columns.
    """
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, title, summary, source_url, discovered_at, similarity_ref
            FROM   topics_seen
            ORDER  BY discovered_at DESC
            LIMIT  ?
            """,
            (limit,),
        ).fetchall()

    return [dict(row) for row in rows]
