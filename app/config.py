"""
Loads environment variables via python-dotenv and exposes a single
Settings object that all other modules import.
"""

import os
from dotenv import load_dotenv

# Load .env from the project root (one level above this file)
load_dotenv()


class Settings:
    """
    Application-wide configuration, populated from environment variables.

    All attributes are @property so they are read from the environment at
    access time (not frozen at import time). Direct assignment is supported
    via an internal _overrides dict — used by tests to redirect DATABASE_PATH
    to a temporary file without polluting the real environment.
    """

    def __init__(self) -> None:
        # Mutable override store — allows ``settings.DATABASE_PATH = "/tmp/x.db"``
        # in tests without modifying os.environ or needing unittest.mock.patch.
        object.__setattr__(self, "_overrides", {})

    def __setattr__(self, name: str, value: object) -> None:
        self._overrides[name] = value

    def __getattr__(self, name: str) -> object:  # pragma: no cover
        # Fallback — only called for names not defined as @property on the class.
        overrides = object.__getattribute__(self, "_overrides")
        if name in overrides:
            return overrides[name]
        raise AttributeError(f"'Settings' object has no attribute {name!r}")

    def _get(self, key: str, default: str) -> str:
        """Read from overrides first, then os.environ, then default."""
        overrides: dict = object.__getattribute__(self, "_overrides")
        if key in overrides:
            return str(overrides[key])
        return os.getenv(key, default)

    # ------------------------------------------------------------------ #
    # LLM
    # ------------------------------------------------------------------ #

    @property
    def LLM_API_KEY(self) -> str:
        overrides: dict = object.__getattribute__(self, "_overrides")
        if "LLM_API_KEY" in overrides:
            return str(overrides["LLM_API_KEY"])
        return (
            os.getenv("LLM_API_KEY")
            or os.getenv("GEMINI_API_KEY")
            or os.getenv("GOOGLE_API_KEY")
            or ""
        )

    @property
    def LLM_MODEL(self) -> str:
        raw = self._get("LLM_MODEL", "gemini-2.0-flash").strip()
        if not raw or "2.5" in raw:
            return "gemini-2.0-flash"
        return raw

    # ------------------------------------------------------------------ #
    # Storage
    # ------------------------------------------------------------------ #

    @property
    def DATABASE_PATH(self) -> str:
        return self._get("DATABASE_PATH", "./data/nexus.db")

    # ------------------------------------------------------------------ #
    # Scheduler
    # ------------------------------------------------------------------ #

    @property
    def DISCOVERY_INTERVAL_SECONDS(self) -> int:
        return int(self._get("DISCOVERY_INTERVAL_SECONDS", "90"))

    # ------------------------------------------------------------------ #
    # Editorial thresholds (PRD §5.2)
    # ------------------------------------------------------------------ #

    @property
    def PUBLISH_THRESHOLD(self) -> float:
        return float(self._get("PUBLISH_THRESHOLD", "70.0"))

    @property
    def EVIDENCE_FLOOR(self) -> float:
        return float(self._get("EVIDENCE_FLOOR", "40.0"))

    # ------------------------------------------------------------------ #
    # Memory and Duplicate Detection (PRD §5.3)
    # ------------------------------------------------------------------ #

    @property
    def SIMILARITY_THRESHOLD(self) -> float:
        return float(self._get("SIMILARITY_THRESHOLD", "0.70"))

    @property
    def MEMORY_WINDOW_SIZE(self) -> int:
        return int(self._get("MEMORY_WINDOW_SIZE", "50"))

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
