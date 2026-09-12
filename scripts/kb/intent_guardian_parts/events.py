"""Intent Guardian events domain component."""

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

from .resources import (
    _continuation_candidate_from_grant,
    _guardian_skill_command,
    normalize_hook_event,
)

from .state import (
    BOOTSTRAP_RETRY_BINDING_FIELDS,
    COMPENSATION_CONTINUATION_PROFILES,
    CONTINUATION_GRANT_SCHEMA,
    CONTINUATION_PROFILES,
    IntentGuardianError,
    SYSTEM_MEMORY_GRANT_ID,
    SYSTEM_MEMORY_MAX_USES,
    SYSTEM_MEMORY_PROFILE,
    _pause_state,
    event_fingerprint,
)

def normalize_provider_event(record: dict[str, Any], *, provider: str) -> dict[str, Any] | None:
    phase = "completed" if str(record.get("type") or "").endswith("completed") else "started"
    item = record.get("item") if isinstance(record.get("item"), dict) else record
    item_type = str(item.get("type") or record.get("type") or "")
    if not item_type or item_type in {"thread.started", "turn.started", "turn.completed", "agent_message", "reasoning"}:
        return None
    payload: dict[str, Any] = {"client": provider, "observation_source": "provider_stream"}
    if item_type in {"command_execution", "command"}:
        command = str(item.get("command") or "")
        registration = _guardian_skill_command(command, provider=provider)
        if registration:
            if registration["action"] == "skill-end" and phase != "completed":
                return None
            if (
                registration["action"] == "skill-end"
                and item.get("status") in {"failed", "error"}
            ):
                return None
            payload.update(
                {
                    "tool_name": "Skill",
                    "tool_input": {
                        "skill": registration["name"],
                        "skill_path": registration["skill_path"],
                    },
                    "session_id": registration["session_id"],
                    "observation_source": "explicit_skill_registration_stream",
                    "registration_command": registration["action"],
                    "registration_contract": registration["contract_path"],
                }
            )
            # A completed skill-start is retained as a start fallback for
            # providers that omit item.started. GuardianSession de-duplicates
            # the normal started+completed pair by call id.
            phase = "started" if registration["action"] == "skill-start" else "completed"
        else:
            payload.update({"tool_name": "command_execution", "tool_input": {"command": command}})
    elif item_type in {"file_change", "file_changes"}:
        changes = item.get("changes") if isinstance(item.get("changes"), list) else []
        targets = [str(change.get("path")) for change in changes if isinstance(change, dict) and change.get("path")]
        payload.update({"tool_name": "file_change", "tool_input": {"target": ",".join(targets)}})
    elif "mcp" in item_type:
        payload.update(
            {
                "tool_name": str(item.get("tool") or item.get("name") or item_type),
                "server_name": str(item.get("server") or item.get("server_name") or "unknown"),
                "tool_input": item.get("arguments") or item.get("input") or {},
                "tool_response": item.get("result") or {},
            }
        )
    elif "skill" in item_type:
        payload.update(
            {
                "tool_name": "Skill",
                "tool_input": {
                    "skill": item.get("skill") or item.get("name") or "unknown",
                    "path": item.get("path") or "",
                },
            }
        )
    elif item_type in {"tool_call", "function_call"}:
        payload.update(
            {
                "tool_name": str(item.get("name") or "unknown"),
                "tool_input": item.get("arguments") or item.get("input") or {},
            }
        )
    else:
        return None
    payload["success"] = item.get("status") not in {"failed", "error"}
    payload["call_id"] = item.get("id") or record.get("id")
    normalized = normalize_hook_event(payload, phase=phase, provider=provider)
    if payload.get("registration_command"):
        normalized["registration_command"] = payload["registration_command"]
        normalized["registration_contract"] = payload["registration_contract"]
    return normalized

def normalize_provider_events(record: dict[str, Any], *, provider: str) -> list[dict[str, Any]]:
    """Return every observable tool event carried by one provider JSON line."""
    if provider == "claude" and record.get("type") == "assistant":
        message = record.get("message") if isinstance(record.get("message"), dict) else {}
        content = message.get("content") if isinstance(message.get("content"), list) else []
        events: list[dict[str, Any]] = []
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            payload = {
                "client": "claude",
                "observation_source": "provider_stream",
                "tool_name": str(block.get("name") or "unknown"),
                "tool_input": block.get("input") if isinstance(block.get("input"), dict) else {},
                "call_id": block.get("id"),
            }
            events.append(normalize_hook_event(payload, phase="started", provider="claude"))
        return events
    item = record.get("item") if isinstance(record.get("item"), dict) else record
    item_type = str(item.get("type") or record.get("type") or "")
    if item_type in {"file_change", "file_changes"}:
        phase = "completed" if str(record.get("type") or "").endswith("completed") else "started"
        changes = item.get("changes") if isinstance(item.get("changes"), list) else []
        events = []
        for change in changes:
            if not isinstance(change, dict) or not change.get("path"):
                continue
            payload = {
                "client": provider,
                "tool_name": "file_change",
                "tool_input": {"target": str(change["path"])},
                "success": item.get("status") not in {"failed", "error"},
                "call_id": item.get("id") or record.get("id"),
            }
            events.append(normalize_hook_event(payload, phase=phase, provider=provider))
        return events
    event = normalize_provider_event(record, provider=provider)
    return [event] if event else []

