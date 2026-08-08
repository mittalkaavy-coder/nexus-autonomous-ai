"""
Integrated autonomous pipeline for NEXUS (PRD §5.1 - §5.7).

Executes the full sequential editorial lifecycle:
  1. Discovery & Normalization (app.discovery)
  2. Record in `topics_seen` for all discovered items (app.database)
  3. Stage A Editorial Scoring & Decision (app.editor)
     - Hard evidence-floor (< 40) check
     - Composite score threshold (>= 70) check
     - Immediate REJECT persistence for failing topics
  4. Stage B Memory / Duplicate Check (app.memory)
     - TF-IDF Cosine Similarity against recent posts and topics_seen
     - Material novelty evaluation
     - REJECT persistence for duplicate topics
  5. Content Generation (app.generator)
     - Persona-grounded post text synthesis
     - Faithful PRD publishing rationale
  6. Persistence in `posts` table (app.database)
     - Stance memory update (app.memory)
"""

import hashlib
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.config import settings
from app.database import insert_post, insert_topic_seen
from app.discovery import discover_topics
from app.editor import make_editorial_decision, score_topic
from app.generator import generate_post
from app.memory import (
    check_duplicate,
    get_stance_reference,
    record_stance,
)

logger = logging.getLogger(__name__)


def _generate_topic_id(candidate: Dict[str, Any]) -> str:
    """Generate a stable, deterministic ID for a discovered topic."""
    url = candidate.get("source_url") or candidate.get("title", "")
    h = hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]
    return f"seen-{h}"


