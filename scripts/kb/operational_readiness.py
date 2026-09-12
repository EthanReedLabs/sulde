#!/usr/bin/env python3
"""Project one fail-closed operational truth from contract, host, and effect facts."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any, Callable

from approval_invariant import (
    ApprovalInvariantError,
    load_projection as load_approval_projection,
)
from approval_timeout_policy import request_phase as approval_request_phase
from host_capabilities import readiness_projection, workspace_identifier
from intervention import (
    InterventionError,
    blocking_attempts,
    is_legacy_git_control_attempt,
    load_projection,
    readiness_blocking_attempts,
    terminal_quarantined_attempts,
)
from intent_guardian_parts.pre_execution_proof import (
    PROOF_FIELDS,
    PROOF_SCHEMA,
    proof_id as pre_execution_proof_id,
)
from native_decision_journal import (
    NativeDecisionJournalError,
    load_projection_read_only as load_native_decision_projection,
    verify_recorded_external_head_receipt,
)
from session_continuity import ContinuationError, continuation_path, load_capsule
try:
    from native_decision_journal import head_proof_read_only as load_native_head_proof
except ImportError:
    # A partial/older runtime without this diagnostic API stays unavailable;
    # never fall back to a mutating recovery reader or synthesize a head.
    def load_native_head_proof(_contract_path: Path) -> dict[str, Any]:
        raise NativeDecisionJournalError("T03 journal head proof unavailable")
from task_ownership import task_lane


SCHEMA = "sulde-operational-readiness-v1"
DEPLOYMENT_GENERATION_NAME = "deployment-generation.json"
RUNTIME_OWNER_NAME = "runtime-owner.json"
ELIGIBLE_DEPLOYMENT_STATES = {
    "installed_live_unverified",
    "active",
    "generation_verified",
}
NATIVE_HEAD_PROOF_SCHEMA = "sulde-native-decision-journal-head-proof-v2"
NATIVE_CURRENT_BINDING_SCHEMA = "sulde-native-transaction-binding-v5"
EXTERNAL_AUTHORITY_PROOF_SCHEMA = "sulde-t06-external-authority-proof-v1"
NATIVE_HEAD_PROOF_FIELDS = {
    "schema",
    "contract_sha256",
    "generation",
    "sequence",
    "event_id",
    "event_sha256",
    "journal_sha256",
    "anchor_sha256",
    "local_consistency_verified",
    "external_authority_verified",
    "external_authority_status",
    "recovery_status",
    "external_anchor_required",
    "external_anchor_boundary",
    "proof_sha256",
}


def _read_json_object(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError):
        return None
    return value if isinstance(value, dict) else None


def _pending_proposal_requires_current_lane(
    contract_path: Path | None,
    contract: dict[str, Any] | None,
    *,
    provider: str | None,
    session_id: str,
    current_lane: dict[str, Any] | None,
) -> bool:
    """Scope a pending next-revision question to the lane that created it.

    A bound sibling lane remains ready for the already approved task. Missing
    or invalid capsule provenance stays fail-closed because the proposal owner
    then cannot be proved.
    """
    if contract_path is None or not isinstance(contract, dict):
        return False
    runtime = contract.get("runtime") if isinstance(contract.get("runtime"), dict) else {}
    digest = str(runtime.get("pending_proposal_digest") or "")
    if not digest:
        return False
    if not isinstance(current_lane, dict) or current_lane.get("state") != "bound":
        return True
    try:
        capsule = load_capsule(continuation_path(contract_path, digest))
    except (ContinuationError, OSError, UnicodeError, ValueError):
        return True
    source = capsule.get("source") if isinstance(capsule.get("source"), dict) else {}
    return bool(
        str(source.get("provider") or "") == str(provider or "").strip().lower()
        and str(source.get("session_id") or "") == session_id.strip()
    )


def _scheduler_inventory_sha256(
    managed: set[str],
    retired: set[str],
) -> str:
    payload = "managed\0" + "\0".join(sorted(managed))
    payload += "\nretired\0" + "\0".join(sorted(retired))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def scheduler_process_projection(
    home_or_owner: Path | dict[str, Any],
    *,
    platform_name: str | None = None,
    launchctl_list_output: str | None = None,
    runner: Callable[..., Any] | None = None,
    aqua_session_available: bool | None = None,
) -> dict[str, Any]:
    """Observe only minimal launchd list truth for the persisted actor set.

    No job detail or environment command is permitted here. A non-Darwin host,
    unavailable user bootstrap domain, timeout, non-zero exit, missing actor,
    failed last exit, or loaded retired actor stays fail closed.
    """
    if isinstance(home_or_owner, dict):
        source = home_or_owner
        owner = {
            "status": source.get("status", source.get("runtime_owner_status")),
            "executable": source.get("executable") or (
                "available-runtime"
                if source.get("runtime_available") is True
                else ""
            ),
            "scheduler": source.get("scheduler", source.get("runtime_scheduler")),
            "managed_labels": source.get(
                "managed_labels", source.get("runtime_managed_labels")
            ),
            "retired_labels": source.get(
                "retired_labels", source.get("runtime_retired_labels")
            ),
        }
        explicit_available = source.get("runtime_available")
    else:
        owner = _read_json_object(
            home_or_owner.expanduser() / RUNTIME_OWNER_NAME
        ) or {}
        explicit_available = None
    managed_values = owner.get("managed_labels")
    retired_values = owner.get("retired_labels")
    managed = {
        str(label)
        for label in (managed_values if isinstance(managed_values, list) else [])
        if str(label).startswith("com.sulde.")
    }
    retired = {
        str(label)
        for label in (retired_values if isinstance(retired_values, list) else [])
        if str(label).startswith("com.sulde.")
    }
    inventory_sha256 = _scheduler_inventory_sha256(managed, retired)
    executable = str(owner.get("executable") or "")
    executable_available = (
        explicit_available is True
        if explicit_available is not None
        else bool(
            executable
            and (
                Path(executable).expanduser().is_file()
                or shutil.which(executable) is not None
            )
        )
    )
    reasons: list[str] = []
    if owner.get("status") != "active":
        reasons.append("runtime_owner_not_active")
    if not executable_available:
        reasons.append("runtime_provider_unavailable")
    if not managed:
        reasons.append("managed_actor_inventory_missing")
    selected_platform = platform_name or sys.platform
    if owner.get("scheduler") != "launchd" or selected_platform not in {
        "darwin",
        "Darwin",
    }:
        reasons.append("launchd_runtime_unavailable")
        return {
            "status": "degraded",
            "probe_status": "unobserved",
            "reasons": list(dict.fromkeys(reasons)),
            "managed": len(managed),
            "loaded": None,
            "missing_labels": [],
            "missing_observed": False,
            "failed_labels": {},
            "retired_loaded_labels": [],
            "inventory_sha256": inventory_sha256,
            "authority": "launchctl_list_process_truth",
        }
    if launchctl_list_output is None:
        if runner is None and os.environ.get("SULDE_TEST_MODE", "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }:
            reasons.append("scheduler_probe_not_injected")
            return {
                "status": "degraded",
                "probe_status": "unobserved",
                "reasons": list(dict.fromkeys(reasons)),
                "managed": len(managed),
                "loaded": None,
                "missing_labels": [],
                "missing_observed": False,
                "failed_labels": {},
                "retired_loaded_labels": [],
                "inventory_sha256": inventory_sha256,
                "authority": "launchctl_list_process_truth",
            }
        if aqua_session_available is None:
            try:
                aqua_session_available = bool(
                    os.getuid() != 0
                    and Path("/dev/console").stat().st_uid == os.getuid()
                )
            except (AttributeError, OSError):
                aqua_session_available = False
        if aqua_session_available is not True:
            reasons.append("aqua_user_domain_unavailable")
            return {
                "status": "degraded",
                "probe_status": "unobserved",
                "reasons": list(dict.fromkeys(reasons)),
                "managed": len(managed),
                "loaded": None,
                "missing_labels": [],
                "missing_observed": False,
                "failed_labels": {},
                "retired_loaded_labels": [],
                "inventory_sha256": inventory_sha256,
                "authority": "launchctl_list_process_truth",
            }
        selected_runner = runner or subprocess.run
        try:
            completed = selected_runner(
                ["launchctl", "list"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired, TypeError, ValueError):
            completed = None
        if completed is None or getattr(completed, "returncode", None) != 0:
            reasons.append("launchctl_list_unavailable")
            return {
                "status": "degraded",
                "probe_status": "unobserved",
                "reasons": list(dict.fromkeys(reasons)),
                "managed": len(managed),
                "loaded": None,
                "missing_labels": [],
                "missing_observed": False,
                "failed_labels": {},
                "retired_loaded_labels": [],
                "inventory_sha256": inventory_sha256,
                "authority": "launchctl_list_process_truth",
            }
        stdout = getattr(completed, "stdout", None)
        if not isinstance(stdout, str):
            reasons.append("launchctl_list_unavailable")
            stdout = ""
        launchctl_list_output = stdout
    if not isinstance(launchctl_list_output, str):
        reasons.append("launchctl_list_unavailable")
        launchctl_list_output = ""
    loaded: dict[str, tuple[str, str]] = {}
    observed_labels = managed | retired
    for line in launchctl_list_output.splitlines():
        fields = line.split()
        if len(fields) >= 3 and fields[-1] in observed_labels:
            loaded[fields[-1]] = (fields[0], fields[1])
    missing = sorted(managed - loaded.keys())
    failed = {
        label: status
        for label, (pid, status) in loaded.items()
        # launchctl retains the previous exit status while an actor is running.
        # Treating that historical value as the current result makes a
        # self-observing actor permanently fail after one degraded cycle.
        if label in managed and pid == "-" and status not in {"-", "0"}
    }
    retired_loaded = sorted(retired & loaded.keys())
    if missing:
        reasons.append("managed_actors_missing")
    if failed:
        reasons.append("managed_actor_last_exit_nonzero")
    if retired_loaded:
        reasons.append("retired_actors_loaded")
    return {
        "status": "ready" if not reasons else "degraded",
        "probe_status": "observed",
        "reasons": list(dict.fromkeys(reasons)),
        "managed": len(managed),
        "loaded": len(managed & loaded.keys()),
        "missing_labels": missing,
        "missing_observed": True,
        "failed_labels": failed,
        "retired_loaded_labels": retired_loaded,
        "inventory_sha256": inventory_sha256,
        "authority": "launchctl_list_process_truth",
    }


def runtime_tree_digest(root: Path) -> str:
    """Hash the immutable runtime using the installer/scheduler algorithm."""
    selected = root.expanduser().resolve()
    if not selected.is_dir():
        raise OSError(f"runtime tree is missing: {selected}")
    digest = hashlib.sha256()
    for path in sorted(selected.rglob("*")):
        if not path.is_file():
            continue
        if "__pycache__" in path.parts or path.suffix == ".pyc" or path.name == ".DS_Store":
            continue
        relative = path.relative_to(selected).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def _resolved_path(value: Any) -> Path | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return Path(text).expanduser().resolve()
    except (OSError, RuntimeError, ValueError):
        return None


def _execution_runtime_root() -> Path:
    configured = os.environ.get("SULDE_RUNTIME_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(__file__).resolve().parents[2]


def _module_runtime_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _guardian_module_generation(runtime_root: Path) -> str:
    path = runtime_root / "scripts/kb/intent_guardian_parts/state.py"
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def _deployment_readiness(
    home: Path,
    provider: str | None,
    scheduler_probe: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate artifact bytes and scheduler ownership as distinct domains."""
    deployment_path = home / DEPLOYMENT_GENERATION_NAME
    owner_path = home / RUNTIME_OWNER_NAME
    deployment = _read_json_object(deployment_path)
    owner = _read_json_object(owner_path)
    deployment_root = _resolved_path((deployment or {}).get("runtime_root"))
    owner_root = _resolved_path((owner or {}).get("runtime_root"))
    execution_root = _execution_runtime_root()
    module_root = _module_runtime_root()
    isolated_test_override = (
        os.environ.get("SULDE_TEST_MODE", "").strip().lower()
        in {"1", "true", "yes", "on"}
    )
    actual_digest = ""
    digest_error = ""
    try:
        actual_digest = runtime_tree_digest(execution_root)
    except (OSError, RuntimeError, ValueError) as error:
        digest_error = type(error).__name__

    deployment_generation = str((deployment or {}).get("generation") or "")
    owner_generation = str((owner or {}).get("generation") or "")
    deployment_digest = str((deployment or {}).get("runtime_tree_sha256") or "")
    owner_digest = str((owner or {}).get("runtime_tree_sha256") or "")
    deployment_labels = (deployment or {}).get("managed_labels")
    owner_labels = (owner or {}).get("managed_labels")
    owner_retired_labels = (owner or {}).get("retired_labels")
    expected_managed = {
        str(value)
        for value in (owner_labels if isinstance(owner_labels, list) else [])
    }
    expected_retired = {
        str(value)
        for value in (
            owner_retired_labels if isinstance(owner_retired_labels, list) else []
        )
    }
    expected_inventory_sha256 = _scheduler_inventory_sha256(
        expected_managed,
        expected_retired,
    )
    executable = str((owner or {}).get("executable") or "")
    executable_available = bool(
        executable
        and (
            Path(executable).expanduser().is_file()
            or shutil.which(executable) is not None
        )
    )
    environment_generation = str(os.environ.get("SULDE_RUNTIME_GENERATION") or "")
    loaded_module_generation = _guardian_module_generation(execution_root)
    artifact_gates = {
        "deployment_generation_present": deployment is not None,
        "deployment_state_eligible": bool(
            deployment
            and str(deployment.get("status") or "") in ELIGIBLE_DEPLOYMENT_STATES
        ),
        "deployment_runtime_root_matches": bool(
            deployment_root is not None and deployment_root == execution_root
        ),
        "executing_module_matches_runtime": bool(
            module_root == execution_root or isolated_test_override
        ),
        "deployment_tree_digest_matches": bool(
            actual_digest and deployment_digest == actual_digest
        ),
        "deployment_generation_matches_tree": bool(
            deployment_generation
            and deployment_generation.endswith(f":{actual_digest}")
        ),
        "loaded_guardian_module_present": bool(loaded_module_generation),
    }
    artifact_reasons = [name for name, passed in artifact_gates.items() if not passed]
    if digest_error:
        artifact_reasons.append(f"runtime_tree_digest_error:{digest_error}")
    artifact = {
        "status": "ready" if all(artifact_gates.values()) else "degraded",
        "gates": artifact_gates,
        "reasons": artifact_reasons,
        "deployment_status": str((deployment or {}).get("status") or "missing"),
        "generation": deployment_generation or None,
        "runtime_root": str(execution_root),
        "executing_module_root": str(module_root),
        "runtime_tree_sha256": actual_digest or None,
        "loaded_module_generation": loaded_module_generation or None,
        "authority": "immutable_artifact_generation",
    }

    gates = {
        "artifact_generation_ready": artifact["status"] == "ready",
        "runtime_owner_present": owner is not None,
        "runtime_owner_active": bool(owner and owner.get("status") == "active"),
        "provider_matches": bool(
            deployment
            and owner
            and deployment.get("provider") == owner.get("provider")
        ),
        "runtime_root_matches": bool(
            deployment_root is not None
            and owner_root is not None
            and deployment_root == owner_root == execution_root
        ),
        "runtime_tree_digest_matches": bool(
            actual_digest
            and deployment_digest == owner_digest == actual_digest
        ),
        "generation_matches": bool(
            deployment_generation
            and deployment_generation == owner_generation
            and deployment_generation.endswith(f":{actual_digest}")
        ),
        "environment_generation_matches": bool(
            not environment_generation
            or environment_generation == deployment_generation
        ),
        "managed_actor_inventory_matches": bool(
            isinstance(deployment_labels, list)
            and bool(deployment_labels)
            and isinstance(owner_labels, list)
            and sorted(str(value) for value in deployment_labels)
            == sorted(str(value) for value in owner_labels)
        ),
        "runtime_executable_available": executable_available,
        "scheduler_process_ready": bool(
            isinstance(scheduler_probe, dict)
            and scheduler_probe.get("status") == "ready"
            and scheduler_probe.get("probe_status") == "observed"
            and scheduler_probe.get("managed") == len(expected_managed)
            and scheduler_probe.get("loaded") == len(expected_managed)
            and scheduler_probe.get("missing_labels") == []
            and scheduler_probe.get("failed_labels") == {}
            and scheduler_probe.get("retired_loaded_labels") == []
            and scheduler_probe.get("inventory_sha256")
            == expected_inventory_sha256
        ),
    }
    reasons = [name for name, passed in gates.items() if not passed]
    reasons.extend(
        reason
        for reason in artifact_reasons
        if reason not in reasons
    )
    if scheduler_probe is None:
        reasons.append("scheduler_probe:unobserved")
    elif scheduler_probe.get("status") != "ready":
        probe_reasons = scheduler_probe.get("reasons")
        reasons.extend(
            f"scheduler_probe:{reason}"
            for reason in (probe_reasons if isinstance(probe_reasons, list) else [])
        )
    scheduler = {
        "status": "ready" if all(gates.values()) else "degraded",
        "gates": gates,
        "reasons": reasons,
        "deployment_status": str((deployment or {}).get("status") or "missing"),
        "runtime_owner_status": str((owner or {}).get("status") or "missing"),
        "provider": str((owner or {}).get("provider") or provider or "unknown"),
        "generation": deployment_generation or None,
        "runtime_root": str(execution_root),
        "executing_module_root": str(module_root),
        "runtime_tree_sha256": actual_digest or None,
        "telemetry_authority": "delivery_integrity_only",
        "process_probe": scheduler_probe,
    }
    return artifact, scheduler


