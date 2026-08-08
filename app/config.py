"""
Loads environment variables via python-dotenv and exposes a single
Settings object that all other modules import.
"""

import os
from dotenv import load_dotenv

# Load .env from the project root (one level above this file)
load_dotenv()


class Settings:
    """Application-wide configuration, populated from environment variables."""

    @property
    def LLM_API_KEY(self) -> str:
        return (
            os.getenv("LLM_API_KEY")
            or os.getenv("GEMINI_API_KEY")
            or os.getenv("GOOGLE_API_KEY")
            or ""
        )

    @property
    def LLM_MODEL(self) -> str:
        return os.getenv("LLM_MODEL", "gemini-2.0-flash")

    # Storage
    DATABASE_PATH: str = os.getenv("DATABASE_PATH", "./data/nexus.db")

    # Scheduler
    DISCOVERY_INTERVAL_SECONDS: int = int(
        os.getenv("DISCOVERY_INTERVAL_SECONDS", "90")
    )

    # Editorial thresholds (PRD §5.2)
    PUBLISH_THRESHOLD: float = float(os.getenv("PUBLISH_THRESHOLD", "70.0"))
    EVIDENCE_FLOOR: float = float(os.getenv("EVIDENCE_FLOOR", "40.0"))

    # Memory and Duplicate Detection (PRD §5.3)
    SIMILARITY_THRESHOLD: float = float(os.getenv("SIMILARITY_THRESHOLD", "0.70"))
    MEMORY_WINDOW_SIZE: int = int(os.getenv("MEMORY_WINDOW_SIZE", "50"))

    def __repr__(self) -> str:  # pragma: no cover
        key_preview = f"{self.LLM_API_KEY[:6]}…" if self.LLM_API_KEY else "<not set>"
        return (
            f"Settings("
            f"LLM_MODEL={self.LLM_MODEL!r}, "
            f"LLM_API_KEY={key_preview}, "
            f"DATABASE_PATH={self.DATABASE_PATH!r}, "
            f"DISCOVERY_INTERVAL_SECONDS={self.DISCOVERY_INTERVAL_SECONDS}, "
            f"PUBLISH_THRESHOLD={self.PUBLISH_THRESHOLD}, "
            f"EVIDENCE_FLOOR={self.EVIDENCE_FLOOR}, "
            f"SIMILARITY_THRESHOLD={self.SIMILARITY_THRESHOLD}, "
            f"MEMORY_WINDOW_SIZE={self.MEMORY_WINDOW_SIZE}"
            f")"
        )


# Singleton — import this everywhere
settings = Settings()
