#!/usr/bin/env python3
"""One success gate for managed-run, intent, approval, and cleanup truth."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from execution_backend import ExecutionBackendError, replay_run_ledger


ZERO_FIELDS = {
    "active_skills": "unclosed Skill lifecycle",
    "open_events": "unfinished tool/MCP event",
    "pending_verifications": "unverified material effect",
    "effect_unknown": "external effect with unknown outcome",
    "interventions_open": "unresolved effect intervention",
    "corrections_open": "unapplied correction intervention",
    "approvals_open": "unanswered approval question",
    "authorized_events": "unconsumed event authorization",
    "integrity_breaches": "control artifact integrity breach",
    "denials": "denied execution event",
}


def terminal_invariant_failures(
    guardian: Mapping[str, Any],
    run_ledger_path: Path,
) -> list[str]:
    """Return every independently provable reason a run is not publishable."""
    failures: list[str] = []
    if guardian.get("schema") != "sulde-guardian-summary-v1":
        failures.append("guardian summary schema is missing or unsupported")
    if guardian.get("policy_unchanged") is not True:
        failures.append("intent policy changed during agent execution")
    if guardian.get("integrity_ok") is not True:
        failures.append("intent/audit/effect/approval integrity is not proven")
    if guardian.get("status") != "active":
        failures.append(
            f"intent contract terminal status is {guardian.get('status')!r}, expected 'active'"
        )
    if guardian.get("pending_proposal") is True:
        failures.append("intent contract still has a pending proposal")
    for field, label in ZERO_FIELDS.items():
        try:
            count = int(guardian.get(field, 0))
        except (TypeError, ValueError):
            failures.append(f"guardian {field} count is invalid")
            continue
        if count:
            failures.append(f"guardian has {count} {label}(s)")

    execution = guardian.get("execution")
    if not isinstance(execution, Mapping):
        failures.append("execution RunHandle evidence is missing")
        execution = {}
    try:
        projection = replay_run_ledger(run_ledger_path)
    except ExecutionBackendError as error:
        failures.append(f"run ledger cannot be replayed: {error}")
        projection = None
    if projection is None:
        failures.append("run ledger is missing or empty")
    else:
        if not projection.terminal:
            failures.append("run ledger has no terminal cleanup fact")
        if projection.recovery_blocked:
            failures.append("run ledger contains an unresolved crash recovery")
        if not projection.publishable:
            failures.append("run ledger result and quiescence are not publishable")
        if execution.get("run_id") != projection.run_id:
            failures.append("guardian execution run id does not match the ledger")
        if projection.result is not None:
            if execution.get("returncode") != projection.result.get("returncode"):
                failures.append("guardian returncode does not match the ledger")
            if execution.get("stop_reason") != projection.result.get("stop_reason"):
                failures.append("guardian stop reason does not match the ledger")
        if projection.disposed is not None:
            if execution.get("cleanup_quiescent") != projection.disposed.get(
                "quiescent"
            ):
                failures.append("guardian quiescence does not match the ledger")
            if execution.get("cleanup_error_count") != projection.disposed.get(
                "error_count"
            ):
                failures.append("guardian cleanup error count does not match the ledger")
    return failures