def _effect_attempt_target(event: dict[str, Any]) -> str:
    """Use a returned identity only for create/existence effects, not update replies."""
    target = str(event.get("target") or "")
    result_target = str(event.get("result_target") or "")
    if event.get("verification_kind") == "existence" and result_target:
        return result_target
    return target or result_target

def _effect_resource_identity(
    contract: dict[str, Any],
    event: dict[str, Any],
) -> tuple[str, str, dict[str, str], dict[str, str]]:
    """Derive one complete typed identity binding from the observed event.

    The returned key, resolution base, validation context and operation
    relation are one atomic projection.  Callers must persist/pass the four
    fields together so no typed key can escape without its replay inputs.
    """
    target = _effect_attempt_target(event)
    kind = str(event.get("kind") or "tool")
    arguments_digest = str(event.get("arguments_digest") or "")
    relation = {
        "schema": "sulde-effect-resource-relation-v1",
        "arguments_digest": arguments_digest,
    }
    local_path = bool(
        kind == "tool"
        and event.get("effect") in {"local_write", "read"}
        and target
        and not target.startswith("[")
        and not isinstance(event.get("git_resource_context"), dict)
        and not re.fullmatch(r"[A-Za-z][A-Za-z0-9+.-]*://.+", target)
        and not target.startswith("git-ref:")
    )
    base = str(
        event.get("resource_base")
        or contract.get("workspace_root")
        or os.getcwd()
    )
    if local_path:
        return canonical_resource_key(target, kind="path", base=base), base, {}, relation
    if kind == "mcp":
        server = str(event.get("server") or "").strip()
        resource_kind = re.sub(
            r"^(?:add|annotate|apply|create|delete|edit|get|list|move|patch|post|query|read|remove|search|set|show|transform|update|write)[_-]?",
            "",
            str(event.get("action") or "").strip().lower(),
        ).strip("_-")
        # Some MCP methods (for example ``transform``) name only the
        # operation. Keep their identity typed without treating the operation
        # name itself as a resource kind.
        resource_kind = resource_kind or "resource"
        if not target and event.get("sensitive_input"):
            # Safety policy rejects this event before an effect attempt is
            # persisted. Use a deterministic non-secret placeholder for that
            # evaluation while ordinary material MCP calls without a stable
            # identifier continue to fail closed below.
            placeholder = "[sensitive-mcp-resource]"
            event["target"] = placeholder
            return (
                canonical_resource_key(placeholder, kind="opaque"),
                "",
                {"schema": "exact", "value": placeholder},
                relation,
            )
        if not server or not resource_kind or not target or not arguments_digest:
            raise IntentGuardianError(
                "MCP resource identity requires server, stable resource kind, identifier, and arguments digest"
            )
        context = {
            "server": server,
            "resource_kind": resource_kind,
            "identifier": target,
        }
        return (
            canonical_resource_key(context, kind="mcp"),
            "",
            context,
            relation,
        )
    git_context = event.get("git_resource_context")
    if isinstance(git_context, dict) and set(git_context) == {"remote", "ref", "oid"}:
        context = {key: str(git_context[key]) for key in ("remote", "ref", "oid")}
        relation["verification_sha256"] = git_ref_verification_digest(
            remote=context["remote"],
            ref=context["ref"],
            oid=context["oid"],
            base=base,
        )
        return (
            canonical_resource_key(context, kind="git", base=base),
            "",
            context,
            relation,
        )
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9+.-]*://.+", target):
        return canonical_resource_key(target, kind="uri"), "", {}, relation
    context = {"schema": "exact", "value": target}
    return canonical_resource_key(target, kind="opaque"), "", context, relation

def _read_proof_target(event: dict[str, Any]) -> str:
    """A read proves the resource it requested; response member IDs cannot retarget it."""
    return str(event.get("target") or event.get("result_target") or "")

def _matches(value: str, patterns: Iterable[str]) -> bool:
    return any(fnmatch.fnmatchcase(value, pattern) for pattern in patterns)

def _matches_mcp_server(value: str, patterns: Iterable[str]) -> bool:
    aliases = {value, value.replace("_", "-"), value.replace("-", "_")}
    return any(_matches(alias, patterns) for alias in aliases)


