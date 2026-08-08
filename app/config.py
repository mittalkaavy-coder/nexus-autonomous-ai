"""
Loads environment variables via python-dotenv — no business logic yet.
"""

import os
from dotenv import load_dotenv

load_dotenv()

LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "")
DATABASE_PATH = os.getenv("DATABASE_PATH", "./data/nexus.db")
DISCOVERY_INTERVAL_SECONDS = int(os.getenv("DISCOVERY_INTERVAL_SECONDS", "90"))
