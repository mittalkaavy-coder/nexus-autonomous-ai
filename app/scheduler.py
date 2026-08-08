"""
NEXUS — Autonomous Background Scheduler (PRD §5.7).

Uses APScheduler's BackgroundScheduler to run the full autonomous pipeline loop:
    discovery -> normalize -> score -> decide -> memory/dedup -> generate -> persist
at configured intervals (DISCOVERY_INTERVAL_SECONDS).

Key Guarantees:
1. Autonomous Operation: Starts once via POST /api/agent/init and runs unattended.
2. Idempotency Guard: Prevents double-scheduling if init is called repeatedly.
3. Concurrency Safety: max_instances=1 and execution lock prevent overlapping cycles.
4. Observability: Structured logging for cycle start, completion metrics, and errors.
5. On-Demand Trigger: Manual trigger mechanism for demo pacing and testing.
"""

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.config import settings
from app.pipeline import run_pipeline_cycle

logger = logging.getLogger(__name__)

# Module-level singleton state
_scheduler: Optional[BackgroundScheduler] = None
_scheduler_lock = threading.Lock()
_active_agent_id: Optional[str] = None
_cycle_count: int = 0
_last_cycle_summary: Optional[Dict[str, Any]] = None
_is_cycle_executing: bool = False
_cycle_exec_lock = threading.Lock()


def _scheduled_cycle_job(agent_id: str, use_demo_fixtures: bool = False) -> Optional[Dict[str, Any]]:
    """
    Job target executed by APScheduler on each interval tick.
    Guarded by `_cycle_exec_lock` to guarantee single-threaded cycle execution.
    """
    global _cycle_count, _last_cycle_summary, _is_cycle_executing

    # Non-blocking lock acquisition to prevent backlog if a cycle runs long
    if not _cycle_exec_lock.acquire(blocking=False):
        logger.warning(
            "[scheduler] Previous editorial cycle is still running for agent '%s' — skipping this tick.",
            agent_id,
        )
        return None

    t0 = time.time()
    _cycle_count += 1
    current_cycle = _cycle_count
    _is_cycle_executing = True

    now_iso = datetime.now(timezone.utc).isoformat()
    logger.info(
        "[scheduler] ==================== AUTONOMOUS CYCLE #%d START ====================",
        current_cycle,
    )
    logger.info(
        "[scheduler] Cycle #%d | Agent: '%s' | Time: %s | Demo Mode: %s",
        current_cycle, agent_id, now_iso, use_demo_fixtures,
    )

    try:
        summary = run_pipeline_cycle(
            agent_id=agent_id,
            use_demo_fixtures=use_demo_fixtures,
        )
        _last_cycle_summary = summary
        elapsed = time.time() - t0

        logger.info(
            "[scheduler] Cycle #%d COMPLETE in %.2fs — Discovered: %d | Published: %d | Rejected: %d | Skipped: %d",
            current_cycle,
            elapsed,
            summary.get("total_candidates", 0),
            summary.get("published", 0),
            summary.get("rejected", 0),
            summary.get("skipped", 0),
        )
        logger.info(
            "[scheduler] ==================== AUTONOMOUS CYCLE #%d END ======================",
            current_cycle,
        )
        return summary

    except Exception as exc:
        elapsed = time.time() - t0
        logger.exception(
            "[scheduler] Cycle #%d FAILED after %.2fs with error: %s",
            current_cycle, elapsed, exc,
        )
        return None

    finally:
        _is_cycle_executing = False
        _cycle_exec_lock.release()


