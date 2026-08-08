"""
Editorial evaluation and decision engine for NEXUS.

Stage A of the editorial pipeline (PRD §5.2, §5.3):
1. Scores a normalized topic candidate across the 5 PRD-defined factors using the LLM.
2. Computes the weighted composite score:
       Relevance        20%
       Novelty          15%
       Technical Impact 25%
       Evidence Quality 20%
       Timeliness       20%
3. Applies editorial decision rules:
       - Hard evidence floor: Evidence Quality < evidence_floor (default 40)
         forces REJECT regardless of composite score, producing a distinct
         non-negotiable reason string.
       - Composite score >= publish_threshold (default 70) -> PUBLISH
       - Composite score < publish_threshold -> REJECT
4. Generates a structured rationale object and a human-readable summary reason
   for every decision (both PUBLISH and REJECT).

Stage B (Memory / duplicate check) is applied in Phase 9 only to candidates
that pass Stage A with PUBLISH.
"""

import json
import logging
import re
import textwrap
import time
from typing import Any, Optional

from app.config import settings
from app.persona import PERSONA

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Weights — locked per PRD §5.2
# ---------------------------------------------------------------------------

WEIGHTS: dict[str, float] = {
    "relevance": 0.20,
    "novelty": 0.15,
    "technical_impact": 0.25,
    "evidence_quality": 0.20,
    "timeliness": 0.20,
}

# LLM call config
_TEMPERATURE: float = 0.2       # Low temp for consistent, structured scoring
_MAX_OUTPUT_TOKENS: int = 2048  # Ample space for 5 verbose factor justifications
_RETRY_DELAY_SECONDS: float = 3.0


# ---------------------------------------------------------------------------
# Score result
# ---------------------------------------------------------------------------


class ScoreResult:
    """
    Holds the LLM-produced factor scores, their justifications, and the
    weighted composite score computed locally (not by the LLM).
    """

    __slots__ = (
        "relevance",
        "novelty",
        "technical_impact",
        "evidence_quality",
        "timeliness",
        "justifications",
        "composite_score",
    )

    def __init__(
        self,
        relevance: float,
        novelty: float,
        technical_impact: float,
        evidence_quality: float,
        timeliness: float,
        justifications: dict[str, str],
    ) -> None:
        self.relevance = relevance
        self.novelty = novelty
        self.technical_impact = technical_impact
        self.evidence_quality = evidence_quality
        self.timeliness = timeliness
        self.justifications = justifications
        self.composite_score = self._compute_composite()

    def _compute_composite(self) -> float:
        return round(
            self.relevance          * WEIGHTS["relevance"]
            + self.novelty          * WEIGHTS["novelty"]
            + self.technical_impact * WEIGHTS["technical_impact"]
            + self.evidence_quality * WEIGHTS["evidence_quality"]
            + self.timeliness       * WEIGHTS["timeliness"],
            2,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "factor_scores": {
                "relevance":        self.relevance,
                "novelty":          self.novelty,
                "technical_impact": self.technical_impact,
                "evidence_quality": self.evidence_quality,
                "timeliness":       self.timeliness,
            },
            "composite_score": self.composite_score,
            "justifications":  self.justifications,
        }

    def __repr__(self) -> str:
        return (
            f"ScoreResult(composite={self.composite_score}, "
            f"relevance={self.relevance}, novelty={self.novelty}, "
            f"technical_impact={self.technical_impact}, "
            f"evidence_quality={self.evidence_quality}, "
            f"timeliness={self.timeliness})"
        )


# ---------------------------------------------------------------------------
# Editorial decision result
# ---------------------------------------------------------------------------


class EditorialDecision:
    """
    Complete editorial decision for a candidate topic.
    Includes decision outcome ('PUBLISH' | 'REJECT'), human-readable reason,
    full factor breakdown, and structured rationale dictionary suitable
    for SQLite persistence and API presentation.
    """

    __slots__ = (
        "candidate",
        "score_result",
        "decision",
        "publish_threshold",
        "evidence_floor",
        "evidence_floor_triggered",
        "summary_reason",
        "rationale",
    )

    def __init__(
        self,
        candidate: dict[str, Any],
        score_result: ScoreResult,
        decision: str,
        publish_threshold: float,
        evidence_floor: float,
        evidence_floor_triggered: bool,
        summary_reason: str,
        rationale: dict[str, Any],
    ) -> None:
        self.candidate = candidate
        self.score_result = score_result
        self.decision = decision
        self.publish_threshold = publish_threshold
        self.evidence_floor = evidence_floor
        self.evidence_floor_triggered = evidence_floor_triggered
        self.summary_reason = summary_reason
        self.rationale = rationale

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.candidate.get("title", ""),
            "source_url": self.candidate.get("source_url", ""),
            "decision": self.decision,
            "composite_score": self.score_result.composite_score,
            "publish_threshold": self.publish_threshold,
            "evidence_floor": self.evidence_floor,
            "evidence_floor_triggered": self.evidence_floor_triggered,
            "summary_reason": self.summary_reason,
            "factor_scores": self.score_result.to_dict()["factor_scores"],
            "rationale": self.rationale,
        }

    def __repr__(self) -> str:
        return (
            f"EditorialDecision(decision={self.decision!r}, "
            f"composite={self.score_result.composite_score}, "
            f"floor_triggered={self.evidence_floor_triggered}, "
            f"title={self.candidate.get('title', '')[:50]!r})"
        )


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

