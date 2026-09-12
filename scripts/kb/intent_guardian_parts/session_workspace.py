"""Durable per-session routing between registered workspace contracts."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
from typing import Any

from intervention import (
    InterventionError,
    load_projection as load_intervention_projection,
    readiness_blocking_attempts,
)
from session_continuity import ContinuationError, continuation_path, load_capsule
from session_lifecycle_lineage import record_transition
from task_ownership import upsert_task_lane
from task_continuation_routing import pending_origin

from .state import (
    IntentGuardianError,
    _exclusive_path_lock,
    active_contract_path,
    atomic_write,
    contract_lock,
    default_contract,
    load_contract,
    now_iso,
    policy_digest,
    session_contract_path,
    workspace_root,
    _write_contract_unlocked,
)


SESSION_WORKSPACE_SCHEMA = "sulde-session-workspace-lane-v1"
HANDOFF_PREPARE_SCHEMA = "sulde-workspace-handoff-prepare-v1"
WORKSPACE_CLEANUP_SCHEMA = "sulde-workspace-cleanup-v1"
_OBJECT_ID = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?")
_TASK_BRANCH = re.compile(r"(?:task|fix|feature|feat|repair)/[^\s]+")


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def session_workspace_path(home: Path, provider: str, session_id: str) -> Path:
    selected_provider = provider.strip().lower()
    selected_session = session_id.strip()
    if selected_provider not in {"claude", "codex"} or not selected_session:
        raise IntentGuardianError("session workspace routing requires provider/session")
    digest = hashlib.sha256(
        f"{selected_provider}\0{selected_session}".encode("utf-8", errors="replace")
    ).hexdigest()[:32]
    return home.expanduser().resolve() / "intent" / "sessions" / (
        f"{selected_provider}-{digest}.workspace.json"
    )


def _git_output(root: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise IntentGuardianError(f"workspace Git identity is unavailable: {error}") from error
    if result.returncode != 0:
        raise IntentGuardianError(
            "workspace Git identity is unavailable: "
            + (result.stderr or result.stdout).strip()[-500:]
        )
    return result.stdout.strip()


def _git_result(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run one read-only Git observation and preserve its return code."""
    try:
        return subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise IntentGuardianError(
            f"workspace Git observation is unavailable: {error}"
        ) from error


def _require_git_success(result: subprocess.CompletedProcess[str], action: str) -> str:
    if result.returncode != 0:
        raise IntentGuardianError(
            f"workspace Git {action} failed: "
            + (result.stderr or result.stdout).strip()[-500:]
        )
    return result.stdout


def _registered_worktree_roots(root: Path) -> set[Path]:
    output = _require_git_success(
        _git_result(root, "worktree", "list", "--porcelain"),
        "worktree inventory",
    )
    roots: set[Path] = set()
    for line in output.splitlines():
        if line.startswith("worktree "):
            roots.add(Path(line[len("worktree ") :]).expanduser().resolve())
    return roots


def _local_branch_exists(root: Path, branch: str) -> bool:
    result = _git_result(root, "show-ref", "--verify", "--quiet", f"refs/heads/{branch}")
    if result.returncode not in {0, 1}:
        _require_git_success(result, "branch observation")
    return result.returncode == 0


def _completion_contract_path(home: Path, release_id: str) -> Path:
    return (
        home.expanduser().resolve()
        / "intent"
        / "sessions"
        / f"completion-{release_id[:32]}.active.json"
    )


def _cleanup_record(contract: dict[str, Any]) -> dict[str, Any] | None:
    raw = contract.get("workspace_cleanup")
    if raw is None:
        return None
    if not isinstance(raw, dict) or raw.get("schema") != WORKSPACE_CLEANUP_SCHEMA:
        raise IntentGuardianError("workspace cleanup record is invalid")
    required = {
        "schema", "release_id", "release_subject_sha256", "status", "provider",
        "session_id", "source_contract", "source_workspace", "source_git_common_dir",
        "source_branch", "source_head", "target_workspace", "target_branch",
        "target_head", "released_at", "completed_at", "completion_evidence_sha256",
        "authority_transferred", "git_mutation_performed",
    }
    if set(raw) != required:
        raise IntentGuardianError("workspace cleanup record fields are invalid")
    if raw.get("status") not in {"pending", "complete"}:
        raise IntentGuardianError("workspace cleanup status is invalid")
    if raw.get("authority_transferred") is not False:
        raise IntentGuardianError("workspace cleanup cannot transfer authority")
    if raw.get("git_mutation_performed") is not False:
        raise IntentGuardianError("Guardian workspace cleanup cannot perform Git mutation")
    subject = {
        key: raw[key]
        for key in (
            "schema", "provider", "session_id", "source_contract", "source_workspace",
            "source_git_common_dir", "source_branch", "source_head", "target_workspace",
            "target_branch", "target_head", "authority_transferred",
            "git_mutation_performed",
        )
    }
    digest = _canonical_sha256(subject)
    if raw.get("release_subject_sha256") != digest or raw.get("release_id") != digest:
        raise IntentGuardianError("workspace cleanup release digest differs")
    if raw["status"] == "complete":
        evidence = {
            "release_id": raw["release_id"],
            "source_workspace_exists": False,
            "source_worktree_registered": False,
            "source_branch_exists": False,
        }
        if raw.get("completion_evidence_sha256") != _canonical_sha256(evidence):
            raise IntentGuardianError("workspace cleanup completion digest differs")
        if not raw.get("completed_at"):
            raise IntentGuardianError("completed workspace cleanup lacks timestamp")
    elif raw.get("completed_at") or raw.get("completion_evidence_sha256"):
        raise IntentGuardianError("pending workspace cleanup has completion evidence")
    return dict(raw)