def _provider(value: str | None, home: Path) -> str | None:
    candidate = str(
        value
        or os.environ.get("SULDE_HOST_PROVIDER")
        or os.environ.get("SULDE_LLM_PROVIDER")
        or ""
    ).strip().lower()
    if candidate in {"claude", "codex"}:
        return candidate
    try:
        owner = json.loads((home / "runtime-owner.json").read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError):
        return None
    candidate = str(owner.get("provider") or "").strip().lower()
    return candidate if candidate in {"claude", "codex"} else None


def _session_id(value: str | None, provider: str | None) -> str:
    if value:
        return value.strip()
    candidates = [os.environ.get("SULDE_HOST_SESSION_ID")]
    if provider == "codex":
        candidates.append(os.environ.get("CODEX_THREAD_ID"))
    elif provider == "claude":
        candidates.append(os.environ.get("CLAUDE_SESSION_ID"))
    return next((str(item).strip() for item in candidates if str(item or "").strip()), "")


def _workspace(value: Path | str | None, session_id: str) -> Path | str | None:
    if value is not None and str(value).strip():
        return value
    configured = os.environ.get("SULDE_WORKSPACE_ROOT")
    if configured:
        return configured
    # A background scheduler's cwd is not an interactive workspace fact.
    return os.getcwd() if session_id else None


