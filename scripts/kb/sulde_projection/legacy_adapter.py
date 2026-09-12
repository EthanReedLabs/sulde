"""Read-only adapter from the current JSON/JSONL control plane."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Any

import approval_invariant
import intervention
import native_decision_journal
from intent_guardian_parts.state import (
    CONTRACT_SCHEMA,
    audit_path,
    validate_contract,
)

from .models import (
    LegacyApprovalState,
    LegacyContractState,
    LegacyControlCut,
    LegacyCutChanged,
    LegacyEffectState,
    LegacyInterventionState,
    LegacyProjectionError,
    LegacySemanticProjection,
    LegacyTaskState,
    SourceFingerprint,
)


MAX_SOURCE_BYTES = 512 * 1024 * 1024
MAX_CONTRACT_BYTES = 16 * 1024 * 1024
_EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()


def _workspace_id(workspace: str) -> str:
    if type(workspace) is not str or not workspace:
        raise LegacyProjectionError("legacy workspace root is invalid")
    canonical = str(Path(workspace).expanduser().resolve(strict=False))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _count_list(value: Any, label: str) -> int:
    if not isinstance(value, list):
        raise LegacyProjectionError(f"legacy {label} must be a list")
    return len(value)


def _contract_material_digest(contract: dict[str, Any]) -> str:
    runtime = contract.get("runtime")
    if not isinstance(runtime, dict):
        raise LegacyProjectionError("legacy runtime projection is missing")
    material = {
        key: value
        for key, value in contract.items()
        if key not in {"runtime", "created_at", "updated_at"}
    }
    material["runtime_material"] = {
        key: runtime.get(key)
        for key in (
            "material_sequence",
            "pending_proposal_digest",
            "pause_scope",
            "pause_reason",
            "pause_class",
            "pause_origin_reason",
            "pause_requires_revision",
            "pause_revision",
        )
    }
    rendered = json.dumps(
        material,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def adapt_legacy_projection(
    contract: dict[str, Any],
    *,
    runtime_generation: str,
    intervention_projection: dict[str, Any],
    approval_summary: dict[str, Any],
    pending_native_transactions: list[dict[str, Any]],
) -> LegacySemanticProjection:
    """Project only current open control state; historical bytes stay in the cut."""
    if not isinstance(contract, dict) or contract.get("schema") != CONTRACT_SCHEMA:
        raise LegacyProjectionError("legacy contract schema is invalid")
    if not isinstance(intervention_projection, dict):
        raise LegacyProjectionError("legacy intervention projection is invalid")
    if not isinstance(approval_summary, dict):
        raise LegacyProjectionError("legacy approval summary is invalid")
    if not isinstance(pending_native_transactions, list):
        raise LegacyProjectionError("legacy native transaction list is invalid")
    historical_native_diagnostics: list[dict[str, Any]] = []
    actionable_native_transactions: list[dict[str, Any]] = []
    for row in pending_native_transactions:
        if native_decision_journal.is_legacy_unsealed_prepared_diagnostic(row):
            historical_native_diagnostics.append(row)
        else:
            actionable_native_transactions.append(row)
    runtime = contract.get("runtime")
    if not isinstance(runtime, dict):
        raise LegacyProjectionError("legacy runtime projection is missing")
    try:
        contract_state = LegacyContractState(contract["status"])
        contract_sequence = int(runtime["sequence"])
        material_sequence = int(runtime["material_sequence"])
        open_approval_requests = int(approval_summary.get("open", 0))
        expired_approval_requests = int(approval_summary.get("expired", 0))
    except (KeyError, TypeError, ValueError) as error:
        raise LegacyProjectionError("legacy typed projection is invalid") from error
    open_events = _count_list(runtime.get("open_events"), "open_events")
    pending_verifications = _count_list(
        runtime.get("pending_verifications"),
        "pending_verifications",
    )
    active_skills = max(
        _count_list(runtime.get("active_skills"), "active_skills"),
        _count_list(runtime.get("active_skill_frames"), "active_skill_frames"),
    )
    task_lanes = runtime.get("task_lanes")
    if not isinstance(task_lanes, list):
        raise LegacyProjectionError("legacy task_lanes must be a list")
    task_epoch = str(contract.get("task_epoch") or "")
    paused_lanes = sum(
        1
        for lane in task_lanes
        if isinstance(lane, dict)
        and lane.get("task_epoch") == task_epoch
        and lane.get("state") == "paused"
    )
    integrity_breaches = _count_list(
        runtime.get("integrity_breaches"),
        "integrity_breaches",
    )
    attempts = intervention_projection.get("attempts")
    interventions = intervention_projection.get("interventions")
    if not isinstance(attempts, dict) or not isinstance(interventions, dict):
        raise LegacyProjectionError("legacy effect projection fields are invalid")
    try:
        blocking_effects = len(
            intervention.readiness_blocking_attempts(intervention_projection)
        )
    except (TypeError, ValueError, RuntimeError) as error:
        raise LegacyProjectionError("legacy effect blockers cannot be derived") from error
    open_interventions = sum(
        1
        for row in interventions.values()
        if isinstance(row, dict) and row.get("status") in {"open", "acknowledged"}
    )
    pending_proposal = bool(runtime.get("pending_proposal_digest"))
    confirmation = contract.get("confirmation")
    confirmation_required = bool(
        isinstance(confirmation, dict) and confirmation.get("required")
    )
    blockers: list[str] = []
    if contract_state is not LegacyContractState.ACTIVE:
        blockers.append(f"contract_{contract_state.value}")
    for label, count in (
        ("open_events", open_events),
        ("pending_verifications", pending_verifications),
        ("active_skills", active_skills),
        ("paused_lanes", paused_lanes),
        ("open_approval_requests", open_approval_requests),
        ("pending_native_transactions", len(actionable_native_transactions)),
        ("blocking_effect_attempts", blocking_effects),
        ("open_interventions", open_interventions),
        ("integrity_breaches", integrity_breaches),
    ):
        if count:
            blockers.append(f"{label}:{count}")
    if pending_proposal:
        blockers.append("pending_proposal")
    if confirmation_required:
        blockers.append("confirmation_required")
    if pending_verifications:
        task_state = LegacyTaskState.VERIFYING
    elif contract_state is LegacyContractState.PAUSED or paused_lanes:
        task_state = LegacyTaskState.AWAITING_HUMAN
    elif open_events or active_skills:
        task_state = LegacyTaskState.RUNNING
    else:
        task_state = LegacyTaskState.NONE
    return LegacySemanticProjection(
        workspace_id=_workspace_id(str(contract.get("workspace_root") or "")),
        intent_id=str(contract.get("intent_id") or ""),
        intent_revision=contract.get("revision"),
        task_epoch=task_epoch,
        runtime_generation=runtime_generation,
        contract_material_digest=_contract_material_digest(contract),
        contract_state=contract_state,
        task_state=task_state,
        approval_state=(
            LegacyApprovalState.ASKED
            if open_approval_requests
            else LegacyApprovalState.NONE
        ),
        effect_state=(
            LegacyEffectState.UNKNOWN if blocking_effects else LegacyEffectState.NONE
        ),
        intervention_state=(
            LegacyInterventionState.OPEN
            if open_interventions
            else LegacyInterventionState.NONE
        ),
        contract_sequence=contract_sequence,
        material_sequence=material_sequence,
        open_events=open_events,
        pending_verifications=pending_verifications,
        active_skills=active_skills,
        paused_lanes=paused_lanes,
        open_approval_requests=open_approval_requests,
        expired_approval_requests=expired_approval_requests,
        pending_native_transactions=len(actionable_native_transactions),
        historical_unsealed_native_transactions=len(historical_native_diagnostics),
        blocking_effect_attempts=blocking_effects,
        open_interventions=open_interventions,
        integrity_breaches=integrity_breaches,
        pending_proposal=pending_proposal,
        confirmation_required=confirmation_required,
        blockers=tuple(blockers),
    )


def _fingerprint(
    label: str,
    path: Path,
    *,
    material: bool,
) -> SourceFingerprint:
    lexical = Path(os.path.abspath(path.expanduser()))
    try:
        before = os.stat(lexical, follow_symlinks=False)
    except FileNotFoundError:
        return SourceFingerprint(
            label=label,
            path=str(lexical),
            material=material,
            exists=False,
            byte_count=0,
            sha256=_EMPTY_SHA256,
            device=0,
            inode=0,
            modified_ns=0,
        )
    if lexical.is_symlink() or not stat.S_ISREG(before.st_mode):
        raise LegacyProjectionError(f"legacy source {label} is not a regular file")
    digest = hashlib.sha256()
    byte_count = 0
    try:
        with lexical.open("rb") as handle:
            opened = os.fstat(handle.fileno())
            if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
                raise LegacyCutChanged(f"legacy source {label} identity changed")
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                byte_count += len(chunk)
                if byte_count > MAX_SOURCE_BYTES:
                    raise LegacyProjectionError(
                        f"legacy source {label} exceeds the 512 MiB cut bound"
                    )
                digest.update(chunk)
    except OSError as error:
        raise LegacyCutChanged(f"legacy source {label} cannot be frozen") from error
    try:
        after = os.stat(lexical, follow_symlinks=False)
    except OSError as error:
        raise LegacyCutChanged(f"legacy source {label} disappeared") from error
    identity_before = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
    )
    identity_after = (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    )
    if identity_before != identity_after or byte_count != after.st_size:
        raise LegacyCutChanged(f"legacy source {label} changed while hashing")
    return SourceFingerprint(
        label=label,
        path=str(lexical),
        material=material,
        exists=True,
        byte_count=byte_count,
        sha256=digest.hexdigest(),
        device=int(after.st_dev),
        inode=int(after.st_ino),
        modified_ns=int(after.st_mtime_ns),
    )


def _source_paths(contract_path: Path) -> tuple[tuple[str, Path, bool], ...]:
    return (
        ("approvals", approval_invariant.event_store_path(contract_path), True),
        ("contract", contract_path, False),
        ("effects", intervention.event_store_path(contract_path), True),
        ("native_anchor", native_decision_journal.head_anchor_path(contract_path), True),
        ("native_decisions", native_decision_journal.journal_path(contract_path), True),
        ("native_pending", native_decision_journal.head_pending_path(contract_path), True),
        ("observations", audit_path(contract_path), False),
    )


def _fingerprint_sources(contract_path: Path) -> tuple[SourceFingerprint, ...]:
    sources = tuple(
        _fingerprint(label, path, material=material)
        for label, path, material in _source_paths(contract_path)
    )
    if sum(source.byte_count for source in sources) > MAX_SOURCE_BYTES:
        raise LegacyProjectionError("legacy source cut exceeds 512 MiB in total")
    return tuple(sorted(sources, key=lambda source: source.label))


def collect_legacy_cut(
    contract_path: Path | str,
    *,
    runtime_generation: str,
) -> LegacyControlCut:
    """Build one optimistic, read-only CAS cut; callers may retry a changed cut."""
    path = Path(contract_path).expanduser()
    first = _fingerprint_sources(path)
    contract_source = next(source for source in first if source.label == "contract")
    if not contract_source.exists:
        raise LegacyProjectionError("legacy contract does not exist")
    if contract_source.byte_count > MAX_CONTRACT_BYTES:
        raise LegacyProjectionError("legacy contract exceeds the 16 MiB parse bound")
    try:
        raw_contract = json.loads(path.read_text(encoding="utf-8"))
        contract = validate_contract(raw_contract)
        effect_projection = intervention.load_projection(path)
        approvals = approval_invariant.summary(path)
        native_projection = native_decision_journal.load_projection_read_only(path)
        native_transactions = [
            dict(row)
            for row in native_projection["transactions"].values()
            if row.get("status") == "active"
        ]
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, RuntimeError) as error:
        raise LegacyProjectionError("legacy sources cannot be replayed") from error
    projection = adapt_legacy_projection(
        contract,
        runtime_generation=runtime_generation,
        intervention_projection=effect_projection,
        approval_summary=approvals,
        pending_native_transactions=native_transactions,
    )
    second = _fingerprint_sources(path)
    if first != second:
        raise LegacyCutChanged("legacy sources changed while the cut was projected")
    return LegacyControlCut.build(sources=second, projection=projection)
