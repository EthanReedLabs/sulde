"""Generational guard for managed runs: switch compatibility and GC planning.

Two responsibilities, both read-first (C3, R1-01):

1. **Switch compatibility** — before a deployment generation switches, the
   run-lease directory is consulted for in-flight executions.  A switch that
   would abandon a running generation can be observed (default) or blocked;
   an unknown active generation is treated as incompatible, never assumed
   safe.  This complements the existing live-session bridges and scheduler
   generation matching; it does not replace them.

2. **Retired-generation reclamation planning** — retired cache trees are
   reclaimable only when reclamation can *prove* no in-flight execution
   references them and the retention window has passed.  Identity rules:
   - the retired record is the real producer shape ``sulde-retired-codex-cache-v1``
     with ``version`` and ``tree_sha256`` (the normalized retired-tree digest);
     a record missing or carrying unparsable identity is kept, never guessed
     from the target directory name;
   - a runtime generation is ``<version>:<tree_sha256>``; the retired-tree
     digest and the delivered runtime-tree digest are *different* digests by
     construction (retirement normalizes the tree), so a target is provably
     unreferenced only when every active lease generation parses AND has a
     different version AND a different tree digest.  Anything else — unknown
     generation, unparsable, matching version, matching tree — keeps the
     target.

Reclamation of shared retired targets is CLOSED (R3-01/R3-02): no caller
declaration can prove complete reference coverage in this architecture, and
the former apply entry point silently recreated vanished scope directories.
``plan_retired_reclamation`` is a pure, read-only diagnostic (per-row
``eligible`` verdicts; ``reclaimable`` always false) and the apply entry
point has been removed so every real entry refuses identically.  Actual
reclamation stays undelivered until an authoritative complete-coverage
proof exists.  Authoritative retirement and audit facts are never touched.
"""

from __future__ import annotations

from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
from typing import Any, Sequence

from run_concurrency import active_run_leases


RECLAIM_PLAN_SCHEMA = "sulde-generation-reclaim-plan-v1"
RETIREMENT_RECORD_SCHEMA = "sulde-retired-codex-cache-v1"
RECORD_SUFFIX = ".retirement.json"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class GenerationGuardError(RuntimeError):
    """A generational switch or reclamation cannot be decided safely."""


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def active_generations(leases_dir: Path) -> dict[str, int]:
    """Count lease files per recorded runtime generation (read-only).

    Scoped to this one leases directory; consumers needing cross-worktree
    coverage must aggregate every scope themselves.  A lease without a
    recorded generation counts under ``""`` (unknown) and is incompatible
    with every concrete target generation.
    """
    counts: dict[str, int] = {}
    for lease in active_run_leases(leases_dir):
        generation = lease.get("runtime_generation") or ""
        counts[generation] = counts.get(generation, 0) + 1
    return counts


def _parse_runtime_generation(generation: str) -> tuple[str, str] | None:
    """Split ``<version>:<tree_sha256>``; anything unparsable is None."""
    if not generation or ":" not in generation:
        return None
    version, _, tree = generation.rpartition(":")
    if not version or not _SHA256_RE.fullmatch(tree):
        return None
    return version, tree


def switch_compatibility_report(
    leases_dir: Path,
    *,
    target_generation: str,
) -> dict[str, Any]:
    """Project whether a generational switch would strand in-flight runs.

    Scope is this leases directory only.
    """
    if not str(target_generation).strip():
        raise GenerationGuardError("target generation must not be empty")
    counts = active_generations(leases_dir)
    incompatible = {
        generation: count
        for generation, count in counts.items()
        if generation != target_generation
    }
    return {
        "schema": "sulde-generation-switch-report-v1",
        "target_generation": str(target_generation),
        "scope": str(leases_dir),
        "active_generations": counts,
        "incompatible_active": incompatible,
        "compatible": not incompatible,
    }


def assert_switch_allowed(
    leases_dir: Path,
    *,
    target_generation: str,
    policy: str = "observe",
) -> dict[str, Any]:
    """Observe (default) or block a generational switch under active runs."""
    if policy not in ("observe", "block"):
        raise GenerationGuardError(f"unsupported switch policy: {policy!r}")
    report = switch_compatibility_report(
        leases_dir, target_generation=target_generation
    )
    if policy == "block" and not report["compatible"]:
        raise GenerationGuardError(
            "generational switch blocked: "
            f"{sum(report['incompatible_active'].values())} active run(s) "
            "still reference other generations"
        )
    return report


