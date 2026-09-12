"""Safe reconciliation and reporting for abandoned material tool events.

The intent contract is a mutable projection.  A reconciliation therefore
commits an append-only settlement row first and only then removes the event
from the projection.  A later invocation can replay that row after a crash;
no path in this module asserts that the tool succeeded or that no write took
place.
"""

from __future__ import annotations

from . import memory_scope

from datetime import datetime, timezone
import fnmatch
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Iterable

from intervention import InterventionError, load_projection as load_effect_projection

from .session_workspace import load_session_workspace
from .state import (
    AGENT_DECISION_SENSITIVE_PATHS,
    EVENT_SCHEMA,
    IntentGuardianError,
    _append_jsonl,
    _write_contract_unlocked,
    audit_path,
    contract_lock,
    event_fingerprint,
    kb_home,
    load_contract,
    now_iso,
    policy_digest,
)


SETTLEMENT_SCHEMA = "sulde-guardian-stale-event-settlement-v2"
CLASSIFIER_VERSION = "guardian-stale-local-write-v3"
DEFAULT_MINIMUM_AGE_SECONDS = 5.0
_HEX64 = re.compile(r"[0-9a-f]{64}")
_CONTROL_PLANE_PATTERNS = (
    *AGENT_DECISION_SENSITIVE_PATHS,
    re.compile(r"^scripts/kb/intent_guardian_parts(?:/|$)", re.IGNORECASE),
    re.compile(r"^scripts/kb/intent-guardian\.py$", re.IGNORECASE),
    re.compile(r"^scripts/kb/install-agents(?:\.[a-z0-9]+)?$", re.IGNORECASE),
    re.compile(
        r"^integrations/(?:codex|claude)/plugins/sulde/(?:hooks|scripts)(?:/|\.|$)",
        re.IGNORECASE,
    ),
)


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


def _lane_sha256(provider: str, session_id: str) -> str:
    return hashlib.sha256(
        f"{provider.strip().lower()}\0{session_id.strip()}".encode(
            "utf-8", errors="replace"
        )
    ).hexdigest()


def _contract_identity(path: Path, contract: dict[str, Any]) -> str:
    return _canonical_sha256(
        {
            "contract_path": str(path.expanduser().resolve()),
            "intent_id": str(contract.get("intent_id") or ""),
        }
    )


def _projection_base_sha256(contract: dict[str, Any]) -> str:
    runtime = contract.get("runtime") if isinstance(contract.get("runtime"), dict) else {}
    return _canonical_sha256(
        {
            "intent_id": contract.get("intent_id"),
            "revision": contract.get("revision"),
            "task_epoch": contract.get("task_epoch"),
            "policy_sha256": policy_digest(contract),
            "runtime_sequence": runtime.get("sequence"),
            "material_sequence": runtime.get("material_sequence"),
            "open_events": runtime.get("open_events"),
            "inconclusive_outcomes": runtime.get("inconclusive_outcomes"),
            "task_continuations": runtime.get("task_continuations"),
        }
    )


