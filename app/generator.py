"""
Content generation engine for NEXUS.

Generates concise, technical, and grounded analysis posts for candidate topics
that have received a final PUBLISH decision (PRD §5.5, §5.6).

Key invariants:
1. Voice and Persona:
   Pulls voice description, standing opinions, and hard rules directly
   from `app.persona.PERSONA` (single source of truth).
2. Strict Grounding:
   Instructs the LLM to stay strictly bounded by the discovered source snippet
   and factual context — no fabricated statistics, quotes, or features.
3. Selective Opinion Application:
   Applies NEXUS's standing editorial stance where genuinely relevant,
   without forcing canned opinions into every post.
4. Faithful Publishing Rationale:
   Constructs the PRD-required rationale object:
     { "why_selected": "...", "why_relevant_now": "...", "editorial_score": <int> }
   drawing directly on actual factor scores and justifications produced during
   editorial scoring (Phase 7/8).
5. Robust Error Handling:
   Retries transient failures once; returns None on unrecoverable failure
   so the pipeline skips persistence rather than publishing broken/partial content.
"""

import logging
import re
import textwrap
import time
from typing import Any, List, Optional

from app.config import settings
from app.editor import ScoreResult
from app.persona import PERSONA

logger = logging.getLogger(__name__)

# LLM call config
_TEMPERATURE: float = 0.3       # Slightly higher than scoring for natural prose, but constrained
_MAX_OUTPUT_TOKENS: int = 1500  # Ample space for 2-3 technical paragraphs
_RETRY_DELAY_SECONDS: float = 3.0


# ---------------------------------------------------------------------------
# Generated Post Data Type
# ---------------------------------------------------------------------------


class GeneratedPost:
    """
    Complete generated post ready for public feed delivery and database storage.
    """

    __slots__ = (
        "topic",
        "summary",
        "text",
        "rationale",
        "sources",
        "editorial_score",
        "created_at",
    )

    def __init__(
        self,
        topic: str,
        summary: str,
        text: str,
        rationale: dict[str, Any],
        sources: List[str],
        editorial_score: float,
        created_at: Optional[str] = None,
    ) -> None:
        self.topic = topic
        self.summary = summary
        self.text = text
        self.rationale = rationale
        self.sources = sources
        self.editorial_score = editorial_score
        self.created_at = created_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "topic": self.topic,
            "summary": self.summary,
            "text": self.text,
            "rationale": self.rationale,
            "sources": self.sources,
            "editorial_score": self.editorial_score,
            "created_at": self.created_at,
        }

    def __repr__(self) -> str:
        return (
            f"GeneratedPost(score={self.editorial_score:.1f}, "
            f"topic={self.topic[:40]!r}, text_len={len(self.text)})"
        )


# ---------------------------------------------------------------------------
# Publishing Rationale Builder (PRD §5.6)
# ---------------------------------------------------------------------------


def build_publishing_rationale(
    candidate: dict[str, Any],
    score_result: ScoreResult,
) -> dict[str, Any]:
    """
    Build the publishing rationale object per PRD §5.6:
      {
        "why_selected": "...",
        "why_relevant_now": "...",
        "editorial_score": <int>
      }

    Draws directly from the actual factor scores and justifications
    produced during the editorial scoring phase, ensuring 100% fidelity.
    """
    comp_score = int(round(score_result.composite_score))

    just_r = score_result.justifications.get("relevance", "").strip()
    just_ti = score_result.justifications.get("technical_impact", "").strip()
    just_t = score_result.justifications.get("timeliness", "").strip()
    just_n = score_result.justifications.get("novelty", "").strip()
    just_eq = score_result.justifications.get("evidence_quality", "").strip()

    # Compose why_selected from technical impact and relevance justifications
    why_selected_parts = []
    if just_ti:
        why_selected_parts.append(just_ti)
    elif just_r:
        why_selected_parts.append(just_r)
    if just_eq:
        why_selected_parts.append(f"Evidence: {just_eq}")
    why_selected = " ".join(why_selected_parts) or f"Topic scored {comp_score}/100 with verified evidence."

    # Compose why_relevant_now from timeliness and novelty justifications
    why_relevant_now_parts = []
    if just_t:
        why_relevant_now_parts.append(just_t)
    if just_n and just_n != just_t:
        why_relevant_now_parts.append(just_n)
    why_relevant_now = " ".join(why_relevant_now_parts) or "Recent technical development in agent infrastructure."

    return {
        "why_selected": why_selected,
        "why_relevant_now": why_relevant_now,
        "editorial_score": comp_score,
        "factor_scores": score_result.to_dict()["factor_scores"],
        "evidence_quality_note": just_eq,
    }


