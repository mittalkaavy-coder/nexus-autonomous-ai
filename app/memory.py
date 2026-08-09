"""
Memory, duplicate detection, and stance tracking engine for NEXUS.

Key responsibilities (PRD §5.3, §5.7):
1. TF-IDF Cosine Similarity:
   Compares new candidate topics against recent entries in `posts` and `topics_seen`.
   Uses Python standard library (math, re, collections.Counter) — zero external heavy dependencies.
2. Material Novelty Evaluation:
   A similarity score >= 0.80 triggers a material novelty check (heuristics / targeted LLM)
   to ensure follow-up releases, new benchmarks, or major updates are published rather than
   falsely discarded.
3. Stance Memory (Stretch Feature):
   Tags topics by subject (e.g. 'state-management', 'mcp-tools', 'inference-benchmarks') and
   tracks NEXUS's latest editorial stance so subsequent rationales maintain consistency.
4. Persistence Wiring:
   Provides helpers to record all discovered topics in `topics_seen` and all editorial
   decisions (both PUBLISH and REJECT) in `posts`.
"""

import json
import logging
import math
import re
import time
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.config import settings
from app.database import (
    get_recent_posts,
    get_recent_topics,
)

logger = logging.getLogger(__name__)

# Common English stop words for clean tokenization
_STOP_WORDS = frozenset([
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and",
    "any", "are", "aren't", "as", "at", "be", "because", "been", "before", "being",
    "below", "between", "both", "but", "by", "can't", "cannot", "could", "couldn't",
    "did", "didn't", "do", "does", "doesn't", "doing", "don't", "down", "during",
    "each", "few", "for", "from", "further", "had", "hadn't", "has", "hasn't",
    "have", "haven't", "having", "he", "he'd", "he'll", "he's", "her", "here",
    "here's", "hers", "herself", "him", "himself", "his", "how", "how's", "i",
    "i'd", "i'll", "i'm", "i've", "if", "in", "into", "is", "isn't", "it", "it's",
    "its", "itself", "let's", "me", "more", "most", "mustn't", "my", "myself",
    "no", "nor", "not", "of", "off", "on", "once", "only", "or", "other", "ought",
    "our", "ours", "ourselves", "out", "over", "own", "same", "shan't", "she",
    "she'd", "she'll", "she's", "should", "shouldn't", "so", "some", "such",
    "than", "that", "that's", "the", "their", "theirs", "them", "themselves",
    "then", "there", "there's", "these", "they", "they'd", "they'll", "they're",
    "they've", "this", "those", "through", "to", "too", "under", "until", "up",
    "very", "was", "wasn't", "we", "we'd", "we'll", "we're", "we've", "were",
    "weren't", "what", "what's", "when", "when's", "where", "where's", "which",
    "while", "who", "who's", "whom", "why", "why's", "with", "won't", "would",
    "wouldn't", "you", "you'd", "you'll", "you're", "you've", "your", "yours",
    "yourself", "yourselves", "via", "says", "using", "new", "released", "launch",
])


# ---------------------------------------------------------------------------
# Pure Python TF-IDF Cosine Similarity Engine
# ---------------------------------------------------------------------------


def tokenize(text: str) -> List[str]:
    """
    Extract alphanumeric word tokens, lowercased, filtering stop words.
    """
    if not text:
        return []
    words = re.findall(r"\b[a-zA-Z0-9_\-\.]+\b", text.lower())
    return [w for w in words if len(w) > 1 and w not in _STOP_WORDS]


def compute_tfidf_vectors(documents: List[str]) -> List[Dict[str, float]]:
    """
    Compute normalized sparse frequency vectors for a list of document strings.

    Args:
        documents: List of text documents.

    Returns:
        List of dicts {term: normalized_weight}.
    """
    if not documents:
        return []

    doc_tokens = [tokenize(doc) for doc in documents]
    n_docs = len(documents)

    # Document frequency across corpus
    df: Counter[str] = Counter()
    for tokens in doc_tokens:
        df.update(set(tokens))

    vectors: List[Dict[str, float]] = []
    for tokens in doc_tokens:
        if not tokens:
            vectors.append({})
            continue

        tf = Counter(tokens)
        vec: Dict[str, float] = {}

        for term, count in tf.items():
            # Sublinear TF with smoothed corpus IDF
            tf_weight = 1.0 + math.log(count)
            idf_weight = math.log((n_docs + 2.0) / (df[term] + 1.0)) + 1.0
            vec[term] = tf_weight * idf_weight

        # L2 normalize
        norm = math.sqrt(sum(w * w for w in vec.values()))
        if norm > 0:
            vec = {t: w / norm for t, w in vec.items()}
        vectors.append(vec)

    return vectors