def _build_scoring_prompt(candidate: dict[str, Any]) -> str:
    """
    Build the scoring prompt that is sent to the LLM.

    The prompt embeds:
      - NEXUS's niche (so the LLM scores relevance correctly)
      - NEXUS's standing editorial opinions (so EvidenceQuality and Novelty
        reflect actual editorial skepticism, not generic vibes)
      - Evidence Quality guardrails (per PRD §5.2)
      - Strict JSON-only output requirement
    """
    niche_str = "\n".join(f"  - {n}" for n in PERSONA.niche)
    exclusions_str = "\n".join(f"  - {e}" for e in PERSONA.niche_exclusions)
    opinions_str = "\n".join(f"  {i+1}. {op}" for i, op in enumerate(PERSONA.standing_opinions))

    title   = candidate.get("title", "")
    summary = candidate.get("summary", "")
    source  = candidate.get("source_url", "")
    snippet = textwrap.shorten(candidate.get("raw_snippet", summary), width=600, placeholder="…")
    pub_at  = candidate.get("published_at", "")

    return f"""You are the editorial scoring engine for NEXUS, an autonomous AI technology analyst.

NEXUS covers this niche:
{niche_str}

NEXUS explicitly ignores:
{exclusions_str}

NEXUS's standing editorial opinions (apply these to your scoring):
{opinions_str}

---

Score the following candidate topic across FIVE factors (each 0–100):

CANDIDATE:
  Title:        {title}
  Summary:      {summary}
  Source URL:   {source}
  Published at: {pub_at}
  Snippet:      {snippet}

---

FACTOR DEFINITIONS:

1. relevance (weight 20%)
   How directly does this topic fall within NEXUS's niche? 0 = off-topic, 100 = core niche.

2. novelty (weight 15%)
   Is this genuinely new information or a rehash of already-covered ground?
   Apply NEXUS's skepticism — blog posts restating known techniques score low.

3. technical_impact (weight 25%)
   How significant is the technical change, release, or finding?
   A new framework capability, architecture, or benchmark matters more than meta-commentary.

4. evidence_quality (weight 20%)
   Apply the following HARD GUARDRAILS — these are non-negotiable:
   - No verifiable source at all → score MUST be 0–25.
   - Secondary article or blog with no primary artifact → score MUST be 25–45.
   - Verifiable primary source (official release note, repo, paper, spec, first-party announcement) → score may be 50–80.
   - Reproducible implementation, benchmark, eval, or independently verifiable technical artifact → score may be 70–100.
   Do NOT let promotional language push the score above these ranges. Be strict.

5. timeliness (weight 20%)
   How time-sensitive is this? Breaking infrastructure changes, fresh releases, or newly published
   papers score higher than evergreen tutorials or historical retrospectives.

---

Return ONLY a JSON object — no preamble, no explanation, no markdown fences. Exact schema:

{{
  "relevance":        <int 0-100>,
  "novelty":          <int 0-100>,
  "technical_impact": <int 0-100>,
  "evidence_quality": <int 0-100>,
  "timeliness":       <int 0-100>,
  "justifications": {{
    "relevance":        "<one sentence>",
    "novelty":          "<one sentence>",
    "technical_impact": "<one sentence>",
    "evidence_quality": "<one sentence>",
    "timeliness":       "<one sentence>"
  }}
}}"""


# ---------------------------------------------------------------------------
# LLM client helper
# ---------------------------------------------------------------------------

