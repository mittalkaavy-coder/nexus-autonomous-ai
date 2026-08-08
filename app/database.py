"""
Handles SQLite database setup and connection.
Plain sqlite3 (stdlib) chosen over SQLAlchemy Core — zero extra dependencies,
no ORM overhead, and NEXUS is a single-node app with simple flat tables.
"""

import sqlite3
import logging
from contextlib import contextmanager
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)


def init_db() -> None:
    """Create all tables if they don't already exist. Called once on server startup."""
    # Ensure the data directory exists
    Path(settings.DATABASE_PATH).parent.mkdir(parents=True, exist_ok=True)

    with get_connection() as conn:
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
    logger.info("Database ready at '%s'", settings.DATABASE_PATH)


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