def _contract_path(home: Path, workspace: Path | str | None) -> Path | None:
    if workspace is None:
        return None
    identifier = workspace_identifier(workspace)
    if not identifier.startswith("sha256:"):
        return None
    return home / "intent" / "workspaces" / f"{identifier.split(':', 1)[1]}.active.json"


def _read_contract(path: Path | None) -> tuple[dict[str, Any] | None, str | None]:
    if path is None:
        return None, "workspace_context_missing"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, "active_contract_missing"
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None, "active_contract_invalid"
    if not isinstance(value, dict) or not str(value.get("intent_id") or ""):
        return None, "active_contract_invalid"
    return value, None


def _diagnostic_contract(
    home: Path,
    *,
    provider: str | None,
    session_id: str,
    workspace: Path | str | None,
    resolved_contract_path: Path | None,
    workspace_explicit: bool,
) -> tuple[Path | None, dict[str, Any] | None, str | None, Path | str | None]:
    """Select one read-only contract context, never borrowing a sibling's truth.

    Doctor passes the path it already resolved, pinning all domains to that
    selection even if a concurrent handoff changes the session mapping. Other
    consumers use the same validated session resolver as the live Guardian.
    This path selects diagnostic facts; it is not execution authority.
    """
    path = resolved_contract_path
    if path is None and provider and session_id:
        # state imports this module; importing its routing consumer at module
        # load time would introduce an operational_readiness -> state cycle.
        from intent_guardian_parts.decision_types import IntentGuardianError
        from intent_guardian_parts.session_workspace import resolve_session_contract

        try:
            path = resolve_session_contract(home, provider, session_id)
        except (IntentGuardianError, OSError, ValueError, TypeError, RuntimeError):
            return None, None, "session_contract_invalid", workspace
    session_selected = path is not None
    if path is None:
        # Compatibility only when there is no session-specific routing target.
        path = _contract_path(home, workspace)
    contract, error = _read_contract(path)
    if session_selected and contract is not None:
        root = contract.get("workspace_root")
        if not isinstance(root, str) or not root.strip():
            return path, None, "session_contract_invalid", workspace
        try:
            if not workspace_explicit:
                # Status/LIFE callers may have only a launch-time cwd or env
                # hint. A valid current-session mapping owns that context.
                workspace = Path(root).expanduser().resolve()
            matches = workspace is not None and (
                Path(root).expanduser().resolve()
                == Path(workspace).expanduser().resolve()
            )
        except (OSError, ValueError, TypeError, RuntimeError):
            return path, None, "session_contract_invalid", workspace
        if not matches:
            return path, None, "session_contract_workspace_mismatch", workspace
    return path, contract, error, workspace


