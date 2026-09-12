"""Intent Guardian resources domain component."""
from __future__ import annotations
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import ast
import fnmatch
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
import time
from typing import Any, Callable, Iterable, Iterator
from memory_annotation import normalize as normalize_memory_annotation, digest as memory_annotation_digest, verify_receipt as verify_memory_receipt
from command_template import (
    execution_domain_commands as _execution_domain_commands,
    git_execution_passthrough as _git_execution_passthrough,
    has_unquoted_shell_control as _has_unquoted_shell_control,
    is_read_only_command as _is_read_only_command,
    read_pipeline_segments as _read_pipeline_segments,
    shell_wrapper_payload as _shell_wrapper_payload,
    split_single_heredoc as _split_single_heredoc,
    split_command_template,
)
from file_lock import lock_exclusive_nonblocking, unlock
from python_data_methods import (
    inline_source, literal_shell_transport, proven_data_method_calls, proven_path_method_calls,
)
from human_control import codex_text_control_requires_native, parse_human_control
from host_capabilities import (
    HostCapabilityError,
    readiness_projection as host_readiness_projection,
)
from launcher_contract import (
    SCRIPT_EFFECT_PROFILES,
    classify_trusted_script_command,
    default_codex_home,
    identify_trusted_script_command,
    verify_installation as verify_launcher_installation,
    installed_launchers_match,
)
from local_file_operations import (
    LocalFileOperationError,
    has_destructive_operation,
    operation_targets,
    parse_apply_patch_operations,
)
from sulde_effects import DEFAULT_EFFECT_ROUTER
from sulde_paths import launcher_home
from resource_adapters import (
    ResourceAdapterError as _ResourceAdapterError,
    classify_hook_resource as _classify_hook_resource,
)
from .orchestrator_resources import (
    unified_exec_nested_calls as _unified_exec_nested_calls,
)
from .control_composition import CompositionServices, normalize_composition
from .event_identity import bind_host_call_identity
from .resource_preflight import (
    codex_plugin_read_only_maintenance_command
    as _codex_plugin_read_only_maintenance_command,
    command_execution_cwd as _command_execution_cwd,
    codex_plugin_cachebuster_v2_candidate
    as _codex_plugin_cachebuster_v2_candidate,
    codex_candidate_promotion_candidate as _codex_candidate_promotion_candidate,
    codex_plugin_install_v2_candidate as _codex_plugin_install_v2_candidate,
    first_input_value as _first_input_value,
    formal_maintenance_reference as _formal_maintenance_reference,
    git_worktree_lifecycle_event as _git_worktree_lifecycle_event,
    git_invocation as _git_invocation,
    _local_git_output,
    _git_remote_digest,
    _git_head_ref,
    _git_upstream,
    _git_positionals,
    git_ref_observation as _git_ref_observation,
    literal_shell_delete_operations as _literal_shell_delete_operations,
    launcher_refresh_candidate as _launcher_refresh_candidate,
    launcher_refresh_verification as _launcher_refresh_verification,
    labels_digest as _labels_digest,
    local_target_label as _local_target_label,
    literal_shell_delete_is_high_risk as _literal_shell_delete_is_high_risk,
    portable_tree_sha256 as _portable_tree_sha256,
    resolved_executable as _resolved_executable,
    response_target as _response_target,
    safe_local_path as _safe_local_path,
    safe_target as _safe_target,
    scheduler_reconcile_candidate as _scheduler_reconcile_candidate,
    scheduler_reconcile_verification as _scheduler_reconcile_verification,
    tool_local_write_targets as _tool_local_write_targets,
    protected_json_object as _protected_json_object,
    unsealed_codex_plugin_cachebuster_invocation
    as _unsealed_codex_plugin_cachebuster_invocation,
    unsealed_sulde_maintenance_invocation
    as _unsealed_sulde_maintenance_invocation,
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
from .state import (
    AGENT_CONTINUATION_PROFILES,
    AGENT_CONTROL_ACTIONS,
    CONTINUATION_PROFILES,
    DESTRUCTIVE_WORDS,
    EFFECTS,
    EVENT_SCHEMA,
    GUARDIAN_LAUNCHER_NAMES,
    HUMAN_CONTROL_ACTIONS,
    IntentGuardianError,
    NATIVE_DECISIONS,
    NATIVE_PERMISSION_CONTROL_ACTIONS,
    PAUSE_SAFE_HOST_CONTROL_ACTIONS,
    READ_ONLY_AGENT_CONTROL_ACTIONS,
    READ_WORDS,
    ARTIFACT_GENERATION,
    LOADED_MODULE_GENERATION,
    RUNTIME_GENERATION,
    SECRET_KEY,
    SYSTEM_MEMORY_PROFILE,
    WRITE_WORDS,
    _SECRET_VALUE_PATTERN,
    _VERIFICATION_CONTENT_KEYS,
    _codex_plugin_cachebuster_binding,
    _codex_plugin_cachebuster_v2_binding,
    _codex_plugin_install_binding,
    _continuation_grant_id,
    _json_version,
    _sha256_path,
    _workspace_tracked_tree_sha256,
    active_contract_path,
    default_contract,
    kb_home,
    now_iso,
    workspace_root,
)
from .session_workspace import resolve_session_contract
from .resource_postconditions import (
    _words, _verification_digest, _memory_annotation_postcondition,
    _write_verification_expectation, _read_verification_evidence, _response_proves_existence,
)

def resolve_contract_path(payload: dict[str, Any], *, cwd: Path | None = None) -> Path | None:
    provider = str(payload.get("client") or payload.get("provider") or "").strip().lower()
    session_id = str(
        payload.get("session_id") or payload.get("sessionId") or ""
    ).strip()
    if provider in {"claude", "codex"} and session_id:
        mapped = resolve_session_contract(kb_home(), provider, session_id)
        if mapped is not None:
            return mapped
    explicit = str(
        payload.get("intent_contract")
        or os.environ.get("SULDE_INTENT_CONTRACT")
        or ""
    ).strip()
    if explicit:
        path = Path(explicit).expanduser()
        if path.is_file():
            return path
        # A launch-time hint is not durable ownership.  If its worktree was
        # removed, continue with the live cwd binding instead of silently
        # disabling supervision for the rest of the session.
    raw_cwd = cwd or Path(str(payload.get("cwd") or os.getcwd()))
    candidate = active_contract_path(kb_home(), workspace_root(raw_cwd))
    return candidate if candidate.is_file() else None

def _section(markdown: str, heading: str) -> str:
    match = re.search(
        rf"^##\s+{re.escape(heading)}[^\n]*\n(.*?)(?=^##\s+|\Z)",
        markdown,
        re.MULTILINE | re.DOTALL,
    )
    return match.group(1).strip() if match else ""

def _bullets(text: str) -> list[str]:
    values: list[str] = []
    for raw in text.splitlines():
        line = re.sub(r"^\s*(?:[-*+]\s+|\d+[.)]\s+|[✅❌]\s*)", "", raw).strip()
        if line and not line.startswith("<"):
            values.append(line[:500])
    return values

def contract_from_brief(
    brief: str,
    *,
    slug: str,
    workspace: Path,
    mode: str = "shadow",
    confirmed_by: str = "human",
    semantic_critic: bool = False,
) -> dict[str, Any]:
    objective = _section(brief, "目标") or next((line.strip("# ") for line in brief.splitlines() if line.strip()), slug)
    criteria = _bullets(_section(brief, "完成标准")) or ["任务终态报告通过 Sulde 独立验收"]
    scope = _section(brief, "范围")
    allowed: list[str] = []
    match = re.search(r"涉及路径\s*[:：]\s*(.+)", scope)
    if match and "<" not in match.group(1):
        allowed = [item.strip(" `") for item in re.split(r"[,，、]", match.group(1)) if item.strip(" `")]
    rejected = []
    forbidden = re.search(r"禁止改动\s*[:：]\s*(.+)", scope)
    if forbidden:
        rejected = [item.strip() for item in re.split(r"[;；]", forbidden.group(1)) if item.strip()]
    return default_contract(
        intent_id=f"l3:{slug}",
        objective=objective[:2_000],
        acceptance_criteria=criteria,
        workspace=workspace,
        mode=mode,
        rationale="由已获人工批准的 Sulde L3 任务书生成",
        reject=rejected,
        allowed_paths=allowed,
        confirmed_by=confirmed_by,
        semantic_critic=semantic_critic,
    )




def _system_memory_annotation_candidate(
    tool_input: dict[str, Any],
    *,
    provider: str,
    expected_digest: str,
) -> dict[str, Any] | None:
    """Return a fixed local policy lane for a small, attributable graph write."""
    normalized_provider = provider.strip().lower()
    if normalized_provider not in {"claude", "codex"}:
        return None
    try:
        normalized = normalize_memory_annotation(tool_input, extracted_by=normalized_provider, bounded=True)
    except (ValueError, TypeError):
        return None
    if set(tool_input) != {"entities", "edges", "extracted_by"}:
        return None
    if tool_input.get("extracted_by") != normalized_provider:
        return None
    entities = tool_input.get("entities")
    edges = tool_input.get("edges")
    if (
        not isinstance(entities, list)
        or not isinstance(edges, list)
        or not 1 <= len(entities) <= 6
        or not 1 <= len(edges) <= 3
    ):
        return None
    entity_names: set[str] = set()
    for entity in entities:
        if not isinstance(entity, dict) or set(entity) != {"name", "type"}:
            return None
        name = entity.get("name")
        if not isinstance(name, str) or not name.strip() or name.strip() in entity_names:
            return None
        entity_names.add(name.strip())
    for edge in edges:
        if not isinstance(edge, dict) or not set(edge).issubset(
            {"src", "rel", "dst", "entry_id", "confidence"}
        ):
            return None
        if not {"src", "rel", "dst"}.issubset(edge):
            return None
        if str(edge.get("src") or "").strip() not in entity_names:
            return None
        if str(edge.get("dst") or "").strip() not in entity_names:
            return None
        entry_id = edge.get("entry_id")
        if entry_id is not None and (isinstance(entry_id, bool) or not isinstance(entry_id, int)):
            return None
        confidence = edge.get("confidence", 1.0)
        if (
            isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not 0.0 <= float(confidence) <= 1.0
        ):
            return None
    postcondition = _memory_annotation_postcondition(tool_input)
    if (
        postcondition is None
        or not expected_digest
        or expected_digest not in {_verification_digest(postcondition), memory_annotation_digest(normalized)}
    ):
        return None
    return {
        "profile_id": SYSTEM_MEMORY_PROFILE,
        "effect": "local_write",
        "capability": "mcp:sulde_kb:memory_annotate",
        "target": f"[memory-annotation:{expected_digest}]",
        "verification_kind": "relation",
        "verification_sha256": expected_digest,
        "entity_count": len(entities),
        "edge_count": len(edges),
        "extracted_by": normalized_provider,
    }


def _memory_receipt_verification(expected_digest: str) -> dict[str, Any] | None:
    """Resolve a digest-only recipe through an independent read-only connection."""
    if not re.fullmatch(r"[0-9a-f]{64}", expected_digest):
        return None
    database = kb_home() / "memory.db"
    try:
        connection = sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True, timeout=0.25)
        try:
            connection.execute("PRAGMA query_only=ON")
            connection.execute("BEGIN")
            result = verify_memory_receipt(connection, expected_digest)
        finally:
            connection.close()
    except (OSError, sqlite3.Error, ValueError, TypeError):
        return None
    if result is None:
        return None
    return {"capability": "mcp:sulde_kb:memory_graph", "evidence": {"relation": [expected_digest]},
            "source": "local_memory_db_read", "recipe_schema": "sulde-memory-annotation-v2"}

