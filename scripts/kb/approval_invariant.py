#!/usr/bin/env python3
"""Append-only approval asked/decided pairing for intent control planes."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import secrets
import tempfile
import time
from typing import Any, Callable, Iterator
from types import SimpleNamespace

_timeout_policy = SimpleNamespace(
    **runpy.run_path(
        str(Path(__file__).resolve().with_name("approval_timeout_policy.py"))
    )
)
ApprovalTimeoutPolicyError = _timeout_policy.ApprovalTimeoutPolicyError
approval_deadlines = _timeout_policy.approval_deadlines
_request_phase = _timeout_policy.request_phase
_cas_schema = SimpleNamespace(
    **runpy.run_path(
        str(Path(__file__).resolve().with_name("approval_cas_schema.py"))
    )
)
ApprovalCASSchemaError = _cas_schema.ApprovalCASSchemaError
approval_decision_identity = _cas_schema.approval_decision_identity
approval_request_identity = _cas_schema.approval_request_identity
fresh_replacement_identity = _cas_schema.fresh_replacement_identity
snapshot_identity = _cas_schema.snapshot_identity
_file_lock = SimpleNamespace(
    **runpy.run_path(str(Path(__file__).resolve().with_name("file_lock.py")))
)
lock_exclusive_nonblocking = _file_lock.lock_exclusive_nonblocking
unlock = _file_lock.unlock
_sulde_paths = SimpleNamespace(
    **runpy.run_path(str(Path(__file__).resolve().with_name("sulde_paths.py")))
)
contract_identity_digest = _sulde_paths.contract_identity_digest


LEGACY_EVENT_SCHEMA = "sulde-approval-pair-event-v1"
EVENT_SCHEMA = "sulde-approval-pair-event-v2"
PROJECTION_SCHEMA = "sulde-approval-pair-projection-v2"
TYPED_RECEIPT_SCHEMA = "sulde-approval-cas-receipt-v1"
REQUEST_BINDING_RECEIPT_SCHEMA = (
    "sulde-approval-request-binding-receipt-v1"
)
DECIDED_REQUEST_RECEIPT_SCHEMA = (
    "sulde-approval-decided-request-receipt-v1"
)
KINDS = {
    "proposal",
    "event",
    "observation-export",
    "intent-confirmation",
    "effect-intervention",
}
OUTCOMES = {
    "allow",
    "approved",
    "cancelled",
    "deny",
    "rejected",
    "replaced",
    "unavailable",
}
LEGACY_OUTCOMES = {"approved", "cancelled", "rejected", "unavailable"}
ROUTES = {"human", "agent", "system"}
_TYPED_AUTHORITY_FIELDS = {
    "typed",
    "snapshot",
    "snapshot_identity",
    "request_identity",
    "replacement_identity",
    "replaced_request_id",
    "replacement_request_id",
    "superseded_by_identity",
    "prompt_shown",
    "prompt_observations",
    "decision_owner",
    "typed_receipt",
    "decision_identity",
    "execution_authorized",
}
_ID_RE = re.compile(r"^apr-[0-9a-f]{24}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_REQUEST_BINDING_RECEIPT_FIELDS = {
    "schema",
    "contract_sha256",
    "request_id",
    "intent_id_sha256",
    "intent_revision",
    "kind",
    "target_sha256",
    "card_sha256",
    "workspace_sha256",
    "proposal_sha256",
    "route",
    "provider",
    "lane_sha256",
    "source",
    "asked_at",
    "expires_at",
    "reassess_at",
    "binding_sha256",
}
_DECIDED_REQUEST_RECEIPT_FIELDS = {
    "schema",
    "contract_sha256",
    "request_id",
    "binding_sha256",
    "outcome",
    "provider",
    "lane_sha256",
    "actor",
    "decided_at",
    "receipt_sha256",
    "decision_sha256",
}


class ApprovalInvariantError(RuntimeError):
    """An approval question/decision sequence is invalid or ambiguous."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _digest(value: Any) -> str:
    return hashlib.sha256(
        str(value or "").encode("utf-8", errors="replace")
    ).hexdigest()


def _canonical_digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8", errors="replace")
    ).hexdigest()


def _is_exact_plain_json(value: Any) -> bool:
    """Reject callbacks, subclasses, non-string keys, and non-JSON scalars."""
    value_type = type(value)
    if value is None or value_type in {str, int, bool}:
        return True
    if value_type is list:
        return all(_is_exact_plain_json(item) for item in value)
    if value_type is dict:
        return all(
            type(key) is str and _is_exact_plain_json(item)
            for key, item in value.items()
        )
    return False


def _strict_canonical(value: Any) -> str:
    if not _is_exact_plain_json(value):
        raise ApprovalInvariantError("approval receipt must be exact plain JSON")
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as error:
        raise ApprovalInvariantError(
            "approval receipt must be exact plain JSON"
        ) from error


def _workspace_digest(workspace: Path | str | None) -> str:
    if workspace is None or not str(workspace).strip():
        return ""
    try:
        identity = str(Path(workspace).expanduser().resolve())
    except OSError:
        identity = str(Path(workspace).expanduser().absolute())
    return _digest(identity)


