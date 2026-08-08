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