def _local_memory_annotation_verification(
    tool_input: dict[str, Any],
    *,
    expected_digest: str,
) -> dict[str, Any] | None:
    """Prove every declared memory row through an independent read-only DB handle."""
    try:
        request = normalize_memory_annotation(tool_input)
    except (ValueError, TypeError):
        request = None
    if request is not None and memory_annotation_digest(request) == expected_digest:
        return _memory_receipt_verification(expected_digest)
    # v1 evidence remains v1: never silently rehash or relabel historical rows.
    postcondition = _memory_annotation_postcondition(tool_input)
    if (
        postcondition is None
        or not expected_digest
        or _verification_digest(postcondition) != expected_digest
    ):
        return None
    database_path = kb_home() / "memory.db"
    try:
        database_uri = f"{database_path.resolve().as_uri()}?mode=ro"
        connection = sqlite3.connect(
            database_uri,
            uri=True,
            timeout=0.25,
        )
        try:
            connection.execute("PRAGMA query_only = ON")
            connection.execute("PRAGMA busy_timeout = 250")
            connection.execute("BEGIN")
            for entity in postcondition["entities"]:
                row = connection.execute(
                    "SELECT 1 FROM mem_entities WHERE name = ? AND type = ? LIMIT 1",
                    (entity["name"], entity["type"]),
                ).fetchone()
                if row is None:
                    return None
            for relation in postcondition["relations"]:
                matching_edge = next(
                    edge
                    for edge in tool_input["edges"]
                    if str(edge.get("src") or "").strip() == relation["subject"]
                    and str(edge.get("rel") or "").strip() == relation["predicate"]
                    and str(edge.get("dst") or "").strip() == relation["object"]
                )
                row = connection.execute(
                    """
                    SELECT 1 FROM mem_edges
                    WHERE src = ? AND rel = ? AND dst = ?
                      AND entry_id IS ? AND extracted_by = ? AND confidence = ?
                    LIMIT 1
                    """,
                    (
                        relation["subject"],
                        relation["predicate"],
                        relation["object"],
                        matching_edge.get("entry_id"),
                        tool_input.get("extracted_by"),
                        float(matching_edge.get("confidence", 1.0)),
                    ),
                ).fetchone()
                if row is None:
                    return None
        finally:
            connection.close()
    except (OSError, sqlite3.Error, UnicodeError, ValueError):
        return None
    return {
        "capability": "mcp:sulde_kb:memory_graph",
        "evidence": {"relation": [expected_digest]},
        "source": "local_memory_db_read",
    }




def _input_digest(tool_input: dict[str, Any]) -> str:
    scrubbed = {
        str(key): "[redacted]" if SECRET_KEY.search(str(key)) else value
        for key, value in tool_input.items()
    }
    try:
        rendered = json.dumps(scrubbed, ensure_ascii=False, sort_keys=True, default=str)
    except (TypeError, ValueError):
        rendered = repr(sorted(tool_input))
    return hashlib.sha256(rendered.encode("utf-8", errors="replace")).hexdigest()

def _contains_sensitive_material(value: Any, *, depth: int = 0) -> bool:
    """Detect possible secret-bearing input without retaining the secret."""
    if depth > 5:
        return False
    if isinstance(value, dict):
        for key, nested in list(value.items())[:200]:
            if (
                SECRET_KEY.search(str(key))
                and nested is not None
                and nested != ""
                and nested is not False
            ):
                return True
            if _contains_sensitive_material(nested, depth=depth + 1):
                return True
        return False
    if isinstance(value, (list, tuple)):
        return any(
            _contains_sensitive_material(item, depth=depth + 1)
            for item in value[:200]
        )
    return bool(_SECRET_VALUE_PATTERN.search(value)) if isinstance(value, str) else False

def _trusted_guardian_launcher_digest(raw_path: str) -> str:
    """Return the launcher digest only for this runtime's known entrypoints."""
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        return ""
    script_root = Path(__file__).resolve().parents[1]
    public_home = launcher_home(kb_home())
    known = {
        (script_root / "intent-guardian.py").expanduser().resolve(),
        (public_home / "bin" / "intent-guardian").expanduser().resolve(),
        (public_home / "bin" / "intent-guardian.cmd").expanduser().resolve(),
        (public_home / "bin" / "intent-guardian.exe").expanduser().resolve(),
        (kb_home() / "bin" / "intent-guardian").expanduser().resolve(),
        (kb_home() / "bin" / "intent-guardian.cmd").expanduser().resolve(),
        (kb_home() / "bin" / "intent-guardian.exe").expanduser().resolve(),
    }
    try:
        resolved = candidate.resolve()
        if resolved not in known or not resolved.is_file():
            return ""
        return hashlib.sha256(resolved.read_bytes()).hexdigest()
    except OSError:
        return ""

def _guardian_invocation(command: str) -> dict[str, Any] | None:
    """Parse a Guardian invocation only when it is the command executable."""
    try:
        tokens = split_command_template(command)
    except ValueError:
        return None
    if not tokens:
        return None
    launcher_index = 0
    first_name = Path(tokens[0]).name.lower()
    if re.fullmatch(r"python(?:\d+(?:\.\d+)*)?(?:\.exe)?", first_name):
        if len(tokens) < 2:
            return None
        launcher_index = 1
    launcher = tokens[launcher_index]
    if Path(launcher).name.lower() not in GUARDIAN_LAUNCHER_NAMES:
        return None
    action_index = launcher_index + 1
    action = tokens[action_index].strip().lower() if len(tokens) > action_index else ""
    return {
        "tokens": tokens,
        "launcher_index": launcher_index,
        "action_index": action_index,
        "action": action,
        "launcher": launcher,
        "runtime_sha256": _trusted_guardian_launcher_digest(launcher),
        "chained": _has_unquoted_shell_control(command),
    }

def parse_native_decision_command(command: str) -> dict[str, str] | None:
    """Parse the one exact command allowed to wait for Codex approval.

    This parser deliberately accepts no shell composition, duplicate options,
    implicit provider, or omitted session binding.  Semantic validity is
    checked again against the active contract by ``native_decision_context``.
    """
    invocation = _guardian_invocation(command)
    if (
        invocation is None
        or invocation["action"] != "native-decision"
        or invocation["chained"]
        or not invocation["runtime_sha256"]
    ):
        return None
    tokens = invocation["tokens"]
    index = int(invocation["action_index"]) + 1
    if index >= len(tokens):
        return None
    kind = tokens[index].strip().lower()
    index += 1
    options: dict[str, str] = {}
    allowed = {
        "--decision",
        "--target",
        "--contract",
        "--provider",
        "--session-id",
    }
    while index < len(tokens):
        option = tokens[index]
        if option not in allowed or option in options or index + 1 >= len(tokens):
            return None
        options[option] = tokens[index + 1]
        index += 2
    decision = options.get("--decision", "").strip().lower()
    provider = options.get("--provider", "").strip().lower()
    session_id = options.get("--session-id", "").strip()
    contract = options.get("--contract", "").strip()
    target = options.get("--target", "current").strip() or "current"
    if (
        kind not in NATIVE_DECISIONS
        or decision not in NATIVE_DECISIONS[kind]
        or provider != "codex"
        or not session_id
        or not contract
    ):
        return None
    return {
        "kind": kind,
        "decision": decision,
        "target": target,
        "contract": contract,
        "provider": provider,
        "session_id": session_id,
        "runtime_sha256": str(invocation["runtime_sha256"]),
    }

def _guardian_control_command(command: str) -> dict[str, Any] | None:
    invocation = _guardian_invocation(command)
    if invocation is None:
        return None
    action = str(invocation["action"])
    if action not in (
        AGENT_CONTROL_ACTIONS
        | HUMAN_CONTROL_ACTIONS
        | NATIVE_PERMISSION_CONTROL_ACTIONS
    ):
        return None
    if not invocation["runtime_sha256"]:
        return None
    if invocation["chained"]:
        segments = _read_pipeline_segments(command)
        if (
            action in READ_ONLY_AGENT_CONTROL_ACTIONS
            and segments
            and all(_is_read_only_command(segment) for segment in segments[1:])
        ):
            return {
                **invocation,
                "route": "agent",
                "read_only_composition": True,
            }
        # The launcher identity is proven, but Guardian controls are one exact
        # invocation and never a shell-composition primitive.  Preserve that
        # control-plane identity so the whole process is denied without
        # misreporting an unexecuted composition as a destructive effect.
        return {
            **invocation,
            "route": "invalid-composition",
        }
    if (
        action in NATIVE_PERMISSION_CONTROL_ACTIONS
        and parse_native_decision_command(command) is None
    ):
        return {
            **invocation,
            "route": "native-permission-invalid",
        }
    return {
        **invocation,
        "route": (
            "agent"
            if action in AGENT_CONTROL_ACTIONS
            else "native-permission"
            if action in NATIVE_PERMISSION_CONTROL_ACTIONS
            else "human"
        ),
    }

def _shell_syntax_check_target(command: str) -> str:
    """Return the one script parsed by an exact shell no-exec invocation."""
    if _has_unquoted_shell_control(command):
        return ""
    try:
        tokens = split_command_template(command)
    except ValueError:
        return ""
    if (
        len(tokens) == 3
        and Path(tokens[0]).name.lower() in {"bash", "sh", "zsh"}
        and tokens[1] == "-n"
        and tokens[2]
        and not tokens[2].startswith("-")
    ):
        return tokens[2]
    return ""

def _direct_host_callback_command(command: str) -> dict[str, Any] | None:
    """Reject attempts to manufacture a host Hook callback from a tool call.

    Real Hooks invoke these entrypoints outside the model's tool lifecycle.
    Letting an Agent run the same files through Bash would make a synthetic
    PermissionRequest indistinguishable from Codex's native callback.
    """
    invocation = _guardian_invocation(command)
    if invocation is not None and invocation.get("action") == "codex-hook":
        return {
            **invocation,
            "route": "host-callback-invalid",
        }
    wrapped = _shell_wrapper_payload(command)
    if wrapped is not None:
        callback = _direct_host_callback_command(wrapped)
        if callback is not None:
            return {
                **callback,
                "tokens": [command],
                "launcher": command,
                "chained": False,
            }
        # An exact shell wrapper delegates classification exclusively to its
        # literal payload.  Scanning the outer argv would mistake a read-only
        # payload ending in ``run-hook.sh`` for direct callback execution.
        return None
    try:
        tokens = split_command_template(command)
    except ValueError:
        return None
    if not tokens or _has_unquoted_shell_control(command):
        return None
    names = [Path(token).name.lower() for token in tokens]
    first = names[0]
    if _shell_syntax_check_target(command) and names[2] == "run-hook.sh":
        # ``-n`` parses without executing the script.  It is a read of the
        # Hook source, not a manufactured host lifecycle callback.
        return None
    callback = False
    if first in {"run-hook.sh", "run-hook.ps1"}:
        callback = True
    elif first in {"bash", "sh", "zsh", "powershell", "powershell.exe", "pwsh"}:
        callback = any(name in {"run-hook.sh", "run-hook.ps1"} for name in names[1:4])
    elif re.fullmatch(r"python(?:\d+(?:\.\d+)*)?(?:\.exe)?", first):
        callback = len(names) > 1 and names[1] in {
            "pre_tool_use.py",
            "pre-tool-use.py",
        }
    elif first in {"pre_tool_use.py", "pre-tool-use.py"}:
        callback = True
    if not callback:
        return None
    return {
        "tokens": tokens,
        "launcher_index": 0,
        "action_index": 0,
        "action": "host-hook-callback",
        "launcher": tokens[0],
        "runtime_sha256": "",
        "chained": False,
        "route": "host-callback-invalid",
    }

def _trusted_script_command(
    command: str,
    *,
    cwd: str | Path | None = None,
) -> dict[str, Any] | None:
    """Resolve a digest-pinned local script declaration or fail closed."""
    try:
        tokens = split_command_template(command)
    except ValueError:
        return None
    if not tokens:
        return None
    working_directory = Path(cwd or os.getcwd()).expanduser()
    if _has_unquoted_shell_control(command):
        identity = identify_trusted_script_command(
            tokens,
            kb_home=kb_home(),
            cwd=working_directory,
        )
        return {**identity, "effect": "unknown", "invalid_composition": True} if identity is not None else None
    identity = identify_trusted_script_command(
        tokens, kb_home=kb_home(), cwd=working_directory,
    )
    if (
        identity is not None
        and identity.get("profile_id") == "sulde-agent-runtime-git-lifecycle-v1"
        and _runtime_read_only_diagnostic_argv(tokens[2:])
    ):
        return {**identity, "effect": "read"}
    return classify_trusted_script_command(
        tokens,
        kb_home=kb_home(),
        cwd=working_directory,
    )