def compute_cosine_similarity(v1: Dict[str, float], v2: Dict[str, float]) -> float:
    """
    Compute cosine similarity between two normalized sparse TF-IDF vectors.
    """
    if not v1 or not v2:
        return 0.0
    common = set(v1.keys()) & set(v2.keys())
    return sum(v1[t] * v2[t] for t in common)


# ---------------------------------------------------------------------------
# Duplicate Check Result Structure
# ---------------------------------------------------------------------------


class DuplicateCheckResult:
    """
    Result of comparing a candidate against memory.
    """

    __slots__ = (
        "is_duplicate",
        "similarity_score",
        "matched_id",
        "matched_title",
        "matched_source_url",
        "reason",
        "material_novelty",
        "novelty_note",
    )

    def __init__(
        self,
        is_duplicate: bool,
        similarity_score: float,
        matched_id: Optional[str] = None,
        matched_title: Optional[str] = None,
        matched_source_url: Optional[str] = None,
        reason: Optional[str] = None,
        material_novelty: bool = False,
        novelty_note: Optional[str] = None,
    ) -> None:
        self.is_duplicate = is_duplicate
        self.similarity_score = similarity_score
        self.matched_id = matched_id
        self.matched_title = matched_title
        self.matched_source_url = matched_source_url
        self.reason = reason
        self.material_novelty = material_novelty
        self.novelty_note = novelty_note

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_duplicate": self.is_duplicate,
            "similarity_score": round(self.similarity_score, 3),
            "matched_id": self.matched_id,
            "matched_title": self.matched_title,
            "matched_source_url": self.matched_source_url,
            "reason": self.reason,
            "material_novelty": self.material_novelty,
            "novelty_note": self.novelty_note,
        }

    def __repr__(self) -> str:
        return (
            f"DuplicateCheckResult(is_duplicate={self.is_duplicate}, "
            f"sim={self.similarity_score:.3f}, matched={self.matched_title!r})"
        )


# ---------------------------------------------------------------------------
# Material Novelty Heuristic & LLM Verification
# ---------------------------------------------------------------------------


def evaluate_material_novelty(
    candidate: Dict[str, Any],
    prior_item: Dict[str, Any],
    sim_score: float,
    use_llm: bool = True,
) -> Tuple[bool, str]:
    """
    Determine whether a candidate with high similarity (>= threshold) contains
    substantively new technical information vs. the prior item (PRD §5.3).

    Returns:
        (is_materially_new: bool, note: str)
    """
    cand_url = (candidate.get("source_url") or "").strip()
    prior_url = (prior_item.get("source_url") or "").strip()

    cand_title = candidate.get("title", "").strip()
    prior_title = (prior_item.get("title") or prior_item.get("topic") or "").strip()

    # Exact URL or exact title match -> definitely duplicate
    if cand_url and prior_url and cand_url == prior_url:
        return False, f"Exact source URL match: {cand_url}"

    if cand_title.lower() == prior_title.lower():
        return False, f"Exact topic title match: '{cand_title}'"

    # Check for obvious version difference (e.g. v0.3 vs v0.4)
    cand_versions = re.findall(r"v?[0-9]+\.[0-9]+(?:\.[0-9]+)?", cand_title)
    prior_versions = re.findall(r"v?[0-9]+\.[0-9]+(?:\.[0-9]+)?", prior_title)
    if cand_versions and prior_versions and cand_versions != prior_versions:
        return True, f"Distinct version release ({', '.join(cand_versions)} vs {', '.join(prior_versions)})"

    # Token overlap heuristic on titles
    cand_tokens = set(tokenize(cand_title))
    prior_tokens = set(tokenize(prior_title))
    if cand_tokens and prior_tokens:
        overlap = len(cand_tokens & prior_tokens) / len(cand_tokens | prior_tokens)
        if overlap >= 0.40:
            return False, f"High title term overlap ({overlap:.2f}) on same release/topic"

    # Targeted LLM check if API key is configured and use_llm is True
    if use_llm and settings.LLM_API_KEY:
        try:
            from google import genai  # type: ignore

            client = genai.Client(api_key=settings.LLM_API_KEY)
            prompt = f"""You are an editorial assistant checking for technical novelty and duplicate coverage.

PRIOR TOPIC:
  Title:   {prior_title}
  Summary: {prior_item.get('summary', '')}

NEW CANDIDATE TOPIC:
  Title:   {cand_title}
  Summary: {candidate.get('summary', '')}

QUESTION:
Does the NEW CANDIDATE contain materially new technical information compared with the PRIOR TOPIC (e.g., a new version release, different architectural benchmark, follow-up patch, or newly introduced capability), OR is it merely re-reporting the exact same event/announcement?

Respond ONLY with a JSON object:
{{
  "is_materially_new": true or false,
  "reason": "One sentence explaining why it is or is not materially new"
}}
"""
            response = client.models.generate_content(
                model=settings.LLM_MODEL,
                contents=prompt,
                config=genai.types.GenerateContentConfig(
                    temperature=0.0,
                    max_output_tokens=300,
                ),
            )
            raw_text = response.text or ""
            cleaned = re.sub(r"```(?:json)?\s*", "", raw_text).strip()
            cleaned = re.sub(r"```\s*$", "", cleaned).strip()
            match = re.search(r"\{.*\}", cleaned, re.DOTALL)
            if match:
                data = json.loads(match.group())
                is_new = bool(data.get("is_materially_new", False))
                reason = str(data.get("reason", ""))
                return is_new, reason
        except Exception as exc:
            logger.debug("[memory] Novelty LLM check note (%s); using heuristic.", exc)

    # Fallback: if similarity meets threshold and no explicit novelty signal, reject
    if sim_score >= 0.70:
        return False, f"High similarity ({sim_score:.2f}) without material novelty"

    return True, f"Distinct technical angle ({sim_score:.2f})"