def _read_audit(path: Path) -> dict[str, Any]:
    """Strictly index source events and committed settlement rows once."""
    source_events: dict[str, list[dict[str, Any]]] = {}
    settlements: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    source = audit_path(path)
    if not source.is_file():
        return {
            "source_events": source_events,
            "settlements": settlements,
            "errors": ["audit_missing"],
        }
    try:
        with source.open("rb") as handle:
            for number, raw in enumerate(handle, 1):
                line = raw.rstrip(b"\r\n")
                if not line.strip():
                    continue
                try:
                    row = json.loads(line.decode("utf-8"))
                except (UnicodeError, json.JSONDecodeError):
                    errors.append(f"invalid_json:{number}")
                    continue
                if not isinstance(row, dict):
                    errors.append(f"invalid_row_type:{number}")
                    continue
                if row.get("schema") == EVENT_SCHEMA:
                    event = row.get("event")
                    if not isinstance(event, dict):
                        errors.append(f"invalid_guardian_event:{number}")
                        continue
                    event_id = str(event.get("event_id") or "")
                    if not event_id:
                        errors.append(f"missing_guardian_event_id:{number}")
                        continue
                    source_events.setdefault(event_id, []).append(
                        {
                            "row": row,
                            "event": event,
                            "source_event_sha256": hashlib.sha256(line).hexdigest(),
                            "line": number,
                        }
                    )
                elif row.get("schema") == SETTLEMENT_SCHEMA:
                    settlement_id = str(row.get("settlement_id") or "")
                    material = {key: value for key, value in row.items() if key != "settlement_sha256"}
                    if (
                        not _HEX64.fullmatch(settlement_id)
                        or row.get("settlement_sha256") != _canonical_sha256(material)
                    ):
                        errors.append(f"invalid_settlement_digest:{number}")
                        continue
                    existing = settlements.get(settlement_id)
                    if existing is not None and existing != row:
                        errors.append(f"conflicting_settlement:{number}")
                        continue
                    settlements[settlement_id] = row
    except OSError as error:
        errors.append(f"audit_unreadable:{type(error).__name__}")
    return {
        "source_events": source_events,
        "settlements": settlements,
        "errors": errors,
    }


def _logical_path(raw: str, workspace: Path) -> str:
    value = str(raw or "").strip()
    if not value or value.startswith("[") or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", value):
        return ""
    candidate = Path(value).expanduser()
    try:
        if candidate.is_absolute():
            resolved = candidate.resolve(strict=False)
            try:
                relative = resolved.relative_to(workspace.resolve(strict=False))
            except ValueError:
                return ""
        else:
            relative = candidate
    except OSError:
        return ""
    parts = relative.parts
    if len(parts) >= 3 and parts[0] == ".worktrees":
        parts = parts[2:]
    if not parts or any(part in {"", ".", ".."} for part in parts):
        return ""
    return Path(*parts).as_posix()


def _source_evidence(
    contract: dict[str, Any],
    open_event: dict[str, Any],
    audit: dict[str, Any],
) -> tuple[dict[str, Any] | None, str]:
    if audit["errors"]:
        return None, "audit_corrupt"
    event_id = str(open_event.get("event_id") or "")
    matches = audit["source_events"].get(event_id, [])
    if len(matches) != 1:
        return None, "source_event_missing" if not matches else "source_event_ambiguous"
    evidence = matches[0]
    source_event = evidence["event"]
    source_decision = evidence["row"].get("decision")
    if not isinstance(source_decision, dict):
        return None, "source_decision_missing"
    exact_fields = (
        "event_id",
        "fingerprint",
        "provider",
        "session_id",
        "task_epoch",
        "kind",
        "capability",
        "target",
        "effect",
        "call_id",
    )
    mismatched = [
        field
        for field in exact_fields
        if open_event.get(field) != source_event.get(field)
    ]
    if mismatched:
        return None, f"source_event_mismatch:{mismatched[0]}"
    if open_event.get("operation_fingerprint") != source_event.get(
        "effect_operation_fingerprint"
    ):
        return None, "source_event_mismatch:operation_fingerprint"
    source_authority = source_event.get("continuation_authority")
    if source_authority is not None and not isinstance(source_authority, dict):
        return None, "source_event_mismatch:continuation_authority"
    source_attempt_id = str(
        source_event.get("effect_attempt_id")
        or source_event.get("attempt_id")
        or ""
    )
    source_grant_id = str((source_authority or {}).get("grant_id") or "")
    source_profile_id = str((source_authority or {}).get("profile_id") or "")
    authority_pairs = (
        ("attempt_id", source_attempt_id),
        ("continuation_grant_id", source_grant_id),
        ("continuation_profile_id", source_profile_id),
    )
    for field, source_value in authority_pairs:
        if str(open_event.get(field) or "") != source_value:
            return None, f"source_event_mismatch:{field}"
    if str(open_event.get("started_at") or "") != str(source_event.get("at") or ""):
        return None, "source_event_mismatch"
    if (
        source_event.get("phase") != "started"
        or source_decision.get("action") != "allow"
        or event_fingerprint(source_event) != open_event.get("fingerprint")
    ):
        return None, "source_event_not_authoritative_dispatch"
    if memory_scope.memory_row(open_event):
        if (not memory_scope.memory_row(source_event)
                or open_event.get("memory_verification") != source_event.get("memory_verification")):
            return None, "source_event_mismatch:memory_verification"
        # A memory request has a typed graph identity, not a filesystem path.
        # Its attempt/profile links still exclude automatic stale settlement.
        return {**evidence, "logical_targets": [], "control_plane": False}, ""
    structured = source_event.get("write_targets")
    raw_targets = (
        list(structured)
        if isinstance(structured, list)
        and structured
        and all(isinstance(item, str) and item for item in structured)
        else [str(source_event.get("target") or "")]
    )
    workspace = Path(contract["workspace_root"]).expanduser()
    targets = [_logical_path(item, workspace) for item in raw_targets]
    if not targets or any(not item for item in targets):
        return None, "source_local_targets_untyped"
    return {
        **evidence,
        "logical_targets": targets,
        "control_plane": any(
            pattern.search(target)
            for target in targets
            for pattern in _CONTROL_PLANE_PATTERNS
        ),
    }, ""