def _current_pre_execution_proof(
    runtime: dict[str, Any],
    *,
    provider: str | None,
    session_id: str,
    loaded_module_generation: str,
    artifact_generation: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Return the last lane proof and the last sealed current-generation proof."""
    rows = runtime.get("pre_execution_proofs")
    proofs = rows if isinstance(rows, list) else []
    lane_proofs = [
        row
        for row in proofs
        if isinstance(row, dict)
        and str(row.get("provider") or "") == str(provider or "")
        and str(row.get("session_id") or "") == session_id
    ]
    last_proof = lane_proofs[-1] if lane_proofs else None
    for row in reversed(lane_proofs):
        material = {key: row.get(key) for key in PROOF_FIELDS if key != "proof_id"}
        if (
            set(row) == PROOF_FIELDS
            and row.get("schema") == PROOF_SCHEMA
            and str(row.get("runtime_generation") or "")
            == loaded_module_generation
            and str(row.get("loaded_module_generation") or "")
            == loaded_module_generation
            and str(row.get("artifact_generation") or "")
            == artifact_generation
            and str(row.get("proof_id") or "") == pre_execution_proof_id(material)
        ):
            return last_proof, row
    return last_proof, None


def _current_effect_truth(
    contract_path: Path | None,
    contract: dict[str, Any] | None,
) -> dict[str, Any]:
    if contract_path is None or contract is None:
        return {
            "status": "unavailable",
            "blocking": None,
            "interventions_open": None,
            "pending_verifications": None,
            "error": "active_contract_unavailable",
        }
    try:
        projection = load_projection(contract_path)
        authoritative_blocking_rows = blocking_attempts(projection)
        blocking_rows = readiness_blocking_attempts(projection)
        quarantined_rows = terminal_quarantined_attempts(projection)
        blocking = len(blocking_rows)
        blocking_ids = {
            str(row.get("attempt_id") or "")
            for row in blocking_rows
            if str(row.get("attempt_id") or "")
        }
        quarantined_ids = {
            str(row.get("attempt_id") or "")
            for row in quarantined_rows
            if str(row.get("attempt_id") or "")
        }
        attempts = projection.get("attempts", {})
        interventions = sum(
            1
            for row in projection.get("interventions", {}).values()
            if isinstance(row, dict) and row.get("status") in {"open", "acknowledged"}
            and not is_legacy_git_control_attempt(
                attempts.get(str(row.get("attempt_id") or ""), {})
            )
        )
    except (InterventionError, OSError, UnicodeError, ValueError) as error:
        return {
            "status": "invalid",
            "blocking": None,
            "interventions_open": None,
            "pending_verifications": None,
            "error": type(error).__name__,
        }
    runtime = contract.get("runtime") if isinstance(contract.get("runtime"), dict) else {}
    pending = runtime.get("pending_verifications")
    pending_rows = [
        row for row in (pending if isinstance(pending, list) else [])
        if isinstance(row, dict)
    ]
    # Debt survives task/revision changes. Derived pending rows disappear from
    # the current-lane gate only through authoritative settlement or explicit
    # terminal quarantine; the latter must never be reported as settlement.
    # A missing attempt remains unknown and therefore blocking.
    unsettled_pending = []
    authoritative_settled = 0
    terminal_quarantined_pending = 0
    for row in pending_rows:
        attempt_id = str(row.get("attempt_id") or "")
        if attempt_id and attempt_id in attempts and attempt_id in quarantined_ids:
            terminal_quarantined_pending += 1
            continue
        if attempt_id and attempt_id in attempts and attempt_id not in blocking_ids:
            authoritative_settled += 1
            continue
        unsettled_pending.append(row)
    pending_count = len(unsettled_pending)
    return {
        "status": "clear" if not blocking and not interventions and not pending_count else "blocked",
        "blocking": blocking,
        "authoritative_blocking": len(authoritative_blocking_rows),
        "terminal_quarantined": len(quarantined_rows),
        "interventions_open": interventions,
        "pending_verifications": pending_count,
        "pending_verifications_total": len(pending_rows),
        "authoritative_settled_pending": authoritative_settled,
        "terminal_quarantined_pending": terminal_quarantined_pending,
        "error": None,
    }


def _sha256_text(value: Any) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8", errors="replace")).hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _is_sha256(value: Any) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _lane_sha256(provider: str | None, session_id: str) -> str:
    if not session_id:
        return ""
    return _sha256_text(f"{str(provider or 'unknown').lower()}\0{session_id}")


def _current_proposal_digest(
    contract: dict[str, Any],
    current_lane: dict[str, Any] | None,
) -> str:
    runtime = (
        contract.get("runtime")
        if isinstance(contract.get("runtime"), dict)
        else {}
    )
    pending = str(runtime.get("pending_proposal_digest") or "").lower()
    if _is_sha256(pending):
        return pending
    lane_digest = str((current_lane or {}).get("proposal_digest") or "").lower()
    return lane_digest if _is_sha256(lane_digest) else ""


def _binding_base_matches(
    binding: dict[str, Any],
    *,
    expected_workspace_path: Path | None,
    expected_intent_id: str,
    expected_revision: int,
    expected_provider: str,
    expected_session_id: str,
) -> bool:
    return bool(
        expected_workspace_path is not None
        and _resolved_path(binding.get("workspace")) == expected_workspace_path
        and binding.get("intent_id") == expected_intent_id
        and int(binding.get("intent_revision") or 0) == expected_revision
        and binding.get("provider") == expected_provider
        and binding.get("session_id") == expected_session_id
    )


def _binding_is_exact_current(
    binding: dict[str, Any],
    *,
    contract: dict[str, Any],
    current_lane: dict[str, Any] | None,
    lanes_present: bool,
    expected_workspace_path: Path | None,
    expected_provider: str,
    expected_session_id: str,
    expected_proposal_digest: str,
) -> bool:
    if not _binding_base_matches(
        binding,
        expected_workspace_path=expected_workspace_path,
        expected_intent_id=str(contract.get("intent_id") or ""),
        expected_revision=int(contract.get("revision") or 0),
        expected_provider=expected_provider,
        expected_session_id=expected_session_id,
    ):
        return False

    # New authority binds the transaction to the current task epoch.  Historical
    # v1/v3 rows remain replayable, but cannot become current authority merely
    # because provider/session/revision values happen to match again.
    if binding.get("schema") == NATIVE_CURRENT_BINDING_SCHEMA:
        if binding.get("task_epoch") != str(contract.get("task_epoch") or ""):
            return False
    elif lanes_present:
        return False

    # A scoped contract must have the exact current lane and proposal target.
    # Legacy contracts without task lanes retain their read-only compatibility
    # projection until the control plane upgrades them.
    if lanes_present:
        if not isinstance(current_lane, dict) or not expected_proposal_digest:
            return False
        if (
            binding.get("approval_kind") == "proposal"
            and binding.get("target") != expected_proposal_digest
        ):
            return False
    elif (
        expected_proposal_digest
        and binding.get("approval_kind") == "proposal"
        and binding.get("target") != expected_proposal_digest
    ):
        return False
    return True


def _request_is_exact_current(
    row: dict[str, Any],
    *,
    expected_workspace: str,
    expected_intent: str,
    expected_revision: int,
    expected_provider: str,
    expected_lane: str,
    expected_proposal_digest: str,
    lanes_present: bool,
    current_lane: dict[str, Any] | None,
) -> bool:
    if not (
        row.get("workspace_sha256") == expected_workspace
        and row.get("intent_id_sha256") == expected_intent
        and int(row.get("intent_revision") or 0) == expected_revision
        and row.get("provider") == expected_provider
        and row.get("lane_sha256") == expected_lane
    ):
        return False
    if lanes_present and (
        not isinstance(current_lane, dict) or not expected_proposal_digest
    ):
        return False
    return bool(
        not expected_proposal_digest
        or row.get("kind") != "proposal"
        or row.get("target_sha256") == _sha256_text(expected_proposal_digest)
    )


def _workspace_sha256(workspace: Path | str | None) -> str:
    if workspace is None or not str(workspace).strip():
        return ""
    resolved = _resolved_path(workspace)
    return _sha256_text(resolved if resolved is not None else workspace)


def _validated_native_head_proof(contract_path: Path) -> dict[str, Any]:
    proof = load_native_head_proof(contract_path)
    if type(proof) is not dict or set(proof) != NATIVE_HEAD_PROOF_FIELDS:
        raise NativeDecisionJournalError("native journal head proof fields invalid")
    if (
        proof.get("schema") != NATIVE_HEAD_PROOF_SCHEMA
        or type(proof.get("generation")) is not int
        or type(proof.get("sequence")) is not int
        or proof["generation"] < 0
        or proof["sequence"] < 0
        or proof["generation"] != proof["sequence"]
        or proof.get("local_consistency_verified") is not True
        or proof.get("external_authority_verified") is not False
        or proof.get("external_authority_status")
        != "external_authority_unverified"
        or proof.get("external_anchor_required") is not True
        or type(proof.get("external_anchor_boundary")) is not str
        or not proof["external_anchor_boundary"]
        or any(
            not _is_sha256(proof.get(field))
            for field in (
                "contract_sha256",
                "event_id",
                "event_sha256",
                "journal_sha256",
                "anchor_sha256",
                "proof_sha256",
            )
        )
        or proof.get("event_id") != proof.get("event_sha256")
    ):
        raise NativeDecisionJournalError("native journal head proof values invalid")
    expected_digest = hashlib.sha256(
        _canonical_json(
            {key: value for key, value in proof.items() if key != "proof_sha256"}
        ).encode("utf-8")
    ).hexdigest()
    if proof["proof_sha256"] != expected_digest:
        raise NativeDecisionJournalError("native journal head proof digest invalid")
    return dict(proof)


def _external_authority_query(
    *,
    head: dict[str, Any],
    binding: dict[str, Any],
    transaction_id: str,
    workspace_sha256: str,
    provider: str,
    session_id: str,
    intent_id_sha256: str,
    intent_revision: int,
) -> dict[str, Any]:
    return {
        "contract_sha256": head["contract_sha256"],
        "workspace_sha256": workspace_sha256,
        "provider": provider,
        "session_id_sha256": _sha256_text(session_id),
        "intent_id_sha256": intent_id_sha256,
        "intent_revision": intent_revision,
        "request_id": str(binding.get("request_id") or ""),
        "card_sha256": str(binding.get("card_sha256") or ""),
        "target_sha256": _sha256_text(binding.get("target")),
        "transaction_id": transaction_id,
        "transaction_binding_sha256": hashlib.sha256(
            _canonical_json(binding).encode("utf-8")
        ).hexdigest(),
        "journal_head_proof_sha256": head["proof_sha256"],
    }


def _external_authority_matches(
    proof: Any,
    *,
    query: dict[str, Any],
    head: dict[str, Any],
) -> bool:
    expected_fields = {"schema", "journal_head_proof", *query.keys()}
    if type(proof) is not dict or set(proof) != expected_fields:
        return False
    if proof.get("schema") != EXTERNAL_AUTHORITY_PROOF_SCHEMA:
        return False
    if proof.get("journal_head_proof") != head:
        return False
    return all(proof.get(key) == value for key, value in query.items())


def _native_decision_truth(
    contract_path: Path | None,
    contract: dict[str, Any] | None,
    *,
    provider: str | None,
    session_id: str,
    workspace: Path | str | None,
    current_lane: dict[str, Any] | None,
    approval_required: bool,
    external_authority_reader: Callable[[dict[str, Any]], Any] | None,
    now: datetime | None,
) -> dict[str, Any]:
    """Replay durable request and native CAS journals for the current lane.

    PermissionRequest observations and their HMAC provenance are intentionally
    absent here: they are telemetry, while these two append-only stores are the
    pairing truth that can settle a human decision.
    """
    empty = {
        "status": "unavailable",
        "settled": False,
        "awaiting_human": 0,
        "reassess_due": 0,
        "expired": 0,
        "cas_mismatch": 0,
        "unsettled": 0,
        "paired_committed": 0,
        "request_scope": {
            "current_active": 0,
            "other_lane_active": 0,
            "historical_active": 0,
            "terminal": 0,
        },
        "transaction_scope": {
            "current_active": 0,
            "other_lane_active": 0,
            "historical_active": 0,
            "terminal": 0,
            "malformed": 0,
        },
        "external_authority_queries": [],
        "reasons": ["active_contract_unavailable"],
        "authority": "approval_pair_and_native_decision_cas",
    }
    if contract_path is None or contract is None:
        return empty
    try:
        approvals = load_approval_projection(contract_path)
        native = load_native_decision_projection(contract_path)
    except (
        ApprovalInvariantError,
        NativeDecisionJournalError,
        OSError,
        UnicodeError,
        ValueError,
    ) as error:
        return {
            **empty,
            "status": "cas_mismatch",
            "cas_mismatch": 1,
            "reasons": [f"decision_journal_invalid:{type(error).__name__}"],
        }

    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        current = current.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)
    expected_provider = str(provider or "unknown").lower()
    expected_lane = _lane_sha256(expected_provider, session_id)
    expected_workspace = _workspace_sha256(workspace)
    expected_intent = _sha256_text(contract.get("intent_id"))
    expected_revision = int(contract.get("revision") or 0)
    expected_workspace_path = _resolved_path(workspace)
    runtime = (
        contract.get("runtime")
        if isinstance(contract.get("runtime"), dict)
        else {}
    )
    lanes_present = bool(
        isinstance(runtime.get("task_lanes"), list)
        and runtime.get("task_lanes")
    )
    expected_proposal_digest = _current_proposal_digest(contract, current_lane)
    try:
        native_head = _validated_native_head_proof(contract_path)
        native_head_error = ""
    except (
        NativeDecisionJournalError,
        OSError,
        UnicodeError,
        TypeError,
        ValueError,
    ) as error:
        native_head = None
        native_head_error = f"native_head_proof_unavailable:{type(error).__name__}"

    requests = [
        row
        for row in approvals.get("requests", {}).values()
        if isinstance(row, dict)
    ]
    workspace_requests = [
        row
        for row in requests
        if row.get("workspace_sha256") == expected_workspace
    ]
    exact = [
        row
        for row in workspace_requests
        if _request_is_exact_current(
            row,
            expected_workspace=expected_workspace,
            expected_intent=expected_intent,
            expected_revision=expected_revision,
            expected_provider=expected_provider,
            expected_lane=expected_lane,
            expected_proposal_digest=expected_proposal_digest,
            lanes_present=lanes_present,
            current_lane=current_lane,
        )
    ]
    exact_by_id = {str(row.get("request_id") or ""): row for row in exact}

    fresh = 0
    reassess_due = 0
    expired = 0
    cas_mismatch = 0
    mismatch_reasons: list[str] = []
    request_scope = {
        "current_active": 0,
        "other_lane_active": 0,
        "historical_active": 0,
        "terminal": 0,
    }
    exact_ids = {str(row.get("request_id") or "") for row in exact}
    for row in workspace_requests:
        request_id = str(row.get("request_id") or "")
        is_exact = request_id in exact_ids
        if row.get("status") != "asked":
            request_scope["terminal"] += 1
            continue
        if is_exact:
            request_scope["current_active"] += 1
        elif (
            row.get("intent_id_sha256") == expected_intent
            and int(row.get("intent_revision") or 0) == expected_revision
            and (
                row.get("provider") != expected_provider
                or row.get("lane_sha256") != expected_lane
            )
        ):
            request_scope["other_lane_active"] += 1
            continue
        else:
            request_scope["historical_active"] += 1
            continue
        phase = approval_request_phase(row, now=current)
        if phase == "expired":
            expired += 1
        elif phase == "reassess_due":
            reassess_due += 1
        else:
            fresh += 1

    transactions = [
        row
        for row in native.get("transactions", {}).values()
        if isinstance(row, dict)
    ]
    current_transactions: list[dict[str, Any]] = []
    transaction_scope = {
        "current_active": 0,
        "other_lane_active": 0,
        "historical_active": 0,
        "terminal": 0,
        "malformed": 0,
    }
    for transaction in transactions:
        binding = transaction.get("binding")
        if not isinstance(binding, dict):
            transaction_scope["malformed"] += 1
            continue
        binding_workspace = _resolved_path(binding.get("workspace"))
        same_workspace = bool(
            expected_workspace_path is not None
            and binding_workspace == expected_workspace_path
        )
        same_intent = binding.get("intent_id") == contract.get("intent_id")
        if not same_workspace:
            continue
        terminal = transaction.get("status") != "active"
        exact_current = _binding_is_exact_current(
            binding,
            contract=contract,
            current_lane=current_lane,
            lanes_present=lanes_present,
            expected_workspace_path=expected_workspace_path,
            expected_provider=expected_provider,
            expected_session_id=session_id,
            expected_proposal_digest=expected_proposal_digest,
        )
        if terminal:
            transaction_scope["terminal"] += 1
            historical_committed = bool(
                transaction.get("stage") == "committed"
                or transaction.get("historical_status") == "committed"
                or transaction.get("status") == "committed"
            )
            if exact_current and historical_committed:
                current_transactions.append(transaction)
            continue
        if exact_current:
            transaction_scope["current_active"] += 1
            current_transactions.append(transaction)
            continue
        same_revision = int(binding.get("intent_revision") or 0) == expected_revision
        if same_intent and same_revision and (
            binding.get("provider") != expected_provider
            or binding.get("session_id") != session_id
        ):
            transaction_scope["other_lane_active"] += 1
        else:
            transaction_scope["historical_active"] += 1

    committed_request_ids: set[str] = set()
    active_transactions = 0
    authority_queries: list[dict[str, Any]] = []
    for transaction in current_transactions:
        binding = transaction["binding"]
        request_id = str(binding.get("request_id") or "")
        request = exact_by_id.get(request_id)
        if request is None:
            cas_mismatch += 1
            mismatch_reasons.append("native_transaction_request_missing")
            continue
        if (
            request.get("kind") != binding.get("approval_kind")
            or request.get("card_sha256") != binding.get("card_sha256")
            or request.get("target_sha256") != _sha256_text(binding.get("target"))
        ):
            cas_mismatch += 1
            mismatch_reasons.append("native_transaction_request_binding_mismatch")
            continue
        if transaction.get("status") == "active":
            active_transactions += 1
            continue
        historical_committed = bool(
            transaction.get("stage") == "committed"
            or transaction.get("historical_status") == "committed"
            or transaction.get("status") == "committed"
        )
        if historical_committed:
            if request.get("status") != "decided":
                cas_mismatch += 1
                mismatch_reasons.append("native_commit_without_decision")
                continue
            try:
                verify_recorded_external_head_receipt(
                    contract_path,
                    str(transaction.get("transaction_id") or ""),
                )
            except (NativeDecisionJournalError, OSError, UnicodeError, ValueError):
                # Legacy/local-only committed rows did not seal the independent
                # external head. They retain the explicit reader fallback and
                # must never be promoted merely because they say "committed".
                pass
            else:
                committed_request_ids.add(request_id)
                continue
            if native_head is None:
                cas_mismatch += 1
                mismatch_reasons.append(native_head_error)
                mismatch_reasons.append("external_authority_unverified")
                continue
            query = _external_authority_query(
                head=native_head,
                binding=binding,
                transaction_id=str(transaction.get("transaction_id") or ""),
                workspace_sha256=expected_workspace,
                provider=expected_provider,
                session_id=session_id,
                intent_id_sha256=expected_intent,
                intent_revision=expected_revision,
            )
            authority_queries.append(query)
            if external_authority_reader is None:
                cas_mismatch += 1
                mismatch_reasons.append("external_authority_unverified")
                continue
            try:
                external_proof = external_authority_reader(dict(query))
            except Exception:
                external_proof = None
            if not _external_authority_matches(
                external_proof,
                query=query,
                head=native_head,
            ):
                cas_mismatch += 1
                mismatch_reasons.append("external_authority_proof_mismatch")
                continue
            committed_request_ids.add(request_id)

    if active_transactions > 1:
        # More than one prepared transaction for the exact current tuple is a
        # real same-scope conflict.  Report one current fault regardless of how
        # much unrelated history exists in the journal.
        cas_mismatch += 1
        mismatch_reasons.append("native_current_scope_conflict")

    # A native human Allow/Deny in the approval ledger is incomplete until the
    # same request reaches the committed CAS stage. Historical system/agent
    # decisions are intentionally outside native PermissionRequest authority.
    for request in exact:
        if (
            request.get("status") == "decided"
            and request.get("source") == "codex_permission_request"
            and request.get("outcome") in {"approved", "rejected"}
            and str(request.get("request_id") or "") not in committed_request_ids
        ):
            cas_mismatch += 1
            mismatch_reasons.append("native_decision_not_committed")

    unsettled = active_transactions
    if approval_required and not (fresh or reassess_due or expired or cas_mismatch):
        unsettled += 1

    if cas_mismatch:
        status = "cas_mismatch"
    elif expired:
        status = "expired"
    elif reassess_due:
        status = "reassess_due"
    elif fresh:
        status = "awaiting_human"
    elif unsettled:
        status = "unsettled"
    elif committed_request_ids:
        status = "settled"
    else:
        status = "not_required"
    settled = status in {"settled", "not_required"}
    reasons = list(dict.fromkeys(mismatch_reasons))
    if not settled and not reasons:
        reasons.append(status)
    return {
        "status": status,
        "settled": settled,
        # reassess_due remains a valid human question, so it is deliberately
        # included in awaiting_human while retaining its own visible count.
        "awaiting_human": fresh + reassess_due,
        "fresh": fresh,
        "reassess_due": reassess_due,
        "expired": expired,
        "cas_mismatch": cas_mismatch,
        "unsettled": unsettled,
        "paired_committed": len(committed_request_ids),
        "request_scope": request_scope,
        "transaction_scope": transaction_scope,
        "external_authority_queries": authority_queries,
        "reasons": reasons,
        "authority": "t06_external_authority_proof_seam",
        "host_provenance_authority": "telemetry_integrity_only",
    }


def recovery_readiness_projection(
    *,
    task_lane_state: str,
    launcher_status: str,
    truth: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Project H05 recovery independently from ordinary task readiness."""
    supplied = truth if isinstance(truth, dict) else {}
    reasons: list[str] = []
    required_fields = ("lane_available", "typed_route_available")
    status_fields = (
        "snapshot_status",
        "hook_generation_status",
        "skill_catalog_status",
    )
    missing_fields = [name for name in required_fields if name not in supplied]
    invalid_fields = [
        name
        for name in required_fields
        if name in supplied and type(supplied[name]) is not bool
    ]
    invalid_fields.extend(
        name
        for name in status_fields
        if name in supplied
        and (not isinstance(supplied[name], str) or not supplied[name])
    )
    if truth is None:
        reasons.append("recovery_truth_unobserved")
    elif not isinstance(truth, dict):
        reasons.append("recovery_truth_malformed")
    if missing_fields:
        reasons.append("recovery_truth_incomplete")
        reasons.extend(f"recovery_truth_missing_{name}" for name in missing_fields)
    if invalid_fields:
        reasons.append("recovery_truth_malformed")
        reasons.extend(f"recovery_truth_invalid_{name}" for name in invalid_fields)

    truth_valid = (
        isinstance(truth, dict) and not missing_fields and not invalid_fields
    )
    lane_available = (
        supplied.get("lane_available")
        if type(supplied.get("lane_available")) is bool
        else None
    )
    typed_route = (
        supplied.get("typed_route_available")
        if type(supplied.get("typed_route_available")) is bool
        else None
    )
    diagnosis_ready = (
        truth_valid and lane_available is True and typed_route is True
    )
    recovery_ready = (
        diagnosis_ready
        and supplied.get("human_confirmation") == "live_verified"
        and supplied.get("repair_execution") == "verified"
        and supplied.get("recovery_verified") is True
    )
    recovery_status = (
        "ready"
        if recovery_ready
        else "diagnosis_available"
        if diagnosis_ready
        else "unavailable"
        if truth_valid
        else "unobserved"
    )
    if truth_valid and lane_available is not True:
        reasons.append("recovery_lane_unavailable")
    if truth_valid and typed_route is not True:
        reasons.append("typed_recovery_route_unavailable")
    snapshot_status = (
        str(supplied.get("snapshot_status"))
        if truth_valid and supplied.get("snapshot_status")
        else "unknown"
    )
    hook_generation = (
        str(supplied.get("hook_generation_status"))
        if truth_valid and supplied.get("hook_generation_status")
        else "unknown"
    )
    skill_catalog = (
        str(supplied.get("skill_catalog_status"))
        if truth_valid and supplied.get("skill_catalog_status")
        else "unknown"
    )
    return {
        "schema": "sulde-recovery-readiness-v1",
        "status": recovery_status,
        "lane_available": lane_available,
        "typed_route_available": typed_route,
        "diagnosis_available": supplied.get("diagnosis_available") is True or diagnosis_ready,
        "human_confirmation": supplied.get("human_confirmation", "unobserved"),
        "repair_execution": supplied.get("repair_execution", "unverified"),
        "recovery_verified": supplied.get("recovery_verified") is True and recovery_ready,
        "last_recovery_verified": supplied.get("recovery_verified") is True and truth_valid,
        "last_terminal": supplied.get("last_terminal"),
        "ordinary_task_lane_required": False,
        "task_lane_state": task_lane_state,
        "launcher_status": launcher_status,
        "snapshot_status": snapshot_status,
        "hook_generation_status": hook_generation,
        "hook_hot_rebind_supported": supplied.get("hook_hot_rebind_supported") is True,
        "skill_catalog_status": skill_catalog,
        "skill_catalog_restart_required": (
            None if skill_catalog == "unknown" else skill_catalog != "current"
        ),
        "available_actions": ["status", "doctor", "readback"] if diagnosis_ready else [],
        "repair_actions_require_target_preflight": [
            "repair_launcher", "repair_generated_bytecode",
        ] if diagnosis_ready else [],
        "active_run": supplied.get("active_run") if truth_valid else None,
        "reasons": list(dict.fromkeys(reasons)),
    }


def project(
    home: Path,
    *,
    provider: str | None = None,
    session_id: str | None = None,
    workspace: Path | str | None = None,
    resolved_contract_path: Path | None = None,
    expected_runtime_sha256: str | None = None,
    scheduler_probe: dict[str, Any] | None = None,
    external_authority_reader: Callable[[dict[str, Any]], Any] | None = None,
    recovery_truth: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Project scheduler delivery separately from interactive supervision.

    HMAC host provenance proves only telemetry integrity. Authorization still
    comes exclusively from a paired native PermissionRequest decision recorded
    in the intent/effect authorities; a signed observation cannot approve work.
    """
    selected_home = home.expanduser()
    selected_provider = _provider(provider, selected_home)
    selected_session = _session_id(session_id, selected_provider)
    selected_workspace = _workspace(workspace, selected_session)
    if scheduler_probe is None:
        scheduler_probe = scheduler_process_projection(selected_home)
    artifact, scheduler = _deployment_readiness(
        selected_home,
        selected_provider,
        scheduler_probe,
    )
    contract_path, contract, contract_error, selected_workspace = _diagnostic_contract(
        selected_home,
        provider=selected_provider,
        session_id=selected_session,
        workspace=selected_workspace,
        resolved_contract_path=resolved_contract_path,
        workspace_explicit=workspace is not None and bool(str(workspace).strip()),
    )
    runtime = contract.get("runtime") if isinstance(contract, dict) and isinstance(contract.get("runtime"), dict) else {}
    confirmation = contract.get("confirmation") if isinstance(contract, dict) and isinstance(contract.get("confirmation"), dict) else {}
    lanes = runtime.get("task_lanes") if isinstance(runtime.get("task_lanes"), list) else []
    current_lane = (
        task_lane(
            contract,
            provider=selected_provider or "unknown",
            session_id=selected_session,
        )
        if isinstance(contract, dict) and selected_session
        else None
    )
    pause_scope = str(runtime.get("pause_scope") or "global")
    global_pause = bool(
        isinstance(contract, dict)
        and contract.get("status") == "paused"
        and pause_scope != "lane"
    )
    lane_pause = bool(
        isinstance(current_lane, dict) and current_lane.get("state") == "paused"
    )
    effective_contract_status = (
        "paused"
        if global_pause or lane_pause
        else "active"
        if isinstance(contract, dict)
        and contract.get("status") == "paused"
        and pause_scope == "lane"
        else str(contract.get("status") or "")
        if isinstance(contract, dict)
        else "missing"
    )
    pending_proposal_for_lane = _pending_proposal_requires_current_lane(
        contract_path,
        contract,
        provider=selected_provider,
        session_id=selected_session,
        current_lane=current_lane,
    )
    approval_required = bool(
        isinstance(contract, dict)
        and (
            effective_contract_status == "paused"
            or pending_proposal_for_lane
            or (
                isinstance(current_lane, dict)
                and current_lane.get("state") == "review_required"
            )
            or (
                confirmation.get("required")
                and str(contract.get("confirmed_by") or "") in {"", "unconfirmed"}
            )
        )
    )
    if not selected_session:
        # Provider-wide rows from old sessions must never be mistaken for the
        # current interactive lane when a scheduler/status process has no lane.
        host = {
            "schema": "sulde-host-capability-contract-v1",
            "provider": selected_provider or "unknown",
            "status": "unobserved",
            "interactive_status": "unobserved",
            "supervision_status": "unobserved",
            "approval_required": approval_required,
            "approval_status": "unobserved",
            "capabilities": {},
            "reason": "current_session_missing",
            "telemetry_authority": "integrity_only_not_permission_authority",
        }
    elif selected_provider is None:
        host = {
            "schema": "sulde-host-capability-contract-v1",
            "provider": "unknown",
            "status": "unavailable",
            "interactive_status": "unobserved",
            "approval_required": approval_required,
            "approval_status": "unobserved",
            "capabilities": {},
            "telemetry_authority": "integrity_only_not_permission_authority",
        }
    else:
        host = readiness_projection(
            selected_home,
            provider=selected_provider,
            session_id=selected_session or None,
            workspace=selected_workspace,
            expected_runtime_sha256=expected_runtime_sha256,
            approval_required=approval_required,
            now=now,
        )
        host["telemetry_authority"] = "integrity_only_not_permission_authority"
    effect = _current_effect_truth(contract_path, contract)
    contract_active = bool(contract and effective_contract_status == "active")
    contract_enforced = bool(contract and contract.get("mode") == "enforce")
    task_lane_bound = bool(
        contract
        and (
            not lanes
        or (
            isinstance(current_lane, dict)
            and current_lane.get("state") == "bound"
        )
        )
    )
    decision = _native_decision_truth(
        contract_path,
        contract,
        provider=selected_provider,
        session_id=selected_session,
        workspace=selected_workspace,
        current_lane=current_lane,
        approval_required=approval_required,
        external_authority_reader=external_authority_reader,
        now=now,
    )
    native_decision_pairing_settled = bool(decision["settled"])
    runtime = contract.get("runtime") if isinstance(contract, dict) else {}
    pre_execution_gaps = [
        row
        for row in (
            runtime.get("pre_execution_gaps")
            if isinstance(runtime.get("pre_execution_gaps"), list)
            else []
        )
        if isinstance(row, dict)
        and str(row.get("provider") or "") == str(selected_provider or "")
        and str(row.get("session_id") or "") == selected_session
    ]
    last_pre_execution_proof, current_pre_execution_proof = (
        _current_pre_execution_proof(
            runtime,
            provider=selected_provider,
            session_id=selected_session,
            loaded_module_generation=str(
                artifact.get("loaded_module_generation") or ""
            ),
            artifact_generation=str(artifact.get("generation") or ""),
        )
    )
    continuation_proof_required = bool(
        isinstance(current_lane, dict)
        and current_lane.get("source") == "native_session_continuation"
    )
    pre_execution_safety = {
        "status": (
            "degraded"
            if pre_execution_gaps
            else "unverified"
            if continuation_proof_required and current_pre_execution_proof is None
            else "verified"
            if current_pre_execution_proof is not None
            else "clear"
        ),
        "blocking_gaps": len(pre_execution_gaps),
        "last_gap": pre_execution_gaps[-1] if pre_execution_gaps else None,
        "authority": "post_only_material_observation_latch",
        "reset_boundary": "verified_negative_canary_same_session_generation",
        "proof_required": continuation_proof_required,
        "proof_current_generation": current_pre_execution_proof is not None,
        "required_generation": artifact.get("generation"),
        "current_probe": (
            runtime.get("pre_execution_probe")
            if isinstance(runtime.get("pre_execution_probe"), dict)
            and runtime.get("pre_execution_probe")
            else None
        ),
        "last_proof": last_pre_execution_proof,
    }
    interactive_gates = {
        "artifact_generation_ready": artifact.get("status") == "ready",
        # Scheduler process health is intentionally absent here.  A failed
        # background actor must remain visible in ``scheduler_readiness`` but
        # cannot make a live Hook/session claim that interactive supervision
        # is unavailable.
        "provider_selected": selected_provider is not None,
        "current_session_bound": bool(selected_session),
        "workspace_bound": selected_workspace is not None,
        "contract_active": contract_active,
        "contract_enforced": contract_enforced,
        "task_lane_bound": task_lane_bound,
        "host_interactive_fresh": host.get("status") == "interactive_ready",
        "host_supervision_fresh": host.get("supervision_status") == "live_verified",
        "pre_execution_safety_clear": not pre_execution_gaps,
        "pre_execution_safety_proven": bool(
            not continuation_proof_required
            or current_pre_execution_proof is not None
        ),
        "permission_request_observed": bool(
            not approval_required or host.get("approval_status") == "live_verified"
        ),
        "permission_request_fresh": bool(
            not approval_required or host.get("approval_status") == "live_verified"
        ),
        "native_decision_pairing_settled": native_decision_pairing_settled,
        "effect_debt_clear": effect.get("status") == "clear",
        "current_effect_clear": effect.get("status") == "clear",
    }
    interactive_reasons = [
        name for name, passed in interactive_gates.items() if not passed
    ]
    if contract_error and contract_error not in interactive_reasons:
        interactive_reasons.append(contract_error)
    interactive_status = (
        "unobserved"
        if not selected_session
        else "ready"
        if all(interactive_gates.values())
        else "degraded"
    )
    interactive = {
        "status": interactive_status,
        "gates": interactive_gates,
        "reasons": interactive_reasons,
        "session_bound": bool(selected_session),
        "workspace_bound": selected_workspace is not None,
        "permission_authority": "native_permission_request_decision_pairing",
        "host_provenance_authority": "telemetry_integrity_only",
        "decision_status": decision["status"],
    }
    selected_task_lane_state = (
        str(current_lane.get("state") or "")
        if isinstance(current_lane, dict)
        else "legacy_unscoped"
        if contract and not lanes
        else "unbound"
    )
    recovery = recovery_readiness_projection(
        task_lane_state=selected_task_lane_state,
        launcher_status=(
            "current" if artifact.get("status") == "ready" else "drifted"
        ),
        truth=recovery_truth,
    )
    readiness_scope = "interactive" if selected_session else "scheduler"
    selected = interactive if selected_session else scheduler
    return {
        "schema": SCHEMA,
        "status": selected["status"],
        "readiness_scope": readiness_scope,
        "artifact_generation_readiness": artifact,
        "scheduler_readiness": scheduler,
        "interactive_readiness": interactive,
        "pre_execution_safety_readiness": pre_execution_safety,
        "effect_debt_readiness": effect,
        "native_decision_pairing_readiness": decision,
        "recovery_readiness": recovery,
        "domains": {
            "artifact_generation": artifact,
            "scheduler": scheduler,
            "interactive": interactive,
            "pre_execution_safety": pre_execution_safety,
            "effect_debt": effect,
            "native_decision_pairing": decision,
            "recovery": recovery,
        },
        "provider": selected_provider,
        "session_bound": bool(selected_session),
        "workspace_bound": selected_workspace is not None,
        "contract_path": str(contract_path) if contract_path else None,
        "intent_id": str(contract.get("intent_id") or "") if contract else None,
        "intent_revision": int(contract.get("revision") or 0) if contract else None,
        "contract_status": str(contract.get("status") or "") if contract else "missing",
        "effective_contract_status": effective_contract_status,
        "pause_scope": (
            "global"
            if global_pause
            else "lane"
            if lane_pause
            else ""
        ),
        "task_lane_state": selected_task_lane_state,
        "contract_mode": str(contract.get("mode") or "") if contract else "missing",
        "approval_required": approval_required,
        "gates": selected["gates"],
        "reasons": selected["reasons"],
        "host_readiness": host,
        "effect_truth": effect,
        "decision_truth": decision,
        "authority": {
            "host_provenance": "telemetry_integrity_only",
            "permission": "native_permission_request_decision_pairing",
            "effect": "append_only_effect_ledger",
        },
    }