def _parse_timestamp(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _request_expired(request: dict[str, Any], *, now: datetime | None = None) -> bool:
    expires = _parse_timestamp(str(request.get("expires_at") or ""))
    if expires is None:
        return False
    return expires <= (now or datetime.now(timezone.utc))


def _timeout_refresh_identity(
    previous_request_document: dict[str, Any],
    replacement_request_document: dict[str, Any],
    *,
    previous_expires_at: str,
) -> str:
    """Bind a same-snapshot refresh without aliasing a material replacement."""
    try:
        previous_identity = approval_request_identity(
            previous_request_document
        )
        replacement_identity = approval_request_identity(
            replacement_request_document
        )
    except ApprovalCASSchemaError as error:
        raise _typed_error(error) from error
    envelope = {
        "document": {
            "previous_request_identity": previous_identity,
            "replacement_request_identity": replacement_identity,
            "previous_expires_at": previous_expires_at,
        },
        "kind": "approval-timeout-refresh",
        "schema": "sulde-approval-cas-identity-v1",
    }
    return "sha256:" + hashlib.sha256(
        _strict_canonical(envelope).encode("utf-8")
    ).hexdigest()


def _typed_error(error: Exception) -> ApprovalInvariantError:
    return ApprovalInvariantError(f"typed approval CAS rejected: {error}")


def _validate_typed_snapshot(snapshot: Any) -> tuple[dict[str, Any], str]:
    try:
        identity = snapshot_identity(snapshot)
    except ApprovalCASSchemaError as error:
        raise _typed_error(error) from error
    # The schema leaf rejects dict subclasses and recursively validates every
    # value, so this shallow copy cannot invoke application-defined callbacks.
    return dict(snapshot), str(identity)


def _require_typed_request_id(request_id: str | None) -> str:
    selected = request_id or ("apr-" + secrets.token_hex(12))
    if type(selected) is not str or not _ID_RE.fullmatch(selected):
        raise ApprovalInvariantError(
            "typed approval request id must match apr- plus 24 lowercase hex digits"
        )
    return selected


def _typed_lane_matches(
    snapshot: dict[str, Any],
    *,
    provider: str,
    session_id: str,
    lane_sha256: str | None = None,
) -> bool:
    selected_lane = (
        _lane_digest(provider, session_id)
        if lane_sha256 is None
        else lane_sha256
    )
    return (
        type(provider) is str
        and type(session_id) is str
        and (lane_sha256 is None or type(lane_sha256) is str)
        and provider == snapshot["provider"]
        and session_id == snapshot["session_id"]
        and selected_lane == snapshot["lane_sha256"]
    )


def _contract_digest(path: Path) -> str:
    return contract_identity_digest(path)


def _stem(path: Path) -> str:
    return path.name[:-5] if path.name.endswith(".json") else path.name


def event_store_path(contract_path: Path) -> Path:
    return contract_path.with_name(f"{_stem(contract_path)}.approvals.jsonl")


def _lane_digest(provider: str, session_id: str) -> str:
    selected = provider.strip().lower() or "unknown"
    lane = session_id.strip()
    return _digest(f"{selected}\0{lane}") if lane else ""


def _source_lane(source: str) -> str:
    """Keep native host approval separate from conversational restoration.

    SessionStart, proposal rendering, and UserPromptSubmit may each observe the
    same readable dialogue question.  They are one authority lane.  A Codex
    PermissionRequest is intentionally a distinct lane because only the
    subsequent native Allow action may consume it.
    """
    selected = source.strip() or "unknown"
    return "codex_permission_request" if selected == "codex_permission_request" else "dialogue"


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
                    raise ApprovalInvariantError(
                        f"approval store lock busy: {lock_path}"
                    )
                time.sleep(0.01)
        try:
            yield
        finally:
            unlock(handle)


def _empty(contract_sha256: str) -> dict[str, Any]:
    return {
        "schema": PROJECTION_SCHEMA,
        "contract_sha256": contract_sha256,
        "sequence": 0,
        "requests": {},
        "updated_at": None,
    }


def _apply(projection: dict[str, Any], row: dict[str, Any]) -> None:
    request_id = str(row.get("request_id") or "")
    event_type = str(row.get("type") or "")
    requests = projection["requests"]
    if event_type == "approval.asked":
        typed = row.get("typed") is True
        if not _ID_RE.fullmatch(request_id) or request_id in requests:
            raise ApprovalInvariantError(
                f"invalid or duplicate approval request id: {request_id!r}"
            )
        kind = str(row.get("kind") or "")
        if kind not in KINDS:
            raise ApprovalInvariantError(f"unsupported approval kind: {kind!r}")
        target_sha256 = str(row.get("target_sha256") or "")
        if not typed and not _SHA256_RE.fullmatch(target_sha256):
            raise ApprovalInvariantError("approval target digest is invalid")
        card_sha256 = str(row.get("card_sha256") or "")
        workspace_sha256 = str(row.get("workspace_sha256") or "")
        proposal_sha256 = str(row.get("proposal_sha256") or "")
        for label, digest in (
            ("card", card_sha256),
            ("workspace", workspace_sha256),
            ("proposal", proposal_sha256),
        ):
            if not typed and digest and not _SHA256_RE.fullmatch(digest):
                raise ApprovalInvariantError(
                    f"approval {label} digest is invalid"
                )
        route = str(row.get("route") or "human")
        if route not in ROUTES:
            raise ApprovalInvariantError(f"unsupported approval route: {route!r}")
        expires_at = str(row.get("expires_at") or "")
        if expires_at and _parse_timestamp(expires_at) is None:
            raise ApprovalInvariantError("approval expiry timestamp is invalid")
        reassess_at = str(row.get("reassess_at") or "")
        if reassess_at and _parse_timestamp(reassess_at) is None:
            raise ApprovalInvariantError(
                "approval reassessment timestamp is invalid"
            )
        intent_revision = row.get("intent_revision")
        if type(intent_revision) is not int:
            raise ApprovalInvariantError("approval intent revision is invalid")
        snapshot = row.get("snapshot")
        snapshot_sha256 = str(row.get("snapshot_identity") or "")
        request_sha256 = str(row.get("request_identity") or "")
        replacement_sha256 = str(row.get("replacement_identity") or "")
        replaced_request_id = str(row.get("replaced_request_id") or "")
        if typed:
            if type(row.get("intent_revision")) is not int:
                raise ApprovalInvariantError(
                    "typed approval revision must be an exact int"
                )
            canonical_snapshot, expected_snapshot_identity = (
                _validate_typed_snapshot(snapshot)
            )
            request_document = {
                "request_id": request_id,
                "snapshot": canonical_snapshot,
            }
            try:
                expected_request_identity = approval_request_identity(
                    request_document
                )
            except ApprovalCASSchemaError as error:
                raise _typed_error(error) from error
            if snapshot_sha256 != expected_snapshot_identity:
                raise ApprovalInvariantError(
                    "typed approval snapshot identity is invalid"
                )
            if request_sha256 != expected_request_identity:
                raise ApprovalInvariantError(
                    "typed approval request identity is invalid"
                )
            if row.get("decision_owner") != "human":
                raise ApprovalInvariantError(
                    "typed approval request must remain human-owned"
                )
            if row.get("prompt_shown") is not False:
                raise ApprovalInvariantError(
                    "typed approval request cannot claim an unobserved prompt"
                )
            if (
                canonical_snapshot["card_sha256"] != card_sha256
                or canonical_snapshot["provider"]
                != str(row.get("provider") or "")
                or canonical_snapshot["lane_sha256"]
                != str(row.get("lane_sha256") or "")
                or canonical_snapshot["target_sha256"] != target_sha256
                or canonical_snapshot["revision"] != intent_revision
                or canonical_snapshot["world_state_sha256"]
                != workspace_sha256
                or route != "human"
            ):
                raise ApprovalInvariantError(
                    "typed approval request fields disagree with its snapshot"
                )
            if bool(replaced_request_id) != bool(replacement_sha256):
                raise ApprovalInvariantError(
                    "typed replacement request lineage is incomplete"
                )
            if replaced_request_id:
                previous = requests.get(replaced_request_id)
                if (
                    not isinstance(previous, dict)
                    or previous.get("typed") is not True
                    or previous.get("status") != "replaced"
                    or previous.get("replacement_request_id") != request_id
                ):
                    raise ApprovalInvariantError(
                        "typed replacement lineage has no replaced predecessor"
                    )
                previous_document = {
                    "request_id": replaced_request_id,
                    "snapshot": previous["snapshot"],
                }
                if canonical_snapshot == previous["snapshot"]:
                    previous_expires_at = str(
                        previous.get("expires_at") or ""
                    )
                    expired_at = _parse_timestamp(previous_expires_at)
                    replaced_at = _parse_timestamp(
                        str(previous.get("replacement_at") or "")
                    )
                    if (
                        expired_at is None
                        or replaced_at is None
                        or expired_at > replaced_at
                    ):
                        raise ApprovalInvariantError(
                            "typed timeout refresh predecessor was not expired"
                        )
                    expected_replacement_identity = _timeout_refresh_identity(
                        previous_document,
                        request_document,
                        previous_expires_at=previous_expires_at,
                    )
                else:
                    try:
                        expected_replacement_identity = fresh_replacement_identity(
                            previous_document,
                            request_document,
                            current_snapshot=canonical_snapshot,
                        )
                    except ApprovalCASSchemaError as error:
                        raise _typed_error(error) from error
                if replacement_sha256 != expected_replacement_identity:
                    raise ApprovalInvariantError(
                        "typed replacement lineage identity is invalid"
                    )
        elif any(
            value
            for value in (
                snapshot_sha256,
                request_sha256,
                replacement_sha256,
                replaced_request_id,
            )
        ):
            raise ApprovalInvariantError(
                "legacy approval request cannot carry typed CAS identities"
            )
        stored_request = {
            "request_id": request_id,
            "intent_id_sha256": str(row.get("intent_id_sha256") or ""),
            "intent_revision": intent_revision,
            "kind": kind,
            "target_sha256": target_sha256,
            "card_sha256": card_sha256,
            "workspace_sha256": workspace_sha256,
            "proposal_sha256": proposal_sha256,
            "route": route,
            "expires_at": expires_at,
            "reassess_at": reassess_at,
            "provider": str(row.get("provider") or "unknown"),
            "lane_sha256": str(row.get("lane_sha256") or ""),
            "source": str(row.get("source") or "unknown"),
            "status": "asked",
            "outcome": None,
            "asked_at": row["at"],
            "decided_at": None,
            "decision_provider": None,
            "decision_lane_sha256": None,
            "receipt_sha256": None,
        }
        if typed:
            stored_request.update({
                "typed": True,
                "snapshot": dict(snapshot),
                "snapshot_identity": snapshot_sha256,
                "request_identity": request_sha256,
                "replacement_identity": replacement_sha256 or None,
                "replaced_request_id": replaced_request_id or None,
                "prompt_shown": False,
                "prompt_observations": 0,
                "decision_owner": "human",
                "typed_receipt": None,
                "decision_identity": None,
                "execution_authorized": False,
            })
        requests[request_id] = stored_request
    elif event_type == "approval.prompt-observed":
        request = requests.get(request_id)
        if not isinstance(request, dict) or request.get("typed") is not True:
            raise ApprovalInvariantError(
                "typed prompt observation has no matching typed request"
            )
        if request["status"] != "asked":
            raise ApprovalInvariantError(
                "typed prompt observation targets a terminal request"
            )
        if row.get("decision_owner") != "human":
            raise ApprovalInvariantError(
                "typed prompt observation owner must be human"
            )
        if row.get("prompt_shown") is not True:
            raise ApprovalInvariantError(
                "only a positively observed native prompt may be persisted"
            )
        if (
            row.get("snapshot_identity") != request["snapshot_identity"]
            or str(row.get("provider") or "") != request["provider"]
            or str(row.get("lane_sha256") or "") != request["lane_sha256"]
        ):
            raise ApprovalInvariantError(
                "typed prompt observation does not match its request snapshot"
            )
        request["prompt_shown"] = True
        request["prompt_observations"] = int(
            request["prompt_observations"]
        ) + 1
    elif event_type == "approval.replaced":
        request = requests.get(request_id)
        if not isinstance(request, dict) or request.get("typed") is not True:
            raise ApprovalInvariantError(
                "typed replacement has no matching typed request"
            )
        if request["status"] != "asked" or request.get("typed_receipt"):
            raise ApprovalInvariantError(
                "typed replacement cannot overwrite a decided request"
            )
        replacement_request_id = str(
            row.get("replacement_request_id") or ""
        )
        if not _ID_RE.fullmatch(replacement_request_id):
            raise ApprovalInvariantError(
                "typed replacement request id is invalid"
            )
        replacement_identity = str(row.get("replacement_identity") or "")
        if not replacement_identity.startswith("sha256:"):
            raise ApprovalInvariantError(
                "typed replacement lineage identity is invalid"
            )
        request["status"] = "replaced"
        request["outcome"] = "replaced"
        request["decided_at"] = row["at"]
        request["decision_provider"] = "system"
        request["decision_lane_sha256"] = ""
        request["decision_actor"] = "fresh-replacement-cas"
        request["replacement_request_id"] = replacement_request_id
        request["superseded_by_identity"] = replacement_identity
        request["replacement_at"] = row["at"]
    elif event_type == "approval.decided":
        request = requests.get(request_id)
        if not isinstance(request, dict):
            raise ApprovalInvariantError(
                f"approval decision has no matching question: {request_id}"
            )
        if request["status"] != "asked":
            raise ApprovalInvariantError(
                f"approval request was already decided: {request_id}"
            )
        outcome = str(row.get("outcome") or "")
        if outcome not in OUTCOMES:
            raise ApprovalInvariantError(
                f"approval decision outcome is unsupported: {outcome!r}"
            )
        typed_decision = row.get("typed") is True
        if typed_decision:
            if request.get("typed") is not True:
                raise ApprovalInvariantError(
                    "typed decision cannot consume a legacy request"
                )
            receipt = row.get("typed_receipt")
            if type(receipt) is not dict:
                raise ApprovalInvariantError(
                    "typed approval decision receipt is missing"
                )
            expected_fields = {
                "schema",
                "request_id",
                "receipt_id",
                "outcome",
                "snapshot",
                "snapshot_identity",
                "request_identity",
                "decision_identity",
                "replacement_identity",
                "execution_authorized",
            }
            if set(receipt) != expected_fields:
                raise ApprovalInvariantError(
                    "typed approval receipt fields are invalid"
                )
            if (
                receipt["schema"] != TYPED_RECEIPT_SCHEMA
                or receipt["request_id"] != request_id
                or receipt["outcome"] != outcome
                or receipt["snapshot"] != request["snapshot"]
                or receipt["snapshot_identity"]
                != request["snapshot_identity"]
                or receipt["request_identity"] != request["request_identity"]
                or receipt["replacement_identity"]
                != request["replacement_identity"]
                or receipt["execution_authorized"] is not False
                or outcome not in {"allow", "deny"}
                or str(row.get("provider") or "") != request["provider"]
                or str(row.get("lane_sha256") or "")
                != request["lane_sha256"]
                or str(row.get("receipt_sha256") or "")
                != _digest(receipt.get("receipt_id"))
            ):
                raise ApprovalInvariantError(
                    "typed approval receipt disagrees with its request"
                )
            decision_document = {
                "request_id": request_id,
                "receipt_id": receipt["receipt_id"],
                "outcome": outcome,
                "snapshot": receipt["snapshot"],
            }
            request_document = {
                "request_id": request_id,
                "snapshot": request["snapshot"],
            }
            try:
                expected_decision_identity = approval_decision_identity(
                    decision_document,
                    request=request_document,
                    current_snapshot=request["snapshot"],
                )
            except ApprovalCASSchemaError as error:
                raise _typed_error(error) from error
            if receipt["decision_identity"] != expected_decision_identity:
                raise ApprovalInvariantError(
                    "typed approval decision identity is invalid"
                )
            if (
                row.get("decision_owner") != "human"
                or request.get("decision_owner") != "human"
                or request.get("prompt_shown") is not True
            ):
                raise ApprovalInvariantError(
                    "typed approval decision lacks a shown human-owned prompt"
                )
            request["typed_receipt"] = dict(receipt)
            request["decision_identity"] = expected_decision_identity
        elif request.get("typed") is True:
            if not (
                outcome in {"cancelled", "unavailable"}
                and str(row.get("provider") or "") == "system"
                and not str(row.get("receipt_sha256") or "")
            ):
                raise ApprovalInvariantError(
                    "typed request requires a typed human decision"
                )
        request["status"] = "decided"
        request["outcome"] = outcome
        request["decided_at"] = row["at"]
        request["decision_provider"] = str(
            row.get("provider") or "unknown"
        )
        request["decision_lane_sha256"] = str(row.get("lane_sha256") or "")
        request["receipt_sha256"] = str(row.get("receipt_sha256") or "") or None
        request["decision_actor"] = str(row.get("actor") or "unknown")
    else:
        raise ApprovalInvariantError(
            f"unsupported approval pair event type: {event_type!r}"
        )
    projection["sequence"] = int(row["sequence"])
    projection["updated_at"] = row["at"]


def _validate_event_generation(row: dict[str, Any]) -> None:
    """Validate authority markers per row, independent of file position.

    Production stores can contain legacy audit rows after typed native
    lifecycles. Position is therefore not an authority boundary: only the
    exact schema, event type, and typed marker on the current row can select
    the strict native lifecycle.
    """
    schema = row.get("schema")
    event_type = row.get("type")
    if schema == LEGACY_EVENT_SCHEMA:
        if event_type not in {"approval.asked", "approval.decided"}:
            raise ApprovalInvariantError(
                "legacy approval schema cannot carry typed event types"
            )
        injected = sorted(_TYPED_AUTHORITY_FIELDS.intersection(row))
        if injected:
            raise ApprovalInvariantError(
                "legacy approval row carries typed authority markers: "
                + ", ".join(injected)
            )
        if (
            event_type == "approval.decided"
            and row.get("outcome") not in LEGACY_OUTCOMES
        ):
            raise ApprovalInvariantError(
                "legacy approval decision carries a typed-only outcome"
            )
        return
    if schema != EVENT_SCHEMA:
        raise ApprovalInvariantError("unsupported approval pair row")
    if event_type in {"approval.prompt-observed", "approval.replaced"}:
        if row.get("typed") is not True:
            raise ApprovalInvariantError(
                "typed approval event must carry the v2 typed marker"
            )
    elif event_type in {"approval.asked", "approval.decided"}:
        if "typed" in row and row.get("typed") is not True:
            raise ApprovalInvariantError(
                "v2 typed marker must be exact true when present"
            )
        if row.get("typed") is not True:
            injected = sorted(
                (_TYPED_AUTHORITY_FIELDS - {"typed"}).intersection(row)
            )
            if injected:
                raise ApprovalInvariantError(
                    "untyped v2 approval row carries typed authority markers: "
                    + ", ".join(injected)
                )
            if (
                event_type == "approval.decided"
                and row.get("outcome") not in LEGACY_OUTCOMES
            ):
                raise ApprovalInvariantError(
                    "untyped v2 approval decision carries a typed-only outcome"
                )
    return


def replay(contract_path: Path, rows: list[dict[str, Any]]) -> dict[str, Any]:
    contract_sha256 = _contract_digest(contract_path)
    projection = _empty(contract_sha256)
    for sequence, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            raise ApprovalInvariantError("unsupported approval pair row")
        _validate_event_generation(row)
        if row.get("contract_sha256") != contract_sha256:
            raise ApprovalInvariantError(
                "approval pair row belongs to another contract"
            )
        actual_sequence = row.get("sequence")
        if type(actual_sequence) is not int:
            raise ApprovalInvariantError("approval pair sequence is invalid")
        if actual_sequence != sequence:
            raise ApprovalInvariantError(
                "approval pair sequence is not contiguous"
            )
        if not isinstance(row.get("at"), str) or not row["at"].strip():
            raise ApprovalInvariantError("approval pair timestamp is missing")
        _apply(projection, row)
    return projection


def _decode_row(raw: bytes) -> dict[str, Any]:
    if not raw.strip():
        raise ApprovalInvariantError("approval pair store has a blank row")
    try:
        value = json.loads(
            raw.decode("utf-8"),
            parse_constant=lambda token: (_ for _ in ()).throw(
                ValueError(f"non-JSON constant {token}")
            ),
        )
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ApprovalInvariantError(f"invalid approval pair JSONL: {error}") from error
    except ValueError as error:
        raise ApprovalInvariantError(f"invalid approval pair JSONL: {error}") from error
    if type(value) is not dict or not _is_exact_plain_json(value):
        raise ApprovalInvariantError(
            "approval pair row is not an exact plain JSON object"
        )
    return value


def _read_rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    payload = path.read_bytes()
    if payload and not payload.endswith(b"\n"):
        raise ApprovalInvariantError("approval pair store has an incomplete tail")
    rows = [_decode_row(raw) for raw in payload.splitlines()]
    return rows


def _target_projection(
    contract_path: Path,
    request_id: str,
    *,
    terminal: bool,
) -> dict[str, Any]:
    """Replay only the authoritative prefix needed for one durable request."""
    if type(request_id) is not str or not _ID_RE.fullmatch(request_id):
        raise ApprovalInvariantError("approval receipt request id is invalid")
    store = event_store_path(contract_path)
    if not store.is_file():
        raise ApprovalInvariantError("approval receipt request disappeared")
    rows: list[dict[str, Any]] = []
    projection: dict[str, Any] | None = None
    for raw in store.read_bytes().splitlines(keepends=True):
        if not raw.endswith(b"\n"):
            raise ApprovalInvariantError(
                "approval pair store has an incomplete target prefix"
            )
        row = _decode_row(raw[:-1])
        rows.append(row)
        if (
            row.get("type") == "approval.asked"
            and row.get("request_id") == request_id
        ):
            projection = replay(contract_path, rows)
            if not terminal:
                return projection
        elif projection is not None and row.get("request_id") == request_id:
            projection = replay(contract_path, rows)
            request = projection["requests"].get(request_id)
            if isinstance(request, dict) and request.get("status") != "asked":
                return projection
    if projection is None:
        raise ApprovalInvariantError("approval receipt request disappeared")
    return projection


def load_projection(contract_path: Path) -> dict[str, Any]:
    return replay(contract_path, _read_rows(event_store_path(contract_path)))


def authoritative_store_bytes(contract_path: Path) -> bytes:
    """Return the exact append-only approval prefix accepted by the supervisor."""
    store = event_store_path(contract_path)
    return store.read_bytes() if store.is_file() else b""


def restore_authoritative_store(contract_path: Path, payload: bytes) -> None:
    """Atomically restore a previously replayed approval prefix after tampering."""
    try:
        text = payload.decode("utf-8")
        rows: list[dict[str, Any]] = []
        if payload and not payload.endswith(b"\n"):
            raise ApprovalInvariantError(
                "refusing to restore an incomplete approval prefix"
            )
        for raw in text.splitlines():
            if not raw.strip():
                raise ApprovalInvariantError(
                    "refusing to restore an approval prefix with blank rows"
                )
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise ApprovalInvariantError(
                    "approval restore row is not an object"
                )
            rows.append(value)
        replay(contract_path, rows)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ApprovalInvariantError(
            f"refusing to restore invalid approval bytes: {error}"
        ) from error

    store = event_store_path(contract_path)
    with _store_lock(store):
        store.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{store.name}.", suffix=".tmp", dir=str(store.parent)
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, store)
            if os.name != "nt":
                directory = os.open(store.parent, os.O_RDONLY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass


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
        sequence = int(projection["sequence"])
        rows: list[dict[str, Any]] = []
        for spec in specs:
            sequence += 1
            row = {
                "schema": EVENT_SCHEMA,
                "contract_sha256": _contract_digest(contract_path),
                "sequence": sequence,
                "at": _now(),
                **spec,
            }
            _apply(projection, row)
            rows.append(row)
        store.parent.mkdir(parents=True, exist_ok=True)
        created = not store.exists()
        descriptor = os.open(store, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
        if os.name != "nt":
            os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "a", encoding="utf-8") as handle:
            for row in rows:
                handle.write(
                    json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
                )
            handle.flush()
            os.fsync(handle.fileno())
        if created and os.name != "nt":
            directory = os.open(store.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        return projection, result


def ask_approval(
    contract_path: Path,
    *,
    intent_id: str,
    intent_revision: int,
    kind: str,
    target: str,
    provider: str = "unknown",
    session_id: str = "",
    source: str,
    card: Any | None = None,
    workspace: Path | str | None = None,
    route: str = "human",
    ttl_seconds: int = 86_400,
    reassess_after_seconds: int | None = None,
    reuse_decided: bool = False,
) -> dict[str, Any]:
    if kind not in KINDS:
        raise ApprovalInvariantError(f"unsupported approval kind: {kind}")
    if not target.strip():
        raise ApprovalInvariantError("approval target must be non-empty")
    selected_provider = provider.strip().lower() or "unknown"
    selected_route = route.strip().lower() or "human"
    if selected_route not in ROUTES:
        raise ApprovalInvariantError(f"unsupported approval route: {selected_route}")
    try:
        ttl = int(ttl_seconds)
    except (TypeError, ValueError) as error:
        raise ApprovalInvariantError("approval ttl_seconds must be an integer") from error
    if ttl <= 0 or ttl > 2_592_000:
        raise ApprovalInvariantError(
            "approval ttl_seconds must be between 1 and 2592000"
        )
    lane_sha256 = _lane_digest(selected_provider, session_id)
    target_sha256 = _digest(target)
    card_sha256 = _canonical_digest(card) if card is not None else ""
    workspace_sha256 = _workspace_digest(workspace)
    proposal_sha256 = target_sha256 if kind == "proposal" else ""
    current_time = datetime.now(timezone.utc)
    reassess_at = ""
    if reassess_after_seconds is None:
        expires_at = (current_time + timedelta(seconds=ttl)).isoformat()
    else:
        try:
            reassess_at, expires_at = approval_deadlines(
                now=current_time,
                reassess_after_seconds=reassess_after_seconds,
                ttl_seconds=ttl,
            )
        except ApprovalTimeoutPolicyError as error:
            raise ApprovalInvariantError(str(error)) from error
    request_id = "apr-" + secrets.token_hex(12)

    def mutation(projection: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
        open_requests = [
            row
            for row in projection["requests"].values()
            if row["status"] == "asked" and not _request_expired(row)
        ]
        existing = next(
            (
                row
                for row in open_requests
                if row["kind"] == kind
                and row["target_sha256"] == target_sha256
                and row["provider"] == selected_provider
                and row["lane_sha256"] == lane_sha256
                and row["card_sha256"] == card_sha256
                and row["workspace_sha256"] == workspace_sha256
                and row["route"] == selected_route
                and _source_lane(row["source"]) == _source_lane(source)
            ),
            None,
        )
        if existing is None and selected_provider == "unknown" and not lane_sha256:
            target_matches = [
                row
                for row in open_requests
                if row["kind"] == kind
                and row["target_sha256"] == target_sha256
                and row["card_sha256"] == card_sha256
                and row["workspace_sha256"] == workspace_sha256
                and row["route"] == selected_route
                and _source_lane(row["source"]) == _source_lane(source)
            ]
            if len(target_matches) == 1:
                existing = target_matches[0]
        if existing is not None:
            return [], str(existing["request_id"])
        if reuse_decided:
            decided_matches = [
                row
                for row in projection["requests"].values()
                if row["status"] == "decided"
                and row["outcome"] in {"approved", "rejected"}
                and row["kind"] == kind
                and row["target_sha256"] == target_sha256
                and row["card_sha256"] == card_sha256
                and row["workspace_sha256"] == workspace_sha256
                and row["route"] == selected_route
                and _source_lane(row["source"]) == _source_lane(source)
            ]
            if len(decided_matches) == 1:
                return [], str(decided_matches[0]["request_id"])
        specs: list[dict[str, Any]] = []
        if kind in {"proposal", "intent-confirmation"}:
            for row in open_requests:
                if (
                    row["kind"] in {"proposal", "intent-confirmation"}
                    and row["request_id"] != (existing or {}).get("request_id")
                    and (
                        row["kind"] != kind
                        or row["target_sha256"] != target_sha256
                        or row["card_sha256"] != card_sha256
                        or row["workspace_sha256"] != workspace_sha256
                    )
                ):
                    specs.append(
                        {
                            "type": "approval.decided",
                            "request_id": row["request_id"],
                            "outcome": "cancelled",
                            "provider": "system",
                            "lane_sha256": "",
                            "receipt_sha256": "",
                            "actor": "proposal-supersession",
                        }
                    )
        specs.append(
            {
                "type": "approval.asked",
                "request_id": request_id,
                "intent_id_sha256": _digest(intent_id),
                "intent_revision": int(intent_revision),
                "kind": kind,
                "target_sha256": target_sha256,
                "card_sha256": card_sha256,
                "workspace_sha256": workspace_sha256,
                "proposal_sha256": proposal_sha256,
                "route": selected_route,
                "expires_at": expires_at,
                "reassess_at": reassess_at,
                "provider": selected_provider,
                "lane_sha256": lane_sha256,
                "source": source,
            }
        )
        return specs, request_id

    projection, selected_id = _mutate(contract_path, mutation)
    return dict(projection["requests"][selected_id])


def decide_approval(
    contract_path: Path,
    *,
    kind: str,
    target: str,
    outcome: str,
    provider: str,
    session_id: str,
    actor: str,
    receipt_id: str = "",
    card: Any | None = None,
    workspace: Path | str | None = None,
    route: str | None = None,
    source: str | None = None,
) -> dict[str, Any]:
    if outcome not in OUTCOMES:
        raise ApprovalInvariantError(f"unsupported approval outcome: {outcome}")
    selected_provider = provider.strip().lower() or "unknown"
    lane_sha256 = _lane_digest(selected_provider, session_id)
    target_sha256 = _digest(target)
    card_sha256 = _canonical_digest(card) if card is not None else None
    workspace_sha256 = (
        _workspace_digest(workspace) if workspace is not None else None
    )
    selected_route = route.strip().lower() if route is not None else None
    if selected_route is not None and selected_route not in ROUTES:
        raise ApprovalInvariantError(f"unsupported approval route: {selected_route}")
    selected_source = source.strip() if source is not None else None
    if selected_source is not None and not selected_source:
        raise ApprovalInvariantError("approval source filter must be non-empty")
    selected_receipt_sha256 = _digest(receipt_id) if receipt_id else ""

    def matches_binding(row: dict[str, Any]) -> bool:
        return (
            (card_sha256 is None or row["card_sha256"] == card_sha256)
            and (
                workspace_sha256 is None
                or row["workspace_sha256"] == workspace_sha256
            )
            and (selected_route is None or row["route"] == selected_route)
            and (
                selected_source is None
                or _source_lane(row["source"]) == _source_lane(selected_source)
            )
        )

    def mutation(
        projection: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], tuple[str, bool]]:
        candidates = [
            row
            for row in projection["requests"].values()
            if row["status"] == "asked"
            and not _request_expired(row)
            and row["kind"] == kind
            and row["target_sha256"] == target_sha256
            and matches_binding(row)
        ]
        exact = [
            row
            for row in candidates
            if row["provider"] == selected_provider
            and row["lane_sha256"] == lane_sha256
        ]
        unbound = [
            row
            for row in candidates
            if row["provider"] == "unknown" and not row["lane_sha256"]
        ]
        selected = exact or unbound or (
            candidates if selected_provider == "unknown" else []
        )
        if len(selected) == 0:
            decided = [
                row
                for row in projection["requests"].values()
                if row["status"] == "decided"
                and row["kind"] == kind
                and row["target_sha256"] == target_sha256
                and row["outcome"] == outcome
                and matches_binding(row)
            ]
            same_lane = [
                row
                for row in decided
                if row.get("decision_provider") == selected_provider
                and row.get("decision_lane_sha256") == lane_sha256
                and (row.get("receipt_sha256") or "")
                == selected_receipt_sha256
            ]
            idempotent = same_lane or (
                decided
                if len(decided) == 1
                and decided[0]["route"] == "human"
                and (decided[0].get("receipt_sha256") or "")
                == selected_receipt_sha256
                else []
            )
            if len(idempotent) == 1:
                return [], (str(idempotent[0]["request_id"]), True)
        if len(selected) != 1:
            raise ApprovalInvariantError(
                "approval decision does not match exactly one open question"
            )
        request_id = str(selected[0]["request_id"])
        return [
            {
                "type": "approval.decided",
                "request_id": request_id,
                "outcome": outcome,
                "provider": selected_provider,
                "lane_sha256": lane_sha256,
                "receipt_sha256": selected_receipt_sha256,
                "actor": actor,
            }
        ], (request_id, False)

    projection, result = _mutate(contract_path, mutation)
    request_id, idempotent = result
    answer = dict(projection["requests"][request_id])
    answer["idempotent"] = idempotent
    return answer


def ask_typed_approval(
    contract_path: Path,
    *,
    snapshot: dict[str, Any],
    kind: str,
    source: str,
    request_id: str | None = None,
    intent_id: str = "typed-approval",
    previous_request_id: str | None = None,
    ttl_seconds: int = 86_400,
    reassess_after_seconds: int = 300,
) -> dict[str, Any]:
    """Append one strict T11 request, optionally replacing a stale lineage.

    The request starts with ``prompt_shown=False``.  Creating or replacing a
    card is correlation state only; neither operation emits a receipt or grants
    effect authority.
    """
    canonical_snapshot, snapshot_sha256 = _validate_typed_snapshot(snapshot)
    selected_id = _require_typed_request_id(request_id)
    if kind not in KINDS:
        raise ApprovalInvariantError(f"unsupported approval kind: {kind}")
    if type(source) is not str or not source.strip():
        raise ApprovalInvariantError("typed approval source must be non-empty")
    if type(intent_id) is not str or not intent_id.strip():
        raise ApprovalInvariantError("typed approval intent_id must be non-empty")
    if type(ttl_seconds) is not int or type(reassess_after_seconds) is not int:
        raise ApprovalInvariantError(
            "typed approval deadlines must be exact integers"
        )
    try:
        reassess_at, expires_at = approval_deadlines(
            now=datetime.now(timezone.utc),
            reassess_after_seconds=reassess_after_seconds,
            ttl_seconds=ttl_seconds,
        )
        request_sha256 = approval_request_identity(
            {"request_id": selected_id, "snapshot": canonical_snapshot}
        )
    except (ApprovalTimeoutPolicyError, ApprovalCASSchemaError) as error:
        raise _typed_error(error) from error

    def mutation(
        projection: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], str]:
        requests = projection["requests"]
        if (
            previous_request_id is not None
            and selected_id == previous_request_id
        ):
            raise ApprovalInvariantError(
                "typed replacement must use a new request id"
            )
        existing_id = requests.get(selected_id)
        if isinstance(existing_id, dict):
            if (
                existing_id.get("typed") is True
                and existing_id.get("request_identity") == request_sha256
            ):
                return [], selected_id
            raise ApprovalInvariantError(
                "typed approval request id is already bound to another snapshot"
            )

        equivalent = [
            row
            for row in requests.values()
            if row.get("typed") is True
            and row.get("kind") == kind
            and row.get("snapshot_identity") == snapshot_sha256
        ]
        terminal_equivalent = [
            row
            for row in equivalent
            if row.get("status") not in {"asked", "replaced"}
        ]
        open_equivalent = [
            row for row in equivalent if row.get("status") == "asked"
        ]
        if terminal_equivalent:
            raise ApprovalInvariantError(
                "typed approval snapshot already has a terminal one-shot request"
            )
        if open_equivalent:
            if len(open_equivalent) != 1:
                raise ApprovalInvariantError(
                    "typed approval snapshot has duplicate open requests"
                )
            open_request = open_equivalent[0]
            if previous_request_id is None:
                return [], str(open_request["request_id"])
            if open_request.get("request_id") != previous_request_id:
                raise ApprovalInvariantError(
                    "typed timeout refresh does not target the open request"
                )
            if not _request_expired(open_request):
                raise ApprovalInvariantError(
                    "typed timeout refresh predecessor is not expired"
                )
        elif equivalent:
            raise ApprovalInvariantError(
                "typed approval snapshot has no open refresh predecessor"
            )

        replacement_sha256 = ""
        if previous_request_id is not None:
            if type(previous_request_id) is not str:
                raise ApprovalInvariantError(
                    "typed previous request id must be an exact string"
                )
            previous = requests.get(previous_request_id)
            if not isinstance(previous, dict) or previous.get("typed") is not True:
                raise ApprovalInvariantError(
                    "typed replacement has no matching previous request"
                )
            if previous["status"] != "asked" or previous.get("typed_receipt"):
                raise ApprovalInvariantError(
                    "typed replacement cannot overwrite a human decision"
                )
            previous_document = {
                "request_id": previous_request_id,
                "snapshot": previous["snapshot"],
            }
            replacement_document = {
                "request_id": selected_id,
                "snapshot": canonical_snapshot,
            }
            if previous["snapshot"] == canonical_snapshot:
                if not _request_expired(previous):
                    raise ApprovalInvariantError(
                        "typed timeout refresh predecessor is not expired"
                    )
                replacement_sha256 = _timeout_refresh_identity(
                    previous_document,
                    replacement_document,
                    previous_expires_at=str(previous.get("expires_at") or ""),
                )
            else:
                try:
                    replacement_sha256 = fresh_replacement_identity(
                        previous_document,
                        replacement_document,
                        current_snapshot=canonical_snapshot,
                    )
                except ApprovalCASSchemaError as error:
                    raise _typed_error(error) from error
            replacement_spec = {
                "type": "approval.replaced",
                "typed": True,
                "request_id": previous_request_id,
                "replacement_request_id": selected_id,
                "replacement_identity": replacement_sha256,
            }
            replaced_request_id = previous_request_id
        else:
            conflicting = [
                row
                for row in requests.values()
                if row.get("typed") is True
                and row["status"] == "asked"
                and row["kind"] == kind
                and row["target_sha256"]
                == canonical_snapshot["target_sha256"]
            ]
            if conflicting:
                raise ApprovalInvariantError(
                    "typed approval target already has an open request; "
                    "fresh replacement lineage is required"
                )
            replacement_spec = None
            replaced_request_id = ""

        asked_spec = {
            "type": "approval.asked",
            "typed": True,
            "request_id": selected_id,
            "intent_id_sha256": _digest(intent_id),
            "intent_revision": canonical_snapshot["revision"],
            "kind": kind,
            "target_sha256": canonical_snapshot["target_sha256"],
            "card_sha256": canonical_snapshot["card_sha256"],
            "workspace_sha256": canonical_snapshot["world_state_sha256"],
            "proposal_sha256": (
                canonical_snapshot["target_sha256"]
                if kind == "proposal"
                else ""
            ),
            "route": "human",
            "expires_at": expires_at,
            "reassess_at": reassess_at,
            "provider": canonical_snapshot["provider"],
            "lane_sha256": canonical_snapshot["lane_sha256"],
            "source": source,
            "snapshot": canonical_snapshot,
            "snapshot_identity": snapshot_sha256,
            "request_identity": request_sha256,
            "decision_owner": "human",
            "prompt_shown": False,
            "replacement_identity": replacement_sha256,
            "replaced_request_id": replaced_request_id,
        }
        specs = [asked_spec]
        if replacement_spec is not None:
            specs.insert(0, replacement_spec)
        return specs, selected_id

    projection, selected = _mutate(contract_path, mutation)
    return dict(projection["requests"][selected])


def replace_typed_approval(
    contract_path: Path,
    *,
    previous_request_id: str,
    snapshot: dict[str, Any],
    kind: str,
    source: str,
    request_id: str | None = None,
    intent_id: str = "typed-approval",
    ttl_seconds: int = 86_400,
    reassess_after_seconds: int = 300,
) -> dict[str, Any]:
    """Create a fresh typed request with explicit immutable lineage."""
    return ask_typed_approval(
        contract_path,
        snapshot=snapshot,
        kind=kind,
        source=source,
        request_id=request_id,
        intent_id=intent_id,
        previous_request_id=previous_request_id,
        ttl_seconds=ttl_seconds,
        reassess_after_seconds=reassess_after_seconds,
    )


def observe_typed_prompt(
    contract_path: Path,
    *,
    request_id: str,
    snapshot: dict[str, Any],
    provider: str,
    session_id: str,
    lane_sha256: str | None = None,
    prompt_shown: bool,
    decision_owner: str,
) -> dict[str, Any]:
    """Persist only a positive native prompt observation for one snapshot."""
    canonical_snapshot, snapshot_sha256 = _validate_typed_snapshot(snapshot)
    if type(prompt_shown) is not bool:
        raise ApprovalInvariantError("prompt_shown must be an exact bool")
    if type(decision_owner) is not str or decision_owner != "human":
        raise ApprovalInvariantError(
            "typed prompt decision_owner must be exact human"
        )
    if not _typed_lane_matches(
        canonical_snapshot,
        provider=provider,
        session_id=session_id,
        lane_sha256=lane_sha256,
    ):
        raise ApprovalInvariantError(
            "typed prompt provider/session/lane does not match its snapshot"
        )

    def mutation(
        projection: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], str]:
        request = projection["requests"].get(request_id)
        if not isinstance(request, dict) or request.get("typed") is not True:
            raise ApprovalInvariantError(
                "typed prompt has no matching request"
            )
        if request["status"] != "asked" or _request_expired(request):
            raise ApprovalInvariantError(
                "typed prompt targets a terminal or expired request"
            )
        if request["snapshot_identity"] != snapshot_sha256:
            raise ApprovalInvariantError(
                "typed prompt snapshot is stale"
            )
        if not prompt_shown or request.get("prompt_shown") is True:
            return [], request_id
        return [{
            "type": "approval.prompt-observed",
            "typed": True,
            "request_id": request_id,
            "snapshot_identity": snapshot_sha256,
            "provider": provider,
            "lane_sha256": canonical_snapshot["lane_sha256"],
            "prompt_shown": True,
            "decision_owner": "human",
        }], request_id

    projection, selected = _mutate(contract_path, mutation)
    return dict(projection["requests"][selected])