def _parse_time(value: Any) -> float | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


def _source_terminal_reason(
    path: Path,
    contract: dict[str, Any],
    open_event: dict[str, Any],
) -> str:
    provider = str(open_event.get("provider") or "").lower()
    session_id = str(open_event.get("session_id") or "")
    task_epoch = str(open_event.get("task_epoch") or "")
    lane_sha256 = _lane_sha256(provider, session_id) if provider and session_id else ""
    for row in contract.get("runtime", {}).get("task_continuations", []):
        if (
            isinstance(row, dict)
            and row.get("source_lane_sha256") == lane_sha256
            and row.get("task_epoch") == task_epoch
            and row.get("authority_transferred") is False
            and row.get("session_id") != session_id
        ):
            return "formal_task_continuation"
    for row in contract.get("runtime", {}).get("host_observations", []):
        if (
            isinstance(row, dict)
            and row.get("provider") == provider
            and row.get("session_id") == session_id
            and row.get("event") == "session_end"
            and row.get("source") == "live_host_hook"
            and row.get("status") in {"ended", "completed"}
        ):
            return "formal_session_end"
    if provider in {"claude", "codex"} and session_id:
        try:
            mapping = load_session_workspace(kb_home(), provider, session_id)
        except (IntentGuardianError, OSError, UnicodeError):
            mapping = None
        if mapping is not None:
            mapped = Path(str(mapping["contract_path"])).expanduser().resolve()
            if mapped != path.expanduser().resolve():
                return "workspace_handoff"
    return ""


def _is_current_lane(
    path: Path,
    contract: dict[str, Any],
    open_event: dict[str, Any],
    *,
    provider: str,
    session_id: str,
) -> bool:
    if not (
        str(open_event.get("provider") or "").lower() == provider.strip().lower()
        and str(open_event.get("session_id") or "") == session_id.strip()
        and str(open_event.get("task_epoch") or "") == str(contract.get("task_epoch") or "")
    ):
        return False
    try:
        mapping = load_session_workspace(kb_home(), provider, session_id)
    except (IntentGuardianError, OSError, UnicodeError):
        return True
    return mapping is None or Path(str(mapping["contract_path"])).expanduser().resolve() == path.expanduser().resolve()


