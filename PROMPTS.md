# AI Usage Log (PROMPTS.md)

This log documents key AI-assisted decisions, prompts, generated components, and subsequent manual modifications throughout the development of **NEXUS — Autonomous AI Technology Analyst**.

---

## Log Entries

### Entry 1: Architecture & Foundation (Database Schema & Fast-Loading Data Access Layer)
- **Date**: 2026-08-08
- **Phase**: Database Design & Core Setup
- **Purpose**: Design the lightweight SQLite schema and data-access layer for `posts` and `topics_seen` adhering to PRD requirements without over-engineering (WAL mode, JSON serialization for sources/rationale).
- **Prompt Used**:
  > "Implement the data-access layer for NEXUS using SQLite in WAL mode with two tables: `posts` (tracking id, agent_id, topic, summary, created_at, generated_text, sources, editorial_score, decision, rationale) and `topics_seen` (tracking id, title, summary, source_url, discovered_at, similarity_ref). Include helper functions with connection management."
- **Generated Code/Architecture**:
  - `app/database.py` with `init_db()`, `get_connection()`, `insert_post()`, `get_posts_by_agent()`, `insert_topic_seen()`, `get_recent_topics()`.
- **Manual Modifications & Engineering**:
  - Added `_safe_json_loads` helper to protect against malformed JSON strings.
  - Added automatic directory creation for `./data/` so SQLite initializes cleanly in both local virtual environments and ephemeral container deployments on Render.

---

### Entry 2: API Contract & Idempotent Agent Lifecycle
- **Date**: 2026-08-08
- **Phase**: Core API Implementation (`app/main.py`)
- **Purpose**: Implement `POST /api/agent/init` and `GET /api/agent/feed` with strict input validation, idempotency guards, and spec-compliant error codes (404 for unknown agents, empty array for newly initialized agents).
- **Prompt Used**:
  > "Implement `POST /api/agent/init` and `GET /api/agent/feed` using FastAPI and Pydantic v2. Init must be idempotent (multiple calls return the same `agentId` without resetting state). Feed must return newest-first ISO 8601 UTC timestamps with `id`, `createdAt`, `text`, `rationale`, and `sources`."
- **Generated Code**:
  - `app/main.py` routing logic, `AgentInitRequest`, `AgentInitResponse`, `FeedResponse`, `PostItem`.
- **Manual Modifications & Engineering**:
  - Unified agent registration with in-memory set and database verification.
  - Added timezone-aware ISO 8601 formatting to guarantee RFC 3339 compliance.

---

### Entry 3: Multi-Source RSS Discovery & Topic Normalization
- **Date**: 2026-08-08
- **Phase**: Topic Discovery Engine (`app/discovery.py`)
- **Purpose**: Implement autonomous discovery across RSS/Atom feeds (GitHub releases, arXiv AI, Hacker News, Hugging Face) with per-source exception isolation and structured fallback fixtures for offline/isolated demo execution.
- **Prompt Used**:
  > "Build `app/discovery.py` using `feedparser` to fetch and normalize candidate topics across multiple tech feeds into a standardized dictionary: `{title, summary, source_url, published_at, raw_source}`. Ensure one broken feed does not fail the entire batch. Provide offline fallback fixtures for resilience."
- **Generated Code**:
  - Feed parsing loops with timeout handling and text sanitization.
  - Curated demo topic fixtures in `DEMO_TOPICS`.
- **Manual Modifications & Engineering**:
  - Added HTML tag stripping with regex for messy RSS feed summaries.
  - Added candidate truncation safeguards (max 8 candidates per batch) to keep LLM token latency and API rate limits manageable during continuous background execution.

---

### Entry 4: 5-Factor Weighted Editorial Scoring System
- **Date**: 2026-08-08
- **Phase**: Editorial Engine (`app/editor.py`)
- **Purpose**: Construct the structured LLM evaluation prompt that assesses candidates across 5 weighted dimensions (Relevance 30%, Novelty 25%, Technical Impact 20%, Evidence Quality 15%, Timeliness 10%) and returns strict JSON scoring.
- **Prompt Used**:
  > "Create an editorial scoring function using the Gemini API that evaluates tech news against NEXUS's niche and standing opinions. It must return structured JSON with 5 factor scores (0-100), factor justifications, a calculated composite score, and an evidence quality assessment."
- **Generated Prompt & Logic**:
  - System and user prompt templates defining the 5 rubric factors.
  - JSON parser extracting `factor_scores`, `justifications`, and `composite_score`.
- **Manual Modifications & Engineering**:
  - Enforced deterministic mathematical calculation of composite score in Python code (`0.30*R + 0.25*N + 0.20*TI + 0.15*EQ + 0.10*T`) rather than trusting the LLM's arithmetic.
  - Added 2-attempt retry loop with exponential backoff on JSON parse failure or rate limiting.

---

### Entry 5: Editorial Decision Engine & Hard Evidence Floor
- **Date**: 2026-08-08
- **Phase**: Decision Engine (`app/editor.py`)
- **Purpose**: Implement the dual-stage decision rule: composite score threshold check (>= 70 default) and non-negotiable hard floor rule (Evidence Quality < 40 forces REJECT).
- **Prompt Used**:
  > "Add `make_editorial_decision` in `app/editor.py`. If Evidence Quality < 40, force REJECT regardless of composite score with a distinct reason string. If composite >= 70 and floor passed, PUBLISH. Otherwise REJECT. Generate structured reasons for both outcomes."
- **Generated Code**:
  - `EditorialDecision` dataclass and threshold evaluation logic.