# ---------------------------------------------------------------------------
# Duplicate Detection API
# ---------------------------------------------------------------------------


def check_duplicate(
    candidate: Dict[str, Any],
    window_size: Optional[int] = None,
    threshold: Optional[float] = None,
    exclude_id: Optional[str] = None,
) -> DuplicateCheckResult:
    """
    Compare a candidate topic against recent posts and topics_seen to detect duplicates.

    Args:
        candidate: Candidate topic dict with 'title', 'summary', 'source_url'.
        window_size: Number of recent items to compare against (default from settings).
        threshold: Cosine similarity cutoff (default from settings: 0.70).
        exclude_id: Optional ID to exclude from comparison (e.g. candidate's own newly logged ID).

    Returns:
        DuplicateCheckResult indicating duplicate status, similarity score, and reasoning.
    """
    limit = window_size or settings.MEMORY_WINDOW_SIZE
    sim_threshold = threshold if threshold is not None else settings.SIMILARITY_THRESHOLD

    recent_posts = get_recent_posts(limit=limit)
    recent_seen = get_recent_topics(limit=limit)

    # Build memory comparison corpus
    memory_items: List[Dict[str, Any]] = []
    seen_ids = set()
    if exclude_id:
        seen_ids.add(exclude_id)

    for p in recent_posts:
        pid = p.get("id", "")
        if pid not in seen_ids:
            seen_ids.add(pid)
            memory_items.append({
                "id": pid,
                "type": "post",
                "title": p.get("topic", ""),
                "summary": p.get("summary", ""),
                "source_url": p.get("sources", [""])[0] if p.get("sources") else "",
                "text": f"{p.get('topic', '')} {p.get('summary', '')}",
            })

    for s in recent_seen:
        sid = s.get("id", "")
        if sid not in seen_ids:
            seen_ids.add(sid)
            memory_items.append({
                "id": sid,
                "type": "topic_seen",
                "title": s.get("title", ""),
                "summary": s.get("summary", ""),
                "source_url": s.get("source_url", ""),
                "text": f"{s.get('title', '')} {s.get('summary', '')}",
            })

    if not memory_items:
        # No prior memory — candidate is clean
        return DuplicateCheckResult(
            is_duplicate=False,
            similarity_score=0.0,
            reason="No prior topics in memory window.",
        )

    # Candidate text
    cand_title = candidate.get("title", "")
    cand_summary = candidate.get("summary", "")
    cand_text = f"{cand_title} {cand_summary}"

    # Compute TF-IDF across all items + candidate for both full text and titles
    all_docs = [item["text"] for item in memory_items] + [cand_text]
    all_titles = [item["title"] for item in memory_items] + [cand_title]

    text_vectors = compute_tfidf_vectors(all_docs)
    title_vectors = compute_tfidf_vectors(all_titles)

    cand_text_vec = text_vectors[-1]
    cand_title_vec = title_vectors[-1]

    highest_sim = 0.0
    best_match: Optional[Dict[str, Any]] = None

    for idx, item in enumerate(memory_items):
        sim_text = compute_cosine_similarity(cand_text_vec, text_vectors[idx])
        sim_title = compute_cosine_similarity(cand_title_vec, title_vectors[idx])
        sim = max(sim_text, sim_title)

        if sim > highest_sim:
            highest_sim = sim
            best_match = item

    logger.debug(
        "[memory] Max similarity for '%s': %.3f with [%s] '%s'",
        cand_title[:40], highest_sim, best_match.get("id") if best_match else "none",
        best_match.get("title", "")[:40] if best_match else "",
    )

    if highest_sim < sim_threshold:
        return DuplicateCheckResult(
            is_duplicate=False,
            similarity_score=highest_sim,
            matched_id=best_match.get("id") if best_match else None,
            matched_title=best_match.get("title") if best_match else None,
            matched_source_url=best_match.get("source_url") if best_match else None,
            reason=f"Similarity {highest_sim:.2f} is below duplicate threshold {sim_threshold:.2f}.",
        )

    # Similarity meets or exceeds threshold -> evaluate material novelty
    is_novel, novelty_note = evaluate_material_novelty(
        candidate=candidate,
        prior_item=best_match,
        sim_score=highest_sim,
    )

    if not is_novel:
        reason = (
            f"Rejected as duplicate: similarity {highest_sim:.2f} >= {sim_threshold:.2f} "
            f"with prior item '{best_match.get('title')}' ({best_match.get('id')}) and lacks material novelty. "
            f"({novelty_note})"
        )
        return DuplicateCheckResult(
            is_duplicate=True,
            similarity_score=highest_sim,
            matched_id=best_match.get("id"),
            matched_title=best_match.get("title"),
            matched_source_url=best_match.get("source_url"),
            reason=reason,
            material_novelty=False,
            novelty_note=novelty_note,
        )

    # Highly similar but contains material novelty
    reason = (
        f"Similarity {highest_sim:.2f} >= {sim_threshold:.2f} with '{best_match.get('title')}', "
        f"but allowed due to material novelty: {novelty_note}"
    )
    return DuplicateCheckResult(
        is_duplicate=False,
        similarity_score=highest_sim,
        matched_id=best_match.get("id"),
        matched_title=best_match.get("title"),
        matched_source_url=best_match.get("source_url"),
        reason=reason,
        material_novelty=True,
        novelty_note=novelty_note,
    )