def _effect_links(
    contract: dict[str, Any],
    open_event: dict[str, Any],
    projection: dict[str, Any] | None,
) -> list[str]:
    event_id = str(open_event.get("event_id") or "")
    fingerprint = str(open_event.get("fingerprint") or "")
    operation = str(open_event.get("operation_fingerprint") or "")
    call_id = str(open_event.get("call_id") or "")
    links: list[str] = []
    if str(open_event.get("attempt_id") or ""):
        links.append("open_event_attempt")
    if str(open_event.get("continuation_grant_id") or ""):
        links.append("open_event_grant")
    if str(open_event.get("continuation_profile_id") or ""):
        links.append("open_event_profile")
    runtime = contract.get("runtime") if isinstance(contract.get("runtime"), dict) else {}
    if fingerprint and fingerprint in runtime.get("authorized_events", []):
        links.append("authorized_event")
    for row in runtime.get("continuation_uses", []):
        if not isinstance(row, dict):
            links.append("invalid_continuation_use")
            continue
        if (
            row.get("fingerprint") == fingerprint
            or (call_id and row.get("call_id") == call_id)
        ):
            links.append("continuation_use")
    for row in runtime.get("pending_verifications", []):
        if not isinstance(row, dict):
            links.append("invalid_pending_verification")
            continue
        values = {
            str(row.get(key) or "")
            for key in (
                "event_id",
                "source_event_id",
                "fingerprint",
                "operation_fingerprint",
                "attempt_id",
            )
        }
        if {event_id, fingerprint, operation, str(open_event.get("attempt_id") or "")} & (values - {""}):
            links.append("pending_verification")
    if projection is not None:
        for row in projection.get("attempts", {}).values():
            if not isinstance(row, dict):
                links.append("invalid_effect_attempt")
                continue
            if (
                row.get("source_event_id") == event_id
                or (operation and row.get("operation_fingerprint") == operation)
            ):
                links.append("effect_attempt_ledger")
    return sorted(set(links))


def _classification_item(
    open_event: dict[str, Any],
    *,
    category: str,
    reason: str,
    source: dict[str, Any] | None,
    links: Iterable[str] = (),
    terminal_reason: str = "",
) -> dict[str, Any]:
    return {
        "category": category,
        "reason": reason,
        "event_id": str(open_event.get("event_id") or ""),
        "fingerprint": str(open_event.get("fingerprint") or ""),
        "provider": str(open_event.get("provider") or "unknown"),
        "session_id": str(open_event.get("session_id") or ""),
        "task_epoch": str(open_event.get("task_epoch") or ""),
        "effect": str(open_event.get("effect") or "unknown"),
        "capability": str(open_event.get("capability") or "unknown"),
        "logical_targets": list(source.get("logical_targets") or []) if source else [],
        "source_event_sha256": str(source.get("source_event_sha256") or "") if source else "",
        "terminal_reason": terminal_reason,
        "effect_links": list(links),
        "open_event": open_event,
    }


