#!/usr/bin/env python3
"""Freeze delivery scope and classify discoveries without silently expanding it."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


DELIVERY_CLASSES = frozenset({"functional", "environment", "report", "optimization"})
BLOCKER_KINDS = frozenset({"security", "data_loss", "acceptance_failure"})


@dataclass(frozen=True)
class Discovery:
    identifier: str
    delivery_class: str
    kind: str
    evidence: str
    affects_current_acceptance: bool = False


@dataclass(frozen=True)
class ScopeDecision:
    identifier: str
    disposition: str
    rationale: str


def classify(discovery: Discovery) -> ScopeDecision:
    if discovery.delivery_class not in DELIVERY_CLASSES:
        raise ValueError(f"unknown delivery class: {discovery.delivery_class}")
    if discovery.evidence not in {"verified", "inconclusive"}:
        raise ValueError(f"unknown evidence state: {discovery.evidence}")
    if discovery.evidence != "verified":
        return ScopeDecision(
            discovery.identifier,
            "inconclusive",
            "evidence is not sufficient to alter the frozen delivery",
        )
    if discovery.kind in {"security", "data_loss"}:
        return ScopeDecision(
            discovery.identifier,
            "blocker",
            "verified security or data-loss risk blocks the frozen delivery",
        )
    if discovery.kind == "acceptance_failure" and discovery.affects_current_acceptance:
        return ScopeDecision(
            discovery.identifier,
            "blocker",
            "verified failure directly violates current acceptance",
        )
    return ScopeDecision(
        discovery.identifier,
        "deferred",
        "adjacent verified work is recorded for a separate frozen delivery",
    )


def closure(decisions: Iterable[ScopeDecision]) -> dict[str, object]:
    rows = tuple(decisions)
    blockers = sorted(row.identifier for row in rows if row.disposition == "blocker")
    unexplained = sorted(
        row.identifier
        for row in rows
        if row.disposition not in {"blocker", "deferred", "inconclusive"}
    )
    return {
        "ready": not blockers and not unexplained,
        "blockers": blockers,
        "unexplained": unexplained,
        "deferred": sorted(
            row.identifier for row in rows if row.disposition == "deferred"
        ),
        "inconclusive": sorted(
            row.identifier for row in rows if row.disposition == "inconclusive"
        ),
    }
