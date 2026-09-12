"""Dependency-free semantic search contract shared by CLI and tests."""

from __future__ import annotations

from typing import Iterable


PURPOSE_ROLES = {
    "route": {"general", "route_positive", "route_negative"},
    "recall": {
        "general", "problem_context", "root_cause", "applicability",
        "route_positive", "route_negative", "outcome_negative",
    },
    "solution": {
        "general", "solution", "outcome_positive", "outcome_negative", "consumer",
    },
    "all": set(),
}

# Hybrid scores remain the public threshold/margin interface.  Absolute cosine
# only resolves genuinely near-tied hybrid candidates, so the score distribution
# consumed by downstream gates does not need an unrelated recalibration.
NEAR_TIE_SCORE_DELTA = 0.01


def applicability_for(role: str, evidence_status: str) -> str:
    if role == "route_negative":
        return "skip"
    if evidence_status == "inconclusive":
        return "inconclusive"
    return "apply"


def rerank_near_ties(
    candidates: Iterable[tuple[str, float, float]],
    *,
    delta: float = NEAR_TIE_SCORE_DELTA,
) -> list[tuple[str, float, float, float]]:
    """Break hybrid near-ties by absolute cosine without changing score values.

    The returned tuple is ``(id, rank_score, hybrid_score, cosine)``.  Rank-score
    values are reassigned within each near-tie cluster, preserving the original
    score distribution for downstream thresholds while making the final order
    stable when normalized lexical/vector evidence disagrees.
    """
    if delta < 0:
        raise ValueError("near-tie delta must be non-negative")
    ordered = sorted(candidates, key=lambda item: (-item[1], item[0]))
    result: list[tuple[str, float, float, float]] = []
    start = 0
    while start < len(ordered):
        anchor = ordered[start][1]
        end = start + 1
        while end < len(ordered) and anchor - ordered[end][1] <= delta + 1e-12:
            end += 1
        cluster = ordered[start:end]
        rank_scores = sorted((item[1] for item in cluster), reverse=True)
        semantic_order = sorted(cluster, key=lambda item: (-item[2], -item[1], item[0]))
        result.extend(
            (item[0], rank_scores[index], item[1], item[2])
            for index, item in enumerate(semantic_order)
        )
        start = end
    return result


def filter_clause(
    container: str | None,
    platform: str | None,
    purpose: str = "recall",
) -> tuple[str, list[str]]:
    clauses: list[str] = []
    parameters: list[str] = []
    if container:
        clauses.append("c.container = ?")
        parameters.append(container)
    if platform:
        clauses.append("(c.platform = ? OR c.platform IN ('cross', 'none'))")
        parameters.append(platform)
    roles = PURPOSE_ROLES[purpose]
    if roles:
        placeholders = ", ".join("?" for _ in roles)
        clauses.append(f"c.role IN ({placeholders})")
        parameters.extend(sorted(roles))
        # Structured v2 documents already have purpose-specific semantic roles.
        # Auxiliary/general sections must not outrank an explicit route or
        # outcome sample. Legacy documents have no semantic roles, so retain
        # general as their compatibility fallback.
        clauses.append("(c.role != 'general' OR c.evidence_status = '')")
    return (" AND " + " AND ".join(clauses) if clauses else ""), parameters