def _generate_post_id(prefix: str = "post") -> str:
    """Generate a unique post record ID."""
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def run_pipeline_cycle(
    agent_id: str = "nexus-001",
    use_demo_fixtures: bool = False,
    candidates_override: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Execute one full autonomous editorial discovery and publishing cycle.

    Args:
        agent_id: ID of the active agent persona (default: 'nexus-001').
        use_demo_fixtures: If True, uses offline demo fixtures instead of live RSS.
        candidates_override: Explicit list of candidate dicts to process (for testing/dry-runs).

    Returns:
        Summary dict containing counts and details of discovered, published, and rejected items.
    """
    now_iso = datetime.now(timezone.utc).isoformat()

    # -----------------------------------------------------------------------
    # Step 1: Topic Discovery
    # -----------------------------------------------------------------------
    if candidates_override is not None:
        candidates = candidates_override
    else:
        candidates = discover_topics(use_demo_fixtures=use_demo_fixtures)

    logger.info(
        "[pipeline] Starting editorial cycle for agent '%s' with %d candidate(s)",
        agent_id, len(candidates),
    )

    # -----------------------------------------------------------------------
    # Step 2: Log all discovered topics into topics_seen
    # -----------------------------------------------------------------------
    for cand in candidates:
        seen_id = _generate_topic_id(cand)
        try:
            insert_topic_seen(
                id=seen_id,
                title=cand.get("title", ""),
                summary=cand.get("summary", ""),
                source_url=cand.get("source_url", ""),
                discovered_at=cand.get("published_at") or now_iso,
                similarity_ref=None,
            )
        except Exception as exc:
            # If already logged, that's fine — continue
            logger.debug("[pipeline] insert_topic_seen note: %s", exc)

    published_count = 0
    rejected_count = 0
    skipped_count = 0
    cycle_results: List[Dict[str, Any]] = []

    # -----------------------------------------------------------------------
    # Process each candidate through Editorial Engine & Memory
    # -----------------------------------------------------------------------
    for cand in candidates:
        title = cand.get("title", "Untitled")
        logger.info("[pipeline] Evaluating candidate: '%s'", title[:60])

        # Step 3A: Editorial Scoring
        score_res = score_topic(cand)
        if score_res is None:
            logger.warning("[pipeline] Scoring failed for '%s' — skipping.", title[:50])
            skipped_count += 1
            continue

        # Step 3B: Stage A Editorial Decision (Score Threshold & Evidence Floor)
        decision = make_editorial_decision(cand, score_res)

        if decision.decision != "PUBLISH":
            # Stage A REJECT: Persist rejection immediately
            post_id = _generate_post_id("rej")
            insert_post(
                id=post_id,
                agent_id=agent_id,
                topic=cand.get("title", ""),
                summary=cand.get("summary", ""),
                created_at=now_iso,
                generated_text=None,
                sources=[cand["source_url"]] if cand.get("source_url") else [],
                editorial_score=score_res.composite_score,
                decision="REJECT",
                rationale=decision.rationale,
            )
            rejected_count += 1
            cycle_results.append({
                "id": post_id,
                "title": title,
                "decision": "REJECT",
                "stage": "Stage A (Editorial Rubric)",
                "reason": decision.summary_reason,
                "score": score_res.composite_score,
            })
            continue

        # -------------------------------------------------------------------
        # Step 4: Stage B Memory / Duplicate Check
        # (Only reached if candidate passed Stage A)
        # -------------------------------------------------------------------
        cand_id = _generate_topic_id(cand)
        dup_result = check_duplicate(cand, exclude_id=cand_id)

        if dup_result.is_duplicate:
            # Stage B REJECT: Duplicate detected
            post_id = _generate_post_id("dup")
            dup_rationale = {
                "why_selected": "N/A — rejected during duplicate evaluation.",
                "why_relevant_now": "N/A",
                "editorial_score": int(round(score_res.composite_score)),
                "rejection_stage": "Stage B (Duplicate Detection)",
                "duplicate_reason": dup_result.reason,
                "matched_reference_id": dup_result.matched_id,
                "matched_reference_title": dup_result.matched_title,
                "similarity_score": dup_result.similarity_score,
            }
            insert_post(
                id=post_id,
                agent_id=agent_id,
                topic=cand.get("title", ""),
                summary=cand.get("summary", ""),
                created_at=now_iso,
                generated_text=None,
                sources=[cand["source_url"]] if cand.get("source_url") else [],
                editorial_score=score_res.composite_score,
                decision="REJECT",
                rationale=dup_rationale,
            )
            rejected_count += 1
            cycle_results.append({
                "id": post_id,
                "title": title,
                "decision": "REJECT",
                "stage": "Stage B (Duplicate Check)",
                "reason": dup_result.reason,
                "score": score_res.composite_score,
                "similarity": dup_result.similarity_score,
            })
            continue

        # -------------------------------------------------------------------
        # Step 5: Content Generation (FINAL DECISION = PUBLISH)
        # -------------------------------------------------------------------
        # Enrich candidate context with stance memory reference if available
        stance_note = get_stance_reference(title, cand.get("summary", ""))
        post = generate_post(cand, score_res)

        if post is None:
            logger.warning("[pipeline] Content generation failed for '%s' — skipping persistence.", title[:50])
            skipped_count += 1
            continue

        # If stance reference exists, attach to publishing rationale
        if stance_note:
            post.rationale["stance_continuity"] = stance_note

        if dup_result.material_novelty and dup_result.matched_title:
            post.rationale["prior_relation"] = (
                f"Related to prior coverage of '{dup_result.matched_title}', with material update: {dup_result.novelty_note}"
            )

        # -------------------------------------------------------------------
        # Step 6: Persist PUBLISH Post
        # -------------------------------------------------------------------
        post_id = _generate_post_id("pub")
        insert_post(
            id=post_id,
            agent_id=agent_id,
            topic=post.topic,
            summary=post.summary,
            created_at=now_iso,
            generated_text=post.text,
            sources=post.sources,
            editorial_score=post.editorial_score,
            decision="PUBLISH",
            rationale=post.rationale,
        )

        # Update Stance Memory
        record_stance(
            topic=post.topic,
            decision="PUBLISH",
            rationale=post.rationale,
        )

        published_count += 1
        cycle_results.append({
            "id": post_id,
            "title": title,
            "decision": "PUBLISH",
            "stage": "Published",
            "reason": post.rationale.get("why_selected", "Passed editorial rubric and uniqueness checks."),
            "score": score_res.composite_score,
            "text_preview": post.text[:120] + "...",
            "rationale": post.rationale,
        })

    logger.info(
        "[pipeline] Editorial cycle complete. Published: %d, Rejected: %d, Skipped: %d",
        published_count, rejected_count, skipped_count,
    )

    return {
        "agent_id": agent_id,
        "total_candidates": len(candidates),
        "published": published_count,
        "rejected": rejected_count,
        "skipped": skipped_count,
        "results": cycle_results,
    }
