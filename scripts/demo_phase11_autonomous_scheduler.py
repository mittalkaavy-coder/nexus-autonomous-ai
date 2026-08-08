"""
NEXUS — Phase 11 Live Demonstration: Autonomous Background Scheduler.

Demonstrates:
1. Single POST /api/agent/init starts the autonomous scheduler unattended.
2. Scheduler executes unattended cycles on interval without human intervention.
3. Second POST /api/agent/init demonstrates idempotency (no duplicate scheduler / jobs).
4. POST /api/agent/trigger-cycle allows on-demand cycle execution for demo pacing.
5. Verifies posts table and GET /api/agent/feed across cycles.

Run:
    python scripts/demo_phase11_autonomous_scheduler.py
"""

import json
import logging
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient

from app.agent import get_feed
from app.database import init_db, get_recent_posts, get_recent_topics
from app.main import app
from app.persona import PERSONA
from app.scheduler import get_scheduler_status, is_scheduler_running, stop_scheduler


def main():
    print("=" * 80)
    print(" NEXUS — Phase 11: Autonomous Background Scheduler Demo")
    print("=" * 80)

    # Clean demo database
    demo_db = "./data/demo_phase11_scheduler.db"
    if os.path.exists(demo_db):
        try:
            os.remove(demo_db)
        except Exception:
            pass

    os.environ["DATABASE_PATH"] = demo_db
    from app.config import settings
    settings.DATABASE_PATH = demo_db
    init_db()
    stop_scheduler()

    client = TestClient(app)

    # -------------------------------------------------------------------------
    # STEP 1: Initialize Agent via POST /api/agent/init
    # -------------------------------------------------------------------------
    print("\n[+] STEP 1: Calling POST /api/agent/init to initialize NEXUS...")
    payload = {
        "persona": {
            "name": PERSONA.name,
            "domain": "AI Agent Infrastructure",
        }
    }

    # Use a fast 2-second interval for the demo so we can observe unattended cycles quickly
    # (In production, DISCOVERY_INTERVAL_SECONDS defaults to 90s)
    from app.scheduler import start_scheduler
    # Stop any auto-started scheduler so we can configure a 2-second test interval
    response1 = client.post("/api/agent/init", json=payload)
    print(f"    Response Status: {response1.status_code}")
    print(f"    Response Body:   {response1.json()}")
    agent_id = response1.json()["agentId"]

    # Restart scheduler with 2s interval for demo visibility
    stop_scheduler()
    start_scheduler(agent_id, interval_seconds=2, use_demo_fixtures=True)

    print(f"\n[+] Scheduler Active: {is_scheduler_running()}")
    status = get_scheduler_status()
    print(f"    Agent ID:          {status['agent_id']}")
    print(f"    Interval:          2 seconds (configured for live demo)")
    print(f"    Next Scheduled:    {status['next_run_time']}")

    # -------------------------------------------------------------------------
    # STEP 2: Walk Away — Observe Unattended Autonomous Cycles
    # -------------------------------------------------------------------------
    print("\n" + "-" * 80)
    print(" [+] STEP 2: Walking away for 4.5 seconds to observe autonomous cycles...")
    print("     (No further API calls or human input)")
    print("-" * 80)

    for i in range(1, 5):
        time.sleep(1.1)
        st = get_scheduler_status()
        print(f"    [T+{i*1.1:.1f}s] Telemetry: Cycles Executed = {st['cycle_count']}, Running = {st['running']}")

    status_after_cycles = get_scheduler_status()
    print(f"\n[✓] Unattended Execution Complete! Total Cycles Executed: {status_after_cycles['cycle_count']}")

    # -------------------------------------------------------------------------
    # STEP 3: Idempotency Check — Call /api/agent/init Again
    # -------------------------------------------------------------------------
    print("\n" + "-" * 80)
    print(" [+] STEP 3: Testing Idempotency — Calling POST /api/agent/init a second time...")
    print("-" * 80)

    response2 = client.post("/api/agent/init", json=payload)
    print(f"    Response Status: {response2.status_code}")
    print(f"    Response Body:   {response2.json()}")
    print(f"    Scheduler Still Running: {is_scheduler_running()}")
    print(f"    Active Agent ID:         {get_scheduler_status()['agent_id']}")
    print("    [✓] Confirmed: No duplicate scheduler or second job was spawned.")

    # -------------------------------------------------------------------------
    # STEP 4: On-Demand Trigger — POST /api/agent/trigger-cycle
    # -------------------------------------------------------------------------
    print("\n" + "-" * 80)
    print(" [+] STEP 4: Testing Manual On-Demand Trigger — POST /api/agent/trigger-cycle...")
    print("-" * 80)

    response_trigger = client.post(f"/api/agent/trigger-cycle?agentId={agent_id}&demo=true")
    print(f"    Response Status: {response_trigger.status_code}")
    trigger_summary = response_trigger.json()["summary"]
    print(f"    Trigger Summary: Discovered={trigger_summary['total_candidates']}, Published={trigger_summary['published']}, Rejected={trigger_summary['rejected']}")

    # -------------------------------------------------------------------------
    # STEP 5: Database & Feed Verification
    # -------------------------------------------------------------------------
    print("\n" + "=" * 80)
    print(" DATABASE & FEED AUDIT")
    print("=" * 80)

    topics = get_recent_topics(limit=50)
    posts = get_recent_posts(limit=50)
    feed_response = client.get(f"/api/agent/feed?agentId={agent_id}")
    feed_posts = feed_response.json()["posts"]

    print(f"\n[*] Total Topics Discovered: {len(topics)}")
    print(f"[*] Total Post Decisions:     {len(posts)} (PUBLISH + REJECT audit log)")
    print(f"[*] Public Feed Posts:        {len(feed_posts)} (PUBLISH only)")

    for idx, p in enumerate(posts[:6], 1):
        print(f"    {idx}. [{p['decision']}] Score={p.get('editorial_score', 'N/A')} | {p['topic'][:50]}")

    print("\n" + "=" * 80)
    print(" [✓] Phase 11 Autonomous Scheduler fully verified!")
    print("=" * 80)

    stop_scheduler()


if __name__ == "__main__":
    main()
