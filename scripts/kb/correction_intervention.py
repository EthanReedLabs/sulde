#!/usr/bin/env python3
"""Durable correction interventions across interactive and managed hosts.

The log records observable control-plane facts only.  In particular, an
``applied`` correction means that Sulde delivered it to a safe host boundary
or interrupted a managed run.  It never claims that a model understood the
user's meaning or that the corrected result satisfies the user.

Free-form correction text and native session identifiers never enter the
store.  They are represented by one-way digests so this control plane can be
observed without becoming a second conversation transcript.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import secrets
import time
from typing import Any, Callable, Iterator

from file_lock import lock_exclusive_nonblocking, unlock

contract_identity_digest = runpy.run_path(
    str(Path(__file__).resolve().with_name("sulde_paths.py"))
)["contract_identity_digest"]


EVENT_SCHEMA = "sulde-correction-intervention-event-v1"
PROJECTION_SCHEMA = "sulde-correction-intervention-projection-v1"
STATES = {
    "proposed",
    "queued",
    "applied",
    "rejected",
    "unsupported",
    "cancelled",
}
TERMINAL_STATES = {"applied", "rejected", "unsupported", "cancelled"}
TRANSITIONS = {
    "proposed": {"queued", "rejected", "unsupported", "cancelled"},
    "queued": {"applied", "rejected", "unsupported", "cancelled"},
    "applied": set(),
    "rejected": set(),
    "unsupported": set(),
    "cancelled": set(),
}
HUMAN_SOURCES = {"user_prompt", "human_terminal"}
AGENT_SOURCES = {"agent_monitor", "policy_engine"}
BOUNDARIES = {
    "user_prompt",
    "pre_tool",
    "turn_stop",
    "managed_run_monitor",
    "policy_pause",
    "manual",
}
SUPPORTED_PROVIDERS = {"claude", "codex"}
_ID_RE = re.compile(r"^cor-[0-9a-f]{24}$")
_REASON_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")


class CorrectionInterventionError(RuntimeError):
    """A correction event store or state transition is invalid."""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _contract_stem(contract_path: Path) -> str:
    name = contract_path.name
    return name[:-5] if name.endswith(".json") else name


def event_store_path(contract_path: Path) -> Path:
    return contract_path.with_name(
        f"{_contract_stem(contract_path)}.corrections.jsonl"
    )


def contract_digest(contract_path: Path) -> str:
    return contract_identity_digest(contract_path)


def text_digest(value: Any) -> str:
    return hashlib.sha256(
        str(value or "").encode("utf-8", errors="replace")
    ).hexdigest()


def session_digest(provider: str, session_id: str) -> str:
    return text_digest(f"{provider.strip().lower()}\0{session_id.strip()}")


def _canonical(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError, OverflowError) as error:
        raise CorrectionInterventionError(
            f"correction event is not lossless JSON: {error}"
        ) from error


@contextmanager
def _store_lock(path: Path, *, timeout: float = 3.0) -> Iterator[None]:
    lock_path = path.with_name(f".{path.name}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout
    with lock_path.open("a+", encoding="utf-8") as handle:
        while True:
            try:
                lock_exclusive_nonblocking(handle)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise CorrectionInterventionError(
                        f"correction store lock busy: {lock_path}"
                    )
                time.sleep(0.01)
        try:
            yield
        finally:
            unlock(handle)


def _empty_projection(expected_contract: str) -> dict[str, Any]:
    return {
        "schema": PROJECTION_SCHEMA,
        "contract_sha256": expected_contract,
        "sequence": 0,
        "interventions": {},
        "idempotency": {},
        "updated_at": None,
    }


def _safe_reason(value: Any) -> str:
    reason = str(value or "").strip().lower()
    if not _REASON_RE.fullmatch(reason):
        raise CorrectionInterventionError(
            "reason_code must be a controlled lowercase identifier"
        )
    return reason


def _validate_base(row: Any, expected_contract: str) -> dict[str, Any]:
    if not isinstance(row, dict) or row.get("schema") != EVENT_SCHEMA:
        raise CorrectionInterventionError("unsupported correction event row")
    if row.get("contract_sha256") != expected_contract:
        raise CorrectionInterventionError(
            "correction event belongs to another intent contract"
        )
    try:
        sequence = int(row.get("sequence"))
    except (TypeError, ValueError) as error:
        raise CorrectionInterventionError(
            "correction event sequence is invalid"
        ) from error
    if sequence < 1:
        raise CorrectionInterventionError(
            "correction event sequence must be positive"
        )
    if not isinstance(row.get("at"), str) or not row["at"].strip():
        raise CorrectionInterventionError("correction event timestamp is missing")
    if row.get("type") not in {
        "correction.intervention_proposed",
        "correction.intervention_transitioned",
    }:
        raise CorrectionInterventionError("unsupported correction event type")
    return row


def _apply_event(projection: dict[str, Any], row: dict[str, Any]) -> None:
    intervention_id = str(row.get("intervention_id") or "")
    interventions = projection["interventions"]
    event_type = row["type"]
    if event_type == "correction.intervention_proposed":
        if not _ID_RE.fullmatch(intervention_id) or intervention_id in interventions:
            raise CorrectionInterventionError(
                f"invalid or duplicate correction intervention id: {intervention_id!r}"
            )
        actor = str(row.get("actor") or "")
        source = str(row.get("source") or "")
        if actor == "human" and source not in HUMAN_SOURCES:
            raise CorrectionInterventionError(
                "human correction authority requires a live prompt or human terminal source"
            )
        if actor == "agent" and source not in AGENT_SOURCES:
            raise CorrectionInterventionError(
                "agent correction proposal requires an agent-monitor source"
            )
        if actor not in {"human", "agent"}:
            raise CorrectionInterventionError("correction actor must be human or agent")
        correction_sha256 = str(row.get("correction_sha256") or "")
        lane_sha256 = str(row.get("lane_sha256") or "")
        if not re.fullmatch(r"[0-9a-f]{64}", correction_sha256):
            raise CorrectionInterventionError("correction digest is invalid")
        if not re.fullmatch(r"[0-9a-f]{64}", lane_sha256):
            raise CorrectionInterventionError("correction lane digest is invalid")
        request_sha256 = str(row.get("request_sha256") or "")
        if request_sha256:
            if not re.fullmatch(r"[0-9a-f]{64}", request_sha256):
                raise CorrectionInterventionError("correction request digest is invalid")
            if request_sha256 in projection["idempotency"]:
                raise CorrectionInterventionError(
                    "correction request digest is duplicated"
                )
            projection["idempotency"][request_sha256] = intervention_id
        interventions[intervention_id] = {
            "intervention_id": intervention_id,
            "intent_id_sha256": str(row.get("intent_id_sha256") or ""),
            "intent_revision": int(row.get("intent_revision") or 0),
            "provider": str(row.get("provider") or "unknown"),
            "lane_sha256": lane_sha256,
            "actor": actor,
            "source": source,
            "correction_sha256": correction_sha256,
            "request_sha256": request_sha256 or None,
            "state": "proposed",
            "created_at": row["at"],
            "updated_at": row["at"],
            "boundary": None,
            "reason_code": "proposed",
            "transitions": [
                {
                    "sequence": int(row["sequence"]),
                    "state": "proposed",
                    "at": row["at"],
                    "boundary": None,
                    "reason_code": "proposed",
                    "actor": actor,
                }
            ],
        }
    else:
        intervention = interventions.get(intervention_id)
        if not isinstance(intervention, dict):
            raise CorrectionInterventionError(
                f"correction transition references unknown id: {intervention_id}"
            )
        state = str(row.get("state") or "")
        current = str(intervention.get("state") or "")
        if state not in STATES or state not in TRANSITIONS.get(current, set()):
            raise CorrectionInterventionError(
                f"invalid correction transition: {current} -> {state}"
            )
        boundary = str(row.get("boundary") or "")
        if boundary not in BOUNDARIES:
            raise CorrectionInterventionError(
                f"unsupported correction boundary: {boundary!r}"
            )
        reason_code = _safe_reason(row.get("reason_code"))
        transition_actor = str(row.get("actor") or "system")
        if transition_actor not in {"human", "agent", "system"}:
            raise CorrectionInterventionError(
                "correction transition actor is invalid"
            )
        intervention["state"] = state
        intervention["updated_at"] = row["at"]
        intervention["boundary"] = boundary
        intervention["reason_code"] = reason_code
        intervention["transitions"].append(
            {
                "sequence": int(row["sequence"]),
                "state": state,
                "at": row["at"],
                "boundary": boundary,
                "reason_code": reason_code,
                "actor": transition_actor,
            }
        )
    projection["sequence"] = int(row["sequence"])
    projection["updated_at"] = row["at"]


def replay(contract_path: Path, rows: list[dict[str, Any]]) -> dict[str, Any]:
    expected_contract = contract_digest(contract_path)
    projection = _empty_projection(expected_contract)
    for expected_sequence, raw in enumerate(rows, 1):
        row = _validate_base(raw, expected_contract)
        if int(row["sequence"]) != expected_sequence:
            raise CorrectionInterventionError(
                "correction event sequence is not contiguous"
            )
        _apply_event(projection, row)
    return projection


def _read_rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line_number, raw in enumerate(handle, 1):
                if not raw.strip():
                    continue
                value = json.loads(raw)
                if not isinstance(value, dict):
                    raise CorrectionInterventionError(
                        f"correction row {line_number} is not an object"
                    )
                rows.append(value)
    except json.JSONDecodeError as error:
        raise CorrectionInterventionError(
            f"invalid correction JSONL: {error}"
        ) from error
    return rows


def load_projection(contract_path: Path) -> dict[str, Any]:
    """Replay the append-only source of truth; no materialized cache is trusted."""
    return replay(contract_path, _read_rows(event_store_path(contract_path)))


def authoritative_store_bytes(contract_path: Path) -> bytes:
    store = event_store_path(contract_path)
    return store.read_bytes() if store.is_file() else b""


def authoritative_snapshot(
    contract_path: Path,
) -> tuple[bytes, dict[str, Any]]:
    """Read bytes and replay state under one producer lock before a managed run."""
    store = event_store_path(contract_path)
    with _store_lock(store):
        payload = store.read_bytes() if store.is_file() else b""
        rows: list[dict[str, Any]] = []
        try:
            for raw in payload.decode("utf-8").splitlines():
                if raw.strip():
                    value = json.loads(raw)
                    if not isinstance(value, dict):
                        raise CorrectionInterventionError(
                            "correction snapshot row is not an object"
                        )
                    rows.append(value)
        except (UnicodeError, json.JSONDecodeError) as error:
            raise CorrectionInterventionError(
                f"invalid correction snapshot: {error}"
            ) from error
        return payload, replay(contract_path, rows)


def restore_authoritative_store(contract_path: Path, payload: bytes) -> None:
    """Restore the parent monitor's last accepted append-only prefix."""
    try:
        rows: list[dict[str, Any]] = []
        for raw in payload.decode("utf-8").splitlines():
            if raw.strip():
                value = json.loads(raw)
                if not isinstance(value, dict):
                    raise CorrectionInterventionError(
                        "correction restore row is not an object"
                    )
                rows.append(value)
        replay(contract_path, rows)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise CorrectionInterventionError(
            f"refusing to restore invalid correction bytes: {error}"
        ) from error
    store = event_store_path(contract_path)
    with _store_lock(store):
        store.parent.mkdir(parents=True, exist_ok=True)
        with store.open("wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())


Mutation = Callable[
    [dict[str, Any]],
    tuple[list[dict[str, Any]], Any],
]


def _mutate(contract_path: Path, mutation: Mutation) -> tuple[dict[str, Any], Any]:
    store = event_store_path(contract_path)
    with _store_lock(store):
        projection = replay(contract_path, _read_rows(store))
        specs, result = mutation(projection)
        if not specs:
            return projection, result
        rows: list[dict[str, Any]] = []
        expected_contract = contract_digest(contract_path)
        sequence = int(projection["sequence"])
        for spec in specs:
            sequence += 1
            row = {
                "schema": EVENT_SCHEMA,
                "contract_sha256": expected_contract,
                "sequence": sequence,
                "at": now_iso(),
                **spec,
            }
            _apply_event(projection, _validate_base(row, expected_contract))
            rows.append(row)
        store.parent.mkdir(parents=True, exist_ok=True)
        with store.open("a", encoding="utf-8") as handle:
            for row in rows:
                handle.write(_canonical(row) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return projection, result


def propose_correction(
    contract_path: Path,
    *,
    intent_id: str,
    intent_revision: int,
    provider: str,
    session_id: str,
    correction: str,
    actor: str = "human",
    source: str = "user_prompt",
    request_id: str = "",
    queue: bool = True,
) -> dict[str, Any]:
    """Persist a correction proposal and, when supported, queue it atomically."""
    clean = correction.strip()
    if not clean:
        raise CorrectionInterventionError("correction must be non-empty")
    selected_provider = provider.strip().lower() or "unknown"
    lane = session_id.strip()
    intervention_id = f"cor-{secrets.token_hex(12)}"
    correction_sha256 = text_digest(clean)
    request_sha256 = text_digest(request_id) if request_id.strip() else ""

    def mutation(projection: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
        if request_sha256 and request_sha256 in projection["idempotency"]:
            return [], str(projection["idempotency"][request_sha256])
        specs = [
            {
                "type": "correction.intervention_proposed",
                "intervention_id": intervention_id,
                "intent_id_sha256": text_digest(intent_id),
                "intent_revision": int(intent_revision),
                "provider": selected_provider,
                "lane_sha256": session_digest(selected_provider, lane),
                "actor": actor,
                "source": source,
                "correction_sha256": correction_sha256,
                "request_sha256": request_sha256,
            }
        ]
        if queue and selected_provider in SUPPORTED_PROVIDERS and lane:
            specs.append(
                {
                    "type": "correction.intervention_transitioned",
                    "intervention_id": intervention_id,
                    "state": "queued",
                    "boundary": "user_prompt" if source == "user_prompt" else "manual",
                    "reason_code": "awaiting_safe_boundary",
                    "actor": "system",
                }
            )
        elif queue:
            specs.append(
                {
                    "type": "correction.intervention_transitioned",
                    "intervention_id": intervention_id,
                    "state": "unsupported",
                    "boundary": "user_prompt" if source == "user_prompt" else "manual",
                    "reason_code": "missing_supported_host_lane",
                    "actor": "system",
                }
            )
        return specs, intervention_id

    projection, selected_id = _mutate(contract_path, mutation)
    return dict(projection["interventions"][selected_id])


def transition_correction(
    contract_path: Path,
    intervention_id: str,
    *,
    state: str,
    boundary: str,
    reason_code: str,
    actor: str = "system",
) -> dict[str, Any]:
    if state not in STATES - {"proposed"}:
        raise CorrectionInterventionError(
            f"unsupported correction target state: {state}"
        )
    if boundary not in BOUNDARIES:
        raise CorrectionInterventionError(
            f"unsupported correction boundary: {boundary}"
        )
    clean_reason = _safe_reason(reason_code)

    def mutation(projection: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
        intervention = projection["interventions"].get(intervention_id)
        if not isinstance(intervention, dict):
            raise CorrectionInterventionError(
                f"unknown correction intervention: {intervention_id}"
            )
        current = str(intervention.get("state") or "")
        if current == state:
            return [], intervention_id
        if current in TERMINAL_STATES:
            raise CorrectionInterventionError(
                f"correction intervention is already terminal: {current}"
            )
        return [
            {
                "type": "correction.intervention_transitioned",
                "intervention_id": intervention_id,
                "state": state,
                "boundary": boundary,
                "reason_code": clean_reason,
                "actor": actor,
            }
        ], intervention_id

    projection, selected_id = _mutate(contract_path, mutation)
    return dict(projection["interventions"][selected_id])


def queued_corrections(
    contract_path: Path,
    *,
    provider: str,
    session_id: str,
) -> list[dict[str, Any]]:
    selected_provider = provider.strip().lower() or "unknown"
    lane_sha256 = session_digest(selected_provider, session_id)
    projection = load_projection(contract_path)
    return [
        dict(row)
        for row in projection["interventions"].values()
        if row.get("state") == "queued"
        and row.get("provider") == selected_provider
        and row.get("lane_sha256") == lane_sha256
    ]


def apply_queued_corrections(
    contract_path: Path,
    *,
    provider: str,
    session_id: str,
    boundary: str,
    reason_code: str,
) -> list[dict[str, Any]]:
    """Close queued items only after one observable safe boundary is reached."""
    applied: list[dict[str, Any]] = []
    for row in queued_corrections(
        contract_path,
        provider=provider,
        session_id=session_id,
    ):
        try:
            applied.append(
                transition_correction(
                    contract_path,
                    str(row["intervention_id"]),
                    state="applied",
                    boundary=boundary,
                    reason_code=reason_code,
                    actor="system",
                )
            )
        except CorrectionInterventionError as error:
            # Another host callback may have won the race.  A terminal state is
            # safe to observe, while malformed or missing state must surface.
            current = load_projection(contract_path)["interventions"].get(
                row["intervention_id"]
            )
            if not isinstance(current, dict) or current.get("state") not in TERMINAL_STATES:
                raise error
    return applied


def summary(contract_path: Path) -> dict[str, Any]:
    projection = load_projection(contract_path)
    states = {state: 0 for state in sorted(STATES)}
    for row in projection["interventions"].values():
        states[str(row["state"])] += 1
    return {
        "schema": "sulde-correction-intervention-summary-v1",
        "sequence": projection["sequence"],
        "interventions": len(projection["interventions"]),
        "by_state": states,
        "open": states["proposed"] + states["queued"],
        "queued": states["queued"],
        "updated_at": projection["updated_at"],
    }
