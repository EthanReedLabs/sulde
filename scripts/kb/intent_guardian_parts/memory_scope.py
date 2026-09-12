"""Pure projections for explicitly memory-independent task work.

This is conflict/freshness scope, never execution permission or effect settlement.
Unknown legacy rows remain material. Call only on normalized Guardian state.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any

PROFILE = "sulde-memory-annotate-v1"
GRANT = hashlib.sha256(f"system-policy:{PROFILE}".encode()).hexdigest()


def independent(contract: dict[str, Any]) -> bool:
    effects = contract.get("decision", {}).get("effects", [])
    return bool(
        contract.get("constraints", {}).get("memory_dependency") == "independent"
        and effects and set(effects).issubset({"read", "local_write"})
        and not contract.get("continuation", {}).get("grants")
    )


def memory_row(row: Any) -> bool:
    if not isinstance(row, dict):
        return False
    recipe = row.get("memory_verification")
    if not isinstance(recipe, dict) or set(recipe) != {"schema", "request_sha256"}:
        return False
    sha = recipe.get("request_sha256")
    candidate = row.get("continuation_candidate") or {}
    if not isinstance(candidate, dict):
        return False
    profile = row.get("continuation_profile_id") or row.get("profile_id") or candidate.get("profile_id")
    grant = row.get("continuation_grant_id") or row.get("grant_id") or candidate.get("grant_id")
    return bool(
        recipe.get("schema") == "sulde-memory-annotation-v2"
        and isinstance(sha, str) and re.fullmatch(r"[0-9a-f]{64}", sha)
        and row.get("verification_sha256") == sha
        and row.get("target") == f"[memory-annotation:{sha}]"
        and row.get("effect") == "local_write"
        and row.get("capability") in ("mcp:sulde_kb:memory_annotate", "mcp:sulde-kb:memory_annotate")
        and row.get("provider") in ("claude", "codex")
        and isinstance(row.get("session_id"), str) and row["session_id"]
        and not row.get("control_plane")
        and profile in (None, "", PROFILE) and grant in (None, "", GRANT)
    )


def sequence(runtime: dict[str, Any], *, scoped: bool) -> int:
    total = int(runtime.get("material_sequence", 0))
    memory = int(runtime.get("memory_material_sequence", 0)) if scoped else 0
    if not 0 <= memory <= total:
        raise ValueError("memory material sequence is inconsistent")
    # Old runtimes only advance total: those writes still invalidate freshness.
    return total - memory


def matches_attempt(row: dict[str, Any], attempts: dict[str, Any]) -> bool:
    attempt = attempts.get(row.get("attempt_id")) if isinstance(row.get("attempt_id"), str) else None
    return bool(memory_row(row) and isinstance(attempt, dict)
                and all(attempt.get(key) == row.get(key) for key in (
                    "capability", "effect", "provider", "session_id", "target", "verification_sha256")))


def blocking_pending(current: dict[str, Any], proposal: dict[str, Any], *, attempts=None) -> list[dict[str, Any]]:
    scoped = independent(proposal)
    return [row for row in current["runtime"]["pending_verifications"]
            if not (scoped and isinstance(attempts, dict) and matches_attempt(row, attempts))]


def proven_memory_row(row: Any, attempts: dict[str, Any]) -> bool:
    """A typed projection alone cannot hide an unrelated authoritative attempt."""
    if not memory_row(row):
        return False
    if row.get("attempt_id"):
        return matches_attempt(row, attempts)
    source = row.get("event_id")
    matches = [key for key, attempt in attempts.items() if isinstance(attempt, dict)
               and source and attempt.get("source_event_id") == source]
    return len(matches) == 1 and matches_attempt({**row, "attempt_id": matches[0]}, attempts)


def advance_sequence(runtime, event, decision, *, matched_started_event):
    """Audit once per allowed material start, or an unmatched completion gap."""
    if (event.get("control_plane") or event.get("supervision_domain") == "execution_passthrough"
            or decision.action != "allow" or event.get("effect") not in
            {"local_write", "external_write", "destructive", "unknown"}):
        return False
    phase = str(event.get("phase") or "")
    if phase == "started" or (phase == "completed" and not matched_started_event):
        runtime["material_sequence"] = int(runtime.get("material_sequence", 0)) + 1
        if memory_row(event):
            runtime["memory_material_sequence"] = int(runtime.get("memory_material_sequence", 0)) + 1
        return True
    return False