def decide_typed_approval(
    contract_path: Path,
    *,
    request_id: str,
    receipt_id: str,
    outcome: str,
    snapshot: dict[str, Any],
    current_snapshot: dict[str, Any],
    provider: str,
    session_id: str,
    lane_sha256: str | None = None,
    decision_owner: str,
    actor: str,
) -> dict[str, Any]:
    """Append one human Allow/Deny receipt after a locked world-snapshot CAS.

    The returned receipt is deliberately data-only and always carries
    ``execution_authorized=False``.  T13 must independently replay this store
    and revalidate the snapshot before advancing its own journal transaction.
    """
    canonical_snapshot, snapshot_sha256 = _validate_typed_snapshot(snapshot)
    canonical_current, _current_identity = _validate_typed_snapshot(
        current_snapshot
    )
    if type(receipt_id) is not str or not receipt_id.strip():
        raise ApprovalInvariantError("typed receipt id must be non-empty")
    if type(outcome) is not str or outcome not in {"allow", "deny"}:
        raise ApprovalInvariantError("typed decision outcome must be allow or deny")
    if type(decision_owner) is not str or decision_owner != "human":
        raise ApprovalInvariantError(
            "typed decision owner must be exact human"
        )
    if type(actor) is not str or not actor.strip():
        raise ApprovalInvariantError("typed human decision actor is required")
    if not _typed_lane_matches(
        canonical_snapshot,
        provider=provider,
        session_id=session_id,
        lane_sha256=lane_sha256,
    ):
        raise ApprovalInvariantError(
            "typed decision provider/session/lane does not match its snapshot"
        )
    request_document = {
        "request_id": request_id,
        "snapshot": canonical_snapshot,
    }
    decision_document = {
        "request_id": request_id,
        "receipt_id": receipt_id,
        "outcome": outcome,
        "snapshot": canonical_snapshot,
    }
    try:
        request_sha256 = approval_request_identity(request_document)
        decision_sha256 = approval_decision_identity(
            decision_document,
            request=request_document,
            current_snapshot=canonical_current,
        )
    except ApprovalCASSchemaError as error:
        raise _typed_error(error) from error

    def mutation(
        projection: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], str]:
        request = projection["requests"].get(request_id)
        if not isinstance(request, dict) or request.get("typed") is not True:
            raise ApprovalInvariantError(
                "typed decision has no matching request"
            )
        if request["status"] != "asked" or request.get("typed_receipt"):
            raise ApprovalInvariantError(
                "typed approval request was already decided or replaced"
            )
        if _request_expired(request):
            raise ApprovalInvariantError("typed approval request has expired")
        if request.get("prompt_shown") is not True:
            raise ApprovalInvariantError(
                "typed approval prompt was not shown"
            )
        if request.get("decision_owner") != "human":
            raise ApprovalInvariantError(
                "typed approval request is not human-owned"
            )
        if (
            request.get("snapshot_identity") != snapshot_sha256
            or request.get("request_identity") != request_sha256
        ):
            raise ApprovalInvariantError(
                "typed decision request snapshot is stale"
            )
        receipt = {
            "schema": TYPED_RECEIPT_SCHEMA,
            "request_id": request_id,
            "receipt_id": receipt_id,
            "outcome": outcome,
            "snapshot": canonical_snapshot,
            "snapshot_identity": snapshot_sha256,
            "request_identity": request_sha256,
            "decision_identity": decision_sha256,
            "replacement_identity": request.get("replacement_identity"),
            "execution_authorized": False,
        }
        return [{
            "type": "approval.decided",
            "typed": True,
            "request_id": request_id,
            "outcome": outcome,
            "provider": provider,
            "lane_sha256": canonical_snapshot["lane_sha256"],
            "receipt_sha256": _digest(receipt_id),
            "actor": actor[:100],
            "decision_owner": "human",
            "typed_receipt": receipt,
        }], request_id

    projection, selected = _mutate(contract_path, mutation)
    return dict(projection["requests"][selected]["typed_receipt"])


