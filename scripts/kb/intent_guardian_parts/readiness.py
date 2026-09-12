"""Intent Guardian readiness domain component."""

from __future__ import annotations

from contextlib import contextmanager

from dataclasses import dataclass

from datetime import datetime, timezone

import fnmatch

import hashlib

import json

import os

from pathlib import Path

import re

import shutil

import sqlite3

import stat

import subprocess

import sys

import tempfile

import time

from typing import Any, Callable, Iterable, Iterator

from command_template import (
    has_unquoted_shell_control as _has_unquoted_shell_control,
    is_read_only_command as _is_read_only_command,
    literal_git_add_paths as _literal_git_add_paths,
    read_pipeline_segments as _read_pipeline_segments,
    split_command_template,
)

from file_lock import lock_exclusive_nonblocking, unlock

from human_control import codex_text_control_requires_native, parse_human_control

from host_capabilities import (
    HostCapabilityError,
    hook_failure_projection,
    readiness_projection as host_readiness_projection,
)

from launcher_contract import (
    classify_trusted_script_command,
    identify_trusted_script_command,
    verify_installation as verify_launcher_installation,
)

from local_file_operations import (
    LocalFileOperationError,
    has_destructive_operation,
    operation_targets,
    parse_apply_patch_operations,
)

from approval_invariant import (
    ApprovalInvariantError,
    authoritative_store_bytes as approval_authoritative_store_bytes,
    ask_approval,
    cancel_request as cancel_approval_request,
    cancel_open_requests as cancel_open_approval_requests,
    decide_approval,
    load_projection as load_approval_projection,
    open_requests as approval_open_requests,
    request_by_id as approval_request_by_id,
    request_for_binding as approval_request_for_binding,
    request_phase as approval_request_phase,
    restore_authoritative_store as restore_approval_authoritative_store,
    summary as approval_pair_summary,
)

from approval_timeout_policy import (
    ApprovalTimeoutPolicyError,
    NATIVE_HUMAN_TTL_SECONDS,
    REASSESS_AFTER_SECONDS,
    UNATTENDED_AGENT_IF_ELIGIBLE,
    UNATTENDED_WAIT,
    normalize_unattended_policy,
    timeout_disposition,
)

from correction_intervention import (
    CorrectionInterventionError,
    apply_queued_corrections,
    propose_correction,
    summary as correction_intervention_summary,
    transition_correction,
)

from intervention import (
    InterventionError,
    acknowledge_intervention as acknowledge_effect_intervention_store,
    authorize_system_retry as authorize_effect_system_retry,
    authoritative_store_bytes,
    begin_attempt,
    blocking_attempts,
    canonical_resource_key,
    effect_operation_fingerprint,
    git_ref_verification_digest,
    load_projection as load_intervention_projection,
    mark_attempt_result,
    mark_attempt_unknown,
    material_event_blocker,
    open_interventions,
    reconcile_legacy_git_control_debt,
    resolve_intervention as resolve_effect_intervention_store,
    resolve_attempt_target,
    restore_authoritative_store,
    retry_grant_for_event,
    summary as intervention_summary,
    verify_from_read,
)

from session_continuity import (
    CONTINUATION_EVENT_SCHEMA,
    ContinuationError,
    build_capsule,
    capsule_summary,
    continuation_path,
    load_capsule,
    locate_codex_rollout,
    recent_dialogue,
    render_context as render_continuation_context,
)

from observation_privacy import (
    ObservationPrivacyError,
    current_export_proposal,
    decide_current_export,
)

from native_decision_journal import (
    NativeDecisionJournalError,
    advance as advance_native_transaction,
    pending as pending_native_transactions,
    prepare as prepare_native_transaction,
    supersede as supersede_native_transaction,
)

from operational_readiness import project as operational_readiness_projection

from production_recovery_readiness import observe_recovery_truth

from task_ownership import (
    CriticCheckpointError,
    TaskOwnershipError,
    blocks_material as _task_lane_blocks_material,
    claim_critic_lane_batch,
    critic_claim_identity_present,
    critic_claim_world_is_current,
    critic_event_for_claim,
    normalize_critic_batches,
    normalize_task_lanes,
    observe_prompt_lane as _observe_prompt_lane_locked,
    record_critic_local_write,
    settle_critic_claim,
    task_lane as _task_lane,
    upsert_task_lane as _upsert_task_lane_locked,
)

from .approvals import (
    _proposal_path_for_digest,
    continuation_status,
)

from .session_workspace import resolve_session_contract, workspace_cleanup_status

from .stale_events import stale_event_report