def _call_llm(prompt: str) -> str:
    """
    Call the configured Gemini model with the given prompt.
    Returns the raw text response string.
    Raises on any API/network error — let the caller handle retries.
    """
    from google import genai  # type: ignore

    client = genai.Client(api_key=settings.LLM_API_KEY)
    models_to_try = [settings.LLM_MODEL, "gemini-2.0-flash", "gemini-1.5-flash"]
    seen = set()
    deduped_models = [m for m in models_to_try if not (m in seen or seen.add(m))]

    last_exc = None
    for model_name in deduped_models:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=genai.types.GenerateContentConfig(
                    temperature=_TEMPERATURE,
                    max_output_tokens=_MAX_OUTPUT_TOKENS,
                ),
            )
            return response.text
        except Exception as exc:
            last_exc = exc
            logger.warning(
                "[editor] LLM call with model '%s' failed: %s — trying next fallback if available",
                model_name, exc,
            )
    if last_exc:
        raise last_exc
    raise RuntimeError("No LLM models available to execute prompt")


# ---------------------------------------------------------------------------
# JSON extraction
# ---------------------------------------------------------------------------

def _extract_json(raw: str) -> dict[str, Any]:
    """
    Parse LLM output defensively:
    1. Strip any markdown code fences (```json … ``` or ``` … ```)
    2. Extract the first {...} block
    3. json.loads it

    Raises ValueError if parsing fails — caller handles it.
    """
    text = re.sub(r"```(?:json)?\s*", "", raw).strip()
    text = re.sub(r"```\s*$", "", text).strip()

    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError(f"No JSON object found in LLM response: {text[:200]!r}")

    return json.loads(match.group())


# ---------------------------------------------------------------------------
# Score validation
# ---------------------------------------------------------------------------

_REQUIRED_FACTORS = frozenset(
    ["relevance", "novelty", "technical_impact", "evidence_quality", "timeliness"]
)


def _validate_and_clamp(data: dict[str, Any]) -> ScoreResult:
    """
    Validate parsed LLM JSON and build a ScoreResult.
    Clamps all factor scores to [0, 100].
    Raises ValueError if required keys are missing.
    """
    missing = _REQUIRED_FACTORS - set(data.keys())
    if missing:
        raise ValueError(f"LLM response missing factor keys: {missing}")

    def clamp(v: Any) -> float:
        try:
            return max(0.0, min(100.0, float(v)))
        except (TypeError, ValueError):
            raise ValueError(f"Non-numeric factor score: {v!r}")

    justifications = data.get("justifications", {})
    if not isinstance(justifications, dict):
        justifications = {}

    return ScoreResult(
        relevance=clamp(data["relevance"]),
        novelty=clamp(data["novelty"]),
        technical_impact=clamp(data["technical_impact"]),
        evidence_quality=clamp(data["evidence_quality"]),
        timeliness=clamp(data["timeliness"]),
        justifications={
            k: str(justifications.get(k, ""))
            for k in _REQUIRED_FACTORS
        },
    )


# ---------------------------------------------------------------------------
# Rationale and reason builder
# ---------------------------------------------------------------------------