def typed_receipts(contract_path: Path) -> list[dict[str, Any]]:
    """Return replay-validated, non-authoritative receipts for T13."""
    receipts = [
        dict(row["typed_receipt"])
        for row in load_projection(contract_path)["requests"].values()
        if type(row.get("typed_receipt")) is dict
    ]
    return sorted(
        receipts,
        key=lambda row: (row["request_id"], row["receipt_id"]),
    )


# A descriptive alias for adapters that do not expose the storage model.
observe_approval_prompt = observe_typed_prompt


def open_requests(
    contract_path: Path,
    *,
    kind: str | None = None,
    workspace: Path | str | None = None,
    route: str | None = None,
) -> list[dict[str, Any]]:
    """Return effective open requests, excluding expired durable questions."""
    if kind is not None and kind not in KINDS:
        raise ApprovalInvariantError(f"unsupported approval kind: {kind}")
    selected_route = route.strip().lower() if route is not None else None
    if selected_route is not None and selected_route not in ROUTES:
        raise ApprovalInvariantError(f"unsupported approval route: {selected_route}")
    workspace_sha256 = (
        _workspace_digest(workspace) if workspace is not None else None
    )
    rows = []
    for request in load_projection(contract_path)["requests"].values():
        if request["status"] != "asked" or _request_expired(request):
            continue
        if kind is not None and request["kind"] != kind:
            continue
        if (
            workspace_sha256 is not None
            and request["workspace_sha256"] != workspace_sha256
        ):
            continue
        if selected_route is not None and request["route"] != selected_route:
            continue
        rows.append(dict(request))
    return sorted(rows, key=lambda row: (row["asked_at"], row["request_id"]))


