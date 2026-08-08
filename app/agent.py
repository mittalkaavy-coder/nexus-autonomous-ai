"""
Handles agent initialization and lifecycle management.
"""

import json
import logging
from datetime import datetime, timezone

from app.database import get_connection

logger = logging.getLogger(__name__)


def initialize_agent(persona: dict) -> str:
    """
    Initialize the NEXUS agent with the given persona config.

    Idempotent: if an agent already exists, logs a notice and returns the
    existing agentId without inserting a new row or scheduling anything again.

    Args:
        persona: dict with at minimum 'name' and 'domain' keys.

    Returns:
        agentId string, e.g. 'nexus-001'.
    """
    with get_connection() as conn:
        # --- Idempotency check ---
        existing = conn.execute(
            "SELECT agent_id FROM agent LIMIT 1"
        ).fetchone()

        if existing:
            existing_id = existing["agent_id"]
            logger.info(
                "Agent init called again — returning existing agent '%s'. "
                "No new agent spawned, no scheduler triggered.",
                existing_id,
            )
            return existing_id

        # --- First-time initialization ---
        # Count rows to generate a sequential, human-readable ID
        count = conn.execute("SELECT COUNT(*) FROM agent").fetchone()[0]
        agent_id = f"nexus-{count + 1:03d}"
        now_iso = datetime.now(timezone.utc).isoformat()

        conn.execute(
            """
            INSERT INTO agent (agent_id, persona_config, initialized_at, status)
            VALUES (?, ?, ?, ?)
            """,
            (agent_id, json.dumps(persona), now_iso, "active"),
        )
        logger.info(
            "Agent '%s' initialized with persona %s at %s",
            agent_id,
            persona,
            now_iso,
        )
        return agent_id


def get_agent(agent_id: str) -> dict | None:
    """
    Return the agent row as a dict, or None if no agent with that ID exists.
    Used by the feed endpoint to distinguish 404 from empty-feed.
    """
    with get_connection() as conn:
        row = conn.execute(
            "SELECT agent_id, status FROM agent WHERE agent_id = ?",
            (agent_id,),
        ).fetchone()
        return dict(row) if row else None


def get_feed(agent_id: str) -> list[dict]:
    """
    Return posts for the given agent, newest-first by createdAt.

    Defensive against the posts table not existing yet (Phase 5):
    catches sqlite3.OperationalError and returns [] rather than 500-ing.
    The caller is responsible for the 404 guard — call get_agent() first.

    Each post dict matches the wire shape:
        id, createdAt, text, rationale, sources (JSON list → Python list)
    """
    import json
    import sqlite3

    with get_connection() as conn:
        try:
            rows = conn.execute(
                """
                SELECT id, created_at AS createdAt, text, rationale, sources
                FROM   posts
                WHERE  agent_id = ?
                ORDER  BY created_at DESC
                """,
                (agent_id,),
            ).fetchall()
        except sqlite3.OperationalError as exc:
            # posts table doesn't exist yet — return empty feed, not a 500
            logger.info(
                "posts table not yet present (%s) — returning empty feed for '%s'.",
                exc,
                agent_id,
            )
            return []

    posts = []
    for row in rows:
        d = dict(row)
        # sources is stored as a JSON array string
        d["sources"] = json.loads(d.get("sources") or "[]")
        posts.append(d)
    return posts