def _build_decision_rationale(
    candidate: dict[str, Any],
    score_result: ScoreResult,
    threshold: float,
    evidence_floor: float,
) -> tuple[str, bool, str, dict[str, Any]]:
    """
    Analyze scores and compute:
      (decision, floor_triggered, summary_reason, structured_rationale)

    Enforces:
      1. Hard floor rule: Evidence Quality < evidence_floor -> REJECT
         Must produce a distinct, clear reason identifying the evidence floor breach.
      2. Composite >= threshold -> PUBLISH with detailed strengths breakdown.
      3. Composite < threshold -> REJECT with detailed drag factors breakdown.
    """
    comp = score_result.composite_score
    eq = score_result.evidence_quality
    floor_triggered = eq < evidence_floor

    factor_map = {
        "relevance": score_result.relevance,
        "novelty": score_result.novelty,
        "technical_impact": score_result.technical_impact,
        "evidence_quality": score_result.evidence_quality,
        "timeliness": score_result.timeliness,
    }

    if floor_triggered:
        decision = "REJECT"
        eq_just = score_result.justifications.get("evidence_quality", "").strip()
        if comp >= threshold:
            summary_reason = (
                f"Rejected: evidence quality ({eq:.0f}/100) is below the minimum floor ({evidence_floor:.0f}/100) "
                f"despite a qualifying composite score of {comp:.1f}/100 (threshold: {threshold:.0f}/100). "
                f"Evidence rationale: {eq_just or 'Unverifiable claims or secondary source without primary technical artifact.'}"
            )
        else:
            summary_reason = (
                f"Rejected: evidence quality ({eq:.0f}/100) is below the minimum floor ({evidence_floor:.0f}/100) "
                f"and composite score ({comp:.1f}/100) failed threshold ({threshold:.0f}/100). "
                f"Evidence rationale: {eq_just or 'Insufficient verifiable evidence.'}"
            )

        # Dragging factors
        low_factors = [
            f"{k.replace('_', ' ').title()} ({v:.0f}/100, weight {int(WEIGHTS[k]*100)}%)"
            for k, v in factor_map.items()
            if v < 60
        ]

        rationale: dict[str, Any] = {
            "decision": "REJECT",
            "composite_score": comp,
            "publish_threshold": threshold,
            "evidence_floor": evidence_floor,
            "evidence_floor_triggered": True,
            "summary_reason": summary_reason,
            "factor_scores": factor_map,
            "primary_violation": (
                f"Evidence Quality ({eq:.0f}/100) failed mandatory floor ({evidence_floor:.0f}/100)"
            ),
            "drag_factors": low_factors,
            "justifications": score_result.justifications,
        }
        return decision, True, summary_reason, rationale

    elif comp >= threshold:
        decision = "PUBLISH"
        # Identify top strengths
        strengths = [
            f"{k.replace('_', ' ').title()} ({v:.0f}/100, weight {int(WEIGHTS[k]*100)}%)"
            for k, v in sorted(factor_map.items(), key=lambda item: item[1], reverse=True)
            if v >= 70
        ]
        key_strength_text = ", ".join(strengths[:3]) if strengths else "well-rounded factor scores"
        ti_just = score_result.justifications.get("technical_impact", "").strip()

        summary_reason = (
            f"Published: composite score {comp:.1f}/100 exceeds threshold {threshold:.0f}/100 "
            f"(Evidence Quality: {eq:.0f}/100 >= floor {evidence_floor:.0f}/100). "
            f"Key strengths: {key_strength_text}. {ti_just}"
        )

        rationale = {
            "decision": "PUBLISH",
            "composite_score": comp,
            "publish_threshold": threshold,
            "evidence_floor": evidence_floor,
            "evidence_floor_triggered": False,
            "summary_reason": summary_reason,
            "factor_scores": factor_map,
            "key_strengths": strengths,
            "justifications": score_result.justifications,
        }
        return decision, False, summary_reason, rationale

    else:
        decision = "REJECT"
        # Find which factors dragged it below threshold
        drag_items = sorted(
            [(k, v, WEIGHTS[k]) for k, v in factor_map.items() if v < 70],
            key=lambda x: x[1],
        )
        drag_desc = [
            f"{k.replace('_', ' ').title()} ({v:.0f}/100, weight {int(w*100)}%)"
            for k, v, w in drag_items
        ]
        drag_str = ", ".join(drag_desc) if drag_desc else "composite score fell short"

        summary_reason = (
            f"Rejected: composite score {comp:.1f}/100 fell short of publish threshold ({threshold:.0f}/100). "
            f"Dragged down by: {drag_str}."
        )

        rationale = {
            "decision": "REJECT",
            "composite_score": comp,
            "publish_threshold": threshold,
            "evidence_floor": evidence_floor,
            "evidence_floor_triggered": False,
            "summary_reason": summary_reason,
            "factor_scores": factor_map,
            "drag_factors": drag_desc,
            "justifications": score_result.justifications,
        }
        return decision, False, summary_reason, rationale


# ---------------------------------------------------------------------------
# Public Scoring and Decision API
# ---------------------------------------------------------------------------