def request_for_binding(
    contract_path: Path,
    *,
    kind: str,
    target: str,
    provider: str,
    session_id: str,
    card: Any,
    workspace: Path | str,
    route: str,
    source: str,
    status: str | None = None,
) -> dict[str, Any] | None:
    """Read one exact approval request without creating new authority state."""
    if kind not in KINDS:
        raise ApprovalInvariantError(f"unsupported approval kind: {kind}")
    selected_provider = provider.strip().lower() or "unknown"
    selected_route = route.strip().lower()
    if selected_route not in ROUTES:
        raise ApprovalInvariantError(f"unsupported approval route: {selected_route}")
    if status is not None and status not in {"asked", "decided"}:
        raise ApprovalInvariantError("approval request status filter is invalid")
    lane_sha256 = _lane_digest(selected_provider, session_id)
    target_sha256 = _digest(target)
    card_sha256 = _canonical_digest(card)
    workspace_sha256 = _workspace_digest(workspace)
    matches = [
        row
        for row in load_projection(contract_path)["requests"].values()
        if row["kind"] == kind
        and row["target_sha256"] == target_sha256
        and row["provider"] == selected_provider
        and row["lane_sha256"] == lane_sha256
        and row["card_sha256"] == card_sha256
        and row["workspace_sha256"] == workspace_sha256
        and row["route"] == selected_route
        and _source_lane(row["source"]) == _source_lane(source)
        and (status is None or row["status"] == status)
        and (
            status != "asked"
            or not _request_expired(row)
        )
    ]
    if len(matches) > 1:
        raise ApprovalInvariantError(
            "approval binding matches more than one durable request"
        )
    return dict(matches[0]) if matches else None