def start_scheduler(
    agent_id: str,
    interval_seconds: Optional[int] = None,
    use_demo_fixtures: bool = False,
    run_immediately: bool = False,
) -> bool:
    """
    Start the autonomous background scheduler for the given agent.

    Guarded against double-scheduling:
    If a scheduler is already running, logs an informational notice and returns False
    without spawning another scheduler or duplicating jobs.

    Args:
        agent_id: The ID of the initialized agent persona.
        interval_seconds: Polling interval in seconds (default from settings: 90s).
        use_demo_fixtures: If True, uses demo fixtures instead of live RSS feeds.
        run_immediately: If True, triggers an immediate first cycle before regular ticks.

    Returns:
        True if the scheduler was newly started, False if it was already running.
    """
    global _scheduler, _active_agent_id

    with _scheduler_lock:
        if _scheduler is not None and _scheduler.running:
            logger.info(
                "[scheduler] Scheduler already active for agent '%s' (request for '%s' ignored — idempotent guard).",
                _active_agent_id, agent_id,
            )
            return False

        interval = interval_seconds or settings.DISCOVERY_INTERVAL_SECONDS
        _active_agent_id = agent_id

        # Instantiate daemon background scheduler
        _scheduler = BackgroundScheduler(daemon=True)

        # Schedule recurring interval job with max_instances=1 and coalesce=True
        _scheduler.add_job(
            _scheduled_cycle_job,
            trigger=IntervalTrigger(seconds=interval),
            id="nexus_editorial_loop",
            name="NEXUS Autonomous Editorial Loop",
            max_instances=1,
            coalesce=True,
            replace_existing=True,
            kwargs={
                "agent_id": agent_id,
                "use_demo_fixtures": use_demo_fixtures,
            },
        )

        _scheduler.start()

        logger.info(
            "[scheduler] Autonomous background scheduler STARTED for agent '%s' (Interval: %ds, Daemon: True)",
            agent_id, interval,
        )

        if run_immediately:
            logger.info("[scheduler] Executing immediate initial cycle on startup...")
            # Run in a separate thread to not block caller
            threading.Thread(
                target=_scheduled_cycle_job,
                args=(agent_id, use_demo_fixtures),
                daemon=True,
                name="nexus-initial-cycle",
            ).start()

        return True


def stop_scheduler() -> bool:
    """
    Gracefully shut down the background scheduler if running.

    Returns:
        True if stopped, False if was not running.
    """
    global _scheduler, _active_agent_id

    with _scheduler_lock:
        if _scheduler is not None and _scheduler.running:
            _scheduler.shutdown(wait=False)
            _scheduler = None
            _active_agent_id = None
            logger.info("[scheduler] Autonomous background scheduler STOPPED.")
            return True
        return False


def is_scheduler_running() -> bool:
    """Return True if the background scheduler is currently running."""
    with _scheduler_lock:
        return _scheduler is not None and _scheduler.running


def get_active_agent_id() -> Optional[str]:
    """Return the ID of the agent currently being serviced by the scheduler."""
    return _active_agent_id


def get_scheduler_status() -> Dict[str, Any]:
    """
    Return operational telemetry and health status for the scheduler.
    """
    with _scheduler_lock:
        running = _scheduler is not None and _scheduler.running
        next_run = None
        if running and _scheduler:
            job = _scheduler.get_job("nexus_editorial_loop")
            if job and job.next_run_time:
                next_run = job.next_run_time.isoformat()

        from app.editor import get_last_scoring_error

        return {
            "running": running,
            "agent_id": _active_agent_id,
            "has_llm_key": bool(settings.LLM_API_KEY),
            "llm_model": settings.LLM_MODEL,
            "last_llm_error": get_last_scoring_error(),
            "interval_seconds": settings.DISCOVERY_INTERVAL_SECONDS,
            "cycle_count": _cycle_count,
            "is_cycle_executing": _is_cycle_executing,
            "next_run_time": next_run,
            "last_cycle_summary": _last_cycle_summary,
        }


def trigger_cycle_now(
    agent_id: Optional[str] = None,
    use_demo_fixtures: bool = False,
    candidates_override: Optional[list] = None,
) -> Dict[str, Any]:
    """
    Manually trigger one editorial cycle immediately for demo/testing convenience.

    This function can be called synchronously from the debug endpoint
    POST /api/agent/trigger-cycle.

    Args:
        agent_id: Optional agent ID (defaults to active agent or 'nexus-001').
        use_demo_fixtures: If True, uses offline demo topics.
        candidates_override: Optional list of specific candidates to test.

    Returns:
        The pipeline summary dict.
    """
    target_agent = agent_id or _active_agent_id or "nexus-001"
    logger.info("[scheduler] Manual cycle triggered on demand for agent '%s'", target_agent)

    # Directly run one pipeline cycle
    if candidates_override is not None:
        summary = run_pipeline_cycle(
            agent_id=target_agent,
            candidates_override=candidates_override,
        )
    else:
        summary = run_pipeline_cycle(
            agent_id=target_agent,
            use_demo_fixtures=use_demo_fixtures,
        )

    global _last_cycle_summary
    _last_cycle_summary = summary
    return summary