def _classify(
    path: Path,
    contract: dict[str, Any],
    *,
    provider: str,
    session_id: str,
    minimum_age_seconds: float,
    audit: dict[str, Any],
    boundary: str = "report",
) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {
        "eligible": [],
        "current_lane_blockers": [],
        "other_lane_stale": [],
        "effect_debt": [],
        "quarantined": [],
    }
    try:
        projection = load_effect_projection(path)
    except (InterventionError, OSError, UnicodeError):
        projection = None
        effect_projection_error = True
    else:
        effect_projection_error = False
    cutoff = datetime.now(timezone.utc).timestamp() - max(0.0, float(minimum_age_seconds))
    rows = contract.get("runtime", {}).get("open_events", [])
    for raw in rows:
        if not isinstance(raw, dict):
            groups["quarantined"].append(
                _classification_item(
                    {}, category="quarantined", reason="invalid_open_event_type", source=None
                )
            )
            continue
        source, source_error = _source_evidence(contract, raw, audit)
        current_lane = _is_current_lane(
            path, contract, raw, provider=provider, session_id=session_id
        )
        same_session = bool(
            str(raw.get("provider") or "").lower() == provider.strip().lower()
            and str(raw.get("session_id") or "") == session_id.strip()
        )
        try:
            mapping = load_session_workspace(kb_home(), provider, session_id)
        except (IntentGuardianError, OSError, UnicodeError):
            mapping = None
        mapped_here = bool(
            mapping is not None
            and Path(str(mapping["contract_path"])).expanduser().resolve()
            == path.expanduser().resolve()
        )
        started = _parse_time(raw.get("started_at"))
        links = _effect_links(contract, raw, projection)
        if effect_projection_error:
            links.append("effect_ledger_unreadable")
        sequential_patch = bool(
            boundary == "proposal_request"
            and (current_lane or (same_session and mapped_here))
            and raw.get("capability") == "tool:apply_patch"
            and raw.get("effect") == "local_write"
            and source is not None
            and not source_error
            and not links
            and started is not None
            and started <= cutoff
        )
        if sequential_patch:
            groups["eligible"].append(
                _classification_item(
                    raw,
                    category="eligible",
                    reason="same_session_apply_patch_missing_completion",
                    source=source,
                    terminal_reason="sequential_proposal_boundary",
                )
            )
            continue
        if current_lane:
            groups["current_lane_blockers"].append(
                _classification_item(
                    raw,
                    category="current_lane_blockers",
                    reason="current_lane_event_still_open",
                    source=source,
                )
            )
            continue
        effect = str(raw.get("effect") or "unknown")
        if effect != "local_write" or links:
            groups["effect_debt"].append(
                _classification_item(
                    raw,
                    category="effect_debt",
                    reason="non_local_or_authority_effect_link",
                    source=source,
                    links=links,
                )
            )
            continue
        if source_error or source is None:
            groups["quarantined"].append(
                _classification_item(
                    raw,
                    category="quarantined",
                    reason=source_error or "source_evidence_invalid",
                    source=source,
                )
            )
            continue
        if source["control_plane"]:
            groups["quarantined"].append(
                _classification_item(
                    raw,
                    category="quarantined",
                    reason="control_plane_local_write",
                    source=source,
                )
            )
            continue
        started = _parse_time(raw.get("started_at"))
        if started is None:
            groups["quarantined"].append(
                _classification_item(
                    raw,
                    category="quarantined",
                    reason="started_at_invalid",
                    source=source,
                )
            )
            continue
        terminal_reason = _source_terminal_reason(path, contract, raw)
        if started > cutoff or not terminal_reason:
            groups["other_lane_stale"].append(
                _classification_item(
                    raw,
                    category="other_lane_stale",
                    reason=("event_fresh" if started > cutoff else "source_session_not_terminal"),
                    source=source,
                    terminal_reason=terminal_reason,
                )
            )
            continue
        groups["eligible"].append(
            _classification_item(
                raw,
                category="eligible",
                reason="stale_local_write_with_terminal_source",
                source=source,
                terminal_reason=terminal_reason,
            )
        )
    return groups


def _settlement_id(path: Path, contract: dict[str, Any], item: dict[str, Any]) -> str:
    return _canonical_sha256(
        {
            "contract_identity": _contract_identity(path, contract),
            "event_id": item["event_id"],
            "source_event_sha256": item["source_event_sha256"],
            "classifier_version": CLASSIFIER_VERSION,
        }
    )


def _valid_committed_settlement(
    path: Path,
    contract: dict[str, Any],
    open_event: dict[str, Any],
    audit: dict[str, Any],
) -> dict[str, Any] | None:
    source, error = _source_evidence(contract, open_event, audit)
    if error or source is None:
        return None
    item = _classification_item(
        open_event,
        category="eligible",
        reason="replay_committed_settlement",
        source=source,
    )
    settlement = audit["settlements"].get(_settlement_id(path, contract, item))
    if not isinstance(settlement, dict):
        return None
    if (
        settlement.get("outcome") != "inconclusive"
        or settlement.get("source_event_id") != item["event_id"]
        or settlement.get("source_event_sha256") != item["source_event_sha256"]
        or settlement.get("authority_transferred") is not False
        or settlement.get("effect_asserted") is not False
    ):
        return None
    return settlement