def request_by_id(contract_path: Path, request_id: str) -> dict[str, Any] | None:
    """Read one durable request by its unguessable journal binding."""
    row = load_projection(contract_path)["requests"].get(request_id)
    return dict(row) if isinstance(row, dict) else None


def _binding_receipt_from_request(
    contract_path: Path,
    request: dict[str, Any],
) -> dict[str, Any]:
    receipt = {
        "schema": REQUEST_BINDING_RECEIPT_SCHEMA,
        "contract_sha256": _contract_digest(contract_path),
        "request_id": request["request_id"],
        "intent_id_sha256": request["intent_id_sha256"],
        "intent_revision": request["intent_revision"],
        "kind": request["kind"],
        "target_sha256": request["target_sha256"],
        "card_sha256": request["card_sha256"],
        "workspace_sha256": request["workspace_sha256"],
        "proposal_sha256": request["proposal_sha256"],
        "route": request["route"],
        "provider": request["provider"],
        "lane_sha256": request["lane_sha256"],
        "source": request["source"],
        "asked_at": request["asked_at"],
        "expires_at": request["expires_at"],
        "reassess_at": request["reassess_at"],
    }
    if type(receipt["intent_revision"]) is not int:
        raise ApprovalInvariantError(
            "approval receipt intent revision must be an exact integer"
        )
    if any(
        type(value) is not str
        for key, value in receipt.items()
        if key != "intent_revision"
    ):
        raise ApprovalInvariantError("approval request binding fields are invalid")
    receipt["binding_sha256"] = hashlib.sha256(
        _strict_canonical(receipt).encode("utf-8")
    ).hexdigest()
    return receipt