def _declared_trusted_script_denial(
    command: str,
    *,
    cwd: str | Path | None = None,
) -> dict[str, Any] | None:
    """Return denial-only metadata for a declared path that fails trust checks."""
    if _has_unquoted_shell_control(command):
        return None
    try:
        tokens = split_command_template(command)
    except ValueError:
        return None
    if len(tokens) < 2 or _trusted_script_command(command, cwd=cwd) is not None:
        return None
    raw_script = Path(tokens[1]).expanduser()
    if not raw_script.is_absolute():
        return None
    try:
        script = raw_script.resolve(strict=True)
        codex_home = default_codex_home().resolve(strict=True)
    except OSError:
        return None
    matched = next(
        (
            profile
            for profile in SCRIPT_EFFECT_PROFILES
            if profile.root_kind == "codex-home"
            and script == (codex_home / profile.script_relative).resolve()
        ),
        None,
    )
    if matched is None:
        return None
    # This does not recover the declared effect or authorize execution.  The
    # failed integrity check still denies the command; it only records that a
    # successful pre-execution denial is terminal and must not pause the lane.
    return {
        "bounded_pre_execution_denial": True,
        "effect": "destructive",
        "kind": "declared-script-integrity",
        "profile_id": matched.profile_id,
        "reason": (
            "声明的可信脚本未通过解释器、摘要或参数完整性校验；"
            "已在执行前拒绝，本次拒绝不暂停当前任务"
        ),
        "target": "[declared-script-integrity]",
        "write_targets": [],
    }


def _runtime_read_only_diagnostic_argv(argv: list[str]) -> bool:
    """Only installed runtime help/verify diagnostics; never the run action."""
    if argv in (["--help"], ["-h"], ["verify", "--help"], ["verify", "-h"]):
        return True
    if (
        len(argv) < 3 or argv[0] != "verify"
        or not Path(argv[1]).is_absolute()
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", argv[2])
    ):
        return False
    options = argv[3:]
    seen: set[str] = set()
    for index in range(0, len(options), 2):
        option = options[index]
        if (
            option not in {"--allowed-paths", "--brief-sha256",
                           "--task-definition-sha256", "--task-id"}
            or option in seen or index + 1 >= len(options)
            or not options[index + 1] or options[index + 1].startswith("-")
        ):
            return False
        if option.endswith("sha256") and not re.fullmatch(
            r"[0-9a-f]{64}", options[index + 1]
        ):
            return False
        seen.add(option)
    return True


def _composition_has_destructive_segment(
    command: str, *, cwd: str | Path | None = None,
) -> bool:
    """Prove executed primitives; this parser never grants read authority."""
    # Here-document bodies belong to the receiving interpreter, not the shell.
    if _split_single_heredoc(command) is not None:
        return False
    return any(
        _literal_destructive_command(segment)
        or (
            segment.strip() != command.strip()
            and not _has_unquoted_shell_control(segment)
            and _command_effect(segment, cwd=cwd) == "destructive"
        )
        for segment in _shell_execution_segments(command)
    )


def _literal_destructive_command(command: str) -> bool:
    try:
        tokens = split_command_template(command, comments=True)
    except ValueError:
        return False
    while tokens and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", tokens[0], re.S):
        tokens.pop(0)
    while tokens and Path(tokens[0]).name in {"env", "command", "exec", "sudo"}:
        tokens.pop(0)
        while tokens and (tokens[0] == "--" or re.fullmatch(
            r"[A-Za-z_][A-Za-z0-9_]*=.*", tokens[0], re.S
        )):
            tokens.pop(0)
    if not tokens:
        return False
    executable = Path(tokens[0]).name.lower()
    return executable == "rm" or (
        executable == "drop" and len(tokens) > 1
        and tokens[1].lower() in {"table", "database"}
    )


def _shell_execution_segments(command: str) -> list[str]:
    """Extract negative evidence, never read authority, from shell boundaries.

    Preserve quoted argv and embedded newlines. Inspect substitutions even in
    double quotes; single quotes and comments are inert. Redirection operands
    stay with their command. Incomplete syntax proves no executable.
    """
    def scan(index: int, end: str = "", depth: int = 0):
        if depth > 32:
            return [], len(command), False
        segments: list[str] = []
        current: list[str] = []
        quote = ""

        def flush():
            segment = "".join(current).strip()
            if segment:
                segments.append(segment)
            current.clear()

        while index < len(command):
            char = command[index]
            if char == "\\" and quote != "'":
                current.append(command[index:index + 2])
                index += 2
                continue
            if quote == "'":
                current.append(char)
                if char == quote:
                    quote = ""
                index += 1
                continue
            if not quote and end and char == end:
                flush()
                return segments, index + 1, True
            substitution = command.startswith("$(", index) or (
                not quote and command[index:index + 2] in {"<(", ">("}
            )
            if substitution or char == "`":
                width, closing = (2, ")") if substitution else (1, "`")
                nested, index, complete = scan(index + width, closing, depth + 1)
                if not complete:
                    return [], index, False
                segments.extend(nested)
                current.append("SUBSTITUTION")
                continue
            if char in {"'", '"'} and (not quote or char == quote):
                quote = "" if quote else char
                current.append(char)
                index += 1
                continue
            if not quote:
                if char == "#" and (not current or current[-1][-1:].isspace()):
                    while index < len(command) and command[index] not in "\n\r":
                        index += 1
                    continue
                if char == "(":
                    flush()
                    nested, index, complete = scan(index + 1, ")", depth + 1)
                    if not complete:
                        return [], index, False
                    segments.extend(nested)
                    continue
                if char in ";&|\n\r":
                    if char == "&" and current and current[-1] in {"<", ">"}:
                        current.append(char)
                    else:
                        flush()
                    index += 1
                    continue
            current.append(char)
            index += 1
        if quote or end:
            return [], index, False
        flush()
        return segments, index, True

    segments, _index, complete = scan(0)
    return segments if complete else []

def _codex_plugin_cachebuster_candidate(
    command: str,
    *,
    cwd: str | Path | None = None,
) -> dict[str, Any] | None:
    """Recognize the official helper with one exact, proposal-bound token."""
    if _has_unquoted_shell_control(command):
        return None
    try:
        tokens = split_command_template(command)
    except ValueError:
        return None
    if len(tokens) != 5 or tokens[3] != "--cachebuster":
        return None
    working_directory = Path(cwd or os.getcwd()).expanduser().resolve()
    interpreter = _resolved_executable(tokens[0], cwd=working_directory)
    if interpreter is None or not re.fullmatch(
        r"python(?:\d+(?:\.\d+)*)?(?:\.exe)?",
        interpreter.name.lower(),
    ):
        return None
    helper_value = Path(tokens[1]).expanduser()
    helper = (
        helper_value if helper_value.is_absolute() else working_directory / helper_value
    ).resolve()
    plugin_value = Path(tokens[2]).expanduser()
    plugin_root = (
        plugin_value if plugin_value.is_absolute() else working_directory / plugin_value
    ).resolve()
    if plugin_root.name != "sulde" or len(plugin_root.parents) < 4:
        return None
    workspace = plugin_root.parents[3]
    if plugin_root != (workspace / "integrations/codex/plugins/sulde").resolve():
        return None
    try:
        binding, _ = _codex_plugin_cachebuster_binding(
            workspace,
            cachebuster=tokens[4],
            interpreter=interpreter,
            helper=helper,
        )
    except IntentGuardianError:
        return None
    profile_id = "codex-plugin-cachebuster-v1"
    expected_digest = _verification_digest(
        {
            "profile_id": profile_id,
            "target": CONTINUATION_PROFILES[profile_id]["target"],
            "binding": binding,
        }
    )
    return {
        "profile_id": profile_id,
        "effect": "local_write",
        "capability": "tool:Bash",
        "target": CONTINUATION_PROFILES[profile_id]["target"],
        "verification_kind": "content",
        "verification_sha256": expected_digest,
        "binding": binding,
    }


def _codex_plugin_install_candidate(
    command: str,
    *,
    cwd: str | Path | None = None,
) -> dict[str, Any] | None:
    """Recognize one exact, digest-bound transactional Codex installation."""
    if _has_unquoted_shell_control(command):
        return None
    try:
        tokens = split_command_template(command)
    except ValueError:
        return None
    if len(tokens) < 3:
        return None
    working_directory = Path(cwd or os.getcwd()).expanduser().resolve()
    interpreter = _resolved_executable(tokens[0], cwd=working_directory)
    if interpreter is None or not re.fullmatch(
        r"python(?:\d+(?:\.\d+)*)?(?:\.exe)?",
        interpreter.name.lower(),
    ):
        return None
    script_value = Path(tokens[1]).expanduser()
    script = (
        script_value if script_value.is_absolute() else working_directory / script_value
    ).resolve()
    if script.name != "install_codex_plugin.py" or not script.is_file():
        return None
    workspace = script.parents[2]
    if script != workspace / "scripts" / "release" / "install_codex_plugin.py":
        return None

    options: dict[str, str] = {}
    json_output = False
    index = 2
    valued = {"--artifact-root", "--kb-home", "--codex", "--platform"}
    while index < len(tokens):
        option = tokens[index]
        if option == "--json":
            if json_output:
                return None
            json_output = True
            index += 1
            continue
        if option not in valued or option in options or index + 1 >= len(tokens):
            return None
        options[option] = tokens[index + 1]
        index += 2
    if not json_output:
        return None

    try:
        binding = _codex_plugin_install_binding(workspace, interpreter=interpreter)
    except IntentGuardianError:
        return None
    path_options = {
        "--artifact-root": "artifact_root",
        "--kb-home": "kb_home",
    }
    for option, binding_key in path_options.items():
        supplied = options.get(option)
        if supplied is None:
            continue
        supplied_path = Path(supplied).expanduser()
        supplied_path = (
            supplied_path
            if supplied_path.is_absolute()
            else working_directory / supplied_path
        )
        if supplied_path.resolve() != Path(binding[binding_key]).resolve():
            return None
    supplied_codex = options.get("--codex")
    if supplied_codex is not None:
        codex_executable = _resolved_executable(supplied_codex, cwd=working_directory)
        if codex_executable is None or codex_executable != Path(binding["codex_path"]):
            return None
    if options.get("--platform", binding["platform"]) != binding["platform"]:
        return None

    expected_digest = _verification_digest(
        {
            "profile_id": "codex-plugin-install-v1",
            "target": CONTINUATION_PROFILES["codex-plugin-install-v1"]["target"],
            "binding": binding,
        }
    )
    return {
        "profile_id": "codex-plugin-install-v1",
        "effect": "external_write",
        "capability": "tool:Bash",
        "target": CONTINUATION_PROFILES["codex-plugin-install-v1"]["target"],
        "verification_kind": "content",
        "verification_sha256": expected_digest,
        "binding": binding,
    }


def _strongest_effect(effects: Iterable[str]) -> str:
    selected = set(effects)
    for effect in ("destructive", "external_write", "local_write", "unknown", "read"):
        if effect in selected:
            return effect
    return "read"


def _literal_process_command(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, (ast.List, ast.Tuple)):
        values: list[str] = []
        for element in node.elts:
            if not isinstance(element, ast.Constant) or not isinstance(
                element.value, (str, int, float)
            ):
                return None
            values.append(str(element.value))
        return " ".join(shlex.quote(value) for value in values)
    return None