# ---------------------------------------------------------------------------
# Prompt Builder
# ---------------------------------------------------------------------------


def _build_generation_prompt(
    candidate: dict[str, Any],
    score_result: ScoreResult,
) -> str:
    """
    Construct the generation prompt injecting persona identity, voice,
    standing opinions, and strict source grounding constraints.
    """
    opinions_str = "\n".join(f"  - {op}" for op in PERSONA.standing_opinions)
    hard_rules_str = "\n".join(f"  - {rule}" for rule in PERSONA.hard_rules)

    title = candidate.get("title", "")
    summary = candidate.get("summary", "")
    source_url = candidate.get("source_url", "")
    raw_snippet = candidate.get("raw_snippet", summary)
    snippet = textwrap.shorten(raw_snippet, width=1000, placeholder="…")
    pub_at = candidate.get("published_at", "")

    ti_note = score_result.justifications.get("technical_impact", "")
    eq_note = score_result.justifications.get("evidence_quality", "")

    return f"""You are {PERSONA.name}, an {PERSONA.role}.

PERSONA VOICE & STYLE:
{PERSONA.voice}

STANDING EDITORIAL OPINIONS:
{opinions_str}

HARD EDITORIAL RULES:
{hard_rules_str}

---

TOPIC TO ANALYZE AND WRITE ABOUT:
  Title:        {title}
  Source URL:   {source_url}
  Published:    {pub_at}
  Source Facts: {summary}
  Raw Snippet:  {snippet}

EDITORIAL ASSESSMENT CONTEXT:
  Composite Score:  {score_result.composite_score:.1f}/100
  Technical Impact: {score_result.technical_impact:.0f}/100 ({ti_note})
  Evidence Quality: {score_result.evidence_quality:.0f}/100 ({eq_note})

---

INSTRUCTIONS:
1. Write a concise, high-density technical post (2-3 short paragraphs, ~150-250 words) analyzing this development for systems engineers and AI infrastructure architects.
2. Clearly explain:
   - What changed or was released technically.
   - Why this matters for real-world agent systems, infrastructure, or developer workflows.
   - Practical architectural implications or trade-offs (e.g. state management, latency, cost, reliability).
3. STRICT GROUNDING:
   - Every fact, mechanism, tool name, or capability MUST be strictly traceable to the provided Source Facts and Snippet.
   - NEVER fabricate numbers, benchmarks, version numbers, or quotes not present in the source.
4. EDITORIAL STANCE:
   - Apply NEXUS's standing opinions ONLY if genuinely relevant (e.g., noting whether benchmarks are reproducible or highlighting the value of native primary implementations vs wrapper layers). Do NOT force generic slogans.
5. TONE:
   - Dry, precise, analytical, and authoritative.
   - NO marketing buzzwords ("game-changer", "revolutionary", "exciting").
   - NO introductory filler ("In today's fast-paced AI world...").
   - NO emojis or generic social media hooks.
6. FORMAT:
   - Output ONLY the post text. Do not include markdown code blocks, headers like "Here is the post:", or quotation marks.
"""


# ---------------------------------------------------------------------------
# LLM Caller
# ---------------------------------------------------------------------------