- **Manual Modifications & Engineering**:
  - Tailored explicit rejection strings (e.g. `Rejected: evidence quality (25/100) is below minimum floor (40/100) and composite score (45.8/100) failed threshold`) to make rejection reasons auditable and prominent in the dashboard.

---

### Entry 6: Grounded Content Synthesis & Faithful Rationale
- **Date**: 2026-08-08
- **Phase**: Generator Engine (`app/generator.py`)
- **Purpose**: Generate concise, technical commentary strictly grounded in the candidate's verified source material in NEXUS's persona voice, plus the PRD-required rationale object.
- **Prompt Used**:
  > "Implement `generate_post` in `app/generator.py`. Prompt the LLM in NEXUS's persona voice (dry, technical, skeptical of unverified claims). Instruct the model never to fabricate stats or quotes not present in source. Produce the PRD rationale object (`why_selected`, `why_relevant_now`, `editorial_score`)."
- **Generated Code**:
  - Generator system prompt and rationale assembly logic.
  - Persona configuration in `app/persona.py`.
- **Manual Modifications & Engineering**:
  - Reused factor justifications directly from the Phase 4 scoring step for `why_selected` and `why_relevant_now` to ensure rationale continuity rather than re-generating disconnected explanations.
  - Attached stance memory context to ensure opinion consistency across related topics over time.

---

### Entry 7: Deduplication & Stance Memory
- **Date**: 2026-08-08
- **Phase**: Memory Engine (`app/memory.py`)
- **Purpose**: Implement lightweight duplicate detection and stance continuity using TF-IDF cosine similarity without introducing heavy external vector databases.
- **Prompt Used**:
  > "Build `app/memory.py` using scikit-learn's `TfidfVectorizer` to calculate cosine similarity between a new candidate topic and recent entries in `topics_seen` and `posts`. If similarity > threshold (0.65), evaluate whether the candidate contains materially new information. Also record stance memory."
- **Generated Code**:
  - `check_duplicate()`, `record_stance()`, `get_stance_reference()`.
- **Manual Modifications & Engineering**:
  - Added fallback handling when `scikit-learn` vocabulary has fewer than 2 tokens.
  - Isolated duplicate checks to only compare against past items within a configurable lookback window (default 50 items).

---

### Entry 8: Autonomous APScheduler Integration
- **Date**: 2026-08-08
- **Phase**: Scheduler Engine (`app/scheduler.py`)
- **Purpose**: Create a self-sustaining background cycle running discovery -> score -> decide -> dedup -> generate -> persist on a configurable interval, started idempotently on first agent initialization.
- **Prompt Used**:
  > "Implement `app/scheduler.py` using `APScheduler` (AsyncIOScheduler). Start the scheduler on `POST /api/agent/init` if not already running. Guard against double-scheduling. Add a debug endpoint `POST /api/agent/trigger-cycle` to trigger immediate manual runs for testing."
- **Generated Code**:
  - `start_agent_scheduler()`, `trigger_cycle_now()`, `get_scheduler_status()`.
- **Manual Modifications & Engineering**:
  - Added execution locking (`_cycle_lock`) to prevent overlapping cycle executions if a long discovery/LLM cycle exceeds the polling interval.
  - Surfaced `last_llm_error` and `cycle_count` in scheduler status for live diagnostic observability.

---

### Entry 9: Dynamic Gemini Model Discovery & Deployment Configuration
- **Date**: 2026-08-08
- **Phase**: Deployment & API Resilience
- **Purpose**: Resolve Gemini API model naming differences across regions and API tiers dynamically (e.g. `gemini-2.0-flash`, `gemini-1.5-flash`, `gemini-flash-latest`) and prepare Render deployment files.
- **Prompt Used**:
  > "Add dynamic model fallback to `app/editor.py` and `app/generator.py`. Query `client.models.list()` on startup to discover available models for the provided API key and fall back gracefully across `gemini-2.0-flash`, `gemini-1.5-flash`, and `gemini-flash-latest`."
- **Generated Code**:
  - `discover_available_model()` dynamic probing logic.
  - `Procfile` and `render.yaml` deployment descriptors.
- **Manual Modifications & Engineering**:
  - Added support for both `GEMINI_API_KEY` and `LLM_API_KEY` environment variables so users can supply either key name seamlessly.
  - Verified end-to-end functionality on live Render deployment (`https://nexus-autonomous-ai-xwsh.onrender.com`).

---

### Entry 10: Equal-Weight Visual Demo Dashboard
- **Date**: 2026-08-08
- **Phase**: Dashboard (`app/dashboard.py`, `app/main.py`)
- **Purpose**: Build a lightweight, responsive server-rendered HTML dashboard that prominently displays published posts and rejected topics side-by-side with equal visual weight, persona rules, and live demo trigger buttons.
- **Prompt Used**:
  > "Build `app/dashboard.py` and add `GET /` and `GET /api/agent/dashboard-data` in `app/main.py`. The dashboard must display Agent Status + Persona Summary, Published Posts, and REJECTED topics with equal visual prominence in a 2-column layout, showing the exact stage and reason for rejection. Include a manual 'Trigger Demo Cycle' button."
- **Generated Code**:
  - `render_dashboard_html()` with vanilla CSS glassmorphism, responsive columns, and real-time JavaScript auto-polling.
- **Manual Modifications & Engineering**:
  - Fixed `PersonaConfig` attribute mappings (`niche`, `voice`, `standing_opinions`, `hard_rules`).
  - Added live status pills and factor radar badges (Relevance, Novelty, Technical Impact, Evidence Quality, Timeliness) for rapid judge inspection.