def _retirement_identity(
    record: dict[str, Any], record_path: Path
) -> tuple[str, str] | None:
    """Extract ``(version, tree_sha256)`` from a real producer record.

    The producer writes ``version`` (the retired alias name, which embeds the
    plugin version) and ``tree_sha256`` (the normalized retired tree digest).
    No other field and no directory-name suffix is trusted: identity missing
    or malformed means the target is kept.
    """
    version = record.get("version")
    tree = record.get("tree_sha256")
    if not isinstance(version, str) or not version.strip():
        return None
    if not isinstance(tree, str) or _SHA256_RE.fullmatch(tree) is None:
        return None
    del record_path
    return version.strip(), tree


def _provably_unreferenced(
    identity: tuple[str, str],
    active: dict[str, int],
) -> tuple[bool, str]:
    """Prove no active lease can reference the retired identity.

    Because the retired-tree digest and the delivered runtime-tree digest are
    different digests by construction, absence of reference is provable only
    by dissociation on BOTH components from every active generation.  Any
    unknown or unparsable active generation blocks the reclamation.
    """
    version, tree = identity
    for generation, count in active.items():
        parsed = _parse_runtime_generation(generation)
        if parsed is None:
            return False, (
                f"active run generation is unknown or unparsable "
                f"({count} lease(s)); reference cannot be ruled out"
            )
        lease_version, lease_tree = parsed
        if lease_version == version:
            return False, (
                f"active run shares the retired version {version!r} "
                f"({count} lease(s))"
            )
        if lease_tree == tree:
            return False, (
                f"active run shares the retired tree digest ({count} lease(s))"
            )
    return True, "no active reference in this scope"


def _row_from_record(
    record_path: Path,
    target: Path,
    *,
    active: dict[str, int],
    retention_seconds: float,
    now: datetime,
) -> dict[str, Any]:
    """Validate one retired record and decide reclaimability."""
    row: dict[str, Any] = {
        "record": str(record_path),
        "target": str(target),
    }
    try:
        record_bytes = record_path.read_bytes()
        record = json.loads(record_bytes.decode("utf-8"))
    except FileNotFoundError:
        row.update(reclaimable=False, reason="retirement record missing")
        return row
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        row.update(
            reclaimable=False, reason=f"retirement record unreadable: {error}"
        )
        return row
    if (
        not isinstance(record, dict)
        or record.get("schema") != RETIREMENT_RECORD_SCHEMA
    ):
        row.update(
            reclaimable=False, reason="retirement record schema is unrecognized"
        )
        return row
    identity = _retirement_identity(record, record_path)
    if identity is None:
        row.update(
            reclaimable=False,
            reason="retirement record identity missing or malformed",
        )
        return row
    # Bind the row to the exact record bytes so apply can detect drift.
    row["record_sha256"] = hashlib.sha256(record_bytes).hexdigest()
    recorded_target = record.get("target")
    try:
        resolved_target = target.resolve(strict=False)
    except (OSError, RuntimeError) as error:
        row.update(reclaimable=False, reason=f"target cannot be resolved: {error}")
        return row
    if isinstance(recorded_target, str) and (
        Path(recorded_target).resolve(strict=False) != resolved_target
    ):
        row.update(
            reclaimable=False,
            reason="recorded target path does not match the record location",
        )
        return row
    if not target.is_dir() or target.is_symlink():
        row.update(
            reclaimable=False, reason="retired target is not a real directory"
        )
        return row
    try:
        age_seconds = max(0.0, now.timestamp() - record_path.stat().st_mtime)
    except OSError as error:
        row.update(
            reclaimable=False, reason=f"retirement record age unavailable: {error}"
        )
        return row
    row["generation"] = f"{identity[0]}:{identity[1]}"
    row["age_seconds"] = int(age_seconds)
    reasons: list[str] = []
    unreferenced, reference_reason = _provably_unreferenced(identity, active)
    if not unreferenced:
        reasons.append(reference_reason)
    if age_seconds < retention_seconds:
        reasons.append(
            f"retention window not met ({int(age_seconds)}s < "
            f"{int(retention_seconds)}s)"
        )
    row["reclaimable"] = not reasons
    row["reason"] = "; ".join(reasons) if reasons else "eligible"
    return row