def _python_source_effect(source: str, *, cwd: str | Path | None, risks: list[str] | None = None, literal_transport: bool = True) -> str:
    """Classify Python only when every executable call is statically proved.

    String literals and container construction are data.  An imported module or
    function call that is not on the small proof surface remains ``unknown``;
    absence from the write-call list is never evidence that arbitrary Python is
    read-only.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return "unknown"
    data_calls = proven_data_method_calls(tree) if literal_transport else set()
    effects: list[str] = []
    process_calls = {
        "os.system",
        "os.popen",
        "subprocess.call",
        "subprocess.check_call",
        "subprocess.check_output",
        "subprocess.getoutput",
        "subprocess.getstatusoutput",
        "subprocess.Popen",
        "subprocess.run",
    }
    destructive_calls = {
        "os.remove",
        "os.rename",
        "os.replace",
        "os.removedirs",
        "shutil.move",
        "shutil.rmtree",
        "pathlib.Path.rename",
        "pathlib.Path.replace",
        "pathlib.Path.rmdir",
        "pathlib.Path.unlink",
    }
    local_write_calls = {
        "os.chmod",
        "os.chown",
        "os.lchmod",
        "os.link",
        "os.mkdir",
        "os.makedirs",
        "os.removexattr",
        "os.setxattr",
        "os.symlink",
        "os.truncate",
        "os.utime",
        "pathlib.Path.chmod",
        "pathlib.Path.hardlink_to",
        "pathlib.Path.mkdir",
        "pathlib.Path.symlink_to",
        "pathlib.Path.touch",
        "pathlib.Path.write_bytes",
        "pathlib.Path.write_text",
        "shutil.copy",
        "shutil.copy2",
        "shutil.copyfile",
        "shutil.copytree",
    }
    safe_import_roots = {
        "ast",
        "collections",
        "datetime",
        "functools",
        "hashlib",
        "itertools",
        "json",
        "math",
        "operator",
        "os",
        "pathlib",
        "re",
        "shlex",
        "shutil",
        "stat",
        "subprocess",
        "sys",
        "textwrap",
        "typing",
    }
    safe_calls = {
        "all",
        "any",
        "bool",
        "bytes",
        "bytearray",
        "dict",
        "enumerate",
        "filter",
        "float",
        "format",
        "frozenset",
        "hash",
        "int",
        "iter",
        "json.dumps",
        "json.loads",
        "len",
        "list",
        "map",
        "max",
        "min",
        "next",
        "pathlib.Path",
        "print",
        "range",
        "repr",
        "reversed",
        "round",
        "set",
        "sorted",
        "str",
        "sum",
        "tuple",
        "type",
        "zip",
    }

    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for imported in node.names:
                root = imported.name.split(".", 1)[0]
                aliases[imported.asname or root] = imported.name
                if root not in safe_import_roots:
                    effects.append("unknown")
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module.split(".", 1)[0] not in safe_import_roots:
                effects.append("unknown")
            for imported in node.names:
                if imported.name != "*":
                    aliases[imported.asname or imported.name] = (
                        f"{node.module}.{imported.name}"
                    )

    path_calls = proven_path_method_calls(tree, aliases)

    def call_name(node: ast.Call) -> str:
        parts: list[str] = []
        current: ast.AST = node.func
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if isinstance(current, ast.Name):
            parts.append(current.id)
        name = ".".join(reversed(parts))
        if not name:
            return name
        head, separator, tail = name.partition(".")
        resolved = aliases.get(head, head)
        return f"{resolved}{separator}{tail}" if separator else resolved

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = call_name(node)
        if id(node) in data_calls:
            # The receiver and arguments are proved builtin data. Calls inside
            # arguments are still visited independently; this never hides exec,
            # subprocess or filesystem effects behind a string method name.
            effects.append("read")
        elif name in process_calls:
            if not node.args:
                effects.append("unknown")
                continue
            nested = _literal_process_command(node.args[0])
            effects.append(
                _command_effect(nested, cwd=cwd, risks=risks) if nested is not None else "unknown"
            )
        elif name in {"exec", "eval"}:
            if not node.args or not isinstance(node.args[0], ast.Constant) or not isinstance(
                node.args[0].value, str
            ):
                effects.append("unknown")
            else:
                effects.append(_python_source_effect(node.args[0].value, cwd=cwd, risks=risks))
        elif name in {"open", "io.open"}:
            mode = "r"
            mode_proved = len(node.args) <= 1
            if len(node.args) > 1:
                if isinstance(node.args[1], ast.Constant) and isinstance(
                    node.args[1].value, str
                ):
                    mode = node.args[1].value
                    mode_proved = True
                else:
                    mode_proved = False
            for keyword in node.keywords:
                if keyword.arg != "mode":
                    continue
                if isinstance(keyword.value, ast.Constant) and isinstance(
                    keyword.value.value, str
                ):
                    mode = keyword.value.value
                    mode_proved = True
                else:
                    mode_proved = False
            if not mode_proved:
                effects.append("unknown")
            elif any(flag in mode for flag in "wax+"):
                effects.append("local_write")
            else:
                effects.append("read")
        elif name in destructive_calls:
            effects.append("destructive")
        elif name.rsplit(".", 1)[-1] in {
            "remove",
            "rename",
            "replace",
            "rmdir",
            "unlink",
        }:
            if id(node) in path_calls:
                effects.append("destructive")
            else:
                effects.append("unknown")
                if risks is not None:
                    risks.append("unresolved-destructive-receiver")
        elif name in local_write_calls or name.rsplit(".", 1)[-1] in {
            "chmod",
            "chown",
            "copy",
            "copy2",
            "copyfile",
            "copytree",
            "hardlink_to",
            "mkdir",
            "setxattr",
            "symlink_to",
            "touch",
            "truncate",
            "utime",
            "write_bytes",
            "write_text",
        }:
            effects.append("local_write")
        elif name in safe_calls:
            effects.append("read")
        else:
            effects.append("unknown")
    return _strongest_effect(effects or ["read"])


def _javascript_string(value: str) -> str | None:
    value = value.strip()
    if len(value) < 2 or value[0] != value[-1] or value[0] not in {"'", '"', "`"}:
        return None
    if value[0] == "`" and "${" in value:
        return None
    body = value[1:-1]
    try:
        return bytes(body, "utf-8").decode("unicode_escape")
    except UnicodeError:
        return None


def _node_source_effect(source: str, *, cwd: str | Path | None, risks: list[str] | None = None) -> str:
    """Classify literal child-process calls while leaving JS strings as data."""
    effects: list[str] = []
    child_call = re.compile(
        r"(?:\bexec|\bexecSync|\bexecFile|\bexecFileSync)\s*\(\s*"
        r"(?P<command>`(?:[^`\\]|\\.)*`|'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\")",
        re.DOTALL,
    )
    for match in child_call.finditer(source):
        nested = _javascript_string(match.group("command"))
        effects.append(
            _command_effect(nested, cwd=cwd, risks=risks) if nested is not None else "unknown"
        )
    spawn_call = re.compile(
        r"\bspawn(?:Sync)?\s*\(\s*(?P<exe>'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\")"
        r"\s*,\s*\[(?P<args>[^\]]*)\]",
        re.DOTALL,
    )
    for match in spawn_call.finditer(source):
        executable = _javascript_string(match.group("exe"))
        arguments = re.findall(
            r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"",
            match.group("args"),
        )
        decoded = [_javascript_string(argument) for argument in arguments]
        if executable is None or any(argument is None for argument in decoded):
            effects.append("unknown")
        else:
            nested = " ".join(
                shlex.quote(value) for value in [executable, *decoded] if value is not None
            )
            effects.append(_command_effect(nested, cwd=cwd, risks=risks))
    if re.search(r"\b(?:exec|execSync|execFile|execFileSync|spawn|spawnSync)\s*\(", source) and not effects:
        effects.append("unknown")
    if re.search(r"\b(?:writeFile|writeFileSync|appendFile|appendFileSync|mkdir|mkdirSync|rename|renameSync)\s*\(", source):
        effects.append("local_write")
    if re.search(r"\b(?:rm|rmSync|rmdir|rmdirSync|unlink|unlinkSync)\s*\(", source):
        effects.append("destructive")
    code_only = re.sub(
        r"//[^\n]*|/\*[\s\S]*?\*/|`(?:[^`\\]|\\.)*`|'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"",
        " ",
        source,
    )
    safe_calls = {
        "Array",
        "Boolean",
        "JSON.parse",
        "JSON.stringify",
        "Number",
        "Object",
        "String",
        "console.error",
        "console.log",
        "console.warn",
        "require",
    }
    known_effect_calls = {
        "appendFile",
        "appendFileSync",
        "exec",
        "execFile",
        "execFileSync",
        "execSync",
        "mkdir",
        "mkdirSync",
        "rename",
        "renameSync",
        "rm",
        "rmSync",
        "rmdir",
        "rmdirSync",
        "spawn",
        "spawnSync",
        "unlink",
        "unlinkSync",
        "writeFile",
        "writeFileSync",
    }
    calls = re.findall(
        r"(?<![\w$])([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*)\s*\(",
        code_only,
    )
    if any(
        name not in safe_calls and name.rsplit(".", 1)[-1] not in known_effect_calls
        for name in calls
    ):
        effects.append("unknown")
    return _strongest_effect(effects or ["read"])


def _structured_command_effect(
    command: str,
    *,
    cwd: str | Path | None,
    risks: list[str] | None = None,
) -> str | None:
    wrapped = _shell_wrapper_payload(command)
    if wrapped is not None:
        return _command_effect(wrapped, cwd=cwd, risks=risks)

    heredoc = _split_single_heredoc(command)
    if heredoc is not None:
        header, body = heredoc
        if re.search(r"(?:^|\s)(?:>>?|[0-9]+>>?)\s*[^&\s]", header):
            header_effect = "local_write"
        else:
            header_effect = "read"
        try:
            tokens = split_command_template(header)
        except ValueError:
            return "unknown"
        if not tokens:
            return "unknown"
        executable = Path(tokens[0]).name.lower()
        if re.fullmatch(r"python(?:\d+(?:\.\d+)*)?(?:\.exe)?", executable):
            body_effect = _python_source_effect(body, cwd=cwd, risks=risks)
        elif executable in {"node", "node.exe"}:
            body_effect = _node_source_effect(body, cwd=cwd, risks=risks)
        elif executable in {"bash", "dash", "ksh", "sh", "zsh"}:
            body_effect = _command_effect(body, cwd=cwd, risks=risks)
        else:
            body_effect = _command_effect(header, cwd=cwd, risks=risks)
        return _strongest_effect((header_effect, body_effect))

    try:
        tokens = split_command_template(command)
    except ValueError:
        return None
    if not tokens:
        return None
    executable = Path(tokens[0]).name.lower()
    if re.fullmatch(r"python(?:\d+(?:\.\d+)*)?(?:\.exe)?", executable):
        source = inline_source(tokens)
        if source is not None and not _has_unquoted_shell_control(command):
            return _python_source_effect(source, cwd=cwd, risks=risks,
                                         literal_transport=literal_shell_transport(command))
    elif executable in {"node", "node.exe"}:
        if "\n" not in command and "\r" not in command and len(tokens) >= 3 and tokens[1] in {"-e", "--eval"}:
            return _node_source_effect(tokens[2], cwd=cwd, risks=risks)
    return None

def _command_effect(command: str, *, cwd: str | Path | None = None, risks: list[str] | None = None) -> str:
    lowered = command.lower()
    if _composition_has_destructive_segment(command, cwd=cwd):
        return "destructive"
    guardian = _guardian_invocation(command)
    if guardian:
        action = str(guardian["action"])
        if not guardian["runtime_sha256"]:
            return "destructive"
        if guardian["chained"]:
            # A trusted read-only Guardian query may be composed with output
            # filters. Classify each remaining segment instead of turning the
            # mere presence of a pipe into a safety pause. Mutating/native
            # controls retain the hard no-composition boundary, while an
            # unprovable formatter degrades to ``unknown``.
            segments = _read_pipeline_segments(command)
            if not segments or action not in READ_ONLY_AGENT_CONTROL_ACTIONS:
                return (
                    "destructive"
                    if _composition_has_destructive_segment(command, cwd=cwd)
                    else "unknown"
                )
            trailing_effects = [
                _command_effect(segment, cwd=cwd, risks=risks) for segment in segments[1:]
            ]
            for effect in ("destructive", "external_write", "local_write", "unknown"):
                if effect in trailing_effects:
                    return effect
            return "read"
        if action in AGENT_CONTROL_ACTIONS | NATIVE_PERMISSION_CONTROL_ACTIONS:
            return "read"
        if action in {"skill-start", "skill-end"}:
            return "local_write" if _guardian_skill_command(command, provider="codex") else "unknown"
        if action in HUMAN_CONTROL_ACTIONS:
            return "destructive"
        return "unknown"
    if _shell_syntax_check_target(command):
        return "read"
    if _git_execution_passthrough(command):
        return "unknown"
    if _codex_plugin_read_only_maintenance_command(command, cwd=cwd):
        return "read"
    structured_effect = _structured_command_effect(command, cwd=cwd, risks=risks)
    if structured_effect is not None:
        return structured_effect
    trusted_script = _trusted_script_command(command, cwd=cwd)
    if trusted_script is not None:
        # Syntax invalidity denies execution but is not destructive evidence.
        if trusted_script.get("invalid_composition"):
            return (
                "destructive"
                if _composition_has_destructive_segment(command, cwd=cwd)
                else "unknown"
            )
        return trusted_script["effect"]
    try:
        command_tokens = split_command_template(command)
    except ValueError:
        command_tokens = []
    if (
        len(command_tokens) >= 2
        and re.fullmatch(
            r"python(?:\d+(?:\.\d+)*)?(?:\.exe)?",
            Path(command_tokens[0]).name.lower(),
        )
        and Path(command_tokens[1]).name
        in {
            "validate_plugin.py",
            "update_plugin_cachebuster.py",
            "install_codex_plugin.py",
        }
    ):
        # These maintenance names cross the Guardian/plugin bootstrap trust
        # boundary.  Only the digest-bound declared path/argv above may run.
        return "destructive"
    execution_domains = _execution_domain_commands(command)
    if execution_domains and len(execution_domains) > 1:
        non_git_effects = [
            _command_effect(segment, cwd=cwd, risks=risks)
            for domain, segment in execution_domains
            if domain != "git"
        ]
        # Git segments are outside Guardian's policy domain. Other segments
        # retain normal policy so composition cannot launder a mutation.
        return _strongest_effect(non_git_effects) if non_git_effects else "unknown"
    # Classify the executable shape before scanning argument text.  A quoted
    # search pattern such as `rg "git push"` is data, not an external effect.
    if _is_read_only_command(command):
        return "read"
    if re.search(r"\b(gh\s+(?:pr|issue|release)\s+(?:create|merge|comment)|curl\b.*\s-X\s*(?:POST|PUT|PATCH|DELETE)|scp\b|rsync\b.*:|npm\s+publish|deploy)\b", lowered, re.IGNORECASE):
        return "external_write"
    local_write_patterns = (
        r"(?:^|[;&|]\s*)(?:mv\b|cp\b|touch\b|mkdir\b|sed\s+-i\b)",
        r"(?:^|[;&|]\s*)(?:tee\b|(?:python\d*|node|ruby|perl)\b.*(?:write|open\s*\(|write_text|write_bytes))",
        r"(?:^|[;&|]\s*)(?:echo|printf)\b[^;&|]*(?:>>?|\|\s*tee\b)",
        r"(?:^|[;&|]\s*)(?:npm|pnpm|yarn)\s+(?:install|add|remove|update)\b",
        r"(?:^|[;&|]\s*)(?:cargo\s+(?:fmt|fix)|go\s+fmt|dart\s+format|swiftformat|prettier|ruff\s+format)\b",
    )
    if any(re.search(pattern, lowered) for pattern in local_write_patterns):
        return "local_write"
    return "unknown"

def _extract_patch_text(value: Any, *, depth: int = 0) -> str:
    """Find one apply_patch envelope without depending on host payload shape."""
    if depth > 6:
        return ""
    if isinstance(value, str):
        return value if "*** Begin Patch" in value else ""
    if isinstance(value, dict):
        for key in ("patch", "input", "value", "arguments", "payload"):
            if key in value:
                found = _extract_patch_text(value[key], depth=depth + 1)
                if found:
                    return found
        for nested in value.values():
            found = _extract_patch_text(nested, depth=depth + 1)
            if found:
                return found
    elif isinstance(value, (list, tuple)):
        for nested in value[:50]:
            found = _extract_patch_text(nested, depth=depth + 1)
            if found:
                return found
    return ""

def _response_strings(value: Any, *, depth: int = 0) -> list[str]:
    if depth > 5:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        found: list[str] = []
        for nested in list(value.values())[:100]:
            found.extend(_response_strings(nested, depth=depth + 1))
        return found[:200]
    if isinstance(value, list):
        found = []
        for nested in value[:100]:
            found.extend(_response_strings(nested, depth=depth + 1))
        return found[:200]
    return []

def _codex_plugin_cachebuster_verification(
    candidate: dict[str, Any],
    *,
    expected_digest: str,
) -> dict[str, Any] | None:
    """Independently prove the helper produced the one sealed manifest/tree."""
    binding = candidate.get("binding")
    if not isinstance(binding, dict) or expected_digest != candidate.get("verification_sha256"):
        return None
    try:
        binder = (
            _codex_plugin_cachebuster_v2_binding
            if candidate.get("profile_id") == "codex-plugin-cachebuster-v2"
            else _codex_plugin_cachebuster_binding
        )
        current_binding, _ = binder(
            Path(binding["workspace_root"]),
            cachebuster=str(binding["cachebuster"]),
            interpreter=Path(binding["interpreter_path"]),
            helper=Path(binding["helper_path"]),
        )
        manifest = Path(binding["manifest_path"]).expanduser().resolve()
        workspace = Path(binding["workspace_root"]).expanduser().resolve()
    except (IntentGuardianError, KeyError, OSError):
        return None
    if current_binding != binding:
        return None
    try:
        manifest_sha256 = _sha256_path(manifest)
        current_tree = _workspace_tracked_tree_sha256(workspace)
        current_version = _json_version(manifest, "Codex plugin manifest")
    except (IntentGuardianError, OSError):
        return None
    if (
        manifest_sha256 != binding["manifest_sha256"]
        or current_tree != binding["tracked_tree_sha256"]
        or current_version != binding["plugin_version"]
    ):
        return None
    return {
        "capability": "tool:codex_plugin_cachebuster_verify",
        "evidence": {"content": [expected_digest]},
        "source": "local_codex_cachebuster_read",
    }

def _codex_plugin_install_verification(
    candidate: dict[str, Any],
    response: Any = None,
    *,
    expected_digest: str,
) -> dict[str, Any] | None:
    """Independently prove the exact installed artifact and local launchers.

    ``response`` is retained for call-site compatibility but is deliberately
    not trusted.  Codex may omit command stdout from PostToolUse, and installer
    self-report is not external-effect evidence.  Every fact below is read
    again from the sealed binding, local filesystem and Codex registry.
    """
    del response
    binding = candidate.get("binding")
    if not isinstance(binding, dict) or expected_digest != candidate.get("verification_sha256"):
        return None
    # Dispatch authorization already required the then-current command
    # candidate to equal this hash-addressed binding. Requiring the mutable
    # workspace to remain byte-identical during later reconciliation would
    # make every subsequent source edit erase proof of an already dispatched
    # operation. This verifier proves the sealed operation's postcondition.
    try:
        artifact = Path(binding["artifact_root"]).expanduser().resolve()
        codex_home = Path(binding["codex_home"]).expanduser().resolve()
        kb_root = Path(binding["kb_home"]).expanduser().resolve()
    except (KeyError, OSError, RuntimeError, ValueError):
        return None
    try:
        listing = subprocess.run(
            [binding["codex_path"], "plugin", "list"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    registered: Path | None = None
    if listing.returncode == 0:
        for line in listing.stdout.splitlines():
            columns = re.split(r"\s{2,}", line.strip(), maxsplit=3)
            if (
                len(columns) == 4
                and columns[0] == "sulde@sulde-local"
                and columns[1] == "installed, enabled"
            ):
                try:
                    registered = Path(columns[3]).expanduser().resolve()
                except (OSError, RuntimeError, ValueError):
                    return None
                break
    if registered is None:
        return None
    version = str(binding["plugin_version"])
    if Path(version).name != version or version in {".", ".."}:
        return None
    staged_plugin = (artifact / "plugins" / "sulde").resolve()
    runtime_cache = (
        codex_home / "plugins" / "cache" / "sulde-local" / "sulde" / version
    ).resolve()
    if registered not in {staged_plugin, runtime_cache}:
        return None
    # Codex may retain a stale VERSION display column after the marketplace
    # path has atomically switched.  The registered path, exact descriptor
    # version and both tree digests below are the authoritative proof; using
    # the display column would leave a completed installation in verifying.
    try:
        runtime_cache.relative_to(codex_home)
    except ValueError:
        return None
    staged_digest = _portable_tree_sha256(staged_plugin)
    if not re.fullmatch(r"[0-9a-f]{64}", staged_digest):
        return None
    if (
        _portable_tree_sha256(registered) != staged_digest
        or _portable_tree_sha256(runtime_cache) != staged_digest
    ):
        return None
    for plugin_root in {registered, runtime_cache}:
        try:
            descriptor = json.loads(
                (plugin_root / ".codex-plugin" / "plugin.json").read_text(
                    encoding="utf-8"
                )
            )
        except (OSError, UnicodeError, json.JSONDecodeError):
            return None
        if not isinstance(descriptor, dict) or descriptor.get("version") != version:
            return None
    launchers = verify_launcher_installation(
        kb_root,
        expected_source_root=runtime_cache / "runtime",
    )
    if not installed_launchers_match(launchers):
        return None
    agents_md = codex_home / "AGENTS.md"
    try:
        rules = agents_md.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None
    if "## Codex 派单档位纪律" not in rules or "$dispatch-task" not in rules:
        return None
    return {
        "capability": "tool:codex_plugin_install_verify",
        "evidence": {"content": [expected_digest]},
        "source": "local_codex_install_read",
    }


def _continuation_candidate_from_grant(grant: dict[str, Any]) -> dict[str, Any]:
    profile_id = str(grant["profile_id"])
    candidate = {
        "profile_id": profile_id,
        "effect": str(grant["effect"]),
        "capability": str(grant["capability"]),
        "target": str(grant["target"]),
        "verification_kind": str(grant["verification_kind"]),
        "binding": json.loads(json.dumps(grant["binding"])),
    }
    candidate["verification_sha256"] = _verification_digest(
        {
            "profile_id": profile_id,
            "target": candidate["target"],
            "binding": candidate["binding"],
        }
    )
    return candidate

def _registered_continuation_verification(
    grant: dict[str, Any],
) -> dict[str, Any] | None:
    candidate = _continuation_candidate_from_grant(grant)
    expected_digest = str(candidate["verification_sha256"])
    if grant["profile_id"] in {
        "codex-plugin-cachebuster-v1",
        "codex-plugin-cachebuster-v2",
    }:
        return _codex_plugin_cachebuster_verification(
            candidate,
            expected_digest=expected_digest,
        )
    if grant["profile_id"] in {
        "codex-plugin-install-v1",
        "codex-plugin-install-v2",
    }:
        return _codex_plugin_install_verification(
            candidate,
            expected_digest=expected_digest,
        )
    if grant["profile_id"] == "sulde-scheduler-reconcile-v1":
        return _scheduler_reconcile_verification(
            candidate,
            expected_digest=expected_digest,
        )
    if grant["profile_id"] == "sulde-launcher-refresh-v1":
        return _launcher_refresh_verification(
            candidate,
            expected_digest=expected_digest,
        )
    return None

def _pending_verification_grant(
    path: Path,
    contract: dict[str, Any],
    row: dict[str, Any],
    *,
    expected_digest: str = "",
) -> dict[str, Any] | None:
    """Recover the immutable grant that dispatched one pending effect.

    Intent revisions deliberately carry runtime debt forward, but the new
    policy may have no continuation grants of its own.  The verifier must not
    lose the proof recipe merely because intent wording changed.  New rows
    therefore carry an exact grant snapshot; legacy rows may recover the same
    hash-addressed grant from an immutable proposal file.
    """
    grant_id = str(row.get("continuation_grant_id") or "")
    row_digest = str(row.get("verification_sha256") or "")
    if row_digest and expected_digest and row_digest != expected_digest:
        return None
    expected_digest = row_digest or expected_digest
    candidates: dict[str, dict[str, Any]] = {}

    def consider(grant: Any) -> None:
        if not isinstance(grant, dict):
            return
        profile_id = str(grant.get("profile_id") or "")
        if profile_id not in AGENT_CONTINUATION_PROFILES:
            return
        try:
            actual_grant_id = _continuation_grant_id(grant)
            candidate = _continuation_candidate_from_grant(grant)
        except (IntentGuardianError, KeyError, TypeError, ValueError):
            return
        if str(grant.get("grant_id") or "") != actual_grant_id:
            return
        if grant_id and actual_grant_id != grant_id:
            return
        if expected_digest and candidate["verification_sha256"] != expected_digest:
            return
        serialized = json.dumps(grant, ensure_ascii=False, sort_keys=True)
        candidates[serialized] = json.loads(serialized)

    for grant in contract.get("continuation", {}).get("grants", []):
        consider(grant)
    consider(row.get("continuation_grant"))
    if candidates:
        return next(iter(candidates.values())) if len(candidates) == 1 else None

    stem = path.name[:-5] if path.name.endswith(".json") else path.name
    for proposal_path in path.parent.glob(f"{stem}.proposal.*.json"):
        try:
            proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
            if not isinstance(proposal, dict):
                continue
            stored_digest = str(proposal.get("proposal_digest") or "")
            link = proposal.get("proposal_for")
            if (
                not re.fullmatch(r"[0-9a-f]{64}", stored_digest)
                or not proposal_path.name.endswith(f".{stored_digest[:16]}.json")
                or not isinstance(link, dict)
                or Path(str(link.get("contract_path") or "")).expanduser().resolve()
                != path.expanduser().resolve()
            ):
                continue
        except (json.JSONDecodeError, OSError, UnicodeError, ValueError):
            continue
        for grant in proposal.get("continuation", {}).get("grants", []):
            consider(grant)
    return next(iter(candidates.values())) if len(candidates) == 1 else None

def _git_ref_read_evidence(
    observation: dict[str, Any],
    response: Any,
) -> list[str]:
    if observation.get("action") != "ls-remote":
        return []
    expected_ref = observation["ref"]
    digests: set[str] = set()
    for value in _response_strings(response):
        for line in value.splitlines():
            match = re.fullmatch(r"\s*([0-9a-fA-F]{40,64})\s+(\S+)\s*", line)
            if match and match.group(2) == expected_ref:
                digests.add(
                    git_ref_verification_digest(
                        remote=str(observation["remote"]),
                        ref=expected_ref,
                        oid=match.group(1).lower(),
                    )
                )
    return sorted(digest for digest in digests if digest)

def _git_ref_read_context(
    observation: dict[str, Any],
    response: Any,
) -> dict[str, str] | None:
    """Recover the exact remote/ref/OID tuple from one ls-remote response."""
    if observation.get("action") != "ls-remote":
        return None
    expected_ref = str(observation["ref"])
    matches: set[str] = set()
    for value in _response_strings(response):
        for line in value.splitlines():
            match = re.fullmatch(r"\s*([0-9a-fA-F]{40,64})\s+(\S+)\s*", line)
            if match and match.group(2) == expected_ref:
                matches.add(match.group(1).lower())
    if len(matches) != 1:
        return None
    return {
        "remote": str(observation["remote"]),
        "ref": expected_ref,
        "oid": next(iter(matches)),
    }

def _command_write_targets(
    command: str,
    *,
    cwd: str | Path | None = None,
) -> list[str]:
    """Extract conservative local write targets from common shell forms."""
    targets: list[str] = []

    def add(value: str) -> None:
        clean = value.strip().strip("'\"")
        if clean and clean not in {"-", "/dev/null"} and clean not in targets:
            targets.append(_safe_local_path(clean))

    trusted_script = _trusted_script_command(command, cwd=cwd)
    if trusted_script is not None and trusted_script.get("effect") == "local_write":
        declared_targets = trusted_script.get("targets")
        if isinstance(declared_targets, list) and declared_targets and all(
            isinstance(value, str) and value for value in declared_targets
        ):
            return [_safe_local_path(value) for value in declared_targets[:20]]
        target = trusted_script.get("target", "")
        return [_safe_local_path(target)] if target else []

    for match in re.finditer(
        r"(?<!\d)(?:>>?|\|\s*tee(?:\s+-a)?)\s*(?:\"([^\"]+)\"|'([^']+)'|([^\s;&|]+))",
        command,
    ):
        add(next((group for group in match.groups() if group), ""))
    # Paths in a literal Python -c argument belong to decoded Python, not the
    # shell's quote-escape transport (e.g. shlex.quote's '"'"' sequence).
    path_source = command
    try:
        python_tokens = split_command_template(command)
    except ValueError:
        python_tokens = []
    python_source = inline_source(python_tokens)
    if python_source is not None:
        path_source = python_source
    for match in re.finditer(
        r"(?:Path|open)\s*\(\s*(?:r|u|b|f|rf|fr)?(?:\"([^\"]+)\"|'([^']+)')",
        path_source,
    ):
        add(next((group for group in match.groups() if group), ""))

    segments = [command] if not _has_unquoted_shell_control(command) else re.split(r"(?:&&|\|\||;)", command)
    for segment in segments:
        try:
            tokens = split_command_template(segment)
        except ValueError:
            continue
        if not tokens:
            continue
        executable = Path(tokens[0]).name.lower()
        operands = [token for token in tokens[1:] if token and not token.startswith("-")]
        if executable in {"touch", "mkdir", "tee"}:
            for operand in operands:
                add(operand)
        elif executable in {"cp", "install"} and operands:
            add(operands[-1])
        elif executable == "mv" and operands:
            for operand in operands[-2:]:
                add(operand)
        elif executable in {"sed", "perl"} and any(token.startswith("-i") for token in tokens[1:]):
            for operand in operands:
                if not re.search(r"[=;]", operand):
                    add(operand)
    return targets[:20]

def _pause_safe_host_control_action(tool_name: str) -> str:
    compact = re.sub(r"[^a-z0-9]+", "", tool_name.lower())
    return compact if compact in PAUSE_SAFE_HOST_CONTROL_ACTIONS else ""

def _guardian_skill_command(
    command: str,
    *,
    provider: str,
) -> dict[str, str] | None:
    """Recognize one exact Codex Skill registration command.

    Registration is a stream signal, not authority.  Restricting the accepted
    shell shape prevents an arbitrary compound command from masquerading as a
    Skill boundary.
    """
    invocation = _guardian_invocation(command)
    if (
        invocation is None
        or invocation["chained"]
        or not invocation["runtime_sha256"]
    ):
        return None
    tokens = invocation["tokens"]
    launcher_index = int(invocation["launcher_index"])
    if len(tokens) <= launcher_index + 2:
        return None
    action = tokens[launcher_index + 1]
    if action not in {"skill-start", "skill-end"}:
        return None
    name = tokens[launcher_index + 2].strip()
    if not name or name.startswith("-"):
        return None

    options: dict[str, str] = {}
    index = launcher_index + 3
    while index < len(tokens):
        option = tokens[index]
        if option not in {
            "--provider", "--session-id", "--skill-path", "--contract",
            "--workspace", "--home",
        } or index + 1 >= len(tokens) or option in options:
            return None
        options[option] = tokens[index + 1]
        index += 2
    declared_provider = options.get("--provider", "").strip().lower()
    contract_path = options.get("--contract", "").strip()
    registration_session = options.get("--session-id", "").strip()
    skill_path = options.get("--skill-path", "").strip()
    if (
        not declared_provider
        or declared_provider != provider.strip().lower()
        or not contract_path
        or not registration_session
        or not skill_path
    ):
        return None
    return {
        "action": action,
        "name": name,
        "provider": declared_provider,
        "session_id": registration_session,
        "skill_path": skill_path,
        "contract_path": contract_path,
        "runtime_sha256": str(invocation["runtime_sha256"]),
    }

def _capability(kind: str, server: str, action: str) -> str:
    if kind == "mcp":
        return f"mcp:{server}:{action}"
    return f"{kind}:{action}"


def canonical_mcp_identity(tool_name: str) -> tuple[str, str]:
    """Normalize native MCP and Codex Apps tool namespaces.

    Codex Apps may expose tools as either
    ``mcp__codex_apps__<app>__<action>`` or the flattened
    ``mcp__codex_apps__<app>_<action>`` form.  The app is the policy server;
    ``codex_apps`` is only a host transport prefix.  Figma is intentionally
    recognized exactly because its whole execution domain is host-owned.
    """
    parts = str(tool_name).split("__")
    if len(parts) >= 4 and parts[0].lower() == "mcp" and parts[1].lower() == "codex_apps":
        return parts[2], "__".join(parts[3:]) or "unknown"
    if (
        len(parts) == 3
        and parts[0].lower() == "mcp"
        and parts[1].lower() == "codex_apps"
        and parts[2].lower().startswith("figma_")
    ):
        return "figma", parts[2][len("figma_"):] or "unknown"
    if len(parts) >= 3 and parts[0].lower() == "mcp":
        return parts[1], "__".join(parts[2:]) or "unknown"
    return "unknown", "unknown"


def _normalize_unified_exec_event(
    payload: dict[str, Any],
    source: str,
    *,
    phase: str,
    provider: str | None,
) -> dict[str, Any] | None:
    """Project Codex's outer JS orchestrator into its provable nested action."""
    if "tools." not in source:
        return None
    calls, unresolved = _unified_exec_nested_calls(source)
    nested_events: list[dict[str, Any]] = []
    for call in calls:
        nested_payload = dict(payload)
        nested_payload["tool_name"] = call["tool_name"]
        nested_payload["tool_input"] = call["tool_input"]
        if call.get("cwd"):
            nested_payload["cwd"] = call["cwd"]
        nested = normalize_hook_event(
                nested_payload,
                phase=phase,
                provider=provider,
            )
        command = call.get("tool_input", {}).get("command", "")
        if nested.get("control_action") in {"skill-start", "skill-end"}:
            registration = _guardian_skill_command(command, provider=nested["provider"])
            if registration:
                nested["composition_registration"] = registration
        nested_events.append(nested)
    material = [
        event
        for event in nested_events
        if event.get("effect") != "read"
        and event.get("supervision_domain") != "execution_passthrough"
    ]
    if len(nested_events) == 1 and not unresolved:
        event = nested_events[0]
        if event.get("effect") == "unknown" and event.get(
            "supervision_domain"
        ) != "execution_passthrough":
            event["uncertainty_kind"] = "unresolved_orchestrator_effect"
            event["target"] = "[unresolved-orchestrator-effect]"
        event["orchestrator_wrapper"] = "codex_unified_exec"
        return event
    if nested_events and not material and not unresolved:
        event = dict(nested_events[0])
        # Preserve *every* control decision in a multi-call wrapper. A read
        # effect is not authority to run native/human controls in another
        # segment, nor may a safe first composition hide a later denial.
        composed_controls = os.name != "nt" and any(nested.get("control_plane") or nested.get("composition") for nested in nested_events)
        passthrough_only = all(
            nested.get("effect") == "read"
            or nested.get("supervision_domain") == "execution_passthrough"
            for nested in nested_events
        )
        event["action"] = "exec-orchestrator"
        event["capability"] = "tool:exec-orchestrator"
        event["target"] = "[orchestrated-read-set]"
        event["arguments_digest"] = _input_digest({"source": source})
        event["event_id"] = hashlib.sha256(
            f"tool\0\0exec-orchestrator\0{event['target']}\0{event['arguments_digest']}".encode(
                "utf-8"
            )
        ).hexdigest()[:24]
        event["effect"] = "unknown" if passthrough_only and any(
            nested.get("supervision_domain") == "execution_passthrough"
            for nested in nested_events
        ) else "read"
        if event["effect"] == "unknown":
            event["uncertainty_kind"] = "execution_passthrough"
            event["supervision_domain"] = "execution_passthrough"
            event["execution_domain"] = "git"
        else:
            event.pop("uncertainty_kind", None)
            event.pop("supervision_domain", None)
            event.pop("execution_domain", None)
        for key in (
            "control_action", "control_plane", "control_route",
            "continuation_candidate", "formal_maintenance", "typed_resource",
            "typed_resource_id", "resource_kind", "write_targets",
            "local_file_operations", "destructive_local_operation",
        ):
            event.pop(key, None)
        event["orchestrator_wrapper"] = "codex_unified_exec"
        if composed_controls:
            event.pop("supervision_domain", None)
            event.pop("execution_domain", None)
            event.pop("uncertainty_kind", None)
            event["effect"] = "read"
            event["control_plane"] = True
            event["control_route"] = "composition"
            event["control_action"] = "composition"
            event["composition"] = {
                "schema": "sulde-control-composition-v1", "error": "",
                "steps": [{"index": index, "after": "orchestrator", "event": nested, "outcome": "not_observed"}
                          for index, nested in enumerate(nested_events, 1)],
                "authority_transferred": False, "step_outcomes": "not_observed",
                "automatic_retry": False, "execution_semantics": "original-orchestrator",
            }
        return event
    fallback_payload = dict(payload)
    fallback_payload["tool_name"] = "Read"
    fallback_payload["tool_input"] = {}
    event = normalize_hook_event(
        fallback_payload,
        phase=phase,
        provider=provider,
    )
    event["action"] = "exec-orchestrator"
    event["capability"] = "tool:exec-orchestrator"
    event["effect"] = "unknown"
    event["target"] = "[unresolved-orchestrator-effect]"
    event["arguments_digest"] = _input_digest({"source": source})
    event["uncertainty_kind"] = "unresolved_orchestrator_effect"
    event["event_id"] = hashlib.sha256(
        f"tool\0\0exec-orchestrator\0{event['target']}\0{event['arguments_digest']}".encode(
            "utf-8"
        )
    ).hexdigest()[:24]
    event["orchestrator_wrapper"] = "codex_unified_exec"
    return event