def _workspace_relative_candidates(resolved: Path, root: Path) -> list[str]:
    """Return physical and logical paths for repository-local worktrees.

    ``.worktrees/<task>`` is a checkout location, not part of the task's
    logical source path.  Path policy therefore evaluates a file there both as
    its physical workspace-relative path and as the checkout-relative tail.
    This is purely filesystem scoping: it neither parses nor authorizes Git
    commands and it never treats the worktree's ``.git`` marker as writable.
    """
    try:
        relative = resolved.relative_to(root)
    except ValueError:
        return []
    candidates = [relative.as_posix()]
    parts = relative.parts
    if len(parts) >= 2 and parts[0] == ".worktrees":
        logical = Path(*parts[2:]).as_posix() if len(parts) > 2 else "."
        if logical not in candidates:
            candidates.append(logical)
    return candidates


def _paths_allowed(targets: Iterable[str], contract: dict[str, Any]) -> bool:
    raw_patterns = contract["constraints"]["allowed_paths"]
    root = Path(contract["workspace_root"]).expanduser()
    resolved_root = root.resolve()
    relative_patterns: list[str] = []
    absolute_patterns: list[str] = []
    for raw_pattern in raw_patterns:
        rendered = str(raw_pattern).strip()
        if not rendered:
            continue
        candidate = Path(rendered).expanduser()
        if candidate.is_absolute():
            # Absolute entries are explicit task roots/paths, including roots
            # outside the prompt cwd.  This is the multi-project authority;
            # the current workspace is merely the base for relative entries.
            absolute_patterns.append(candidate.resolve(strict=False).as_posix())
        else:
            pattern = candidate.as_posix()
            relative_patterns.append(pattern[2:] if pattern.startswith("./") else pattern)
    normalized_targets = [str(item) for item in targets if str(item)]
    for item in normalized_targets:
        try:
            path = Path(item).expanduser()
            resolved = (path if path.is_absolute() else root / path).resolve()
        except OSError:
            return False
        if set(resolved.parts) & {".git", ".codex-agent"}:
            return False
        if not raw_patterns:
            try:
                resolved.relative_to(resolved_root)
            except ValueError:
                return False
            continue
        absolute = resolved.as_posix()
        absolute_descendants = [
            f"{pattern.rstrip('/')}/**" for pattern in absolute_patterns
        ]
        absolute_match = _matches(absolute, absolute_patterns) or _matches(
            absolute, absolute_descendants
        )
        relative_descendants = [
            f"{pattern.rstrip('/')}/**" for pattern in relative_patterns
        ]
        relative_match = any(
            "." in relative_patterns
            or _matches(relative, relative_patterns)
            or _matches(relative, relative_descendants)
            for relative in _workspace_relative_candidates(resolved, resolved_root)
        )
        if not (absolute_match or relative_match):
            return False
    return bool(normalized_targets)

def _path_allowed(target: str, contract: dict[str, Any]) -> bool:
    return _paths_allowed((target,), contract)

def _paths_frozen(targets: Iterable[str], contract: dict[str, Any]) -> bool:
    raw_patterns = contract["constraints"]["frozen_paths"]
    if not raw_patterns:
        return False
    root = Path(contract["workspace_root"]).resolve()
    relative_patterns: list[str] = []
    absolute_patterns: list[str] = []
    for raw_pattern in raw_patterns:
        candidate = Path(str(raw_pattern)).expanduser()
        if candidate.is_absolute():
            absolute_patterns.append(candidate.resolve(strict=False).as_posix())
        else:
            pattern = candidate.as_posix()
            relative_patterns.append(pattern[2:] if pattern.startswith("./") else pattern)
    for item in (str(part) for part in targets if str(part)):
        try:
            path = Path(item).expanduser()
            resolved = (path if path.is_absolute() else root / path).resolve()
        except OSError:
            continue
        absolute = resolved.as_posix()
        if _matches(absolute, absolute_patterns) or _matches(
            absolute,
            [f"{pattern.rstrip('/')}/**" for pattern in absolute_patterns],
        ):
            return True
        relative_descendants = [
            f"{pattern.rstrip('/')}/**" for pattern in relative_patterns
        ]
        if any(
            _matches(relative, relative_patterns)
            or _matches(relative, relative_descendants)
            for relative in _workspace_relative_candidates(resolved, root)
        ):
            return True
    return False

def _path_frozen(target: str, contract: dict[str, Any]) -> bool:
    return _paths_frozen((target,), contract)

def _event_local_targets(event: dict[str, Any]) -> list[str]:
    structured = event.get("write_targets")
    if isinstance(structured, list) and all(
        isinstance(value, str) and value for value in structured
    ):
        return list(structured)
    target = str(event.get("target") or "")
    return [target] if target and not target.startswith("[") else []