def request_binding_receipt(
    contract_path: Path,
    request_id: str,
) -> dict[str, Any]:
    """Return a read-only receipt for one independently replayed request prefix."""
    projection = _target_projection(contract_path, request_id, terminal=False)
    request = projection["requests"].get(request_id)
    if type(request) is not dict:
        raise ApprovalInvariantError("approval receipt request disappeared")
    return _binding_receipt_from_request(contract_path, request)


def verify_request_binding_receipt(
    contract_path: Path,
    receipt: dict[str, Any],
) -> dict[str, Any]:
    """Verify a closed request receipt against its immutable store prefix."""
    if (
        type(receipt) is not dict
        or not _is_exact_plain_json(receipt)
        or set(receipt) != _REQUEST_BINDING_RECEIPT_FIELDS
    ):
        raise ApprovalInvariantError(
            "approval request binding receipt fields are invalid"
        )
    if type(receipt.get("intent_revision")) is not int:
        raise ApprovalInvariantError(
            "approval receipt intent revision must be an exact integer"
        )
    request_id = receipt.get("request_id")
    if type(request_id) is not str:
        raise ApprovalInvariantError("approval receipt request id is invalid")
    projection = _target_projection(contract_path, request_id, terminal=False)
    request = projection["requests"].get(request_id)
    if type(request) is not dict:
        raise ApprovalInvariantError("approval receipt request disappeared")
    expected = _binding_receipt_from_request(contract_path, request)
    if receipt != expected:
        raise ApprovalInvariantError(
            "approval request binding receipt was substituted"
        )
    return dict(request)