def normalize_hook_event(
    payload: dict[str, Any],
    *,
    phase: str,
    provider: str | None = None,
) -> dict[str, Any]:
    tool_name = str(payload.get("tool_name") or payload.get("toolName") or payload.get("name") or "unknown")
    raw_input = payload.get("tool_input") or payload.get("toolInput") or payload.get("input") or {}
    tool_input = raw_input if isinstance(raw_input, dict) else {"value": raw_input}
    lowered = tool_name.lower()
    if (
        lowered in {"exec", "functions.exec"}
        and not isinstance(raw_input, dict)
        and isinstance(raw_input, str)
    ):
        orchestrated = _normalize_unified_exec_event(
            payload,
            raw_input,
            phase=phase,
            provider=provider,
        )
        if orchestrated is not None:
            return orchestrated
    kind = "tool"
    server = ""
    action = tool_name
    control: dict[str, Any] | None = None
    continuation_candidate: dict[str, Any] | None = None
    git_ref: dict[str, Any] | None = None
    write_targets: list[str] = []
    local_file_operations: list[dict[str, str]] = []
    destructive_local_operation = False
    high_risk_local_operation = False
    invocation_violation: dict[str, Any] | None = None
    supervision_domain = "intent_guardian"
    execution_domain = ""
    uncertainty_kind = ""
    command = ""
    host_control = _pause_safe_host_control_action(tool_name)
    if lowered == "skill" or lowered.startswith("skill:") or "skill_name" in tool_input:
        kind = "skill"
        action = str(tool_input.get("skill") or tool_input.get("skill_name") or tool_name.split(":", 1)[-1])
    elif lowered.startswith("mcp__"):
        kind = "mcp"
        server, action = canonical_mcp_identity(tool_name)
    elif payload.get("server_name") or payload.get("serverName"):
        kind = "mcp"
        server = str(payload.get("server_name") or payload.get("serverName"))
        action = str(payload.get("mcp_tool") or payload.get("mcpTool") or tool_name)

    capability = _capability(kind, server, action)
    registered_effect = DEFAULT_EFFECT_ROUTER.resolve(capability)
    server_tokens = {
        token
        for token in re.split(r"[^a-z0-9]+", server.strip().lower())
        if token
    }
    normalized_action = action.strip().lower().replace("-", "_")
    figma_passthrough = bool(
        kind == "mcp"
        and (
            "figma" in server_tokens
            or normalized_action == "figma"
            or normalized_action.startswith("figma__")
            or (
                server.strip().lower() == "codex_apps"
                and normalized_action.startswith("figma_")
            )
        )
    )
    if figma_passthrough:
        supervision_domain = "execution_passthrough"
        execution_domain = "figma"

    target = _first_input_value(
        tool_input,
        (
            "file_path", "path", "target", "url", "uri", "repo", "repository",
            "fileKey", "file_key", "node_id", "nodeId", "document_id",
            "documentId", "query", "subject", "name",
        ),
    )
    if kind == "skill":
        skill_path = _first_input_value(tool_input, ("skill_path", "skillPath", "path"))
        if skill_path:
            target = skill_path
    response = payload.get("tool_response")
    if response is None:
        response = payload.get("toolResponse")
    if response is None:
        response = payload.get("output")
    result_target = _response_target(response)
    words = _words(action)
    if kind == "skill":
        effect = "read"
    elif kind == "mcp":
        if registered_effect is not None:
            effect = registered_effect.effect_class.value
        elif words & DESTRUCTIVE_WORDS:
            effect = "destructive"
        elif words & WRITE_WORDS:
            effect = "external_write"
        elif words & READ_WORDS:
            effect = "read"
        else:
            effect = "unknown"
            uncertainty_kind = "unresolved_external_write"
    elif host_control:
        effect = "read"
        target = f"[host-control:{host_control}]"
        control = {
            "action": f"host:{host_control}",
            "route": "agent",
            "runtime_sha256": "",
        }
    elif lowered in {"write", "edit", "multiedit", "file_change"}:
        effect = "local_write"
        if target:
            write_targets = [_safe_local_path(target)]
            target = _local_target_label(write_targets)
    elif lowered == "apply_patch":
        patch_text = _extract_patch_text(tool_input)
        try:
            parsed_operations = parse_apply_patch_operations(patch_text)
        except LocalFileOperationError:
            parsed_operations = ()
        if parsed_operations:
            local_file_operations = [
                {
                    "operation": operation.operation,
                    "path": _safe_local_path(operation.path),
                }
                for operation in parsed_operations
            ]
            write_targets = [
                _safe_local_path(value) for value in operation_targets(parsed_operations)
            ]
            destructive_local_operation = has_destructive_operation(parsed_operations)
            # apply_patch already carries an exact, reviewable file operation
            # envelope.  Deleting or renaming individual files is ordinary
            # Agent-owned local work; protected control paths are checked by
            # policy independently.
            high_risk_local_operation = False
            effect = "local_write"
            target = _local_target_label(write_targets)
        else:
            effect = "unknown"
            target = "[unresolved-patch-target]"
            uncertainty_kind = "unresolved_local_write"
    elif lowered in {
        "read",
        "glob",
        "grep",
        "find",
        "view_image",
        "search",
        "webrun",
        "web.run",
        "web__run",
    }:
        effect = "read"
    elif lowered in {"bash", "exec", "exec_command", "command_execution"}:
        command = str(tool_input.get("command") or tool_input.get("cmd") or "")
        if "intent-guardian" in command and _has_unquoted_shell_control(command):
            composed = normalize_composition(
                {**payload, "tool_input": tool_input}, command, phase=phase, provider=provider,
                services=CompositionServices(
                    normalize_hook_event, _has_unquoted_shell_control, _guardian_invocation,
                    _shell_execution_segments, _input_digest, _contains_sensitive_material,
                    _command_execution_cwd, _guardian_control_command, _guardian_skill_command,
                    _strongest_effect, _composition_has_destructive_segment, _local_target_label,
                ),
            )
            if composed is not None:
                return composed
        command_cwd = _command_execution_cwd(payload, tool_input)
        # Codex keeps Hook ``cwd`` pinned to the session launch directory even
        # after an approved session -> worktree handoff.  Relative shell and
        # local-file semantics must still use that raw execution cwd, while a
        # proposal-bound maintenance command must resolve its grant against
        # the durable task lane selected by the bridge.
        maintenance_workspace = payload.get("sulde_workspace_root")
        maintenance_cwd = (
            str(maintenance_workspace)
            if isinstance(maintenance_workspace, str)
            and maintenance_workspace.strip()
            else command_cwd
        )
        git_passthrough = _git_execution_passthrough(command)
        shell_delete_operations = (
            None
            if git_passthrough
            else _literal_shell_delete_operations(
                command,
                cwd=command_cwd,
                require_existing=phase != "completed",
            )
        )
        syntax_check_target = _shell_syntax_check_target(command)
        continuation_candidate = None if git_passthrough else (
            _codex_plugin_cachebuster_v2_candidate(command, cwd=maintenance_cwd)
            or _codex_plugin_install_v2_candidate(command, cwd=maintenance_cwd)
            or _scheduler_reconcile_candidate(command, cwd=maintenance_cwd)
            or _launcher_refresh_candidate(command, cwd=maintenance_cwd)
            or _codex_plugin_cachebuster_candidate(command, cwd=maintenance_cwd)
            or _codex_candidate_promotion_candidate(command, cwd=maintenance_cwd)
            or _codex_plugin_install_candidate(command, cwd=maintenance_cwd)
        )
        invocation_violation = None if git_passthrough else (
            None
            if continuation_candidate is not None
            or _codex_plugin_read_only_maintenance_command(
                command,
                cwd=maintenance_cwd,
            )
            else (
                _unsealed_codex_plugin_cachebuster_invocation(
                    command,
                    cwd=maintenance_cwd,
                )
                or _unsealed_sulde_maintenance_invocation(
                    command,
                    cwd=maintenance_cwd,
                )
                or _declared_trusted_script_denial(
                    command,
                    cwd=command_cwd,
                )
            )
        )
        control = None if git_passthrough else (
            _guardian_control_command(command) or _direct_host_callback_command(command)
        )
        registration = None if git_passthrough else _guardian_skill_command(
            command, provider=(provider or str(payload.get("client") or "unknown")),
        )
        command_risks: list[str] = []
        effect = (
            "unknown"
            if git_passthrough
            else continuation_candidate["effect"]
            if continuation_candidate is not None
            else (
                invocation_violation["effect"]
                if invocation_violation is not None
                else (
                    "read"
                    if registration or control
                    else (
                        "local_write"
                        if shell_delete_operations is not None
                        else _command_effect(command, cwd=command_cwd, risks=command_risks)
                    )
                )
            )
        )
        if command_risks and effect != "destructive" and invocation_violation is None:
            # A known write in the same program cannot hide an unresolved
            # delete/replace receiver behind the ordinary local_write class.
            effect = "unknown"
            invocation_violation = {
                "effect": "unknown", "kind": "unresolved-destructive-receiver",
                "reason": "对象类型未能证明；该方法可能改变文件，当前调用需明确目标和风险后再执行",
                "target": "[unresolved-destructive-receiver]", "write_targets": [],
            }
            uncertainty_kind = "unresolved_destructive_receiver"
        trusted_composition = (
            None if git_passthrough or not _has_unquoted_shell_control(command)
            else _trusted_script_command(command, cwd=command_cwd)
        )
        if (
            (control and control.get("route") == "invalid-composition")
            or (trusted_composition and trusted_composition.get("invalid_composition"))
        ):
            effect = (
                "destructive"
                if _composition_has_destructive_segment(command, cwd=command_cwd)
                else "unknown"
            )
            invocation_violation = {
                "effect": effect,
                "kind": "invalid-composition",
                "reason": "可信脚本必须是单个精确调用；禁止未证明的 shell 组合",
                "target": "[invalid-composition]",
                "write_targets": [],
            }
        if git_passthrough:
            supervision_domain = "execution_passthrough"
            execution_domain = "git"
            uncertainty_kind = "execution_passthrough"
        write_targets = (
            list(invocation_violation["write_targets"])
            if invocation_violation is not None
            else (
                [operation["path"] for operation in shell_delete_operations]
                if shell_delete_operations is not None
                else (
                    _command_write_targets(command, cwd=command_cwd)
                    if effect == "local_write"
                    else []
                )
            )
        )
        write_targets = _tool_local_write_targets(write_targets, payload, tool_input)
        if shell_delete_operations is not None:
            local_file_operations = shell_delete_operations
            destructive_local_operation = True
            high_risk_local_operation = _literal_shell_delete_is_high_risk(
                command,
                shell_delete_operations,
            )
        if continuation_candidate is not None:
            target = continuation_candidate["target"]
        elif invocation_violation is not None:
            target = invocation_violation["target"]
        elif effect == "local_write" and write_targets:
            target = _local_target_label(write_targets)
        elif effect == "local_write":
            # We know the command writes, but cannot prove where.  Do not feed
            # a command string into path policy as if it were a filename.
            effect = "unknown"
            target = "[unresolved-command-target]"
            uncertainty_kind = "unresolved_local_write"
        elif git_ref is not None:
            target = git_ref["target"]
        elif syntax_check_target:
            target = syntax_check_target
        else:
            target = f"[command:{hashlib.sha256(command.encode('utf-8', errors='replace')).hexdigest()[:16]}]"
        if effect == "unknown" and not uncertainty_kind:
            uncertainty_kind = "opaque_execution"
    else:
        effect = (
            registered_effect.effect_class.value
            if registered_effect is not None
            else "unknown"
        )
        if effect == "unknown":
            uncertainty_kind = "opaque_execution"
    digest = _input_digest(tool_input)
    verification_kind, verification_sha256 = _write_verification_expectation(
        action,
        tool_input,
    )
    is_local_memory_annotation = (
        kind == "mcp"
        and server.lower() in {"sulde_kb", "sulde-kb"}
        and action.strip().lower() == "memory_annotate"
        and _memory_annotation_postcondition(tool_input) is not None
    )
    memory_request = None
    memory_validation_error = ""
    if (kind == "mcp" and server.lower() in {"sulde_kb", "sulde-kb"}
            and action.strip().lower() == "memory_annotate"):
        try:
            normalize_memory_annotation(tool_input, extracted_by=(provider or str(payload.get("client") or "unknown")), bounded=True)
        except (TypeError, ValueError) as error:
            memory_validation_error = str(error)
            effect = "local_write"
    if is_local_memory_annotation and verification_sha256:
        try:
            memory_request = normalize_memory_annotation(tool_input, bounded=True)
        except (ValueError, TypeError):
            memory_request = None
        if memory_request is not None:
            verification_sha256 = memory_annotation_digest(memory_request)
        target = f"[memory-annotation:{verification_sha256}]"
        continuation_candidate = _system_memory_annotation_candidate(
            tool_input,
            provider=(provider or str(payload.get("client") or "unknown")),
            expected_digest=verification_sha256,
        )
        if continuation_candidate is not None:
            effect = continuation_candidate["effect"]
    if continuation_candidate is not None:
        verification_kind = continuation_candidate["verification_kind"]
        verification_sha256 = continuation_candidate["verification_sha256"]
    fingerprint_source = f"{kind}\0{server}\0{action}\0{target}\0{digest}"
    # A tool-local cwd is the actual resolution base for relative command
    # targets; the host payload cwd is only the workspace/session fallback.
    resource_base = str(
        _command_execution_cwd(payload, tool_input)
    )
    classification_cwd = _command_execution_cwd(payload, tool_input)
    try:
        typed_resource = None if execution_domain == "git" else _classify_hook_resource(
            tool_name,
            tool_input,
            cwd=classification_cwd,
            provider=(provider or str(payload.get("client") or "unknown")),
            session_id=str(
                payload.get("session_id") or payload.get("sessionId") or ""
            ), phase=phase,
        )
    except (_ResourceAdapterError, OSError, ValueError):
        typed_resource = None
    if (
        isinstance(typed_resource, dict)
        and typed_resource.get("kind") == "figma"
        and typed_resource.get("status") == "classified"
        and typed_resource.get("effect") == "read"
    ):
        effect = "read"
        uncertainty_kind = ""
        verification_kind, verification_sha256 = "none", ""
    event = {
        "schema": EVENT_SCHEMA,
        "event_id": hashlib.sha256(fingerprint_source.encode("utf-8")).hexdigest()[:24],
        "at": now_iso(),
        "phase": phase,
        "provider": provider or str(payload.get("client") or "unknown"),
        "observation_source": str(
            payload.get("observation_source")
            or ("native_skill_hook" if kind == "skill" else "host_hook")
        ),
        "session_id": str(payload.get("session_id") or payload.get("sessionId") or ""),
        "permission_mode": str(
            payload.get("permission_mode")
            or payload.get("permissionMode")
            or ""
        ),
        "kind": kind,
        "server": server,
        "action": action,
        "capability": capability,
        "target": target,
        "result_target": result_target,
        "effect": effect if effect in EFFECTS else "unknown",
        "arguments_digest": digest,
        "resource_base": resource_base,
        "runtime_generation": RUNTIME_GENERATION,
        "loaded_module_generation": LOADED_MODULE_GENERATION,
        "artifact_generation": ARTIFACT_GENERATION,
        "sensitive_input": _contains_sensitive_material(tool_input),
        "success": payload.get("success"),
        "verification_kind": verification_kind,
        "verification_sha256": verification_sha256,
    }
    if supervision_domain != "intent_guardian":
        event["supervision_domain"] = supervision_domain
        event["execution_domain"] = execution_domain
    if uncertainty_kind:
        event["uncertainty_kind"] = uncertainty_kind
    if typed_resource is not None:
        event["typed_resource"] = typed_resource
        event["resource_kind"] = str(typed_resource.get("kind") or "")
        if (
            typed_resource.get("kind") == "local_delete"
            and typed_resource.get("status") == "rejected"
            and not local_file_operations
        ):
            # A command that names the delete primitive but cannot be sealed
            # as one exact local target is destructive uncertainty, not an
            # ordinary opaque command. This keeps malformed/aliased ``rm``
            # fail-closed at PreToolUse.
            event["effect"] = "destructive"
            event["uncertainty_kind"] = "rejected_local_delete"
            bounded_delete = (
                _literal_shell_delete_operations(
                    command,
                    cwd=classification_cwd,
                    require_existing=False,
                )
                if command
                else None
            )
            event["invocation_violation"] = {
                "effect": "destructive",
                "reason": str(
                    typed_resource.get("reason")
                    or "local delete resource could not be sealed"
                ),
                "target": "[rejected-local-delete]",
                "write_targets": [],
                # This distinguishes a bounded command-shape rejection from
                # wildcard/root/traversal/composed deletion uncertainty. The
                # command is still denied; the flag only prevents an
                # unexecuted safe-shape typo from pausing the whole task.
                "bounded_pre_execution_denial": bool(bounded_delete),
            }
        if typed_resource.get("resource_id"):
            event["typed_resource_id"] = str(typed_resource["resource_id"])
        if (
            typed_resource.get("kind") == "figma"
            and typed_resource.get("status") == "rejected"
            and event["effect"] != "read"
            and not event["target"]
        ):
            event["target"] = "[unresolved-figma-target]"
    if git_ref is not None:
        git_context = None
        if all(git_ref.get(field) for field in ("remote", "ref", "oid")):
            git_context = {
                field: str(git_ref[field]) for field in ("remote", "ref", "oid")
            }
        elif response is not None:
            git_context = _git_ref_read_context(git_ref, response)
        if git_context is not None:
            event["git_resource_context"] = git_context
    if continuation_candidate is not None:
        event["continuation_candidate"] = continuation_candidate
        if (continuation_candidate.get("profile_id") == SYSTEM_MEMORY_PROFILE
                and memory_request is not None):
            event["memory_verification"] = {"schema": "sulde-memory-annotation-v2",
                                             "request_sha256": verification_sha256}
    if memory_validation_error:
        event["invocation_violation"] = {
            "kind": "memory-annotation-validation", "effect": "local_write",
            "reason": "记忆登记参数无效（未执行，无需续行 grant）：" + memory_validation_error,
            "bounded_pre_execution_denial": True,
        }
    if (
        lowered in {"bash", "exec", "exec_command", "command_execution"}
        and invocation_violation is not None
    ):
        event["invocation_violation"] = invocation_violation
        if invocation_violation.get("formal_maintenance") is True:
            event["formal_maintenance"] = True
    elif (
        lowered in {"bash", "exec", "exec_command", "command_execution"}
        and effect != "read"
        and _formal_maintenance_reference(command)
    ):
        event["formal_maintenance"] = True
    event.update({"write_targets": write_targets} if write_targets else {})
    if supervision_domain != "execution_passthrough":
        event.update(_git_worktree_lifecycle_event(typed_resource))
    if local_file_operations:
        event["local_file_operations"] = local_file_operations
        event["destructive_local_operation"] = destructive_local_operation
        event["high_risk_local_operation"] = high_risk_local_operation
    if response is not None:
        evidence = _read_verification_evidence(response)
        if lowered in {"bash", "exec", "exec_command", "command_execution"} and git_ref is not None:
            git_evidence = _git_ref_read_evidence(git_ref, response)
            if git_evidence:
                evidence["relation"] = sorted(
                    set(evidence.get("relation", [])) | set(git_evidence)
                )
        proof_target = target or result_target
        if proof_target and _response_proves_existence(response):
            evidence["existence"] = [
                hashlib.sha256(
                    proof_target.encode("utf-8", errors="replace")
                ).hexdigest()
            ]
        event["verification_evidence"] = evidence
    if (
        phase == "completed"
        and is_local_memory_annotation
        and payload.get("success") is not False
    ):
        independent_verification = _local_memory_annotation_verification(
            tool_input,
            expected_digest=verification_sha256,
        )
        if independent_verification is not None:
            event["independent_verification"] = independent_verification
    elif (
        phase == "completed"
        and continuation_candidate is not None
        and continuation_candidate.get("profile_id") in {
            "codex-plugin-cachebuster-v1",
            "codex-plugin-cachebuster-v2",
        }
        and payload.get("success") is not False
    ):
        independent_verification = _codex_plugin_cachebuster_verification(
            continuation_candidate,
            expected_digest=verification_sha256,
        )
        if independent_verification is not None:
            event["independent_verification"] = independent_verification
    elif (
        phase == "completed"
        and continuation_candidate is not None
        and continuation_candidate.get("profile_id") in {
            "codex-plugin-install-v1",
            "codex-plugin-install-v2",
        }
        and payload.get("success") is not False
    ):
        independent_verification = _codex_plugin_install_verification(
            continuation_candidate,
            response,
            expected_digest=verification_sha256,
        )
        if independent_verification is not None:
            event["independent_verification"] = independent_verification
    elif (
        phase == "completed"
        and continuation_candidate is not None
        and continuation_candidate.get("profile_id")
        == "sulde-scheduler-reconcile-v1"
        and payload.get("success") is not False
    ):
        independent_verification = _scheduler_reconcile_verification(
            continuation_candidate,
            expected_digest=verification_sha256,
        )
        if independent_verification is not None:
            event["independent_verification"] = independent_verification
    elif (
        phase == "completed"
        and continuation_candidate is not None
        and continuation_candidate.get("profile_id")
        == "sulde-launcher-refresh-v1"
        and payload.get("success") is not False
    ):
        independent_verification = _launcher_refresh_verification(
            continuation_candidate,
            expected_digest=verification_sha256,
        )
        if independent_verification is not None:
            event["independent_verification"] = independent_verification
    if control:
        event.update(
            {
                "control_plane": True,
                "control_action": control["action"],
                "control_route": control["route"],
                "control_runtime_sha256": control["runtime_sha256"],
            }
        )
    call_id = (
        payload.get("call_id")
        or payload.get("callId")
        or payload.get("tool_use_id")
        or payload.get("toolUseId")
    )
    if call_id:
        event["call_id"] = str(call_id)
        bind_host_call_identity(event)
    verification_for = (
        payload.get("verification_for")
        or payload.get("verificationFor")
        or tool_input.get("verification_for")
        or tool_input.get("verificationFor")
    )
    if verification_for:
        event["verification_for"] = str(verification_for)
    return event