def _human_approved_local_destructive(
    contract: dict[str, Any],
    event: dict[str, Any],
) -> bool:
    decision = contract.get("decision")
    effects = set(decision.get("effects") or []) if isinstance(decision, dict) else set()
    return bool(
        event.get("destructive_local_operation")
        and event.get("capability") == "tool:apply_patch"
        and contract["permissions"].get("local_write") is True
        and contract["permissions"].get("destructive") == "confirm"
        and {"local_write", "destructive"}.issubset(effects)
        and decision.get("selected_route") == "human"
        and contract.get("confirmed_by") == "human-readable-proposal-approval"
        and re.fullmatch(
            r"[0-9a-f]{64}",
            str(contract.get("applied_proposal_digest") or ""),
        )
        and re.fullmatch(
            r"[0-9a-f]{64}",
            str(contract.get("applied_approval_receipt_id") or ""),
        )
    )

def _completion_shape_matches(
    dispatched: dict[str, Any],
    completed: dict[str, Any],
    *,
    allow_verification_drift: bool = False,
) -> bool:
    """Require one host call to retain its material semantics across callbacks."""
    if (
        dispatched.get("provider") != completed.get("provider")
        or dispatched.get("session_id") != completed.get("session_id")
        or (dispatched.get("task_epoch") and completed.get("task_epoch")
            and dispatched["task_epoch"] != completed["task_epoch"])
    ):
        return False
    for field in ("kind", "capability", "effect", "verification_kind"):
        prior = str(dispatched.get(field) or "")
        current = str(completed.get(field) or "")
        if prior and current and prior != current:
            return False
    prior_digest = str(dispatched.get("verification_sha256") or "")
    current_digest = str(completed.get("verification_sha256") or "")
    if (
        prior_digest
        and current_digest
        and prior_digest != current_digest
        and not allow_verification_drift
    ):
        return False
    # Create/existence calls may learn their stable object identity only in the
    # response.  Other effects must retain the exact sealed target.
    prior_target = str(dispatched.get("target") or "")
    current_target = str(completed.get("target") or "")
    if (
        str(completed.get("verification_kind") or "") != "existence"
        and prior_target
        and current_target
        and prior_target != current_target
        and (
            not dispatched.get("effect_resource_key")
            or dispatched.get("effect_resource_key")
            != completed.get("effect_resource_key")
        )
    ):
        return False
    return True

def duplicate_host_call(runtime: dict[str, Any], event: dict[str, Any]):
    """Resolve dispatch epoch and duplicate delivery without minting authority.

    Provider file-change streams fan out one call into several typed targets.
    The actual host call ID stays intact; the target separates those components.
    """
    call_id = str(event.get("call_id") or "")
    if not call_id or event["kind"] == "skill" or event.get("control_plane"):
        return None
    def same_call(row):
        return (isinstance(row, dict) and row.get("call_id") == call_id
                and row.get("provider") == event.get("provider")
                and row.get("session_id") == event.get("session_id")
                and (event.get("capability") != "tool:file_change" or row.get("target") == event.get("target")))
    opened = [row for row in runtime["open_events"] if same_call(row)]
    settled = [row for row in runtime.get("completed_calls", []) if same_call(row)]
    if event["phase"] == "completed" and len(opened) == 1:
        event["task_epoch"] = opened[0].get("task_epoch", event["task_epoch"])
    duplicate = settled or (opened if event["phase"] == "started" else [])
    if not duplicate:
        return None
    prior = duplicate[0]
    shape = dict(event, task_epoch=prior.get("task_epoch", event["task_epoch"]))
    exact = len(duplicate) == 1 and _completion_shape_matches(prior, shape)
    return bool(exact and (event["phase"] == "completed" or not settled)), prior.get("event_id")


def _matching_continuation_uses(
    contract: dict[str, Any],
    event: dict[str, Any],
    *,
    grant_id: str,
    fingerprint: str,
) -> list[dict[str, Any]]:
    """Find the one dispatch use behind a completion, including hot upgrades."""
    uses = [
        row
        for row in contract["runtime"].get("continuation_uses", [])
        if isinstance(row, dict)
        and row.get("grant_id") == grant_id
        and row.get("provider") == event.get("provider")
        and row.get("session_id") == event.get("session_id")
    ]
    call_id = str(event.get("call_id") or "")
    if not call_id:
        exact = [row for row in uses if row.get("fingerprint") == fingerprint
                 and not row.get("call_id") and _completion_shape_matches(row, event)]
        return exact if len(exact) == 1 else []
    direct = [
        row
        for row in uses
        if row.get("call_id") == call_id
        and _completion_shape_matches(row, event)
    ]
    if len(direct) == 1:
        return direct
    if len(direct) > 1:
        return []
    # Compatibility for starts recorded before continuation uses carried a
    # call_id.  The open event binds that legacy fingerprint to the host call.
    open_matches = [
        row
        for row in contract["runtime"].get("open_events", [])
        if isinstance(row, dict)
        and str(row.get("call_id") or "") == call_id
        and _completion_shape_matches(row, event)
    ]
    if len(open_matches) != 1:
        return []
    dispatch_fingerprint = str(open_matches[0].get("fingerprint") or "")
    legacy = [row for row in uses if row.get("fingerprint") == dispatch_fingerprint
              and not row.get("call_id") and _completion_shape_matches(row, event)]
    return legacy if len(legacy) == 1 else []