def _project_settlements(
    contract: dict[str, Any],
    rows: list[tuple[dict[str, Any], dict[str, Any]]],
) -> None:
    event_ids = {str(event.get("event_id") or "") for event, _ in rows}
    runtime = contract["runtime"]
    runtime["open_events"] = [
        row
        for row in runtime["open_events"]
        if not isinstance(row, dict) or str(row.get("event_id") or "") not in event_ids
    ]
    fingerprints = {
        str(event.get("fingerprint") or "") for event, _ in rows if event.get("fingerprint")
    }
    runtime["authorized_events"] = [
        value for value in runtime["authorized_events"] if value not in fingerprints
    ]
    outcomes = runtime["inconclusive_outcomes"]
    existing_ids = {
        str(row.get("settlement_id") or "")
        for row in outcomes
        if isinstance(row, dict)
    }
    for event, settlement in rows:
        if settlement["settlement_id"] in existing_ids:
            continue
        outcomes.append(
            {
                "schema": SETTLEMENT_SCHEMA,
                "settlement_id": settlement["settlement_id"],
                "event_id": str(event.get("event_id") or ""),
                "fingerprint": str(event.get("fingerprint") or ""),
                "capability": str(event.get("capability") or "unknown"),
                "target": str(event.get("target") or ""),
                "source_event_sha256": settlement["source_event_sha256"],
                "settlement_sha256": settlement["settlement_sha256"],
                "recorded_at": settlement["at"],
                "reason": (
                    "a later control boundary found an abandoned local write after "
                    "formal source-lane termination; execution outcome remains inconclusive"
                ),
                "authority_transferred": False,
                "effect_asserted": False,
            }
        )
        existing_ids.add(str(settlement["settlement_id"]))
    runtime["inconclusive_outcomes"] = outcomes[-100:]


def reconcile_stale_local_write_events_locked(
    path: Path,
    contract: dict[str, Any],
    *,
    provider: str,
    session_id: str,
    minimum_age_seconds: float = DEFAULT_MINIMUM_AGE_SECONDS,
    boundary: str = "proposal_request",
) -> list[dict[str, Any]]:
    """Append and project eligible settlements while the contract lock is held."""
    if not contract.get("runtime", {}).get("open_events"):
        return []
    audit = _read_audit(path)
    replay: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for raw in list(contract["runtime"]["open_events"]):
        if not isinstance(raw, dict):
            continue
        settlement = _valid_committed_settlement(path, contract, raw, audit)
        if settlement is not None:
            replay.append((raw, settlement))
    if replay:
        _project_settlements(contract, replay)

    groups = _classify(
        path,
        contract,
        provider=provider,
        session_id=session_id,
        minimum_age_seconds=minimum_age_seconds,
        audit=audit,
        boundary=boundary,
    )
    if not groups["eligible"]:
        return [dict(event) for event, _ in replay]

    base_sha256 = _projection_base_sha256(contract)
    committed: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for item in groups["eligible"]:
        if _projection_base_sha256(contract) != base_sha256:
            raise IntentGuardianError("stale-event settlement projection CAS changed")
        settlement_id = _settlement_id(path, contract, item)
        material = {
            "schema": SETTLEMENT_SCHEMA,
            "settlement_id": settlement_id,
            "classifier_version": CLASSIFIER_VERSION,
            "at": now_iso(),
            "boundary": str(boundary)[:100],
            "contract_identity": _contract_identity(path, contract),
            "intent_id": str(contract["intent_id"]),
            "intent_revision": int(contract["revision"]),
            "task_epoch": str(contract["task_epoch"]),
            "runtime_sequence": int(contract["runtime"].get("sequence", 0)),
            "material_sequence": int(contract["runtime"].get("material_sequence", 0)),
            "projection_base_sha256": base_sha256,
            "source_event_id": item["event_id"],
            "source_event_sha256": item["source_event_sha256"],
            "source_fingerprint": item["fingerprint"],
            "source_provider": item["provider"],
            "source_session_id": item["session_id"],
            "source_task_epoch": item["task_epoch"],
            "terminal_reason": item["terminal_reason"],
            "logical_targets": item["logical_targets"],
            "outcome": "inconclusive",
            "authority_transferred": False,
            "effect_asserted": False,
        }
        settlement = {**material, "settlement_sha256": _canonical_sha256(material)}
        existing = audit["settlements"].get(settlement_id)
        if existing is not None and existing != settlement:
            raise IntentGuardianError("stale-event settlement idempotency collision")
        if existing is None:
            _append_jsonl(audit_path(path), settlement)
            audit["settlements"][settlement_id] = settlement
        committed.append((item["open_event"], settlement))
    _project_settlements(contract, committed)
    return [dict(event) for event, _ in [*replay, *committed]]