from .state import (
    IntentGuardianError,
    RUNTIME_GENERATION,
    active_contract_path,
    audit_path,
    bound_contract_path,
    load_contract,
    rebind_marker_path,
    retire_marker_path,
    workspace_root,
)

def reconcile_git_control_debt_locked(
    path: Path,
    contract: dict[str, Any],
) -> list[str]:
    """Quarantine historical Git debt without asserting its external truth."""
    try:
        reconciled = set(reconcile_legacy_git_control_debt(path))
    except (InterventionError, OSError, UnicodeError):
        return []
    if reconciled:
        pending = contract["runtime"].get("pending_verifications", [])
        contract["runtime"]["pending_verifications"] = [
            row for row in pending if not isinstance(row, dict)
            or str(row.get("attempt_id") or "") not in reconciled
        ]
    return sorted(reconciled)

def _approval_capture_summary(
    observations: list[dict[str, Any]],
    *,
    provider: str | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    selected = [
        row
        for row in observations
        if row["event"] == "user_prompt_submit"
        and (provider is None or row["provider"].lower() == provider.lower())
        and (session_id is None or row["session_id"] == session_id)
    ]
    live = [row for row in selected if row["source"] == "live_host_hook"]
    synthetic = [row for row in selected if row["source"] == "synthetic_smoke"]
    if live:
        status = "live_verified"
    elif synthetic:
        status = "synthetic_only"
    else:
        status = "unobserved"
    return {
        "status": status,
        "provider": provider or "any",
        "session_id": session_id or "any",
        "live_observations": len(live),
        "synthetic_observations": len(synthetic),
        "last_observation": selected[-1] if selected else None,
    }

def _audit_window(path: Path, *, deep: bool) -> tuple[list[str], dict[str, Any]]:
    """Read a bounded audit tail by default; explicit deep reports stream all rows."""
    if not path.is_file():
        return [], {
            "mode": "deep" if deep else "tail",
            "file_bytes": 0,
            "scanned_bytes": 0,
            "scanned_lines": 0,
            "truncated": False,
        }
    file_bytes = path.stat().st_size
    if deep:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            lines = list(handle)
        scanned_bytes = file_bytes
        truncated = False
    else:
        maximum_bytes = 256 * 1024
        with path.open("rb") as handle:
            start = max(0, file_bytes - maximum_bytes)
            handle.seek(start)
            raw = handle.read(maximum_bytes)
        if start:
            newline = raw.find(b"\n")
            raw = raw[newline + 1 :] if newline >= 0 else b""
        lines = raw.decode("utf-8", errors="replace").splitlines()
        if len(lines) > 512:
            lines = lines[-512:]
        scanned_bytes = len(raw)
        truncated = start > 0
    return lines, {
        "mode": "deep" if deep else "tail",
        "file_bytes": file_bytes,
        "scanned_bytes": scanned_bytes,
        "scanned_lines": len(lines),
        "truncated": truncated,
    }


def _bounded_rows(rows: list[dict[str, Any]], *, limit: int = 20) -> dict[str, Any]:
    return {
        "total": len(rows),
        "returned": min(len(rows), limit),
        "truncated": len(rows) > limit,
        "items": rows[-limit:],
    }


def guardian_report(
    path: Path,
    *,
    deep_audit: bool = False,
    provider: str = "",
    session_id: str = "",
) -> dict[str, Any]:
    contract = load_contract(path)
    try:
        effect_truth = intervention_summary(path)
        effect_projection = load_intervention_projection(path)
        approval_truth = approval_pair_summary(path)
    except (
        ApprovalInvariantError,
        InterventionError,
        OSError,
        UnicodeError,
    ) as error:
        raise IntentGuardianError(
            f"cannot replay approval/effect truth: {error}"
        ) from error
    counts: dict[str, int] = {}
    denied = 0
    providers: dict[str, int] = {}
    skill_sources: dict[str, int] = {}
    audit = audit_path(path)
    audit_lines, audit_window = _audit_window(audit, deep=deep_audit)
    if audit_lines:
        for line in audit_lines:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            kind = str((row.get("event") or {}).get("kind") or "unknown")
            event = row.get("event") if isinstance(row.get("event"), dict) else {}
            if event:
                counts[kind] = counts.get(kind, 0) + 1
                provider = str(event.get("provider") or "unknown")
                providers[provider] = providers.get(provider, 0) + 1
                if kind == "skill":
                    source = str(event.get("observation_source") or "unknown")
                    skill_sources[source] = skill_sources.get(source, 0) + 1
            if (row.get("decision") or {}).get("would_action") == "deny":
                denied += 1
    observations = contract["runtime"]["host_observations"]
    approval_capture = _approval_capture_summary(observations)
    approval_capture["by_provider"] = {
        observed_provider: _approval_capture_summary(
            observations,
            provider=observed_provider,
        )
        for observed_provider in sorted(
            {
                row["provider"].lower()
                for row in observations
                if row["event"] == "user_prompt_submit" and row["provider"]
            }
        )
    }
    receipts = contract["runtime"]["approval_receipts"]
    proposal_decisions = contract["runtime"]["proposal_decisions"]
    pending_digest = contract["runtime"]["pending_proposal_digest"]
    pending_route = "none"
    if pending_digest:
        try:
            pending = load_contract(_proposal_path_for_digest(path, pending_digest))
            pending_route = str((pending.get("decision") or {}).get("selected_route") or "human")
        except (IntentGuardianError, OSError, UnicodeError):
            pending_route = "invalid"
    root = Path(contract["workspace_root"])
    runtime = contract["runtime"]
    current_epoch = contract["task_epoch"]
    current_pending = list(runtime["pending_verifications"])
    current_interventions_open = sum(
        1
        for row in effect_projection["interventions"].values()
        if row.get("status") in {"open", "acknowledged"}
    )
    stale_events = stale_event_report(
        path,
        contract,
        provider=provider,
        session_id=session_id,
    )
    workspace_cleanup = workspace_cleanup_status(contract)
    return {
        "intent_id": contract["intent_id"],
        "revision": contract["revision"],
        "task_epoch": current_epoch,
        "runtime_generation": RUNTIME_GENERATION,
        "status": contract["status"],
        "mode": contract["mode"],
        "objective": contract["objective"],
        "event_counts": counts,
        "providers": providers,
        "skill_observation_sources": skill_sources,
        "findings": denied,
        "open_events": runtime["open_events"],
        "pending_verifications": runtime["pending_verifications"],
        "verified_effects": _bounded_rows(runtime["verified_effects"]),
        "inconclusive_outcomes": _bounded_rows(runtime["inconclusive_outcomes"]),
        "stale_events": stale_events,
        "workspace_cleanup": workspace_cleanup,
        "effect_truth": effect_truth,
        "supervision": {
            "metrics": dict(runtime["supervision_metrics"]),
            "current_pending_verifications": len(current_pending),
            "historical_pending_verifications": 0,
            "current_interventions_open": current_interventions_open,
            "historical_interventions_open": 0,
            "legacy_event_authority_migrations": int(
                runtime["legacy_event_authority_migrations"]
            ),
            "legacy_open_event_migrations": int(
                runtime["legacy_open_event_migrations"]
            ),
        },
        "workspace": {
            "root": str(root),
            "exists": root.exists(),
            "status": "available" if root.exists() else "workspace_root_missing",
        },
        "approval_capture": approval_capture,
        "approval_requests": approval_truth,
        "approval_receipts": {
            "total": len(receipts),
            "unconsumed": sum(1 for row in receipts if not row["consumed_at"]),
            "last": receipts[-1] if receipts else None,
        },
        "proposal_decisions": {
            "pending": bool(pending_digest),
            "pending_route": pending_route,
            "human_approved": sum(
                1
                for row in proposal_decisions
                if row["authority"] == "human" and row["verdict"] == "approve"
            ),
            "human_rejected": sum(
                1
                for row in proposal_decisions
                if row["authority"] == "human" and row["verdict"] == "reject"
            ),
            "agent_approved": sum(
                1
                for row in proposal_decisions
                if row["authority"] == "agent-policy" and row["verdict"] == "approve"
            ),
            "last": proposal_decisions[-1] if proposal_decisions else None,
        },
        "coverage": {
            "claude_skill": "native Skill tool events through PreToolUse/PostToolUse",
            "codex_skill": "explicit skill-start/skill-end registration; no claim of native hidden Skill lifecycle",
            "mcp": "PreToolUse/PostToolUse plus managed L3 provider stream",
            "tools": "PreToolUse/PostToolUse plus managed L3 provider stream",
            "reasoning": "not observed; only observable actions and evidence are supervised",
        },
        "audit_path": str(audit),
        "audit_window": audit_window,
    }

def guardian_inventory(
    home: Path,
    *,
    provider: str | None = None,
) -> dict[str, Any]:
    workspace_dir = home / "intent" / "workspaces"
    contracts: list[dict[str, Any]] = []
    invalid: list[dict[str, str]] = []
    for path in sorted(workspace_dir.glob("*.active.json")):
        try:
            contract = load_contract(path)
            report = guardian_report(path)
        except (IntentGuardianError, OSError, UnicodeError) as error:
            invalid.append({"contract_path": str(path), "error": str(error)})
            continue
        runtime = contract["runtime"]
        observations = runtime["host_observations"]
        capture = _approval_capture_summary(observations, provider=provider)
        contracts.append(
            {
                "contract_path": str(path),
                "intent_id": report["intent_id"],
                "revision": report["revision"],
                "contract_status": report["status"],
                "workspace": report["workspace"],
                "approval_capture": capture,
                "rebind_eligible": (
                    not report["workspace"]["exists"]
                    and not report["open_events"]
                    and not report["pending_verifications"]
                    and not report["effect_truth"]["interventions_open"]
                    and not runtime["active_skill_frames"]
                ),
            }
        )
    orphaned = [row for row in contracts if not row["workspace"]["exists"]]
    return {
        "status": "degraded" if orphaned or invalid else "ready",
        "provider": provider or "any",
        "contracts": contracts,
        "counts": {
            "active_contract_files": len(contracts),
            "orphaned": len(orphaned),
            "invalid": len(invalid),
        },
        "orphaned": orphaned,
        "invalid": invalid,
        "next_action": (
            "Review each orphan. The Agent must use a current-host native approval before "
            "executing an exact rebind or retirement; if no trustworthy native route is "
            "available, keep it blocked without delegating a CLI command to the user. Never "
            "copy old approvals into a new workspace."
            if orphaned
            else "No orphaned workspace contracts detected."
        ),
    }

def guardian_doctor(
    home: Path,
    workspace: Path,
    *,
    provider: str | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    requested_root = workspace.expanduser().resolve()
    selected_provider = provider.strip().lower() if provider else None
    selected_session = session_id.strip() if session_id else None
    mapped_path = None
    if selected_provider and selected_session:
        mapped_path = resolve_session_contract(
            home,
            selected_provider,
            selected_session,
        )
    if mapped_path is not None:
        path = mapped_path
        root = Path(load_contract(path)["workspace_root"]).expanduser().resolve()
    else:
        root = workspace_root(requested_root)
        path = active_contract_path(home, root)
    exact_path = bound_contract_path(home, requested_root)
    if (
        path != exact_path
        and not path.is_file()
        and (
            exact_path.is_file()
            or rebind_marker_path(exact_path).is_file()
            or retire_marker_path(exact_path).is_file()
        )
    ):
        # A deleted nested worktree may now resolve to a living parent repo.
        # Preserve its former exact binding for orphan diagnosis/recovery.
        root = requested_root
        path = exact_path
    host_readiness = host_readiness_projection(
        home,
        provider=selected_provider,
        session_id=selected_session,
        workspace=root,
    )
    hook_failures = hook_failure_projection(
        home,
        provider=selected_provider,
        session_id=selected_session,
        workspace=root,
    )
    operational_readiness = operational_readiness_projection(
        home,
        provider=selected_provider,
        session_id=selected_session,
        workspace=root,
        resolved_contract_path=path,
        recovery_truth=observe_recovery_truth(home),
    )
    if not path.is_file():
        retirement_path = retire_marker_path(path)
        if retirement_path.is_file():
            try:
                retirement = json.loads(retirement_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as error:
                raise IntentGuardianError(
                    f"invalid workspace retirement marker {retirement_path}: {error}"
                ) from error
            return {
                "status": "retired",
                "workspace": {
                    "root": str(root),
                    "exists": root.exists(),
                    "status": "workspace_retired",
                },
                "contract_path": str(path),
                "contract_exists": False,
                "retirement": retirement,
                "host_readiness": host_readiness,
                "hook_failures": hook_failures,
                "operational_readiness": operational_readiness,
                "approval_capture": {
                    "status": "unobserved",
                    "provider": selected_provider or "any",
                    "session_id": selected_session or "any",
                    "reason": "this abandoned workspace binding was retired",
                },
                "next_action": "No action is required for this retired workspace binding.",
            }
        marker_path = rebind_marker_path(path)
        if marker_path.is_file():
            try:
                marker = json.loads(marker_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as error:
                raise IntentGuardianError(
                    f"invalid workspace rebind marker {marker_path}: {error}"
                ) from error
            return {
                "status": "rebound",
                "workspace": {
                    "root": str(root),
                    "exists": root.exists(),
                    "status": "workspace_rebound",
                },
                "contract_path": str(path),
                "contract_exists": False,
                "rebind": marker,
                "host_readiness": host_readiness,
                "hook_failures": hook_failures,
                "operational_readiness": operational_readiness,
                "approval_capture": {
                    "status": "unobserved",
                    "provider": selected_provider or "any",
                    "session_id": selected_session or "any",
                    "reason": "this workspace binding was retired",
                },
                "next_action": (
                    "Use the destination workspace and approve a new intent proposal there; "
                    "old approvals were invalidated."
                ),
            }
        return {
            "status": "unobserved",
            "workspace": {
                "root": str(root),
                "exists": root.exists(),
                "status": "available" if root.exists() else "workspace_root_missing",
            },
            "contract_path": str(path),
            "contract_exists": False,
            "host_readiness": host_readiness,
            "hook_failures": hook_failures,
            "operational_readiness": operational_readiness,
            "approval_capture": {
                "status": "unobserved",
                "provider": selected_provider or "any",
                "session_id": selected_session or "any",
                "reason": "no live UserPromptSubmit event established a workspace contract",
            },
            "next_action": (
                "The Agent may run prepare-proposal to create a non-authorizing shadow "
                "contract. Human-routed proposals require a repaired/restarted host hook; "
                "eligible deterministic low-risk proposals may use agent-policy. A copied CLI "
                "command is not a substitute for a live human-prompt receipt."
            ),
        }
    report = guardian_report(
        path,
        provider=selected_provider or "",
        session_id=selected_session or "",
    )
    overall_capture = report["approval_capture"]
    observations = load_contract(path)["runtime"]["host_observations"]
    provider_capture = (
        _approval_capture_summary(observations, provider=selected_provider)
        if selected_provider
        else dict(overall_capture)
    )
    capture = (
        _approval_capture_summary(
            observations,
            provider=selected_provider,
            session_id=selected_session,
        )
        if selected_session
        else dict(provider_capture)
    )
    capture["overall_status"] = overall_capture["status"]
    capture["provider_status"] = provider_capture["status"]
    capture["by_provider"] = overall_capture["by_provider"]
    capture["authority"] = "observation_only_not_operational_readiness"
    report["approval_capture"] = capture
    report["host_readiness"] = host_readiness
    report["hook_failures"] = hook_failures
    report["operational_readiness"] = operational_readiness
    continuation = continuation_status(path)
    report["continuation"] = continuation
    cleanup_pending = report["workspace_cleanup"]["status"] == "pending"
    if cleanup_pending:
        next_action = report["workspace_cleanup"]["next_action"]
    elif operational_readiness["status"] == "ready":
        next_action = "Chat approval is available in the current host session."
    else:
        actions: list[str] = []
        interactive = operational_readiness.get("interactive_readiness", {})
        scheduler = operational_readiness.get("scheduler_readiness", {})
        effect_truth = operational_readiness.get("effect_truth", {})
        interactive_reasons = set(interactive.get("reasons") or [])
        if (
            not selected_session
            or {
                "current_session_bound",
                "host_interactive_fresh",
                "host_supervision_fresh",
            }
            & interactive_reasons
        ):
            actions.append(
                "Restart or open a fresh host session so SessionStart, UserPromptSubmit and "
                "tool supervision are observed for this exact runtime generation."
            )
        if effect_truth.get("status") not in {None, "clear"}:
            actions.append(
                "Do not repeat the side effect; let the registered verifier or an exact native "
                "effect intervention settle the append-only effect debt."
            )
        if scheduler.get("status") not in {None, "ready"}:
            actions.append(
                "The scheduler generation is not reconciled; keep operational readiness "
                "degraded until its separately approved generation-fenced command succeeds."
            )
        if continuation["status"] == "ready":
            actions.append(
                "Do not repeat an approval here; the authority-free continuation capsule is "
                "ready for the restarted or fresh session."
            )
        elif (
            continuation["status"] == "missing"
            and report["proposal_decisions"]["pending"]
        ):
            actions.append(
                "Mechanically prepare the continuation capsule before restarting; the resumed "
                "conversation will present its native Allow/Deny decision."
            )
        if not actions:
            actions.append(
                "Operational gates remain degraded; inspect operational_readiness.reasons and "
                "do not substitute historical prompt observations for current authority."
            )
        next_action = " ".join(actions)
    report.update(
        {
            "status": (
                "cleanup_pending"
                if cleanup_pending
                else "ready"
                if operational_readiness["status"] == "ready"
                else "degraded"
            ),
            "contract_path": str(path),
            "contract_exists": True,
            "next_action": next_action,
        }
    )
    return report