def _completion_open_event_index(
    open_events: list[Any],
    event: dict[str, Any],
    *,
    fingerprint: str,
) -> int | None:
    """Pair one completion to its dispatch without trusting fingerprint alone."""
    call_id = str(event.get("call_id") or "")
    if call_id:
        by_call = [
            index
            for index, row in enumerate(open_events)
            if isinstance(row, dict)
            and str(row.get("call_id") or "") == call_id
            and _completion_shape_matches(row, event)
        ]
        if len(by_call) == 1:
            return by_call[0]
        if len(by_call) > 1:
            return None
    by_fingerprint = [
        index
        for index, row in enumerate(open_events)
        if isinstance(row, dict)
        and row.get("fingerprint") == fingerprint
        and row.get("provider") == event.get("provider")
        and row.get("session_id") == event.get("session_id")
        and _completion_shape_matches(row, event)
        and (
            event.get("kind") == "skill"
            or (not event.get("call_id") and not row.get("call_id"))
            or not row.get("call_id")
            or row.get("call_id") == event.get("call_id")
        )
    ]
    return by_fingerprint[0] if len(by_fingerprint) == 1 else None

def _hot_upgrade_completion_authorization(
    contract: dict[str, Any],
    event: dict[str, Any],
) -> dict[str, Any] | None:
    """Adopt one verified callback whose runtime changed during its own install.

    An installer can replace the stable Hook bridge before Codex emits the
    matching PostToolUse callback.  The new runtime then sees the post-
    cachebuster tracked tree rather than the proposal-time tree embedded in the
    sealed install grant.  That expected drift must not turn a completed,
    independently verified installation into permanent effect debt.

    This is not a general digest bypass.  Authority comes from the unique
    provider/session/call-id dispatch already stored in both ``open_events``
    and ``continuation_uses``.  Every binding field except the install
    profile's tracked-tree digest remains exact, the runtime generation must
    actually change, and the new runtime must already have completed the
    registered local verifier for its observed candidate.
    """
    if event.get("phase") != "completed":
        return None
    call_id = str(event.get("call_id") or "")
    candidate = event.get("continuation_candidate")
    independent = event.get("independent_verification")
    if (
        not call_id
        or not isinstance(candidate, dict)
        or not isinstance(independent, dict)
    ):
        return None
    profile_id = str(candidate.get("profile_id") or "")
    allowed_binding_drift = {
        "codex-plugin-install-v1": {"tracked_tree_sha256"},
    }.get(profile_id)
    verifier_identity = {
        "codex-plugin-install-v1": (
            "tool:codex_plugin_install_verify",
            "local_codex_install_read",
        ),
    }.get(profile_id)
    if not allowed_binding_drift or verifier_identity is None:
        return None
    current_verification = str(candidate.get("verification_sha256") or "")
    evidence = independent.get("evidence")
    if (
        event.get("verification_sha256") != current_verification
        or independent.get("capability") != verifier_identity[0]
        or independent.get("source") != verifier_identity[1]
        or not isinstance(evidence, dict)
        or evidence.get("content") != [current_verification]
    ):
        return None

    open_matches = [
        row
        for row in contract.get("runtime", {}).get("open_events", [])
        if isinstance(row, dict)
        and str(row.get("call_id") or "") == call_id
        and _completion_shape_matches(
            row,
            event,
            allow_verification_drift=True,
        )
    ]
    if len(open_matches) != 1:
        return None
    dispatched = open_matches[0]
    if (
        not str(dispatched.get("runtime_generation") or "")
        or dispatched.get("runtime_generation") == event.get("runtime_generation")
    ):
        return None
    grant_id = str(dispatched.get("continuation_grant_id") or "")
    if (
        not grant_id
        or dispatched.get("continuation_profile_id") != profile_id
    ):
        return None
    uses = [
        row
        for row in contract.get("runtime", {}).get("continuation_uses", [])
        if isinstance(row, dict)
        and row.get("grant_id") == grant_id
        and row.get("profile_id") == profile_id
        and row.get("provider") == event.get("provider")
        and row.get("session_id") == event.get("session_id")
        and str(row.get("call_id") or "") == call_id
        and row.get("fingerprint") == dispatched.get("fingerprint")
        and _completion_shape_matches(
            row,
            event,
            allow_verification_drift=True,
        )
    ]
    if len(uses) != 1:
        return None
    grants = [
        grant
        for grant in contract.get("continuation", {}).get("grants", [])
        if isinstance(grant, dict)
        and grant.get("grant_id") == grant_id
        and grant.get("profile_id") == profile_id
    ]
    if len(grants) != 1:
        return None
    grant = grants[0]
    try:
        acceptance_index = int(grant["acceptance_index"])
        acceptance_digest = hashlib.sha256(
            contract["acceptance_criteria"][acceptance_index].encode("utf-8")
        ).hexdigest()
        dispatched_candidate = _continuation_candidate_from_grant(grant)
    except (IndexError, KeyError, TypeError, ValueError):
        return None
    if (
        acceptance_digest != grant.get("acceptance_sha256")
        or candidate.get("effect") != grant.get("effect")
        or grant.get("effect") != event.get("effect")
        or grant.get("capability") != event.get("capability")
        or candidate.get("target") != grant.get("target")
        or grant.get("target") != event.get("target")
        or candidate.get("verification_kind")
        != grant.get("verification_kind")
        or grant.get("verification_kind") != event.get("verification_kind")
    ):
        return None
    dispatched_binding = dispatched_candidate.get("binding")
    current_binding = candidate.get("binding")
    if not isinstance(dispatched_binding, dict) or not isinstance(current_binding, dict):
        return None
    binding_fields = set(dispatched_binding) | set(current_binding)
    drift = {
        field
        for field in binding_fields
        if dispatched_binding.get(field) != current_binding.get(field)
    }
    if not drift or not drift.issubset(allowed_binding_drift):
        return None
    if any(
        not re.fullmatch(r"[0-9a-f]{64}", str(current_binding.get(field) or ""))
        for field in drift
    ):
        return None
    dispatch_verification = str(dispatched_candidate["verification_sha256"])
    if (
        dispatched.get("verification_sha256") != dispatch_verification
        or uses[0].get("verification_sha256") != dispatch_verification
    ):
        return None
    used = sum(
        1
        for row in contract.get("runtime", {}).get("continuation_uses", [])
        if isinstance(row, dict) and row.get("grant_id") == grant_id
    )
    return {
        "authority": "contract-grant",
        "grant_id": grant_id,
        "profile_id": profile_id,
        "use_number": used,
        "max_uses": int(grant["max_uses"]),
        "fingerprint": event_fingerprint(event),
        "dispatch_fingerprint": str(dispatched.get("fingerprint") or ""),
        "dispatch_verification_sha256": dispatch_verification,
        "observed_verification_sha256": current_verification,
        "allowed_binding_drift": sorted(drift),
        "completion": True,
        "hot_upgrade_adopted": True,
    }