def reconcile_stale_local_write_events(
    path: Path,
    *,
    provider: str,
    session_id: str,
    minimum_age_seconds: float = DEFAULT_MINIMUM_AGE_SECONDS,
    boundary: str = "proposal_request",
) -> list[dict[str, Any]]:
    selected_provider = str(provider or "").strip().lower()
    selected_session = str(session_id or "").strip()
    if not selected_provider or not selected_session:
        return []
    with contract_lock(path):
        contract = load_contract(path)
        before = _projection_base_sha256(contract)
        reconciled = reconcile_stale_local_write_events_locked(
            path,
            contract,
            provider=selected_provider,
            session_id=selected_session,
            minimum_age_seconds=minimum_age_seconds,
            boundary=boundary,
        )
        if reconciled or _projection_base_sha256(contract) != before:
            _write_contract_unlocked(path, contract)
    return reconciled


def _public_item(item: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in item.items() if key != "open_event"}


def stale_event_report(
    path: Path,
    contract: dict[str, Any] | None = None,
    *,
    provider: str = "",
    session_id: str = "",
    minimum_age_seconds: float = DEFAULT_MINIMUM_AGE_SECONDS,
) -> dict[str, Any]:
    current = contract or load_contract(path)
    if not current.get("runtime", {}).get("open_events"):
        settled = [
            row
            for row in current.get("runtime", {}).get("inconclusive_outcomes", [])
            if isinstance(row, dict) and row.get("schema") == SETTLEMENT_SCHEMA
        ]
        return {
            "schema": "sulde-guardian-stale-event-report-v2",
            "current_lane_blockers": [],
            "other_lane_stale": [],
            "effect_debt": [],
            "settled_inconclusive": settled[-20:],
            "settled_inconclusive_total": len(settled),
            "quarantined_high_risk": [],
            "eligible_for_reconciliation": [],
            "audit_integrity": {
                "status": "not_scanned_no_open_events",
                "errors": [],
            },
        }
    audit = _read_audit(path)
    groups = _classify(
        path,
        current,
        provider=provider,
        session_id=session_id,
        minimum_age_seconds=minimum_age_seconds,
        audit=audit,
    )
    settled = sorted(
        audit["settlements"].values(), key=lambda row: str(row.get("at") or "")
    )
    return {
        "schema": "sulde-guardian-stale-event-report-v2",
        "current_lane_blockers": [_public_item(row) for row in groups["current_lane_blockers"]],
        "other_lane_stale": [_public_item(row) for row in groups["other_lane_stale"]],
        "effect_debt": [_public_item(row) for row in groups["effect_debt"]],
        "settled_inconclusive": settled[-20:],
        "settled_inconclusive_total": len(settled),
        "quarantined_high_risk": [_public_item(row) for row in groups["quarantined"]],
        "eligible_for_reconciliation": [_public_item(row) for row in groups["eligible"]],
        "audit_integrity": {
            "status": "invalid" if audit["errors"] else "valid",
            "errors": list(audit["errors"][:20]),
        },
    }


def _normalize_pattern(raw: str, workspace: Path) -> str:
    value = str(raw or "").strip().replace("\\", "/")
    if not value:
        return ""
    candidate = Path(value).expanduser()
    if candidate.is_absolute():
        logical = _logical_path(value, workspace)
        return logical or candidate.resolve(strict=False).as_posix()
    while value.startswith("./"):
        value = value[2:]
    parts = Path(value).parts
    if len(parts) >= 3 and parts[0] == ".worktrees":
        value = Path(*parts[2:]).as_posix()
    return value


