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
    Return PUBLISH-decision posts for the given agent, newest-first.

    The caller is responsible for the 404 guard — call get_agent() first.
    Empty state returns [] without error; rejected posts are excluded.

    Each returned dict matches the API wire shape exactly:
        id, createdAt (ISO 8601 UTC), text, rationale (dict), sources (list[str])
    """
    import json

    from app.database import get_posts_by_agent

    all_posts = get_posts_by_agent(agent_id)

    feed = []
    for post in all_posts:
        if post.get("decision") != "PUBLISH":
            continue
        feed.append(
            {
                "id": post["id"],
                "createdAt": post["created_at"],   # ISO 8601 UTC
                "text": post.get("generated_text") or "",
                "rationale": post.get("rationale", {}),
                "sources": post.get("sources", []),
            }
        )
    return feed