def _continuation_authorization(
    contract: dict[str, Any],
    event: dict[str, Any],
) -> dict[str, Any] | None:
    """Match dispatch, then its callback, to one sealed continuation lane."""
    phase = str(event.get("phase") or "")
    if phase not in {"started", "completed"} or contract.get("status") == "closed":
        return None
    # The top-level paused status is a compatibility projection: one sibling
    # lane may be paused while this exact provider/session lane remains bound.
    # Only the applicable pause revokes continuation authority.
    if _pause_state(
        contract,
        provider=str(event.get("provider") or "unknown"),
        session_id=str(event.get("session_id") or ""),
    ) is not None:
        return None
    if contract.get("confirmed_by") in {"unconfirmed", "unconfirmed-proposal"}:
        return None
    candidate = event.get("continuation_candidate")
    if not isinstance(candidate, dict):
        return None
    if phase == "completed":
        hot_upgrade = _hot_upgrade_completion_authorization(contract, event)
        if hot_upgrade is not None:
            return hot_upgrade
    fingerprint = event_fingerprint(event)
    uses = contract["runtime"].get("continuation_uses", [])
    profile_id = str(candidate.get("profile_id") or "")

    if profile_id == SYSTEM_MEMORY_PROFILE:
        if (
            not contract["permissions"]["local_write"]
            or event.get("kind") != "mcp"
            or str(event.get("server") or "").replace("-", "_").lower() != "sulde_kb"
            or str(event.get("action") or "").lower() != "memory_annotate"
            or event.get("effect") != "local_write"
            or candidate.get("effect") != "local_write"
            or candidate.get("target") != event.get("target")
            or candidate.get("verification_kind") != "relation"
            or candidate.get("verification_sha256") != event.get("verification_sha256")
            or candidate.get("extracted_by") != str(event.get("provider") or "").lower()
        ):
            return None
        matching_uses = _matching_continuation_uses(
            contract,
            event,
            grant_id=SYSTEM_MEMORY_GRANT_ID,
            fingerprint=fingerprint,
        )
        used = sum(
            1
            for row in uses
            if isinstance(row, dict) and row.get("grant_id") == SYSTEM_MEMORY_GRANT_ID
        )
        if phase == "completed":
            if not matching_uses:
                return None
            return {
                "authority": "system-policy",
                "grant_id": SYSTEM_MEMORY_GRANT_ID,
                "profile_id": SYSTEM_MEMORY_PROFILE,
                "use_number": used,
                "max_uses": 0,  # no lifetime usage cap; bounded request shape
                "fingerprint": fingerprint,
                "dispatch_fingerprint": matching_uses[0]["fingerprint"],
                "completion": True,
            }
        # Historical usage is audit, not permission. Batch shape and exact
        # attribution are checked by the registered memory capability above.
        return {
            "authority": "system-policy",
            "grant_id": SYSTEM_MEMORY_GRANT_ID,
            "profile_id": SYSTEM_MEMORY_PROFILE,
            "use_number": used + 1,
            "max_uses": 0,
            "fingerprint": fingerprint,
        }

    for grant in contract.get("continuation", {}).get("grants", []):
        if not isinstance(grant, dict) or grant.get("profile_id") != profile_id:
            continue
        acceptance_index = int(grant["acceptance_index"])
        current_acceptance_sha256 = hashlib.sha256(
            contract["acceptance_criteria"][acceptance_index].encode("utf-8")
        ).hexdigest()
        if (
            current_acceptance_sha256 != grant["acceptance_sha256"]
            or candidate.get("effect") != grant["effect"]
            or event.get("effect") != grant["effect"]
            or event.get("capability") != grant["capability"]
            or candidate.get("target") != grant["target"]
            or event.get("target") != grant["target"]
            or candidate.get("verification_kind") != grant["verification_kind"]
            or event.get("verification_kind") != grant["verification_kind"]
            or candidate.get("binding") != grant["binding"]
        ):
            continue
        matching_uses = _matching_continuation_uses(
            contract,
            event,
            grant_id=grant["grant_id"],
            fingerprint=fingerprint,
        )
        used = sum(
            1
            for row in uses
            if isinstance(row, dict) and row.get("grant_id") == grant["grant_id"]
        )
        if phase == "completed":
            if not matching_uses:
                return None
            return {
                "authority": "contract-grant",
                "grant_id": grant["grant_id"],
                "profile_id": profile_id,
                "use_number": used,
                "max_uses": int(grant["max_uses"]),
                "fingerprint": fingerprint,
                "dispatch_fingerprint": matching_uses[0]["fingerprint"],
                "completion": True,
            }
        if used >= int(grant["max_uses"]):
            return None
        return {
            "authority": "contract-grant",
            "grant_id": grant["grant_id"],
            "profile_id": profile_id,
            "use_number": used + 1,
            "max_uses": int(grant["max_uses"]),
            "fingerprint": fingerprint,
        }
    return None