def workspace_cleanup_status(contract: dict[str, Any]) -> dict[str, Any]:
    """Project one durable cleanup receipt without mutating Git or the contract."""
    record = _cleanup_record(contract)
    if record is None:
        return {"status": "not_applicable"}
    result = dict(record)
    if record["status"] == "complete":
        result["next_action"] = "No workspace cleanup remains."
        return result
    target = Path(record["target_workspace"]).expanduser().resolve()
    source = Path(record["source_workspace"]).expanduser().resolve()
    registered = source in _registered_worktree_roots(target)
    branch_exists = _local_branch_exists(target, str(record["source_branch"]))
    result.update(
        {
            "source_workspace_exists": source.exists(),
            "source_worktree_registered": registered,
            "source_branch_exists": branch_exists,
            "next_action": (
                "Agent must finish the ordinary Git worktree/branch cleanup, then run "
                "finalize-workspace-cleanup. No user command, copied text or session restart "
                "is required."
            ),
        }
    )
    return result


def workspace_cleanup_context(contract: dict[str, Any]) -> str:
    cleanup = workspace_cleanup_status(contract)
    if cleanup["status"] != "pending":
        return ""
    return (
        "[sulde intent] WORKTREE_CLEANUP_PENDING authority_transferred=false\n"
        "上一任务的执行权限已经撤销。Agent 应通过普通 Git passthrough 清理任务 "
        f"worktree 与本地分支（{cleanup['source_branch']}），随后调用 "
        "finalize-workspace-cleanup 并回读回执。不要要求用户复制命令、关闭会话或"
        "手工清理；若本轮中断，下一轮继续同一幂等收尾。"
    )


def registered_worktree_identity(workspace: Path) -> dict[str, str]:
    root = workspace_root(workspace).expanduser().resolve()
    top = Path(_git_output(root, "rev-parse", "--show-toplevel")).resolve()
    if top != root:
        raise IntentGuardianError("workspace is not the registered worktree root")
    common_raw = Path(_git_output(root, "rev-parse", "--git-common-dir"))
    common = (root / common_raw).resolve() if not common_raw.is_absolute() else common_raw.resolve()
    branch = _git_output(root, "symbolic-ref", "--quiet", "--short", "HEAD")
    head = _git_output(root, "rev-parse", "HEAD").lower()
    if not branch or _OBJECT_ID.fullmatch(head) is None or not common.is_dir():
        raise IntentGuardianError("workspace worktree branch/HEAD identity is invalid")
    return {
        "workspace_root": str(root),
        "git_common_dir": str(common),
        "branch": branch,
        "head": head,
    }


def _mapping_material(mapping: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in mapping.items() if key != "mapping_sha256"}


def _validated_mapping(
    path: Path, *, require_target: bool = True, target_document: dict | None = None,
) -> dict[str, Any]:
    try:
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise IntentGuardianError("session workspace mapping is not a regular file")
        if os.name != "nt" and metadata.st_uid != os.getuid():
            raise IntentGuardianError("session workspace mapping has another owner")
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise IntentGuardianError(f"session workspace mapping is invalid: {error}") from error
    fields = {
        "schema", "provider", "session_id", "contract_path", "workspace_root",
        "git_common_dir", "branch", "head", "source_contract_path", "bound_at",
        "mapping_sha256",
    }
    if not isinstance(value, dict) or set(value) != fields:
        raise IntentGuardianError("session workspace mapping fields are invalid")
    if value.get("schema") != SESSION_WORKSPACE_SCHEMA:
        raise IntentGuardianError("session workspace mapping schema is unsupported")
    if value.get("mapping_sha256") != _canonical_sha256(_mapping_material(value)):
        raise IntentGuardianError("session workspace mapping digest differs")
    contract = Path(str(value.get("contract_path") or "")).expanduser().resolve()
    root = Path(str(value.get("workspace_root") or "")).expanduser().resolve()
    if require_target:
        if not contract.is_file() or not root.is_dir():
            raise IntentGuardianError("session workspace mapping target is unavailable")
        loaded = load_contract(contract)
        if target_document is not None:
            target_document.update(loaded)
        if Path(loaded["workspace_root"]).expanduser().resolve() != root:
            raise IntentGuardianError("session workspace mapping and contract root differ")
    return value


def load_session_workspace(
    home: Path, provider: str, session_id: str, *, target_document: dict | None = None,
) -> dict[str, Any] | None:
    path = session_workspace_path(home, provider, session_id)
    try:
        value = _validated_mapping(path, target_document=target_document)
    except FileNotFoundError:
        return None
    if value["provider"] != provider.strip().lower() or value["session_id"] != session_id.strip():
        raise IntentGuardianError("session workspace mapping lane differs")
    return value


def resolve_session_contract(home: Path, provider: str, session_id: str) -> Path | None:
    document: dict[str, Any] = {}
    mapping = load_session_workspace(home, provider, session_id, target_document=document)
    if mapping is not None:
        try:
            origin = pending_origin(mapping, document)
        except (ValueError, KeyError, TypeError) as error:
            raise IntentGuardianError(str(error)) from error
        if origin is not None:
            load_contract(origin)
            return origin.resolve()
        return Path(mapping["contract_path"]).expanduser().resolve()
    # Git worktrees use a lineage-fenced mapping. Non-Git workspaces cannot
    # produce that identity, but their per-session contract is still a safe,
    # deterministic routing target and must not fall back to another session's
    # workspace anchor.
    fallback = session_contract_path(home, provider, session_id)
    if not fallback.is_file():
        return None
    load_contract(fallback)
    return fallback.resolve()


def session_may_discover_contract(
    contract: dict[str, Any], *, provider: str, session_id: str
) -> bool:
    """Allow discovery only for an empty contract or this exact native lane."""
    lanes = [
        row
        for row in contract.get("runtime", {}).get("task_lanes", [])
        if isinstance(row, dict)
    ]
    return not lanes or any(
        str(row.get("provider") or "").lower() == provider.strip().lower()
        and str(row.get("session_id") or "") == session_id.strip()
        for row in lanes
    )


def _write_mapping(home: Path, mapping: dict[str, Any]) -> dict[str, Any]:
    path = session_workspace_path(home, mapping["provider"], mapping["session_id"])
    with _exclusive_path_lock(path.with_name("." + path.name + ".lock")):
        return _write_mapping_unlocked(home, mapping)