def _paths_overlap(targets: Iterable[str], patterns: Iterable[str], workspace: Path) -> bool:
    normalized_patterns = [_normalize_pattern(item, workspace) for item in patterns]
    normalized_patterns = [item for item in normalized_patterns if item]
    if not normalized_patterns:
        return True
    for target in targets:
        for pattern in normalized_patterns:
            base = pattern.rstrip("/")
            if (
                fnmatch.fnmatchcase(target, pattern)
                or target == base
                or (
                    not any(char in pattern for char in "*?[")
                    and (
                        base.startswith(f"{target}/")
                        or target.startswith(f"{base}/")
                    )
                )
            ):
                return True
    return False


def proposal_open_event_blockers(
    path: Path,
    contract: dict[str, Any],
    *,
    provider: str,
    session_id: str,
    allowed_paths: Iterable[str],
    memory_independent: bool = False,
) -> list[dict[str, Any]]:
    """Return only lane/effect/resource conflicts for a proposed revision."""
    report = stale_event_report(
        path,
        contract,
        provider=provider,
        session_id=session_id,
    )
    blockers: list[dict[str, Any]] = []
    workspace = Path(contract["workspace_root"]).expanduser()
    current_events = {
        str(row.get("event_id") or ""): row
        for row in contract.get("runtime", {}).get("open_events", [])
        if isinstance(row, dict)
    }
    cutoff = datetime.now(timezone.utc).timestamp() - DEFAULT_MINIMUM_AGE_SECONDS
    for item in report["current_lane_blockers"]:
        opened = current_events.get(str(item.get("event_id") or ""))
        started = _parse_time(opened.get("started_at")) if opened else None
        typed_targets = item.get("logical_targets", [])
        safely_disjoint = bool(
            report["audit_integrity"]["status"] == "valid"
            and item.get("effect") == "local_write"
            and not item.get("effect_links")
            and isinstance(typed_targets, list)
            and typed_targets
            and all(isinstance(target, str) and target for target in typed_targets)
            and _HEX64.fullmatch(str(item.get("source_event_sha256") or ""))
            and started is not None
            and started <= cutoff
            and not _paths_overlap(typed_targets, allowed_paths, workspace)
        )
        if not safely_disjoint:
            blockers.append(item)
    blockers.extend(report["effect_debt"])
    blockers.extend(report["eligible_for_reconciliation"])
    for item in [*report["other_lane_stale"], *report["quarantined_high_risk"]]:
        reason = str(item["reason"])
        if reason.startswith(("audit_", "invalid_", "source_")) and reason != "source_session_not_terminal":
            blockers.append(item)
        elif _paths_overlap(item.get("logical_targets", []), allowed_paths, workspace):
            blockers.append(item)
    # Never remove or settle audit state. The authoritative source validation
    # above must succeed before a digest-bound local memory event is disjoint.
    if memory_independent and report["audit_integrity"]["status"] == "valid":
        blockers = [item for item in blockers if not (
            _HEX64.fullmatch(str(item.get("source_event_sha256") or ""))
            and memory_scope.memory_row(current_events.get(str(item.get("event_id") or "")))
            and item.get("category") in {"current_lane_blockers", "effect_debt"}
        )]
    return blockers


def proposal_open_event_blocker(
    path: Path,
    contract: dict[str, Any],
    proposal: dict[str, Any],
    provider: str,
    session_id: str,
) -> dict[str, Any] | None:
    blockers = proposal_open_event_blockers(
        path,
        contract,
        provider=provider,
        session_id=session_id,
        allowed_paths=proposal["constraints"]["allowed_paths"],
        memory_independent=memory_scope.independent(proposal),
    )
    return blockers[0] if blockers else None


def require_proposal_open_event_clear(
    path: Path,
    contract: dict[str, Any],
    proposal: dict[str, Any],
    receipt: dict[str, Any],
) -> None:
    blocker = proposal_open_event_blocker(
        path,
        contract,
        proposal,
        str(receipt.get("provider") or "unknown"),
        str(receipt.get("session_id") or ""),
    )
    if blocker:
        raise IntentGuardianError(
            "cannot apply while a lane/effect/resource event is still open: "
            f"category={blocker['category']} reason={blocker['reason']} "
            f"event_id={blocker['event_id']}"
        )