def _scope_states(leases_dirs: Sequence[Path]) -> list[dict[str, Any]]:
    """Observe every declared lease scope without mutating anything."""
    states: list[dict[str, Any]] = []
    for leases_dir in leases_dirs:
        if not leases_dir.is_dir() or leases_dir.is_symlink():
            states.append(
                {
                    "leases_dir": str(leases_dir),
                    "status": "missing",
                    "active_generations": {},
                }
            )
            continue
        try:
            counts = active_generations(leases_dir)
        except GenerationGuardError as error:
            states.append(
                {
                    "leases_dir": str(leases_dir),
                    "status": "unreadable",
                    "error": str(error)[:200],
                    "active_generations": None,
                }
            )
            continue
        states.append(
            {
                "leases_dir": str(leases_dir),
                "status": "observed",
                "active_generations": counts,
            }
        )
    return states


def plan_retired_reclamation(
    retired_dir: Path,
    *,
    leases_dirs: Sequence[Path],
    retention_seconds: float,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Diagnostic plan for retired generation trees; reclaims nothing.

    R2-04/R3-01: reference coverage is explicit, never implied.  The caller
    declares every leases directory that can hold a reference to the shared
    retired targets; each declared scope is observed read-only.  "Scanned
    one directory" is not "all references covered", and — since no
    authoritative workspace registry exists in this architecture — a
    caller-supplied scope list or boolean can never PROVE complete
    coverage.  Shared-target reclamation is therefore CLOSED: the plan is
    diagnostic only (per-row ``eligible`` verdicts), ``reclaimable`` is
    always false, and the former apply entry point has been removed
    (R3-02: its guard lock silently recreated vanished scope directories).
    Actual reclamation remains undelivered until an authoritative
    complete-coverage proof exists.
    """
    if retention_seconds < 0:
        raise GenerationGuardError("retention_seconds must be non-negative")
    if not leases_dirs:
        raise GenerationGuardError(
            "no lease scopes declared; reference coverage cannot be proven"
        )
    current = now or datetime.now(timezone.utc)
    scopes = _scope_states(list(leases_dirs))
    observed = [scope for scope in scopes if scope["status"] == "observed"]
    coverage_complete = bool(observed) and len(observed) == len(scopes)
    # Combined references across every observed scope.
    combined: dict[str, int] = {}
    for scope in observed:
        for generation, count in scope["active_generations"].items():
            combined[generation] = combined.get(generation, 0) + count
    targets: list[dict[str, Any]] = []
    if retired_dir.is_dir() and not retired_dir.is_symlink():
        for record_path in sorted(retired_dir.glob(f"*{RECORD_SUFFIX}")):
            candidate = record_path.name[: -len(RECORD_SUFFIX)]
            if not candidate:
                continue
            row = _row_from_record(
                record_path,
                retired_dir / candidate,
                active=combined,
                retention_seconds=retention_seconds,
                now=current,
            )
            # R2-04: keep the diagnostic verdict visible (eligible w.r.t.
            # references/retention/identity) while the actionable verdict
            # (reclaimable) stays false unless coverage is proven complete
            # AND the caller certified the scope set — actual reclamation is
            # disabled, the target stays not-closed.
            row["eligible"] = row["reclaimable"]
            # R3-01: shared-target reclamation is closed.  Even a complete,
            # certified-looking scope list cannot prove the absence of
            # references outside the declared scopes, so the actionable
            # verdict is always false.
            if row["reclaimable"]:
                row["reclaimable"] = False
                row["reason"] = (
                    "shared-target reclamation is closed: complete reference "
                    "coverage cannot be proven in this architecture "
                    "(diagnostic eligible verdict only); target stays "
                    "not-closed"
                )
            targets.append(row)
    else:
        raise GenerationGuardError(
            f"retired directory is missing or not a real directory: {retired_dir}"
        )
    return {
        "schema": RECLAIM_PLAN_SCHEMA,
        "planned_at": current.isoformat(),
        "retired_dir": str(retired_dir),
        "leases_dirs": [str(path) for path in leases_dirs],
        "scope": "retired-dir-and-declared-lease-scopes",
        "coverage": (
            "complete" if coverage_complete else "insufficient"
        ),
        "reclamation": "closed-diagnostic-only",
        "scopes": scopes,
        "retention_seconds": int(retention_seconds),
        "active_generations": combined,
        "targets": targets,
        "reclaimable_count": sum(1 for row in targets if row["reclaimable"]),
    }