def _call_llm(prompt: str) -> str:
    """
    Call Gemini model to generate content with resilient fallback.
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
                "[generator] LLM call with model '%s' failed: %s — trying next fallback if available",
                model_name, exc,
            )
    if last_exc:
        raise last_exc
    raise RuntimeError("No LLM models available to execute prompt")


def _clean_generated_text(text: str) -> str:
    """
    Clean up generated output to ensure pure prose without meta tags.
    """
    cleaned = text.strip()
    # Strip markdown code blocks if the model wrapped it
    cleaned = re.sub(r"^```(?:markdown|text)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    # Strip common leading meta-phrases
    cleaned = re.sub(r"^(?:Here is the (?:analysis|post|write-up|content):?\s*)", "", cleaned, flags=re.IGNORECASE)
    # Strip surrounding quotes if whole post was enclosed
    if (cleaned.startswith('"') and cleaned.endswith('"')) or (cleaned.startswith("'") and cleaned.endswith("'")):
        cleaned = cleaned[1:-1].strip()
    return cleaned.strip()


# ---------------------------------------------------------------------------
# Public Generation API
# ---------------------------------------------------------------------------


def generate_post(
    candidate: dict[str, Any],
    score_result: ScoreResult,
) -> Optional[GeneratedPost]:
    """
    Generate the analysis post text and rationale object for a candidate
    that passed the editorial decision engine with PUBLISH.

    Args:
        candidate: Normalized candidate topic dict.
        score_result: ScoreResult from editorial scoring.

    Returns:
        GeneratedPost with clean text, rationale object, sources, and score,
        or None if generation fails after retry.
    """
    if not settings.LLM_API_KEY:
        logger.error(
            "LLM_API_KEY not configured — cannot generate post for '%s'.",
            candidate.get("title", "?")[:50],
        )
        return None

    title = candidate.get("title", "?")[:60]
    prompt = _build_generation_prompt(candidate, score_result)

    for attempt in range(1, 3):
        try:
            logger.info("[generation] Attempt %d/2 — generating post for '%s'", attempt, title)
            raw_text = _call_llm(prompt)
            cleaned_text = _clean_generated_text(raw_text)

            if not cleaned_text or len(cleaned_text) < 50:
                raise ValueError(f"Generated text too short or empty: {cleaned_text!r}")

            # Build faithful publishing rationale
            rationale = build_publishing_rationale(candidate, score_result)

            # Sources list
            sources = []
            if candidate.get("source_url"):
                sources.append(candidate["source_url"])

            post = GeneratedPost(
                topic=candidate.get("title", ""),
                summary=candidate.get("summary", ""),
                text=cleaned_text,
                rationale=rationale,
                sources=sources,
                editorial_score=score_result.composite_score,
            )

            logger.info(
                "[generation] Successfully generated post for '%s' (%d chars, score=%.1f)",
                title, len(cleaned_text), score_result.composite_score,
            )
            return post

        except Exception as exc:
            logger.warning(
                "[generation] Error on attempt %d/2 for '%s': %s",
                attempt, title, exc,
            )
            if attempt < 2:
                exc_str = str(exc)
                if "429" in exc_str or "RESOURCE_EXHAUSTED" in exc_str:
                    match = re.search(r"retry in ([0-9]+(?:\.[0-9]+)?)s", exc_str, re.IGNORECASE)
                    if not match:
                        match = re.search(r"retryDelay'?:\s*'([0-9]+)s", exc_str, re.IGNORECASE)
                    delay = float(match.group(1)) + 2.0 if match else 20.0
                    logger.info("[generation] Rate limited (429). Waiting %.1fs before retry...", delay)
                    time.sleep(delay)
                else:
                    time.sleep(_RETRY_DELAY_SECONDS)
            else:
                logger.error(
                    "[generation] Generation failed permanently for '%s' — skipping persistence.",
                    title,
                )
                return None

    return None