def score_topic(candidate: dict[str, Any]) -> Optional[ScoreResult]:
    """
    Score a normalized topic candidate using the LLM across the 5 PRD factors.

    Performs one retry on transient failure (timeout, network error, 429).
    Returns None — not raising — if both attempts fail or the response
    cannot be parsed. The caller must treat None as "skip this cycle".

    Args:
        candidate: Normalized topic dict from discovery with keys:
                   title, summary, source_url, published_at, raw_snippet.

    Returns:
        ScoreResult with factor scores, composite score, and justifications,
        or None on unrecoverable failure.
    """
    if not settings.LLM_API_KEY:
        logger.error(
            "LLM_API_KEY is not set — cannot score topic '%s'. Set it in .env.",
            candidate.get("title", "?")[:60],
        )
        return None

    title = candidate.get("title", "?")[:60]
    prompt = _build_scoring_prompt(candidate)

    for attempt in range(1, 3):  # attempt 1, then one retry (attempt 2)
        try:
            logger.info(
                "[scoring] Attempt %d/2 — scoring '%s'", attempt, title
            )
            raw = _call_llm(prompt)
            data = _extract_json(raw)
            result = _validate_and_clamp(data)
            logger.info(
                "[scoring] '%s' -> composite=%.1f (R=%.0f N=%.0f TI=%.0f EQ=%.0f T=%.0f)",
                title,
                result.composite_score,
                result.relevance,
                result.novelty,
                result.technical_impact,
                result.evidence_quality,
                result.timeliness,
            )
            return result

        except (ValueError, KeyError) as exc:
            logger.warning(
                "[scoring] Parse error on attempt %d/2 for '%s': %s — skipping.",
                attempt, title, exc,
            )
            return None

        except Exception as exc:
            logger.warning(
                "[scoring] API error on attempt %d/2 for '%s': %s",
                attempt, title, exc,
            )
            if attempt < 2:
                exc_str = str(exc)
                if "429" in exc_str or "RESOURCE_EXHAUSTED" in exc_str:
                    match = re.search(r"retry in ([0-9]+(?:\.[0-9]+)?)s", exc_str, re.IGNORECASE)
                    if not match:
                        match = re.search(r"retryDelay'?:\s*'([0-9]+)s", exc_str, re.IGNORECASE)
                    delay = float(match.group(1)) + 2.0 if match else 20.0
                    logger.info("[scoring] Rate limited (429). Waiting %.1fs before retry...", delay)
                    time.sleep(delay)
                else:
                    time.sleep(_RETRY_DELAY_SECONDS)
            else:
                logger.warning(
                    "[scoring] Both attempts failed for '%s' — skipping this cycle.",
                    title,
                )
                return None

    return None


def make_editorial_decision(
    candidate: dict[str, Any],
    score_result: ScoreResult,
    threshold: Optional[float] = None,
    evidence_floor: Optional[float] = None,
) -> EditorialDecision:
    """
    Apply editorial judgment to an already-scored candidate.

    Args:
        candidate: Normalized topic candidate dict.
        score_result: ScoreResult produced by score_topic().
        threshold: Minimum composite score required to publish.
                   Defaults to settings.PUBLISH_THRESHOLD (70.0).
        evidence_floor: Minimum Evidence Quality score required.
                   Defaults to settings.EVIDENCE_FLOOR (40.0).

    Returns:
        EditorialDecision with decision ('PUBLISH' | 'REJECT'), human reason,
        and structured rationale.
    """
    thresh = float(threshold if threshold is not None else settings.PUBLISH_THRESHOLD)
    floor = float(evidence_floor if evidence_floor is not None else settings.EVIDENCE_FLOOR)

    decision, floor_triggered, summary_reason, rationale = _build_decision_rationale(
        candidate=candidate,
        score_result=score_result,
        threshold=thresh,
        evidence_floor=floor,
    )

    logger.info(
        "[decision] '%s' -> %s (composite=%.1f, EQ=%.0f, floor_triggered=%s)",
        candidate.get("title", "?")[:50],
        decision,
        score_result.composite_score,
        score_result.evidence_quality,
        floor_triggered,
    )

    return EditorialDecision(
        candidate=candidate,
        score_result=score_result,
        decision=decision,
        publish_threshold=thresh,
        evidence_floor=floor,
        evidence_floor_triggered=floor_triggered,
        summary_reason=summary_reason,
        rationale=rationale,
    )


def decide_topic(
    candidate: dict[str, Any],
    threshold: Optional[float] = None,
    evidence_floor: Optional[float] = None,
) -> Optional[EditorialDecision]:
    """
    End-to-end evaluation for a single candidate: score then decide.
    Returns None if scoring fails (skip candidate this cycle).
    """
    score_result = score_topic(candidate)
    if score_result is None:
        return None

    return make_editorial_decision(
        candidate=candidate,
        score_result=score_result,
        threshold=threshold,
        evidence_floor=evidence_floor,
    )


def evaluate_batch(
    candidates: list[dict[str, Any]],
    threshold: Optional[float] = None,
    evidence_floor: Optional[float] = None,
) -> list[EditorialDecision]:
    """
    Evaluate a batch of candidate topics through scoring and decision.
    Skipped/failed items (score_topic returning None) are omitted from the output.

    Note: Persistence to SQLite database happens in Phase 10.
    # TODO: Phase 10 - Persist decisions (insert_post, insert_topic_seen)
    """
    decisions: list[EditorialDecision] = []
    for c in candidates:
        dec = decide_topic(c, threshold=threshold, evidence_floor=evidence_floor)
        if dec is not None:
            decisions.append(dec)
    return decisions