# ---------------------------------------------------------------------------
# Simple Stance Memory (Stretch Feature)
# ---------------------------------------------------------------------------

_SUBJECT_TAGS = {
    "state-persistence": ["checkpoint", "sqlite", "postgres", "persistence", "stateful", "memory"],
    "mcp-tooling": ["mcp", "model context protocol", "tool", "gateway", "proxy", "agent tool"],
    "inference-optimization": ["inference", "latency", "throughput", "vllm", "sglang", "speculative"],
    "agent-frameworks": ["langgraph", "autogen", "crewai", "smolagents", "framework"],
    "benchmarking-evals": ["benchmark", "eval", "evaluation", "swe-bench", "leaderboard"],
}

_STANCE_REGISTRY: Dict[str, Dict[str, Any]] = {}


def tag_topic_subject(title: str, summary: str) -> List[str]:
    """
    Extract subject category tags from a topic's title and summary.
    """
    combined = f"{title} {summary}".lower()
    tags = []
    for tag, keywords in _SUBJECT_TAGS.items():
        if any(kw in combined for kw in keywords):
            tags.append(tag)
    return tags or ["general-ai-infra"]


def record_stance(
    topic: str,
    decision: str,
    rationale: Dict[str, Any],
    tags: Optional[List[str]] = None,
) -> None:
    """
    Record NEXUS's stance on a given subject tag for ongoing editorial coherence.
    """
    applied_tags = tags or tag_topic_subject(topic, rationale.get("why_selected", ""))
    now_iso = datetime.now(timezone.utc).isoformat()

    for tag in applied_tags:
        _STANCE_REGISTRY[tag] = {
            "last_topic": topic,
            "last_decision": decision,
            "last_opinion": rationale.get("why_selected", ""),
            "updated_at": now_iso,
        }


def get_stance_reference(topic: str, summary: str) -> Optional[str]:
    """
    Retrieve any previous stance connection for inclusion in the rationale.
    """
    tags = tag_topic_subject(topic, summary)
    for tag in tags:
        if tag in _STANCE_REGISTRY:
            prior = _STANCE_REGISTRY[tag]
            return f"Consistent with NEXUS's stance on '{tag}' established during analysis of '{prior['last_topic']}'."
    return None
