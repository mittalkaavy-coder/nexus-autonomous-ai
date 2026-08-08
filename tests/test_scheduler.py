"""
Unit and integration tests for Phase 11: Autonomous Background Scheduler.

Tests:
1. Scheduler start, stop, and running status.
2. Idempotent startup guard against double-scheduling.
3. Manual cycle trigger mechanism.
4. FastAPI POST /api/agent/init starts scheduler autonomously.
5. Multiple /api/agent/init calls remain idempotent without creating duplicate jobs.
6. FastAPI POST /api/agent/trigger-cycle manual endpoint.
7. Autonomous interval execution (verifies unattended multi-cycle runs).

Run:
    python tests/test_scheduler.py
"""

import os
import sys
import time
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.database import init_db
from app.main import app
from app.persona import PERSONA
from app.scheduler import (
    get_scheduler_status,
    is_scheduler_running,
    start_scheduler,
    stop_scheduler,
    trigger_cycle_now,
)


class TestScheduler(unittest.TestCase):

    def setUp(self):
        self.test_db = f"./data/test_sched_{self._testMethodName}.db"
        os.environ["DATABASE_PATH"] = self.test_db
        from app.config import settings
        settings.DATABASE_PATH = self.test_db
        init_db()

        # Stop any background scheduler left over from previous tests
        stop_scheduler()

    def tearDown(self):
        stop_scheduler()
        if os.path.exists(self.test_db):
            try:
                os.remove(self.test_db)
            except Exception:
                pass

    def test_scheduler_start_and_stop(self):
        """Verify scheduler starts, reports running state, and stops cleanly."""
        self.assertFalse(is_scheduler_running())

        started = start_scheduler("nexus-test-001", interval_seconds=60)
        self.assertTrue(started)
        self.assertTrue(is_scheduler_running())

        status = get_scheduler_status()
        self.assertTrue(status["running"])
        self.assertEqual(status["agent_id"], "nexus-test-001")
        self.assertIsNotNone(status["next_run_time"])

        stopped = stop_scheduler()
        self.assertTrue(stopped)
        self.assertFalse(is_scheduler_running())

    def test_scheduler_idempotency_guard(self):
        """Verify that calling start_scheduler multiple times does NOT start duplicate schedulers."""
        started_first = start_scheduler("nexus-test-001", interval_seconds=60)
        self.assertTrue(started_first)

        # Second call should be ignored by idempotency guard
        started_second = start_scheduler("nexus-test-001", interval_seconds=60)
        self.assertFalse(started_second)
        self.assertTrue(is_scheduler_running())

        # Third call with different agent ID should also be ignored while running
        started_third = start_scheduler("nexus-test-002", interval_seconds=30)
        self.assertFalse(started_third)
        self.assertEqual(get_scheduler_status()["agent_id"], "nexus-test-001")

    @patch("app.scheduler.run_pipeline_cycle")
    def test_manual_trigger_cycle(self, mock_cycle):
        """Verify trigger_cycle_now executes pipeline cycle synchronously."""
        mock_cycle.return_value = {
            "agent_id": "nexus-001",
            "total_candidates": 2,
            "published": 1,
            "rejected": 1,
            "skipped": 0,
            "results": [],
        }

        res = trigger_cycle_now(agent_id="nexus-001", use_demo_fixtures=True)
        self.assertEqual(res["published"], 1)
        mock_cycle.assert_called_once_with(agent_id="nexus-001", use_demo_fixtures=True)

    @patch("app.scheduler.run_pipeline_cycle")
    def test_api_init_starts_scheduler(self, mock_cycle):
        """Verify that POST /api/agent/init starts the scheduler autonomously."""
        client = TestClient(app)

        payload = {
            "persona": {
                "name": PERSONA.name,
                "domain": "AI Agent Infrastructure",
            }
        }

        response = client.post("/api/agent/init", json=payload)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(is_scheduler_running())

        # Verify idempotency: calling /api/agent/init again returns 200 without error
        response2 = client.post("/api/agent/init", json=payload)
        self.assertEqual(response2.status_code, 200)
        self.assertEqual(response2.json()["agentId"], response.json()["agentId"])
        self.assertTrue(is_scheduler_running())

    @patch("app.scheduler.run_pipeline_cycle")
    def test_api_trigger_cycle_endpoint(self, mock_cycle):
        """Verify POST /api/agent/trigger-cycle endpoint forces an immediate cycle."""
        mock_cycle.return_value = {
            "agent_id": "nexus-001",
            "total_candidates": 3,
            "published": 2,
            "rejected": 1,
            "skipped": 0,
            "results": [],
        }

        client = TestClient(app)
        response = client.post("/api/agent/trigger-cycle?agentId=nexus-001&demo=true")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["summary"]["published"], 2)

    @patch("app.scheduler.run_pipeline_cycle")
    def test_autonomous_interval_execution(self, mock_cycle):
        """
        Verify unattended autonomous execution:
        With a 1-second interval, wait 2.3 seconds and verify at least 2 cycles ran.
        """
        mock_cycle.return_value = {
            "agent_id": "nexus-auto-test",
            "total_candidates": 1,
            "published": 1,
            "rejected": 0,
            "skipped": 0,
            "results": [],
        }

        start_scheduler("nexus-auto-test", interval_seconds=1)
        self.assertTrue(is_scheduler_running())

        # Wait for 2.3 seconds so at least 2 ticks fire autonomously
        time.sleep(2.3)

        self.assertGreaterEqual(mock_cycle.call_count, 2)
        status = get_scheduler_status()
        self.assertGreaterEqual(status["cycle_count"], 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
