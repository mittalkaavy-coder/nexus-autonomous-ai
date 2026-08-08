"""
Manual smoke test for Phase 5 — posts table + feed endpoint.

Steps:
  1. Ensure the DB and tables are created.
  2. Ensure the NEXUS agent exists (insert if not present).
  3. Insert one fake PUBLISH post via insert_post().
  4. Call the feed endpoint through the FastAPI TestClient.
  5. Validate the response shape against the API contract exactly.
  6. Delete the fake post — leave the DB clean before Phase 6.

Run from the project root:
    python tests/test_phase5_posts.py
"""

import json
import sys
import os

# Make sure 'app' is importable from the project root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient

from app.main import app
from app.database import init_db, insert_post, get_posts_by_agent, get_connection

# ---------------------------------------------------------------------------
# Test data
# ---------------------------------------------------------------------------

FAKE_AGENT_ID = "nexus-001"

FAKE_POST = {
    "id": "post-phase5-smoke",
    "agent_id": FAKE_AGENT_ID,
    "topic": "OpenAI releases GPT-5 system card",
    "summary": "OpenAI published a detailed system card for GPT-5, including eval methodology and safety mitigations.",
    "created_at": "2026-08-08T10:00:00+00:00",
    "generated_text": (
        "OpenAI released the GPT-5 system card on 8 Aug 2026. "
        "The document details red-team methodology, RLHF pipeline changes, "
        "and new refusal benchmarks. Primary source: openai.com/research/gpt-5-system-card."
    ),
    "sources": ["https://openai.com/research/gpt-5-system-card"],
    "editorial_score": 87.5,
    "decision": "PUBLISH",
    "rationale": {
        "why_selected": "Primary source published by OpenAI; directly relevant to AI agent infrastructure.",
        "why_relevant_now": "System card release is the canonical artifact for evaluating safety claims.",
        "editorial_score": 87.5,
    },
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def ensure_agent_exists():
    """Insert the agent row if it isn't there so the feed endpoint returns 200."""
    import json
    from datetime import datetime, timezone

    with get_connection() as conn:
        exists = conn.execute(
            "SELECT 1 FROM agent WHERE agent_id = ?", (FAKE_AGENT_ID,)
        ).fetchone()
        if not exists:
            conn.execute(
                "INSERT INTO agent (agent_id, persona_config, initialized_at, status) VALUES (?, ?, ?, ?)",
                (
                    FAKE_AGENT_ID,
                    json.dumps({"name": "NEXUS", "domain": "AI Technology"}),
                    datetime.now(timezone.utc).isoformat(),
                    "active",
                ),
            )
            print(f"  [setup] Inserted agent '{FAKE_AGENT_ID}'.")
        else:
            print(f"  [setup] Agent '{FAKE_AGENT_ID}' already exists — skipping insert.")


def delete_fake_post():
    """Remove the smoke-test post so the DB is clean for Phase 6."""
    with get_connection() as conn:
        conn.execute("DELETE FROM posts WHERE id = ?", (FAKE_POST["id"],))
    print(f"  [cleanup] Deleted post '{FAKE_POST['id']}' — posts table is clean.")


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------

def pre_cleanup():
    """Remove any leftover fake post from a previous failed run so re-runs are idempotent."""
    with get_connection() as conn:
        conn.execute("DELETE FROM posts WHERE id = ?", (FAKE_POST["id"],))


def run_test():
    print("\n=== Phase 5 Manual Smoke Test ===\n")

    # 1. Init DB
    init_db()
    print("[1] DB initialised -- tables created (or already exist).")

    # 2. Ensure agent row exists
    ensure_agent_exists()
    print("[2] Agent row verified.")

    # Pre-cleanup: remove fake post from any previous failed run
    pre_cleanup()
    print("[2b] Pre-cleanup done (idempotent re-run safety).\n")

    # 3. Insert fake post
    insert_post(**FAKE_POST)
    print(f"[3] Inserted fake post '{FAKE_POST['id']}' via insert_post().")

    # Verify it's in the DB
    rows = get_posts_by_agent(FAKE_AGENT_ID)
    assert any(r["id"] == FAKE_POST["id"] for r in rows), "Post not found in DB after insert!"
    print(f"    Confirmed in DB — get_posts_by_agent() returned {len(rows)} row(s).\n")

    # 4. Call the feed endpoint
    client = TestClient(app)
    response = client.get(f"/api/agent/feed?agentId={FAKE_AGENT_ID}")

    print(f"[4] GET /api/agent/feed?agentId={FAKE_AGENT_ID}")
    print(f"    HTTP status: {response.status_code}")
    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"

    body = response.json()
    print(f"    Response body:\n{json.dumps(body, indent=4)}\n")

    # 5. Validate shape against API contract
    print("[5] Validating response against API contract ...")

    assert "posts" in body, "Missing top-level 'posts' key."
    assert isinstance(body["posts"], list), "'posts' must be a list."

    # Find our fake post in the response
    matching = [p for p in body["posts"] if p["id"] == FAKE_POST["id"]]
    assert len(matching) == 1, f"Expected 1 matching post, got {len(matching)}."
    post = matching[0]

    # --- Field names ---
    required_fields = {"id", "createdAt", "text", "rationale", "sources"}
    missing = required_fields - set(post.keys())
    assert not missing, f"Missing fields in feed post: {missing}"
    print("    [PASS] All required fields present: id, createdAt, text, rationale, sources")

    # --- Field values ---
    assert post["id"] == FAKE_POST["id"], f"id mismatch: {post['id']}"
    print(f"    [PASS] id = '{post['id']}'")

    # createdAt must be ISO 8601 UTC (contains 'T' and ends with Z or +00:00)
    created_at = post["createdAt"]
    assert "T" in created_at, f"createdAt not ISO 8601: '{created_at}'"
    assert created_at.endswith("Z") or "+00:00" in created_at or "Z" in created_at, (
        f"createdAt not UTC: '{created_at}'"
    )
    print(f"    [PASS] createdAt = '{created_at}' (ISO 8601 UTC)")

    assert post["text"] == FAKE_POST["generated_text"], "text field mismatch."
    print("    [PASS] text matches generated_text")

    assert isinstance(post["sources"], list), "sources must be a list."
    assert post["sources"] == FAKE_POST["sources"], f"sources mismatch: {post['sources']}"
    print(f"    [PASS] sources = {post['sources']}")

    assert post["rationale"] == FAKE_POST["rationale"], f"rationale mismatch: {post['rationale']}"
    print("    [PASS] rationale matches (dict with why_selected, why_relevant_now, editorial_score)")

    print("\n    [ALL PASSED] All contract assertions passed.\n")

    # 6. Cleanup
    delete_fake_post()

    # Verify cleanup
    rows_after = get_posts_by_agent(FAKE_AGENT_ID)
    publish_rows = [r for r in rows_after if r["decision"] == "PUBLISH"]
    assert not any(r["id"] == FAKE_POST["id"] for r in rows_after), "Fake post still in DB after cleanup!"
    print(f"    Verified: posts table has {len(publish_rows)} PUBLISH row(s) remaining (fake post gone).")

    print("\n=== Test PASSED -- DB is clean, ready for Phase 6 ===\n")


if __name__ == "__main__":
    run_test()