def _retag_guardian_violation(
    event: dict[str, Any],
    *,
    action: str,
    target: str,
) -> None:
    event.update(
        {
            "kind": "tool",
            "action": action,
            "capability": f"guardian:{action}",
            "effect": "destructive",
            "target": target,
        }
    )
    event["event_id"] = hashlib.sha256(
        "\0".join(
            str(event.get(key) or "")
            for key in ("provider", "session_id", "capability", "target", "arguments_digest")
        ).encode("utf-8")
    ).hexdigest()[:24]

def _registered_compensation_predecessor(
    contract: dict[str, Any],
    event: dict[str, Any],
    blocker: dict[str, Any],
) -> str:
    """Return one old unknown attempt an exact sealed action may compensate."""
    authority = event.get("continuation_authority")
    if not isinstance(authority, dict):
        return ""
    profile_id = str(authority.get("profile_id") or "")
    profile = CONTINUATION_PROFILES.get(profile_id)
    if (
        event.get("phase") != "started"
        or profile_id not in COMPENSATION_CONTINUATION_PROFILES
        or not isinstance(profile, dict)
        or blocker.get("attempt_state") != "unknown"
        or blocker.get("intervention_status") not in {"open", "acknowledged"}
        or event.get("effect") != profile.get("effect")
        or event.get("capability") != profile.get("capability")
        or event.get("target") != profile.get("target")
    ):
        return ""
    predecessor_id = str(blocker.get("attempt_id") or "")
    current_grant_id = str(authority.get("grant_id") or "")
    for row in contract.get("runtime", {}).get("pending_verifications", []):
        if not isinstance(row, dict) or row.get("attempt_id") != predecessor_id:
            continue
        old_grant = row.get("continuation_grant")
        if (
            row.get("outcome_unknown") is not True
            or row.get("continuation_profile_id") != profile_id
            or row.get("target") != profile["target"]
            or not isinstance(old_grant, dict)
            or old_grant.get("schema") != CONTINUATION_GRANT_SCHEMA
            or old_grant.get("profile_id") != profile_id
            or old_grant.get("effect") != profile["effect"]
            or old_grant.get("capability") != profile["capability"]
            or old_grant.get("target") != profile["target"]
            or old_grant.get("verification_kind")
            != profile["verification_kind"]
            or not current_grant_id
            or old_grant.get("grant_id") == current_grant_id
        ):
            return ""
        return predecessor_id
    return ""