def decided_request_receipt(
    contract_path: Path,
    request_receipt: dict[str, Any],
    *,
    outcome: str,
    provider: str,
    session_id: str,
    actor: str,
) -> dict[str, Any]:
    """Verify one exact human decision without trusting later store suffixes."""
    request = verify_request_binding_receipt(contract_path, request_receipt)
    if any(
        type(value) is not str
        for value in (outcome, provider, session_id, actor)
    ):
        raise ApprovalInvariantError("approval decision receipt values are invalid")
    selected_provider = provider.strip().lower()
    selected_session = session_id.strip()
    selected_actor = actor.strip()
    selected_outcome = outcome.strip()
    if not all(
        (selected_provider, selected_session, selected_actor, selected_outcome)
    ):
        raise ApprovalInvariantError("approval decision receipt values are invalid")
    projection = _target_projection(
        contract_path,
        request["request_id"],
        terminal=True,
    )
    decided = projection["requests"][request["request_id"]]
    if decided["status"] == "replaced":
        raise ApprovalInvariantError("approval request was replaced")
    if decided["status"] != "decided":
        phase = "expired" if _request_expired(decided) else "open"
        raise ApprovalInvariantError(f"approval request is still {phase}")
    expected_lane = _lane_digest(selected_provider, selected_session)
    if (
        decided["route"] != "human"
        or decided["provider"] != selected_provider
        or decided["lane_sha256"] != expected_lane
        or decided["decision_provider"] != selected_provider
        or decided["decision_lane_sha256"] != expected_lane
        or decided["decision_actor"] != selected_actor
        or decided["outcome"] != selected_outcome
    ):
        raise ApprovalInvariantError(
            "approval decision provider/session/lane/actor/outcome binding mismatch"
        )
    result = {
        "schema": DECIDED_REQUEST_RECEIPT_SCHEMA,
        "contract_sha256": request_receipt["contract_sha256"],
        "request_id": request["request_id"],
        "binding_sha256": request_receipt["binding_sha256"],
        "outcome": decided["outcome"],
        "provider": decided["decision_provider"],
        "lane_sha256": decided["decision_lane_sha256"],
        "actor": decided["decision_actor"],
        "decided_at": decided["decided_at"],
        "receipt_sha256": decided["receipt_sha256"] or "",
    }
    if set(result) != _DECIDED_REQUEST_RECEIPT_FIELDS - {"decision_sha256"}:
        raise ApprovalInvariantError("approval decision receipt fields are invalid")
    if any(type(value) is not str for value in result.values()):
        raise ApprovalInvariantError("approval decision receipt fields are invalid")
    result["decision_sha256"] = hashlib.sha256(
        _strict_canonical(result).encode("utf-8")
    ).hexdigest()
    return result


def request_phase(
    request: dict[str, Any],
    *,
    now: datetime | None = None,
) -> str:
    """Expose the dual-clock phase without changing approval authority."""
    if request.get("typed") is True:
        status = request.get("status")
        if status != "asked":
            return str(status or "invalid")
        current = now or datetime.now(timezone.utc)
        if _request_expired(request, now=current):
            return "expired"
        reassess = _parse_timestamp(str(request.get("reassess_at") or ""))
        return (
            "reassess_due"
            if reassess is not None and reassess <= current
            else "fresh"
        )
    return _request_phase(request, now=now)


def cancel_request(
    contract_path: Path,
    request_id: str,
    *,
    actor: str,
) -> dict[str, Any]:
    """Cancel one exact durable question without granting its target action."""
    clean_actor = actor.strip()
    if not _ID_RE.fullmatch(request_id):
        raise ApprovalInvariantError("approval request id is invalid")
    if not clean_actor:
        raise ApprovalInvariantError("approval cancellation actor is required")

    def mutation(
        projection: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], tuple[str, bool]]:
        request = projection["requests"].get(request_id)
        if not isinstance(request, dict):
            raise ApprovalInvariantError(
                "approval cancellation has no matching question"
            )
        if request["status"] == "decided":
            if request["outcome"] == "cancelled":
                return [], (request_id, True)
            raise ApprovalInvariantError(
                "approval cancellation targets an already decided question"
            )
        return [
            {
                "type": "approval.decided",
                "request_id": request_id,
                "outcome": "cancelled",
                "provider": "system",
                "lane_sha256": "",
                "receipt_sha256": "",
                "actor": clean_actor[:100],
            }
        ], (request_id, False)

    projection, result = _mutate(contract_path, mutation)
    selected_id, idempotent = result
    answer = dict(projection["requests"][selected_id])
    answer["idempotent"] = idempotent
    return answer


def cancel_open_requests(
    contract_path: Path,
    *,
    kinds: set[str],
    actor: str,
) -> int:
    """Cancel obsolete question kinds without granting their target action."""
    selected = {str(value) for value in kinds}
    if not selected or not selected.issubset(KINDS):
        raise ApprovalInvariantError("cancel_open_requests kinds are invalid")
    clean_actor = actor.strip()
    if not clean_actor:
        raise ApprovalInvariantError("cancel_open_requests actor is required")

    def mutation(projection: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
        rows = [
            row
            for row in projection["requests"].values()
            if row["status"] == "asked"
            and not _request_expired(row)
            and row["kind"] in selected
        ]
        return [
            {
                "type": "approval.decided",
                "request_id": row["request_id"],
                "outcome": "cancelled",
                "provider": "system",
                "lane_sha256": "",
                "receipt_sha256": "",
                "actor": clean_actor[:100],
            }
            for row in rows
        ], len(rows)

    _projection, cancelled = _mutate(contract_path, mutation)
    return int(cancelled)


def summary(contract_path: Path) -> dict[str, Any]:
    projection = load_projection(contract_path)
    requests = list(projection["requests"].values())
    active_open = [
        row
        for row in requests
        if row["status"] == "asked" and not _request_expired(row)
    ]
    expired = [
        row
        for row in requests
        if row["status"] == "asked" and _request_expired(row)
    ]
    reassess_due = [
        row
        for row in active_open
        if request_phase(row) == "reassess_due"
    ]
    by_outcome = {outcome: 0 for outcome in sorted(OUTCOMES)}
    for row in requests:
        if row["outcome"] in by_outcome:
            by_outcome[str(row["outcome"])] += 1
    return {
        "schema": "sulde-approval-pair-summary-v1",
        "sequence": projection["sequence"],
        "requests": len(requests),
        "open": len(active_open),
        "expired": len(expired),
        "reassess_due": len(reassess_due),
        "typed_receipts": sum(
            1 for row in requests if type(row.get("typed_receipt")) is dict
        ),
        "execution_authorized": 0,
        "by_outcome": by_outcome,
        "updated_at": projection["updated_at"],
    }