def _write_mapping_unlocked(home: Path, mapping: dict[str, Any]) -> dict[str, Any]:
    sealed = dict(mapping)
    sealed["mapping_sha256"] = _canonical_sha256(_mapping_material(sealed))
    path = session_workspace_path(home, sealed["provider"], sealed["session_id"])
    atomic_write(path, json.dumps(sealed, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    if os.name != "nt":
        path.chmod(0o600)
    return sealed


def bind_session_workspace(
    home: Path,
    *,
    provider: str,
    session_id: str,
    contract_path: Path,
    source_contract_path: Path | None = None,
) -> dict[str, Any] | None:
    """Bind one native session to one contract without transferring authority.

    This writes routing metadata only.  It copies no task lane, approval,
    grant, event, or effect state from another contract.
    """
    selected_provider = provider.strip().lower()
    selected_session = session_id.strip()
    if selected_provider not in {"claude", "codex"} or not selected_session:
        return None
    selected_contract = contract_path.expanduser().resolve()
    contract = load_contract(selected_contract)
    root = Path(contract["workspace_root"]).expanduser().resolve()
    try:
        identity = registered_worktree_identity(root)
    except IntentGuardianError:
        # Session isolation also applies to non-Git workspaces. They have no
        # branch/HEAD lineage to fence, so bind the exact validated contract
        # and workspace root with an explicitly empty Git identity.
        identity = {
            "workspace_root": str(root),
            "git_common_dir": "",
            "branch": "",
            "head": "",
        }
    return _write_mapping(
        home,
        {
            "schema": SESSION_WORKSPACE_SCHEMA,
            "provider": selected_provider,
            "session_id": selected_session,
            "contract_path": str(selected_contract),
            **identity,
            "source_contract_path": (
                str(source_contract_path.expanduser().resolve())
                if source_contract_path is not None
                else ""
            ),
            "bound_at": now_iso(),
        },
    )


def prepare_session_mapping_rebind(
    home: Path,
    *,
    source_contract_path: Path,
    source_workspace: Path,
    target_contract_path: Path,
    target_workspace: Path,
) -> list[dict[str, Any]]:
    """Freeze mapped-session updates for one orphan-contract rebind.

    Missing source targets are expected here, so mapping structure and digest
    are validated independently from target availability.  A mapped session
    may only follow the contract to a registered worktree in the same Git
    common-dir; non-Git scratch rebinding remains available when no live
    session mapping references the orphan.
    """
    source_contract = source_contract_path.expanduser().resolve()
    source_root = source_workspace.expanduser().resolve()
    sessions_root = home.expanduser().resolve() / "intent" / "sessions"
    if not sessions_root.is_dir():
        return []

    matches: list[tuple[Path, str, dict[str, Any]]] = []
    for mapping_path in sorted(sessions_root.glob("*.workspace.json")):
        mapping = _validated_mapping(mapping_path, require_target=False)
        expected_path = session_workspace_path(
            home, str(mapping["provider"]), str(mapping["session_id"])
        )
        if expected_path.resolve() != mapping_path.resolve():
            raise IntentGuardianError(
                "session workspace mapping filename differs from its identity"
            )
        mapped_contract = Path(str(mapping["contract_path"])).expanduser().resolve()
        mapped_root = Path(str(mapping["workspace_root"])).expanduser().resolve()
        contract_matches = mapped_contract == source_contract
        workspace_matches = mapped_root == source_root
        if contract_matches != workspace_matches:
            raise IntentGuardianError(
                "session workspace mapping only partially matches the orphan binding"
            )
        if contract_matches:
            matches.append(
                (
                    mapping_path,
                    mapping_path.read_text(encoding="utf-8"),
                    mapping,
                )
            )
    if not matches:
        return []

    target_identity = registered_worktree_identity(target_workspace)
    target_contract = target_contract_path.expanduser().resolve()
    rebound_at = now_iso()
    plan: list[dict[str, Any]] = []
    for mapping_path, before, mapping in matches:
        if str(mapping["git_common_dir"]) != target_identity["git_common_dir"]:
            raise IntentGuardianError(
                "mapped session rebind requires the same Git common-dir"
            )
        plan.append(
            {
                "path": mapping_path,
                "before": before,
                "mapping": {
                    "schema": SESSION_WORKSPACE_SCHEMA,
                    "provider": str(mapping["provider"]),
                    "session_id": str(mapping["session_id"]),
                    "contract_path": str(target_contract),
                    **target_identity,
                    "source_contract_path": str(source_contract),
                    "bound_at": rebound_at,
                },
            }
        )
    return plan


def apply_session_mapping_rebind(
    home: Path, plan: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Publish a frozen mapping batch, restoring every prior byte on failure."""
    applied: list[dict[str, Any]] = []
    try:
        for item in plan:
            path = Path(item["path"]).expanduser().resolve()
            # Track the attempt before publishing so even a post-replace chmod
            # failure restores the exact prior bytes.
            applied.append(item)
            sealed = _write_mapping(home, dict(item["mapping"]))
            if session_workspace_path(
                home, sealed["provider"], sealed["session_id"]
            ).resolve() != path:
                raise IntentGuardianError(
                    "session workspace rebind target path differs"
                )
    except Exception:
        for item in reversed(applied):
            path = Path(item["path"]).expanduser().resolve()
            atomic_write(path, str(item["before"]))
            if os.name != "nt":
                path.chmod(0o600)
        raise
    return [dict(item["mapping"]) for item in plan]


def seed_session_workspace_hint(
    home: Path,
    *,
    provider: str,
    session_id: str,
    contract_path: Path,
) -> dict[str, Any] | None:
    """Persist the launch-time contract only when this session has no lane yet."""
    if not session_id.strip() or provider.strip().lower() not in {"claude", "codex"}:
        return None
    existing = load_session_workspace(home, provider, session_id)
    if existing is not None:
        return existing
    return bind_session_workspace(
        home,
        provider=provider,
        session_id=session_id,
        contract_path=contract_path,
    )


def _translate_allowed_paths(
    values: list[str], source_root: Path, target_root: Path
) -> list[str]:
    translated: list[str] = []
    for raw in values:
        candidate = Path(raw).expanduser()
        if candidate.is_absolute():
            try:
                relative = candidate.resolve().relative_to(source_root)
            except (OSError, ValueError):
                translated.append(raw)
            else:
                translated.append(str((target_root / relative).resolve()))
        else:
            translated.append(raw)
    return translated


def _current_session_approved_target(
    contract: dict[str, Any], *, provider: str, session_id: str
) -> bool:
    """Return whether this exact session approved the target's current task.

    An existing contract is not inherited from the source workspace.  It may
    be adopted only after the target contract independently applied a proposal
    and bound the same native session to its current task epoch.
    """
    proposal_digest = str(contract.get("applied_proposal_digest") or "")
    if (
        contract.get("status") != "active"
        or contract.get("confirmation", {}).get("required")
        or not proposal_digest
    ):
        return False
    return any(
        row.get("provider") == provider.strip().lower()
        and row.get("session_id") == session_id.strip()
        and row.get("state") == "bound"
        and row.get("task_epoch") == contract.get("task_epoch")
        and row.get("proposal_digest") == proposal_digest
        for row in contract.get("runtime", {}).get("task_lanes", [])
        if isinstance(row, dict)
    )


def _current_session_unconfirmed_target(
    path: Path,
    contract: dict[str, Any],
    *,
    provider: str,
    session_id: str,
) -> bool:
    """Recognize a same-session proposal bootstrap with zero material authority."""
    pending = str(contract.get("runtime", {}).get("pending_proposal_digest") or "")
    if (
        contract.get("status") != "active"
        or not contract.get("confirmation", {}).get("required")
        or not re.fullmatch(r"[0-9a-f]{64}", pending)
        or contract.get("applied_proposal_digest")
    ):
        return False
    runtime = contract.get("runtime", {})
    for field in (
        "authorized_events",
        "open_events",
        "pending_verifications",
        "verified_effects",
        "approval_receipts",
        "continuation_uses",
        "task_continuations",
        "pre_execution_gaps",
    ):
        if runtime.get(field):
            return False
    if int(runtime.get("material_sequence", 0)) != 0:
        return False
    try:
        capsule = load_capsule(continuation_path(path, pending))
    except (ContinuationError, OSError, UnicodeError):
        return False
    source = capsule.get("source") if isinstance(capsule.get("source"), dict) else {}
    return bool(
        capsule.get("proposal_digest") == pending
        and source.get("provider") == provider.strip().lower()
        and source.get("session_id") == session_id.strip()
        and capsule.get("authority", {}).get("transferred") is False
    )


def prepare_workspace_handoff(
    home: Path,
    source_contract_path: Path,
    target_workspace: Path,
    *,
    provider: str,
    session_id: str,
) -> dict[str, Any]:
    """Create an authority-free target contract for one registered worktree."""
    source_path = source_contract_path.expanduser().resolve()
    source = load_contract(source_path)
    source_identity = registered_worktree_identity(Path(source["workspace_root"]))
    target_identity = registered_worktree_identity(target_workspace)
    if source_identity["workspace_root"] == target_identity["workspace_root"]:
        raise IntentGuardianError("workspace handoff target is already active")
    if source_identity["git_common_dir"] != target_identity["git_common_dir"]:
        raise IntentGuardianError("workspace handoff requires the same Git common-dir")
    current = load_session_workspace(home, provider, session_id)
    if current is not None and Path(current["contract_path"]).resolve() != source_path:
        raise IntentGuardianError("workspace handoff source is not the current session contract")
    target_root = Path(target_identity["workspace_root"])
    target_path = active_contract_path(home, target_root)
    common_marker = {
        "schema": HANDOFF_PREPARE_SCHEMA,
        "source_contract_path": str(source_path),
        "source_policy_sha256": policy_digest(source),
        "source_revision": int(source["revision"]),
        "prepared_for_provider": provider.strip().lower(),
        "prepared_for_session": session_id.strip(),
        "source_git_common_dir": source_identity["git_common_dir"],
        "source_branch": source_identity["branch"],
        "source_head": source_identity["head"],
        "target_git_common_dir": target_identity["git_common_dir"],
        "target_branch": target_identity["branch"],
        "target_head": target_identity["head"],
    }
    adopt_existing = False
    adopt_without_decision = False
    with contract_lock(target_path):
        if target_path.is_file():
            target = load_contract(target_path)
            existing_marker = target.get("workspace_handoff_prepare")
            repeated_clone = {
                **common_marker,
                "handoff_mode": "clone-source-task",
                "task_epoch": str(target.get("task_epoch") or ""),
            }
            if (
                isinstance(existing_marker, dict)
                and existing_marker.get("handoff_mode") == "clone-source-task"
            ):
                if {
                    key: existing_marker.get(key) for key in repeated_clone
                } != repeated_clone:
                    raise IntentGuardianError(
                        "target workspace handoff preparation differs"
                    )
                # This is the authority-free target created by the first
                # prepare call, not an independently existing target task.
                # Repeating prepare must remain idempotent and must not
                # silently reinterpret it as an adopt-existing handoff.
                handoff_mode = "clone-source-task"
            else:
                handoff_mode = ""
            pending_same_session = _current_session_unconfirmed_target(
                target_path,
                target,
                provider=provider,
                session_id=session_id,
            )
            if not handoff_mode:
                handoff_mode = (
                    "adopt-unconfirmed-contract"
                    if pending_same_session
                    else "adopt-existing-contract"
                )
            stable_marker = {
                **common_marker,
                "handoff_mode": handoff_mode,
                "task_epoch": str(target["task_epoch"]),
            }
            if handoff_mode != "clone-source-task":
                stable_marker.update(
                    {
                        "target_intent_id": str(target["intent_id"]),
                        "target_policy_sha256": policy_digest(target),
                        "target_revision": int(target["revision"]),
                    }
                )
            if isinstance(existing_marker, dict):
                if {
                    key: existing_marker.get(key) for key in stable_marker
                } != stable_marker:
                    if not (
                        _current_session_approved_target(
                            target, provider=provider, session_id=session_id,
                        )
                        or _current_session_unconfirmed_target(
                            target_path,
                            target,
                            provider=provider,
                            session_id=session_id,
                        )
                    ):
                        raise IntentGuardianError(
                            "target workspace handoff preparation differs"
                        )
                    # No route moved during prepare.  When the same session
                    # independently approves a newer target revision/HEAD,
                    # replace only its stale unconsumed preparation marker.
                    target["workspace_handoff_prepare"] = {
                        **stable_marker, "prepared_at": now_iso(),
                    }
                    _write_contract_unlocked(target_path, target)
            elif not (
                _current_session_approved_target(
                    target, provider=provider, session_id=session_id,
                )
                or pending_same_session
            ):
                raise IntentGuardianError(
                    "target workspace has an independent contract not approved by "
                    "the current session"
                )
            else:
                target["workspace_handoff_prepare"] = {
                    **stable_marker, "prepared_at": now_iso(),
                }
                _write_contract_unlocked(target_path, target)
            adopt_existing = handoff_mode != "clone-source-task"
            adopt_without_decision = handoff_mode == "adopt-existing-contract"
        else:
            stable_marker = {
                **common_marker,
                "handoff_mode": "clone-source-task",
                "task_epoch": str(source["task_epoch"]),
            }
            marker = {**stable_marker, "prepared_at": now_iso()}
            source_root = Path(source_identity["workspace_root"])
            constraints = json.loads(json.dumps(source["constraints"]))
            constraints["allowed_paths"] = _translate_allowed_paths(
                list(constraints.get("allowed_paths") or []), source_root, target_root
            )
            target = default_contract(
                intent_id=str(source["intent_id"]),
                objective=str(source["objective"]),
                acceptance_criteria=list(source["acceptance_criteria"]),
                workspace=target_root,
                mode=str(source["mode"]),
                rationale=str(source.get("rationale") or ""),
                confirmed_by="workspace-handoff-pending-native-approval",
                confirmation_required=True,
                semantic_critic=bool(source.get("critic", {}).get("enabled")),
            )
            target["revision"] = int(source["revision"])
            target["task_epoch"] = str(source["task_epoch"])
            target["constraints"] = constraints
            target["permissions"] = json.loads(json.dumps(source["permissions"]))
            target["skills"] = json.loads(json.dumps(source["skills"]))
            target["mcp"] = json.loads(json.dumps(source["mcp"]))
            target["critic"] = json.loads(json.dumps(source["critic"]))
            if isinstance(source.get("decision"), dict):
                target["decision"] = json.loads(json.dumps(source["decision"]))
            target["continuation"] = {"grants": []}
            target["confirmation"] = {
                "required": True,
                "reason": "等待当前 Codex 会话原生确认 workspace handoff",
            }
            target["workspace_handoff_prepare"] = marker
            _write_contract_unlocked(target_path, target)
    mapping = None
    if adopt_existing and adopt_without_decision:
        # The target task already has an independently applied proposal bound
        # to this exact native session.  Publishing the route transfers no
        # authority, so making it atomic here avoids depending on a second
        # Guardian-mediated command that a broken old Guardian could self-lock.
        mapping = _write_mapping(
            home,
            {
                "schema": SESSION_WORKSPACE_SCHEMA,
                "provider": provider.strip().lower(),
                "session_id": session_id.strip(),
                "contract_path": str(target_path.resolve()),
                **target_identity,
                "source_contract_path": str(source_path),
                "bound_at": now_iso(),
            },
        )

        record_transition(
            home, provider=provider.strip().lower(), session_id=session_id.strip(),
            source_workspace=str(source_identity["workspace_root"]), mapping=mapping,
            receipt_id="independently-applied-proposal:" + str(target["applied_proposal_digest"]),
        )
    return {
        "schema": HANDOFF_PREPARE_SCHEMA,
        "status": "bound" if mapping is not None else "prepared",
        "authority_transferred": False,
        "source_contract": str(source_path),
        "target_contract": str(target_path.resolve()),
        "source": source_identity,
        "target": target_identity,
        "mapping": mapping,
    }


def workspace_handoff_context(
    home: Path,
    source_contract_path: Path,
    target_workspace: Path,
    *,
    provider: str,
    session_id: str,
) -> dict[str, Any]:
    source_path = source_contract_path.expanduser().resolve()
    source = load_contract(source_path)
    source_identity = registered_worktree_identity(Path(source["workspace_root"]))
    target_identity = registered_worktree_identity(target_workspace)
    target_path = active_contract_path(home, Path(target_identity["workspace_root"]))
    if not target_path.is_file():
        raise IntentGuardianError("workspace handoff target contract is not prepared")
    target = load_contract(target_path)
    marker = target.get("workspace_handoff_prepare")
    marker_value = marker if isinstance(marker, dict) else {}
    common_differs = (
        not isinstance(marker, dict)
        or marker_value.get("schema") != HANDOFF_PREPARE_SCHEMA
        or marker_value.get("source_contract_path") != str(source_path)
        or marker_value.get("source_policy_sha256") != policy_digest(source)
        or marker_value.get("source_git_common_dir") != source_identity["git_common_dir"]
        or marker_value.get("source_branch") != source_identity["branch"]
        or marker_value.get("source_head") != source_identity["head"]
        or marker_value.get("target_git_common_dir") != target_identity["git_common_dir"]
        or marker_value.get("target_branch") != target_identity["branch"]
        or marker_value.get("target_head") != target_identity["head"]
    )
    handoff_mode = str(marker_value.get("handoff_mode") or "clone-source-task") if isinstance(marker, dict) else ""
    if handoff_mode == "adopt-existing-contract":
        lineage_differs = (
            marker_value.get("target_intent_id") != target.get("intent_id")
            or marker_value.get("target_policy_sha256") != policy_digest(target)
            or marker_value.get("target_revision") != target.get("revision")
            or marker_value.get("task_epoch") != target.get("task_epoch")
            or not _current_session_approved_target(
                target, provider=provider, session_id=session_id,
            )
        )
    elif handoff_mode == "adopt-unconfirmed-contract":
        lineage_differs = (
            marker_value.get("target_intent_id") != target.get("intent_id")
            or marker_value.get("target_policy_sha256") != policy_digest(target)
            or marker_value.get("target_revision") != target.get("revision")
            or marker_value.get("task_epoch") != target.get("task_epoch")
            or not _current_session_unconfirmed_target(
                target_path,
                target,
                provider=provider,
                session_id=session_id,
            )
        )
    else:
        lineage_differs = (
            handoff_mode != "clone-source-task"
            or marker_value.get("task_epoch") != source.get("task_epoch")
            or target.get("intent_id") != source.get("intent_id")
            or target.get("task_epoch") != source.get("task_epoch")
        )
    if common_differs or lineage_differs:
        raise IntentGuardianError("workspace handoff target contract lineage differs")
    if source_identity["git_common_dir"] != target_identity["git_common_dir"]:
        raise IntentGuardianError("workspace handoff Git common-dir changed")
    current = load_session_workspace(home, provider, session_id)
    if current is not None and Path(current["contract_path"]).resolve() != source_path:
        raise IntentGuardianError("workspace handoff source is not the current session contract")
    subject = {
        "schema": "sulde-workspace-handoff-subject-v1",
        "provider": provider.strip().lower(),
        "session_id": session_id.strip(),
        "handoff_mode": handoff_mode,
        "intent_id": str(target["intent_id"]),
        "task_epoch": str(target["task_epoch"]),
        "source_contract": str(source_path),
        "source_policy_sha256": policy_digest(source),
        "target_contract": str(target_path.resolve()),
        "target_policy_sha256": policy_digest(target),
        "git_common_dir": target_identity["git_common_dir"],
        "target_workspace": target_identity["workspace_root"],
        "target_branch": target_identity["branch"],
        "target_head": target_identity["head"],
    }
    card = {
        "要决定的结果": "把当前 Codex 会话切换到已注册的任务 worktree",
        "当前工作区": source_identity["workspace_root"],
        "目标工作区": target_identity["workspace_root"],
        "目标分支": target_identity["branch"],
        "目标 HEAD": target_identity["head"],
        "Git common-dir": target_identity["git_common_dir"],
        "会继承": (
            "目标工作区中由当前会话独立批准的任务、约束和验收标准"
            if handoff_mode == "adopt-existing-contract"
            else "同一任务的目标、约束和验收标准"
        ),
        "明确不继承": (
            "旧合同 grant、批准回执、authorized/open event、pending verification、"
            "effect debt、continuation token 或 active skill"
        ),
        "失败语义": "映射提交失败时继续使用当前合同，不锁住原任务",
        "切换摘要": _canonical_sha256(subject),
    }
    return {
        "subject": subject,
        "target": target_identity["workspace_root"],
        "card": card,
        "source_contract": source_path,
        "target_contract": target_path.resolve(),
        "source_identity": source_identity,
        "target_identity": target_identity,
        "handoff_mode": handoff_mode,
    }


def apply_workspace_handoff(
    home: Path,
    source_contract_path: Path,
    target_workspace: Path,
    *,
    provider: str,
    session_id: str,
    receipt_id: str,
) -> dict[str, Any]:
    """Prepare target state, then atomically publish the session route last."""
    context = workspace_handoff_context(
        home,
        source_contract_path,
        target_workspace,
        provider=provider,
        session_id=session_id,
    )
    target_path = Path(context["target_contract"])
    with contract_lock(target_path):
        target = load_contract(target_path)
        if context["handoff_mode"] == "clone-source-task":
            target["confirmation"] = {"required": False, "reason": ""}
            target["confirmed_by"] = "codex-native-workspace-handoff"
        unconfirmed = context["handoff_mode"] == "adopt-unconfirmed-contract"
        upsert_task_lane(
            target,
            provider=provider,
            session_id=session_id,
            state="review_required" if unconfirmed else "bound",
            source=(
                "native_workspace_handoff_existing_contract"
                if context["handoff_mode"] == "adopt-existing-contract"
                else "native_workspace_handoff_unconfirmed"
                if unconfirmed
                else "native_workspace_handoff"
            ),
            proposal_digest=str(target.get("applied_proposal_digest") or ""),
            continuation_token="",
            continuation_eligible=True,
        )
        target["runtime"]["host_observations"].append(
            {
                "event": "workspace_handoff",
                "provider": provider,
                "session_id": session_id,
                "source": "live_host_hook",
                "status": "bound",
                "source_contract": str(Path(source_contract_path).resolve()),
                "receipt_id": receipt_id,
                "authority_transferred": False,
                "at": now_iso(),
            }
        )
        target["runtime"]["host_observations"] = target["runtime"][
            "host_observations"
        ][-100:]
        _write_contract_unlocked(target_path, target)
    mapping = _write_mapping(
        home,
        {
            "schema": SESSION_WORKSPACE_SCHEMA,
            "provider": provider.strip().lower(),
            "session_id": session_id.strip(),
            "contract_path": str(target_path),
            **context["target_identity"],
            "source_contract_path": str(Path(source_contract_path).resolve()),
            "bound_at": now_iso(),
        },
    )

    lineage_recorded = record_transition(
        home, provider=provider.strip().lower(), session_id=session_id.strip(),
        source_workspace=str(context["source_identity"]["workspace_root"]),
        mapping=mapping, receipt_id=receipt_id,
    )
    return {
        "schema": "sulde-workspace-handoff-result-v1",
        "status": "bound",
        "authority_transferred": False,
        "receipt_id": receipt_id,
        "mapping": mapping,
        "lifecycle_lineage_recorded": lineage_recorded,
    }


def _require_release_clear(path: Path, contract: dict[str, Any]) -> None:
    runtime = contract["runtime"]
    blockers = []
    current_epoch = str(contract.get("task_epoch") or "")

    def blocks_release(row: Any) -> bool:
        if not isinstance(row, dict):
            return True
        if str(row.get("task_epoch") or "") in {"", current_epoch}:
            return True
        return row.get("effect") != "local_write" or any(
            row.get(key)
            for key in ("attempt_id", "effect_attempt_id", "continuation_grant")
        )

    for field in ("open_events", "pending_verifications", "pre_execution_gaps"):
        if any(blocks_release(row) for row in runtime.get(field, [])):
            blockers.append(field)
    frames = runtime.get("active_skill_frames", [])
    if (runtime.get("active_skills") and not frames) or any(
        not isinstance(row, dict)
        or str(row.get("task_epoch") or "") in {"", current_epoch}
        for row in frames
    ):
        blockers.append("active_skills")
    if runtime.get("pending_proposal_digest"):
        blockers.append("pending_proposal")
    try:
        effect_blockers = readiness_blocking_attempts(load_intervention_projection(path))
    except (InterventionError, OSError, UnicodeError) as error:
        raise IntentGuardianError(
            f"workspace release cannot replay effect truth: {error}"
        ) from error
    if effect_blockers:
        blockers.append("effect_debt")
    if blockers:
        raise IntentGuardianError(
            "workspace release requires settled task state: " + ", ".join(blockers)
        )


def _release_subject(
    source_path: Path,
    source: dict[str, str],
    target: dict[str, str],
    *,
    provider: str,
    session_id: str,
) -> dict[str, Any]:
    return {
        "schema": WORKSPACE_CLEANUP_SCHEMA,
        "provider": provider.strip().lower(),
        "session_id": session_id.strip(),
        "source_contract": str(source_path),
        "source_workspace": source["workspace_root"],
        "source_git_common_dir": source["git_common_dir"],
        "source_branch": source["branch"],
        "source_head": source["head"],
        "target_workspace": target["workspace_root"],
        "target_branch": target["branch"],
        "target_head": target["head"],
        "authority_transferred": False,
        "git_mutation_performed": False,
    }


def _close_released_source(
    source_path: Path,
    *,
    provider: str,
    session_id: str,
    release_id: str,
    anchor_path: Path,
) -> None:
    with contract_lock(source_path):
        source = load_contract(source_path)
        existing = source.get("workspace_release")
        if isinstance(existing, dict) and existing.get("release_id") == release_id:
            return
        source["status"] = "closed"
        source["workspace_release"] = {
            "schema": "sulde-workspace-release-source-v1",
            "release_id": release_id,
            "provider": provider.strip().lower(),
            "session_id": session_id.strip(),
            "completion_contract": str(anchor_path),
            "authority_transferred": False,
            "released_at": now_iso(),
        }
        source["runtime"]["host_observations"].append(
            {
                "event": "workspace_release",
                "provider": provider.strip().lower(),
                "session_id": session_id.strip(),
                "source": "agent_completion_release",
                "status": "closed",
                "release_id": release_id,
                "authority_transferred": False,
                "at": now_iso(),
            }
        )
        source["runtime"]["host_observations"] = source["runtime"][
            "host_observations"
        ][-100:]
        _write_contract_unlocked(source_path, source)


def release_completed_workspace(
    home: Path,
    source_contract_path: Path,
    target_workspace: Path,
    *,
    provider: str,
    session_id: str,
) -> dict[str, Any]:
    """Deauthorize a merged task and publish a retryable cleanup anchor.

    Every Git call in this transition is observational. The Agent performs the
    subsequent worktree and branch removal through ordinary Git passthrough.
    """
    selected_provider = provider.strip().lower()
    selected_session = session_id.strip()
    if selected_provider not in {"claude", "codex"} or not selected_session:
        raise IntentGuardianError("workspace release requires provider/session")
    source_path = source_contract_path.expanduser().resolve()
    mapping_path = session_workspace_path(home, selected_provider, selected_session)
    lock_path = mapping_path.with_name(f".{mapping_path.name}.release.lock")
    with _exclusive_path_lock(lock_path):
        current = load_session_workspace(home, selected_provider, selected_session)
        if current is None:
            raise IntentGuardianError("workspace release requires a current session mapping")
        current_path = Path(current["contract_path"]).expanduser().resolve()
        if current_path != source_path:
            current_contract = load_contract(current_path)
            record = _cleanup_record(current_contract)
            if record is None or Path(record["source_contract"]).resolve() != source_path:
                raise IntentGuardianError(
                    "workspace release source is not the current session contract"
                )
            _close_released_source(
                source_path,
                provider=selected_provider,
                session_id=selected_session,
                release_id=str(record["release_id"]),
                anchor_path=current_path,
            )
            return {
                "schema": "sulde-workspace-release-result-v1",
                "status": str(record["status"]),
                "authority_transferred": False,
                "git_mutation_performed": False,
                "completion_contract": str(current_path),
                "mapping": current,
                "cleanup": workspace_cleanup_status(current_contract),
            }

        source_contract = load_contract(source_path)
        if source_contract["status"] != "active":
            raise IntentGuardianError("workspace release source contract is not active")
        _require_release_clear(source_path, source_contract)
        source_identity = registered_worktree_identity(
            Path(source_contract["workspace_root"])
        )
        target_identity = registered_worktree_identity(target_workspace)
        if source_identity["workspace_root"] == target_identity["workspace_root"]:
            raise IntentGuardianError("workspace release target is already active")
        if source_identity["git_common_dir"] != target_identity["git_common_dir"]:
            raise IntentGuardianError("workspace release requires the same Git common-dir")
        if _TASK_BRANCH.fullmatch(source_identity["branch"]) is None:
            raise IntentGuardianError("workspace release source is not a disposable task branch")
        if target_identity["branch"] != "dev":
            raise IntentGuardianError("workspace release target must be the dev branch")
        source_root = Path(source_identity["workspace_root"])
        dirty = _require_git_success(
            _git_result(source_root, "status", "--porcelain=v1", "--untracked-files=all"),
            "status observation",
        )
        if dirty:
            raise IntentGuardianError("workspace release source worktree is not clean")
        source_ref = _git_output(
            source_root, "rev-parse", f"refs/heads/{source_identity['branch']}"
        ).lower()
        if source_ref != source_identity["head"]:
            raise IntentGuardianError("workspace release source branch/HEAD differs")
        ancestor = _git_result(
            Path(target_identity["workspace_root"]),
            "merge-base",
            "--is-ancestor",
            source_identity["head"],
            target_identity["head"],
        )
        if ancestor.returncode == 1:
            raise IntentGuardianError("workspace release source HEAD is not merged into dev")
        _require_git_success(ancestor, "merge ancestry observation")

        subject = _release_subject(
            source_path,
            source_identity,
            target_identity,
            provider=selected_provider,
            session_id=selected_session,
        )
        release_id = _canonical_sha256(subject)
        anchor_path = _completion_contract_path(home, release_id)
        with contract_lock(anchor_path):
            if anchor_path.is_file():
                anchor = load_contract(anchor_path)
                record = _cleanup_record(anchor)
                if record is None or record["release_id"] != release_id:
                    raise IntentGuardianError("workspace completion anchor differs")
            else:
                anchor = default_contract(
                    intent_id=f"completion:{release_id[:24]}",
                    objective="上一任务已完成；等待 Agent 清理临时 Git 资源并接收下一任务",
                    acceptance_criteria=[
                        "源 worktree 与本地任务分支均由 Agent 通过普通 Git 操作清理",
                        "清理完成后写入可核验且幂等的 completion receipt",
                    ],
                    workspace=Path(target_identity["workspace_root"]),
                    mode="enforce",
                    rationale="完成态只保留最小会话路由与不可变清理证据",
                    preserve=["不继承已完成任务的任何执行权限或效果状态"],
                    reject=["Guardian 不得执行 Git 删除、移动、合并或分支操作"],
                    allowed_paths=[],
                    confirmed_by="system-completion-release",
                )
                anchor["permissions"] = {
                    "local_write": False,
                    "external_write": "deny",
                    "destructive": "deny",
                }
                anchor["skills"] = {"allow": ["*"], "deny": []}
                anchor["mcp"] = {
                    "allow_servers": [],
                    "allow_tools": [],
                    "local_servers": ["sulde-kb"],
                    "unknown_effect": "deny",
                }
                anchor["continuation"] = {"grants": []}
                record = {
                    **subject,
                    "release_id": release_id,
                    "release_subject_sha256": release_id,
                    "status": "pending",
                    "released_at": now_iso(),
                    "completed_at": "",
                    "completion_evidence_sha256": "",
                }
                anchor["workspace_cleanup"] = record
                _write_contract_unlocked(anchor_path, anchor)
        # CAS the exact mapping observed before publishing the new route.
        latest = load_session_workspace(home, selected_provider, selected_session)
        if latest is None or latest.get("mapping_sha256") != current.get("mapping_sha256"):
            raise IntentGuardianError("workspace release session mapping changed concurrently")
        mapping = _write_mapping(
            home,
            {
                "schema": SESSION_WORKSPACE_SCHEMA,
                "provider": selected_provider,
                "session_id": selected_session,
                "contract_path": str(anchor_path),
                **target_identity,
                "source_contract_path": str(source_path),
                "bound_at": now_iso(),
            },
        )
        _close_released_source(
            source_path,
            provider=selected_provider,
            session_id=selected_session,
            release_id=release_id,
            anchor_path=anchor_path,
        )

        lineage_recorded = record_transition(
            home, provider=selected_provider, session_id=selected_session,
            source_workspace=source_identity["workspace_root"],
            mapping=mapping, receipt_id=release_id,
        )
        return {
            "schema": "sulde-workspace-release-result-v1",
            "lifecycle_lineage_recorded": lineage_recorded,
            "status": "pending",
            "authority_transferred": False,
            "git_mutation_performed": False,
            "completion_contract": str(anchor_path),
            "mapping": mapping,
            "cleanup": workspace_cleanup_status(load_contract(anchor_path)),
        }


def finalize_workspace_cleanup(
    home: Path,
    completion_contract_path: Path,
    *,
    provider: str,
    session_id: str,
) -> dict[str, Any]:
    """Seal cleanup only after Git and filesystem observations prove completion."""
    selected_provider = provider.strip().lower()
    selected_session = session_id.strip()
    anchor_path = completion_contract_path.expanduser().resolve()
    mapping_path = session_workspace_path(home, selected_provider, selected_session)
    lock_path = mapping_path.with_name(f".{mapping_path.name}.release.lock")
    with _exclusive_path_lock(lock_path):
        mapping = load_session_workspace(home, selected_provider, selected_session)
        if mapping is None or Path(mapping["contract_path"]).resolve() != anchor_path:
            raise IntentGuardianError(
                "workspace cleanup finalization requires the current completion anchor"
            )
        with contract_lock(anchor_path):
            anchor = load_contract(anchor_path)
            record = _cleanup_record(anchor)
            if record is None:
                raise IntentGuardianError("completion contract lacks workspace cleanup record")
            if (
                record["provider"] != selected_provider
                or record["session_id"] != selected_session
            ):
                raise IntentGuardianError("workspace cleanup belongs to another session")
            if record["status"] == "complete":
                return {
                    "schema": "sulde-workspace-cleanup-result-v1",
                    "status": "complete",
                    "idempotent": True,
                    "cleanup": workspace_cleanup_status(anchor),
                }
            target = Path(record["target_workspace"]).expanduser().resolve()
            source = Path(record["source_workspace"]).expanduser().resolve()
            if source in _registered_worktree_roots(target):
                raise IntentGuardianError("source worktree is still registered")
            if source.exists():
                raise IntentGuardianError("source workspace path still exists")
            if _local_branch_exists(target, str(record["source_branch"])):
                raise IntentGuardianError("source task branch still exists")
            evidence = {
                "release_id": record["release_id"],
                "source_workspace_exists": False,
                "source_worktree_registered": False,
                "source_branch_exists": False,
            }
            record["status"] = "complete"
            record["completed_at"] = now_iso()
            record["completion_evidence_sha256"] = _canonical_sha256(evidence)
            anchor["workspace_cleanup"] = record
            anchor["runtime"]["host_observations"].append(
                {
                    "event": "workspace_cleanup",
                    "provider": selected_provider,
                    "session_id": selected_session,
                    "source": "agent_git_readback",
                    "status": "complete",
                    "release_id": record["release_id"],
                    "evidence_sha256": record["completion_evidence_sha256"],
                    "authority_transferred": False,
                    "at": now_iso(),
                }
            )
            anchor["runtime"]["host_observations"] = anchor["runtime"][
                "host_observations"
            ][-100:]
            _write_contract_unlocked(anchor_path, anchor)
        return {
            "schema": "sulde-workspace-cleanup-result-v1",
            "status": "complete",
            "idempotent": False,
            "cleanup": workspace_cleanup_status(load_contract(anchor_path)),
        }