def _registered_semantic_retry_intervention(
    contract: dict[str, Any],
    event: dict[str, Any],
    blocker: dict[str, Any],
) -> str:
    """Bind a command alias to one sealed, unconsumed installation retry.

    Event fingerprints deliberately include the observable command input.  A
    stable launcher, absolute interpreter path, or equivalent shell spelling
    can therefore change the fingerprint even though the continuation grant
    still proves the same provider/session/target and machine boundary.  Only
    a previously authorized retry plus two fully validated continuation grants
    may bridge that syntactic difference.  Arbitrary commands never enter this
    path, and the intervention store consumes the authority exactly once.
    """
    authority = event.get("continuation_authority")
    if not isinstance(authority, dict):
        return ""
    profile_id = str(authority.get("profile_id") or "")
    current_grant_id = str(authority.get("grant_id") or "")
    profile = CONTINUATION_PROFILES.get(profile_id)
    if (
        event.get("phase") != "started"
        or profile_id not in COMPENSATION_CONTINUATION_PROFILES
        or not isinstance(profile, dict)
        or blocker.get("attempt_state") != "unknown"
        or blocker.get("intervention_status") != "resolved"
        or blocker.get("decision") != "retry_authorized"
        or blocker.get("retry_consumed_by")
        or blocker.get("takeover_provider") != event.get("provider")
        or blocker.get("takeover_session_id") != event.get("session_id")
        or event.get("effect") != profile.get("effect")
        or event.get("capability") != profile.get("capability")
        or event.get("target") != profile.get("target")
        or not current_grant_id
    ):
        return ""
    current_matches = [
        grant
        for grant in contract.get("continuation", {}).get("grants", [])
        if isinstance(grant, dict)
        and grant.get("grant_id") == current_grant_id
        and grant.get("profile_id") == profile_id
    ]
    if len(current_matches) != 1:
        return ""
    current_grant = current_matches[0]
    current_binding = current_grant.get("binding")
    if (
        current_grant.get("schema") != CONTINUATION_GRANT_SCHEMA
        or current_grant.get("effect") != event.get("effect")
        or current_grant.get("capability") != event.get("capability")
        or current_grant.get("target") != event.get("target")
        or current_grant.get("verification_kind")
        != event.get("verification_kind")
        or not isinstance(current_binding, dict)
    ):
        return ""
    try:
        current_verification = _continuation_candidate_from_grant(current_grant)[
            "verification_sha256"
        ]
    except (KeyError, TypeError, ValueError):
        return ""
    if current_verification != event.get("verification_sha256"):
        return ""

    predecessor_id = str(blocker.get("attempt_id") or "")
    intervention_id = str(blocker.get("intervention_id") or "")
    matches = []
    for row in contract.get("runtime", {}).get("pending_verifications", []):
        if not isinstance(row, dict) or row.get("attempt_id") != predecessor_id:
            continue
        old_grant = row.get("continuation_grant")
        old_binding = old_grant.get("binding") if isinstance(old_grant, dict) else None
        if (
            row.get("outcome_unknown") is not True
            or row.get("provider") != event.get("provider")
            or row.get("target") != event.get("target")
            or row.get("capability") != event.get("capability")
            or row.get("continuation_profile_id") != profile_id
            or not isinstance(old_grant, dict)
            or old_grant.get("schema") != CONTINUATION_GRANT_SCHEMA
            or old_grant.get("grant_id") == current_grant_id
            or old_grant.get("profile_id") != profile_id
            or old_grant.get("effect") != event.get("effect")
            or old_grant.get("capability") != event.get("capability")
            or old_grant.get("target") != event.get("target")
            or old_grant.get("verification_kind")
            != event.get("verification_kind")
            or not isinstance(old_binding, dict)
            or any(
                old_binding.get(field) != current_binding.get(field)
                for field in BOOTSTRAP_RETRY_BINDING_FIELDS
            )
        ):
            continue
        try:
            old_verification = _continuation_candidate_from_grant(old_grant)[
                "verification_sha256"
            ]
        except (KeyError, TypeError, ValueError):
            continue
        if row.get("verification_sha256") != old_verification:
            continue
        matches.append(row)
    return intervention_id if intervention_id and len(matches) == 1 else ""
