"""
Editorial scoring for NEXUS.

Scores a single normalized topic candidate across the 5 PRD-defined factors
using the LLM. Returns raw scores + justifications; the publish/reject
threshold and evidence-floor rule are applied in the next phase (Phase 8).

Scoring factors and weights (PRD §5.2):
    Relevance        20%
    Novelty          15%
    Technical Impact 25%
    Evidence Quality 20%
    Timeliness       20%

Score contract:
    score_topic(candidate) -> ScoreResult | None

    Returns None if the LLM call fails after one retry, or if the response
    cannot be parsed. None means "skip this candidate this cycle" — the
    caller must NOT crash when it receives None.
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
_MAX_OUTPUT_TOKENS: int = 2048  # 1024 was too tight for 5 verbose justifications
_RETRY_DELAY_SECONDS: float = 3.0

# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


class ScoreResult:
    """
    Holds the LLM-produced factor scores, their justifications, and the
    weighted composite score computed locally (not by the LLM).
    """

    __slots__ = (
        "relevance", "novelty", "technical_impact", "evidence_quality", "timeliness",
        "justifications", "composite_score",
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
            self.relevance       * WEIGHTS["relevance"]
            + self.novelty       * WEIGHTS["novelty"]
            + self.technical_impact * WEIGHTS["technical_impact"]
            + self.evidence_quality * WEIGHTS["evidence_quality"]
            + self.timeliness    * WEIGHTS["timeliness"],
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
    response = client.models.generate_content(
        model=settings.LLM_MODEL,
        contents=prompt,
        config=genai.types.GenerateContentConfig(
            temperature=_TEMPERATURE,
            max_output_tokens=_MAX_OUTPUT_TOKENS,
        ),
    )
    return response.text


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
    # Strip markdown fences
    text = re.sub(r"```(?:json)?\s*", "", raw).strip()
    text = re.sub(r"```\s*$", "", text).strip()

    # Find the first {...} block in case there is surrounding prose
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
# Public API
# ---------------------------------------------------------------------------

def score_topic(candidate: dict[str, Any]) -> Optional[ScoreResult]:
    """
    Score a normalized topic candidate using the LLM.

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
                result.relevance, result.novelty,
                result.technical_impact, result.evidence_quality, result.timeliness,
            )
            return result

        except (ValueError, KeyError) as exc:
            # Parsing / validation error — retrying won't help
            logger.warning(
                "[scoring] Parse error on attempt %d/2 for '%s': %s — skipping.",
                attempt, title, exc,
            )
            return None

        except Exception as exc:
            # Network/API error — retry once with a brief delay
            logger.warning(
                "[scoring] API error on attempt %d/2 for '%s': %s",
                attempt, title, exc,
            )
            if attempt < 2:
                time.sleep(_RETRY_DELAY_SECONDS)
            else:
                logger.warning(
                    "[scoring] Both attempts failed for '%s' — skipping this cycle.",
                    title,
                )
                return None

    return None  # unreachable, but satisfies the type checker
