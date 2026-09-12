#!/usr/bin/env python3
"""Append-only recovery journal for already-presented native decisions.

The journal is correlation and recovery state, never approval authority.  A
replayer must independently prove that the bound approval request was durably
decided by the native host before advancing any semantic state.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import runpy
import stat
import tempfile
import time
from typing import Any, Callable, Iterator, Mapping, Optional, TypedDict

from approval_invariant import (
    ApprovalInvariantError,
    decided_request_receipt,
    event_store_path as approval_event_store_path,
    request_binding_receipt,
    verify_request_binding_receipt,
)
from file_lock import lock_exclusive_nonblocking, unlock
from task_continuation_routing import verify_route as verify_selected_task_route

contract_identity_digest = runpy.run_path(
    str(Path(__file__).resolve().with_name("sulde_paths.py"))
)["contract_identity_digest"]


EVENT_SCHEMA = "sulde-native-decision-journal-event-v1"
PROJECTION_SCHEMA = "sulde-native-decision-journal-v1"
BINDING_SCHEMA_V3 = "sulde-native-transaction-binding-v3"
BINDING_SCHEMA_V4 = "sulde-native-transaction-binding-v4"
BINDING_SCHEMA = "sulde-native-transaction-binding-v5"
HEAD_ANCHOR_SCHEMA = "sulde-native-decision-journal-head-v1"
HEAD_PENDING_ANCHOR_SCHEMA = "sulde-native-decision-journal-head-pending-anchor-v1"
HEAD_PENDING_SCHEMA = "sulde-native-decision-journal-head-pending-v1"
HEAD_PROOF_SCHEMA = "sulde-native-decision-journal-head-proof-v2"
RECOVERY_PLAN_SCHEMA = "sulde-native-internal-recovery-plan-v2"
RECOVERY_RESULT_SCHEMA = "sulde-native-internal-recovery-result-v1"
TERMINAL_REPLAY_SCHEMA = "sulde-native-terminal-replay-diagnostic-v1"
T06_ADAPTER_RECEIPT_SCHEMA = "sulde-t06-operation-adapter-receipt-v1"
T06_POSTCONDITION_RECEIPT_SCHEMA = "sulde-t06-authoritative-postcondition-receipt-v1"
APPROVAL_CAS_EVENT_SCHEMA = "sulde-approval-pair-event-v2"
APPROVAL_CAS_RECEIPT_SCHEMA = "sulde-approval-cas-receipt-v1"
T10_BATCH_EVENT_SCHEMA = "sulde-intervention-event-v2"
AUTHORITY_RECEIPT_EVENT_SCHEMA = "sulde-native-authority-receipt-event-v1"
EFFECT_POSTCONDITION_RECEIPT_SCHEMA = (
    "sulde-native-effect-postcondition-receipt-v1"
)
CONTRACT_POSTCONDITION_RECEIPT_SCHEMA = (
    "sulde-native-contract-postcondition-receipt-v1"
)
EXTERNAL_HEAD_RECEIPT_SCHEMA = "sulde-native-external-head-receipt-v1"
AUTHORITY_ADVANCEMENT_RESULT_SCHEMA = (
    "sulde-native-authority-advancement-result-v1"
)
GRANT_BROKER_PROTOCOL_SCHEMA = "sulde-grant-broker-v1"
GRANT_BROKER_ADAPTER_SCHEMA = "sulde-native-grant-broker-adapter-v1"
STAGES = (
    "prepared",
    "approval_decided",
    "effect_applied",
    "contract_applied",
    "committed",
)
TERMINAL_STAGES = frozenset({"committed", "superseded"})
OPERATION_SPECS = {
    "proposal": {
        "kind": "proposal",
        "approval_kind": "proposal",
        "decisions": {"approve": "approve-proposal", "reject": "reject-proposal"},
        "external_boundary": "proposal execution outside sealed internal contract state",
    },
    "resume": {
        "kind": "resume",
        "approval_kind": "intent-confirmation",
        "decisions": {"resume": "resume"},
        "external_boundary": "resumed task execution",
    },
    "task-continuation": {
        "kind": "task-continuation",
        "approval_kind": "intent-confirmation",
        "decisions": {"approve": "continue-task"},
        "external_boundary": "material work in the newly bound task session",
    },
    "effect": {
        "kind": "effect-intervention",
        "approval_kind": "effect-intervention",
        "decisions": {
            "retry_authorized": "intervention-resolve",
            "reprobe_authorized": "intervention-resolve",
            "abort": "intervention-resolve",
        },
        "external_boundary": "external retry, reprobe, compensation, or tool execution",
    },
    "intent": {
        "kind": "intent",
        "approval_kind": "intent-confirmation",
        "decisions": {"confirm": "confirm-intent", "reject": "reject-intent"},
        "external_boundary": "work started under the confirmed intent",
    },
    "observation-export": {
        "kind": "observation-export",
        "approval_kind": "observation-export",
        "decisions": {
            "approve": "approve-observation-export",
            "reject": "reject-observation-export",
        },
        "external_boundary": "export file creation, overwrite, upload, or publication",
    },
}
_OPERATION_ALIASES = {"effect-intervention": "effect"}
_LEGACY_BINDING_FIELDS = {
    "request_id",
    "kind",
    "decision",
    "target",
    "action",
    "approval_kind",
    "intent_id",
    "intent_revision",
    "workspace",
    "provider",
    "session_id",
    "card_sha256",
}
_SEALED_V3_CORE_FIELDS = _LEGACY_BINDING_FIELDS | {
    "schema",
    "operation",
    "source",
    "request_binding_sha256",
    "seal_id",
}
_SEALED_V4_CORE_FIELDS = _SEALED_V3_CORE_FIELDS | {"task_epoch"}
_SEALED_CORE_FIELDS = _SEALED_V4_CORE_FIELDS | {
    "effect_attempt_id",
    "effect_subject_intent_revision",
}
_SEALED_V3_BINDING_FIELDS = _SEALED_V3_CORE_FIELDS | {"seal_event_id"}
_SEALED_V4_BINDING_FIELDS = _SEALED_V4_CORE_FIELDS | {"seal_event_id"}
_SEALED_BINDING_FIELDS = _SEALED_CORE_FIELDS | {"seal_event_id"}


class NativeDecisionJournalError(RuntimeError):
    """The native decision journal is unavailable or internally inconsistent."""


class NativeDecisionAdvancementInterrupted(RuntimeError):
    """Deterministic test-only interruption after an authority read-back."""


_REQUEST_VALIDATIONS: ContextVar[dict[str, Any] | None] = ContextVar(
    "native_request_validation_scope", default=None
)
_ACTIVE_REQUEST_VALIDATIONS: ContextVar[dict[str, Any] | None] = ContextVar(
    "native_request_validation_pass", default=None
)


@contextmanager
def _request_validation_scope() -> Iterator[None]:
    """Ephemeral successful prefix checks, never decisions or execution tickets.

    Each receipt-chain call owns an empty cache, including nested calls. Nothing
    survives the call, a crash or an exception; no process-global/TTL reuse.
    """
    token = _REQUEST_VALIDATIONS.set({})
    active_token = _ACTIVE_REQUEST_VALIDATIONS.set(None)
    try:
        yield
    finally:
        _ACTIVE_REQUEST_VALIDATIONS.reset(active_token)
        _REQUEST_VALIDATIONS.reset(token)


def _request_source_identity(contract_path: Path) -> tuple[Any, ...]:
    source = approval_event_store_path(contract_path)
    try:
        before = source.lstat()
        payload = _stable_read_source_bytes(source, label="approval request reuse")
        after = source.lstat()
    except OSError as error:
        raise NativeDecisionJournalError(f"cannot observe approval request source: {error}") from error
    fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns", "st_mode", "st_uid", "st_nlink")
    identity = tuple(getattr(before, field) for field in fields)
    if identity != tuple(getattr(after, field) for field in fields):
        raise NativeDecisionJournalError("approval source changed during request validation")
    return str(source), identity, hashlib.sha256(payload).hexdigest()


@contextmanager
def _request_validation_pass(contract_path: Path) -> Iterator[None]:
    cache = _REQUEST_VALIDATIONS.get()
    if cache is None:
        yield
        return
    try:
        source = _request_source_identity(contract_path)
        if cache.get("source") != source:
            cache.clear()
            cache.update(source=source, requests={})
        token = _ACTIVE_REQUEST_VALIDATIONS.set(cache["requests"])
        try:
            yield
            if _request_source_identity(contract_path) != source:
                raise NativeDecisionJournalError("approval source changed during request validation")
        finally:
            _ACTIVE_REQUEST_VALIDATIONS.reset(token)
    except BaseException:
        cache.clear()  # Never retain a partially successful or failed pass.
        raise


def _verified_request_prefix(contract_path: Path, receipt: dict[str, Any]) -> dict[str, Any]:
    cache = _ACTIVE_REQUEST_VALIDATIONS.get()
    if cache is None or type(receipt) is not dict or not _is_plain_json(receipt):
        return verify_request_binding_receipt(contract_path, receipt)
    key = _canonical(receipt)
    if key in cache:
        return _plain_json_copy(cache[key])
    request = verify_request_binding_receipt(contract_path, receipt)
    if len(cache) < 512:
        cache[key] = _plain_json_copy(request)
    return request


class JournalHeadProof(TypedDict):
    """Local head material that T06 must compare with an independent anchor."""

    schema: str
    contract_sha256: str
    generation: int
    sequence: int
    event_id: str
    event_sha256: str
    journal_sha256: str
    anchor_sha256: str
    local_consistency_verified: bool
    external_authority_verified: bool
    external_authority_status: str
    recovery_status: str
    external_anchor_required: bool
    external_anchor_boundary: str
    proof_sha256: str


class AuthorityAdvancementResult(TypedDict):
    """Data-only outcome from one external-authority stage CAS."""

    schema: str
    transaction_id: str
    operation: str
    prior_stage: str
    stage: str
    status: str
    reason: str
    advanced: bool
    local_consistency_verified: bool
    external_authority_verified: bool
    authority_status: str
    receipt_schema: str
    receipt_sha256: str
    journal_head_proof: JournalHeadProof


class NativeEffectReceipt(TypedDict):
    """Closed receipt emitted after an operation-specific effect read-back."""

    schema: str
    receipt_id: str
    contract_sha256: str
    transaction_id: str
    operation: str
    decision: str
    request_id: str
    request_binding_sha256: str
    card_sha256: str
    binding_sha256: str
    prior_stage: str
    prior_source_event_id: str
    journal_generation: int
    journal_event_id: str
    journal_sha256: str
    source_kind: str
    source_sha256: str
    source_event_id: str
    postcondition: dict[str, Any]
    postcondition_sha256: str
    receipt_sha256: str


class NativeContractReceipt(NativeEffectReceipt):
    """Closed receipt emitted after the formal contract projection is observed."""


class NativeExternalHeadReceipt(NativeEffectReceipt):
    """Closed receipt held in a store separate from the native journal."""


@dataclass(frozen=True)
class NativeAuthorityReaders:
    """Compatibility envelope for the public authority seam.

    These values are data-only and are never opened.  Authority-store paths are
    derived from ``contract_path`` inside :func:`advance_with_authority`; this
    type remains so older callers do not need an ABI-breaking signature change.
    """

    approval: Path | str | None
    effect: Path | str | None
    contract: Path | str | None
    head_anchor: Path | str | None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


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
        raise NativeDecisionJournalError(
            f"native decision journal value is not lossless JSON: {error}"
        ) from error


def _contract_digest(contract_path: Path) -> str:
    return contract_identity_digest(contract_path)


def journal_path(contract_path: Path) -> Path:
    name = contract_path.name
    stem = name[:-5] if name.endswith(".json") else name
    return contract_path.with_name(f".{stem}.native-decisions.jsonl")


def head_anchor_path(contract_path: Path) -> Path:
    store = journal_path(contract_path)
    return store.with_name(f"{store.name}.head.json")


def _head_pending_path(contract_path: Path) -> Path:
    anchor = head_anchor_path(contract_path)
    return anchor.with_name(f"{anchor.name}.pending")


def head_pending_path(contract_path: Path) -> Path:
    """Return the recovery sidecar path without creating or repairing it."""
    return _head_pending_path(contract_path)


@contextmanager
def _store_lock(path: Path, *, timeout: float = 3.0) -> Iterator[None]:
    lock_path = path.with_name(f".{path.name}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout
    with lock_path.open("a+", encoding="utf-8") as handle:
        if os.name != "nt":
            os.fchmod(handle.fileno(), 0o600)
        while True:
            try:
                lock_exclusive_nonblocking(handle)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise NativeDecisionJournalError(
                        f"native decision journal lock busy: {lock_path}"
                    )
                time.sleep(0.01)
        try:
            yield
        finally:
            unlock(handle)


def _empty(contract_path: Path) -> dict[str, Any]:
    return {
        "schema": PROJECTION_SCHEMA,
        "contract_sha256": _contract_digest(contract_path),
        "sequence": 0,
        "seals": {},
        "transactions": {},
        "updated_at": None,
    }


def _operation(value: Any) -> str:
    if type(value) is not str:
        raise NativeDecisionJournalError("native transaction operation must be a string")
    selected = value.strip().lower()
    selected = _OPERATION_ALIASES.get(selected, selected)
    if selected not in OPERATION_SPECS:
        raise NativeDecisionJournalError("unsupported native transaction operation")
    return selected


def _validate_binding(binding: Any) -> dict[str, Any]:
    if type(binding) is not dict or not _is_plain_json(binding):
        raise NativeDecisionJournalError("native decision binding must be an object")
    fields = set(binding)
    if frozenset(fields) not in {
        frozenset(_LEGACY_BINDING_FIELDS),
        frozenset(_SEALED_V3_BINDING_FIELDS),
        frozenset(_SEALED_V4_BINDING_FIELDS),
        frozenset(_SEALED_BINDING_FIELDS),
    }:
        raise NativeDecisionJournalError("native decision binding fields are invalid")
    integer_fields = {"intent_revision", "effect_subject_intent_revision"}
    if type(binding["intent_revision"]) is not int or any(
        type(value) is not str
        for key, value in binding.items()
        if key not in integer_fields
    ) or any(
        type(binding[key]) is not int
        for key in integer_fields
        if key in binding
    ):
        raise NativeDecisionJournalError("native decision binding types are invalid")
    normalized = dict(binding)
    if fields == _LEGACY_BINDING_FIELDS:
        # Preserve every row accepted by the v1 journal.  These bindings are
        # replayable correlation evidence only: generic recovery below stops
        # closed because they have no sealed approval-request receipt.
        if (
            not normalized["request_id"].startswith("apr-")
            or normalized["provider"] != "codex"
            or not normalized["session_id"]
            or not normalized["target"]
            or normalized["intent_revision"] <= 0
            or len(normalized["card_sha256"]) != 64
        ):
            raise NativeDecisionJournalError(
                "native decision binding values are invalid"
            )
    else:
        operation = _operation(normalized["operation"])
        spec = OPERATION_SPECS[operation]
        schema = normalized["schema"]
        task_epoch_valid = (
            schema == BINDING_SCHEMA_V3
            and fields == _SEALED_V3_BINDING_FIELDS
        ) or (
            schema == BINDING_SCHEMA_V4
            and fields == _SEALED_V4_BINDING_FIELDS
            and type(normalized.get("task_epoch")) is str
            and len(normalized["task_epoch"]) == 24
            and all(
                character in "0123456789abcdef"
                for character in normalized["task_epoch"]
            )
        ) or (
            schema == BINDING_SCHEMA
            and fields == _SEALED_BINDING_FIELDS
            and type(normalized.get("task_epoch")) is str
            and len(normalized["task_epoch"]) == 24
            and all(
                character in "0123456789abcdef"
                for character in normalized["task_epoch"]
            )
        )
        effect_subject_valid = schema in {BINDING_SCHEMA_V3, BINDING_SCHEMA_V4} or (
            operation == "effect"
            and normalized.get("effect_attempt_id", "").startswith("att-")
            and len(normalized.get("effect_attempt_id", "")) == 28
            and all(
                character in "0123456789abcdef"
                for character in normalized.get("effect_attempt_id", "")[4:]
            )
            and normalized.get("effect_subject_intent_revision", 0) > 0
        ) or (
            operation != "effect"
            and normalized.get("effect_attempt_id") == ""
            and normalized.get("effect_subject_intent_revision") == 0
        )
        if (
            not _is_request_id(normalized["request_id"])
            or normalized["provider"] != "codex"
            or not normalized["session_id"]
            or not normalized["target"]
            or not normalized["decision"]
            or not normalized["action"]
            or not normalized["intent_id"]
            or not normalized["workspace"]
            or normalized["intent_revision"] <= 0
            or not _is_sha256(normalized["card_sha256"])
            or not task_epoch_valid
            or not effect_subject_valid
            or normalized["kind"] != spec["kind"]
            or normalized["approval_kind"] != spec["approval_kind"]
            or spec["decisions"].get(normalized["decision"])
            != normalized["action"]
            or not normalized["source"]
            or not _is_sha256(normalized["request_binding_sha256"])
            or not normalized["seal_id"].startswith("nds-")
            or not _is_sha256(normalized["seal_event_id"])
        ):
            raise NativeDecisionJournalError(
                "native durable seal binding values are invalid"
            )
    return normalized


def _is_sha256(value: Any) -> bool:
    return type(value) is str and len(value) == 64 and all(
        character in "0123456789abcdef" for character in value
    )


def _is_request_id(value: Any) -> bool:
    return (
        type(value) is str
        and len(value) == 28
        and value.startswith("apr-")
        and all(character in "0123456789abcdef" for character in value[4:])
    )


def _binding_operation(binding: dict[str, Any]) -> str | None:
    if set(binding) not in (
        _SEALED_V3_BINDING_FIELDS,
        _SEALED_V4_BINDING_FIELDS,
        _SEALED_BINDING_FIELDS,
    ):
        return None
    return _operation(binding["operation"])


def _historical_terminal(transaction: dict[str, Any]) -> bool:
    return (
        transaction.get("historical_terminal_seen") is True
        or transaction.get("status") in TERMINAL_STAGES
    )


def is_legacy_unsealed_prepared_diagnostic(transaction: Any) -> bool:
    """Return whether one active row is historical correlation evidence only.

    The classification is intentionally exact.  It never grants mutation or
    execution authority; it only lets the read-only legacy cut distinguish a
    v1 ``prepared`` correlation row from a sealed transaction that can still
    advance.  Unknown, partial, terminal, or schema-bearing rows remain
    ordinary pending transactions and therefore fail closed.
    """
    if type(transaction) is not dict:
        return False
    binding = transaction.get("binding")
    stage_details = transaction.get("stage_details")
    if (
        transaction.get("status") != "active"
        or transaction.get("stage") != "prepared"
        or transaction.get("sealed") is not False
        or transaction.get("operation") is not None
        or transaction.get("historical_terminal_seen") is not False
        or type(transaction.get("local_consistency_verified")) is not bool
        or transaction.get("external_authority_verified") is not False
        or type(transaction.get("prepared_at")) is not str
        or not transaction.get("prepared_at")
        or type(transaction.get("updated_at")) is not str
        or not transaction.get("updated_at")
        or type(binding) is not dict
        or set(binding) != _LEGACY_BINDING_FIELDS
        or type(stage_details) is not dict
        or set(stage_details) != {"prepared"}
        or type(stage_details.get("prepared")) is not dict
    ):
        return False
    try:
        normalized = _validate_binding(binding)
        return (
            _binding_operation(normalized) is None
            and transaction_id(normalized) == transaction.get("transaction_id")
        )
    except NativeDecisionJournalError:
        return False


def _require_durable_seal_origin(
    projection: dict[str, Any],
    transaction: dict[str, Any],
) -> dict[str, Any]:
    """Return the binding only when replay proved its exact seal origin.

    A binding that merely resembles the current sealed schema is not mutation
    authority.  The append-only ``sealed`` event must exist, match the binding
    and event id exactly, and have been consumed by this exact transaction.
    This deliberately does not inspect the transaction's current stage.
    """
    binding = transaction.get("binding")
    seals = projection.get("seals")
    tx_id = transaction.get("transaction_id")
    if type(binding) is dict and type(seals) is dict:
        seal_id = binding.get("seal_id")
        seal_event_id = binding.get("seal_event_id")
        seal = seals.get(seal_id) if type(seal_id) is str else None
        if (
            type(seal_event_id) is str
            and type(tx_id) is str
            and type(seal) is dict
            and seal.get("seal_id") == seal_id
            and seal.get("seal_event_id") == seal_event_id
            and seal.get("binding") == binding
            and seal.get("consumed_by") == tx_id
        ):
            normalized = _validate_binding(binding)
            if _binding_operation(normalized) is not None:
                return normalized
    raise NativeDecisionJournalError(
        "legacy or unsealed native transactions are diagnostic read-only; "
        "mutation requires one exact verified durable seal origin"
    )


def transaction_id(binding: dict[str, Any]) -> str:
    normalized = _validate_binding(binding)
    return "ndt-" + hashlib.sha256(
        _canonical(normalized).encode("utf-8")
    ).hexdigest()[:32]


def _digest(value: Any) -> str:
    if type(value) is not str:
        raise NativeDecisionJournalError("native decision digest input must be a string")
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _card_digest(card: Any) -> str:
    if type(card) is not dict or not _is_plain_json(card):
        raise NativeDecisionJournalError("native approval card must be plain JSON")
    return hashlib.sha256(
        _canonical(card).encode("utf-8")
    ).hexdigest()


def _workspace_identity(workspace: Path | str) -> str:
    if type(workspace) is not str and not isinstance(workspace, Path):
        raise NativeDecisionJournalError("native decision workspace is invalid")
    try:
        return str(Path(workspace).expanduser().resolve())
    except OSError:
        return str(Path(workspace).expanduser().absolute())


def _workspace_digest(workspace: Path | str) -> str:
    return _digest(_workspace_identity(workspace))


def _lane_digest(provider: str, session_id: str) -> str:
    return _digest(f"{provider}\0{session_id}") if session_id else ""


def _plain_json_copy(value: Any) -> Any:
    if not _is_plain_json(value):
        raise NativeDecisionJournalError("native decision value must be exact plain JSON")
    if type(value) is list:
        return [_plain_json_copy(item) for item in value]
    if type(value) is dict:
        return {key: _plain_json_copy(item) for key, item in value.items()}
    return value


def _card_declarations(value: Any, keys: set[str]) -> list[Any]:
    declarations: list[Any] = []
    if type(value) is dict:
        for key, nested in value.items():
            if key.strip().lower() in keys:
                declarations.append(nested)
            declarations.extend(_card_declarations(nested, keys))
    elif type(value) is list:
        for nested in value:
            declarations.extend(_card_declarations(nested, keys))
    return declarations


def _validate_card_semantics(
    card: Any,
    *,
    operation: str,
    decision: str,
    action: str,
) -> None:
    if type(card) is not dict or not _is_plain_json(card):
        raise NativeDecisionJournalError(
            "native approval card must be a plain JSON object"
        )
    expected = {
        "operation_id": operation,
        "decision_id": decision,
        "action": action,
    }
    for field, sealed in expected.items():
        declarations = _card_declarations(card, {field})
        if len(declarations) != 1 or field not in card:
            raise NativeDecisionJournalError(
                f"native approval card requires one top-level machine {field}"
            )
        declared = declarations[0]
        if type(declared) is not str or declared != sealed:
            raise NativeDecisionJournalError(
                f"native approval card machine {field} does not match the seal"
            )

    # Equivalent English machine fields would create a second interpretation.
    # Human-facing labels may repeat the exact value, but may never contradict
    # the canonical machine choice.
    forbidden_machine_aliases = {
        "operation": "operation_id",
        "decision": "decision_id",
        "action_id": "action",
    }
    for alias, canonical in forbidden_machine_aliases.items():
        if _card_declarations(card, {alias}):
            raise NativeDecisionJournalError(
                f"native approval card has multiple machine {canonical} fields"
            )
    presentations = {
        "operation_id": {"操作", "操作类型"},
        "decision_id": {"本次决策", "决策"},
        "action": {"本次选择", "选择", "动作"},
    }
    for canonical, aliases in presentations.items():
        # Presentation labels define the sealed choice only at the card root.
        # Nested task/continuation descriptions may legitimately contain words
        # such as ``动作``; treating those as a second machine declaration makes
        # the approval card reject its own generated continuation steps.
        for key, declared in card.items():
            if key.strip().lower() not in aliases:
                continue
            if type(declared) is not str or declared != expected[canonical]:
                raise NativeDecisionJournalError(
                    f"native approval card prose contradicts machine {canonical}"
                )


def _binding_sha256(binding: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical(_validate_binding(binding)).encode("utf-8")).hexdigest()


def _authority_sha256(
    binding: dict[str, Any], decision_receipt: dict[str, Any]
) -> str:
    return hashlib.sha256(
        _canonical(
            {
                "binding_sha256": _binding_sha256(binding),
                "request_binding_sha256": binding["request_binding_sha256"],
                "decision_sha256": decision_receipt["decision_sha256"],
            }
        ).encode("utf-8")
    ).hexdigest()


def _validate_seal_core(binding: Any) -> dict[str, Any]:
    if type(binding) is not dict or not _is_plain_json(binding):
        raise NativeDecisionJournalError("native durable seal binding is invalid")
    fields = set(binding)
    if frozenset(fields) not in {
        frozenset(_SEALED_V3_CORE_FIELDS),
        frozenset(_SEALED_V4_CORE_FIELDS),
        frozenset(_SEALED_CORE_FIELDS),
    }:
        raise NativeDecisionJournalError("native durable seal binding fields are invalid")
    integer_fields = {"intent_revision", "effect_subject_intent_revision"}
    if type(binding["intent_revision"]) is not int or any(
        type(value) is not str
        for key, value in binding.items()
        if key not in integer_fields
    ) or any(
        type(binding[key]) is not int
        for key in integer_fields
        if key in binding
    ):
        raise NativeDecisionJournalError("native durable seal binding types are invalid")
    full = dict(binding, seal_event_id="0" * 64)
    normalized = _validate_binding(full)
    normalized.pop("seal_event_id")
    return normalized


def _seal_id(
    binding_without_seal_id: dict[str, Any],
    card: dict[str, Any],
    request_receipt: dict[str, Any],
) -> str:
    material = {
        "binding": binding_without_seal_id,
        "card": card,
        "request_receipt": request_receipt,
    }
    return "nds-" + hashlib.sha256(_canonical(material).encode("utf-8")).hexdigest()[:32]


def _verify_request_semantics(
    contract_path: Path,
    binding: dict[str, Any],
    card: dict[str, Any],
    receipt: dict[str, Any],
) -> dict[str, Any]:
    operation = _operation(binding["operation"])
    spec = OPERATION_SPECS[operation]
    _validate_card_semantics(
        card,
        operation=operation,
        decision=binding["decision"],
        action=binding["action"],
    )
    try:
        request = _verified_request_prefix(contract_path, receipt)
    except (ApprovalInvariantError, OSError, TypeError) as error:
        raise NativeDecisionJournalError(
            f"cannot verify durable native approval seal: {error}"
        ) from error
    expected = {
        "request_id": binding["request_id"],
        "intent_id_sha256": _digest(binding["intent_id"]),
        "intent_revision": binding["intent_revision"],
        "kind": spec["approval_kind"],
        "target_sha256": _digest(binding["target"]),
        "card_sha256": _card_digest(card),
        "workspace_sha256": _workspace_digest(binding["workspace"]),
        "proposal_sha256": (
            _digest(binding["target"]) if spec["approval_kind"] == "proposal" else ""
        ),
        "route": "human",
        "provider": binding["provider"],
        "lane_sha256": _lane_digest(binding["provider"], binding["session_id"]),
        "source": binding["source"],
    }
    mismatches = [key for key, value in expected.items() if request.get(key) != value]
    if receipt.get("binding_sha256") != binding["request_binding_sha256"]:
        mismatches.append("request_binding_sha256")
    if expected["card_sha256"] != binding["card_sha256"]:
        mismatches.append("card_sha256")
    if mismatches:
        raise NativeDecisionJournalError(
            "native approval request binding mismatch: " + ", ".join(mismatches)
        )
    return request


def seal_binding(
    contract_path: Path,
    *,
    operation: str,
    decision: str,
    target: str,
    action: str,
    intent_id: str,
    intent_revision: int,
    task_epoch: str,
    effect_attempt_id: str,
    effect_subject_intent_revision: int,
    workspace: Path | str,
    provider: str,
    session_id: str,
    source: str,
    card: Any,
    request_id: str,
    receipt: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Seal one existing native request without creating approval authority.

    Every raw semantic value is checked against the approval store's immutable
    digests.  Passing ``receipt`` is useful across process boundaries; a stale
    or substituted request receipt is rejected even when the card and target
    happen to be identical.
    """
    string_values = (
        operation,
        decision,
        target,
        action,
        intent_id,
        task_epoch,
        effect_attempt_id,
        provider,
        session_id,
        source,
        request_id,
    )
    if any(type(value) is not str for value in string_values):
        raise NativeDecisionJournalError("native decision seal values are invalid")
    if (
        type(intent_revision) is not int
        or type(intent_revision) is bool
        or type(effect_subject_intent_revision) is not int
        or type(effect_subject_intent_revision) is bool
    ):
        raise NativeDecisionJournalError("native decision intent revision is invalid")
    if type(card) is not dict or not _is_plain_json(card):
        raise NativeDecisionJournalError("native approval card must be a plain JSON object")
    if receipt is not None and (type(receipt) is not dict or not _is_plain_json(receipt)):
        raise NativeDecisionJournalError("native approval request receipt must be plain JSON")
    selected_operation = _operation(operation)
    spec = OPERATION_SPECS[selected_operation]
    selected_provider = provider.strip().lower()
    clean_session = session_id.strip()
    clean_source = source.strip()
    clean_decision = decision.strip()
    clean_target = target.strip()
    clean_action = action.strip()
    clean_intent = intent_id.strip()
    clean_task_epoch = task_epoch.strip()
    clean_effect_attempt_id = effect_attempt_id.strip()
    revision = intent_revision
    if (
        selected_provider != "codex"
        or not clean_session
        or not clean_source
        or not clean_decision
        or not clean_target
        or not clean_action
        or not clean_intent
        or len(clean_task_epoch) != 24
        or any(
            character not in "0123456789abcdef"
            for character in clean_task_epoch
        )
        or revision <= 0
    ):
        raise NativeDecisionJournalError("native decision seal values are invalid")
    _validate_card_semantics(
        card,
        operation=selected_operation,
        decision=clean_decision,
        action=clean_action,
    )
    try:
        sealed_request = (
            _plain_json_copy(receipt)
            if receipt is not None
            else request_binding_receipt(contract_path, request_id)
        )
        verify_request_binding_receipt(contract_path, sealed_request)
    except (ApprovalInvariantError, TypeError, ValueError) as error:
        raise NativeDecisionJournalError(
            f"cannot seal native approval request: {error}"
        ) from error
    card_copy = _plain_json_copy(card)
    binding_without_seal = {
        "schema": BINDING_SCHEMA,
        "operation": selected_operation,
        "request_id": request_id,
        "kind": spec["kind"],
        "decision": clean_decision,
        "target": clean_target,
        "action": clean_action,
        "approval_kind": spec["approval_kind"],
        "intent_id": clean_intent,
        "intent_revision": revision,
        "task_epoch": clean_task_epoch,
        "effect_attempt_id": clean_effect_attempt_id,
        "effect_subject_intent_revision": effect_subject_intent_revision,
        "workspace": _workspace_identity(workspace),
        "provider": selected_provider,
        "session_id": clean_session,
        "source": clean_source,
        "card_sha256": _card_digest(card_copy),
        "request_binding_sha256": sealed_request["binding_sha256"],
    }
    seal_id = _seal_id(binding_without_seal, card_copy, sealed_request)
    core = _validate_seal_core(dict(binding_without_seal, seal_id=seal_id))
    _verify_request_semantics(contract_path, dict(core, seal_event_id="0" * 64), card_copy, sealed_request)

    def mutation(projection: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
        for existing_id, existing in projection["seals"].items():
            existing_binding = existing["binding"]
            if existing_binding["request_id"] != request_id:
                continue
            existing_core = dict(existing_binding)
            existing_core.pop("seal_event_id")
            if (
                existing_id == seal_id
                and existing_core == core
                and existing["card"] == card_copy
                and existing["request_receipt"] == sealed_request
            ):
                return [], existing_id
            raise NativeDecisionJournalError(
                "native approval request already has a durable seal"
            )
        return [{
            "event": "sealed",
            "seal_id": seal_id,
            "binding": core,
            "card": card_copy,
            "request_receipt": sealed_request,
        }], seal_id

    projection, selected = _mutate(contract_path, mutation)
    return dict(projection["seals"][selected]["binding"])


def _apply(projection: dict[str, Any], row: dict[str, Any]) -> None:
    event = row.get("event")
    if type(event) is not str:
        raise NativeDecisionJournalError("native decision event is invalid")
    if event == "sealed":
        seal_id = row.get("seal_id")
        core = _validate_seal_core(row.get("binding"))
        card = row.get("card")
        receipt = row.get("request_receipt")
        if (
            type(seal_id) is not str
            or seal_id != core["seal_id"]
            or type(card) is not dict
            or not _is_plain_json(card)
            or type(receipt) is not dict
            or not _is_plain_json(receipt)
            or _seal_id(
                {key: value for key, value in core.items() if key != "seal_id"},
                card,
                receipt,
            ) != seal_id
        ):
            raise NativeDecisionJournalError("native durable seal digest is invalid")
        seals = projection["seals"]
        if seal_id in seals:
            raise NativeDecisionJournalError("duplicate native durable seal")
        if any(
            sealed["binding"]["request_id"] == core["request_id"]
            for sealed in seals.values()
        ):
            raise NativeDecisionJournalError("approval request has multiple durable seals")
        binding = dict(core, seal_event_id=row["event_id"])
        _validate_binding(binding)
        seals[seal_id] = {
            "seal_id": seal_id,
            "seal_event_id": row["event_id"],
            "seal_sequence": row["sequence"],
            "binding": binding,
            "card": _plain_json_copy(card),
            "request_receipt": _plain_json_copy(receipt),
            "consumed_by": None,
            "sealed_at": row["at"],
        }
        projection["sequence"] = row["sequence"]
        projection["updated_at"] = row["at"]
        return

    tx_id = row.get("transaction_id")
    if type(tx_id) is not str or not tx_id.startswith("ndt-"):
        raise NativeDecisionJournalError("native decision transaction id is invalid")
    transactions = projection["transactions"]
    if event == "prepared":
        if tx_id in transactions:
            raise NativeDecisionJournalError("duplicate native decision prepare")
        binding = _validate_binding(row.get("binding"))
        if transaction_id(binding) != tx_id:
            raise NativeDecisionJournalError("native decision transaction digest mismatch")
        if _binding_operation(binding) is not None:
            seal = projection["seals"].get(binding["seal_id"])
            if (
                not isinstance(seal, dict)
                or seal["seal_event_id"] != binding["seal_event_id"]
                or seal["binding"] != binding
                or row.get("expected_seal_event_id") != binding["seal_event_id"]
                or seal["consumed_by"] is not None
            ):
                raise NativeDecisionJournalError(
                    "native prepare does not consume one exact durable seal"
                )
            seal["consumed_by"] = tx_id
        transactions[tx_id] = {
            "transaction_id": tx_id,
            "binding": binding,
            "operation": _binding_operation(binding),
            "sealed": _binding_operation(binding) is not None,
            "stage": "prepared",
            "status": "active",
            "historical_terminal_seen": False,
            "local_consistency_verified": False,
            "external_authority_verified": False,
            "stage_details": {"prepared": dict(row.get("details") or {})},
            "prepared_at": row["at"],
            "updated_at": row["at"],
        }
    elif event == "advanced":
        transaction = transactions.get(tx_id)
        if not isinstance(transaction, dict) or transaction["status"] != "active":
            raise NativeDecisionJournalError("native decision advance has no active transaction")
        stage = row.get("stage")
        prior = row.get("expected_stage")
        if type(stage) is not str or type(prior) is not str:
            raise NativeDecisionJournalError("native decision stage types are invalid")
        if stage not in STAGES[1:] or prior != transaction["stage"]:
            raise NativeDecisionJournalError("native decision stage CAS is invalid")
        if STAGES.index(stage) != STAGES.index(prior) + 1:
            raise NativeDecisionJournalError("native decision stages are not contiguous")
        transaction["stage"] = stage
        transaction["stage_details"][stage] = dict(row.get("details") or {})
        transaction["updated_at"] = row["at"]
        if stage == "committed":
            # A committed row records what an earlier writer claimed.  T03 can
            # replay that history and validate the local chain, but it cannot
            # turn the row into current execution authority without T06's
            # independently anchored head comparison.
            transaction["status"] = "external_authority_unverified"
            transaction["historical_status"] = "committed"
            transaction["historical_terminal_seen"] = True
            transaction["external_authority_verified"] = False
            transaction["committed_at"] = row["at"]
    elif event == "superseded":
        transaction = transactions.get(tx_id)
        if not isinstance(transaction, dict) or transaction["status"] != "active":
            raise NativeDecisionJournalError("native decision supersession has no active transaction")
        transaction["stage"] = "superseded"
        transaction["status"] = "superseded"
        transaction["historical_status"] = "superseded"
        transaction["historical_terminal_seen"] = True
        transaction["external_authority_verified"] = False
        reason = row.get("reason")
        if type(reason) is not str:
            raise NativeDecisionJournalError("native supersession reason is invalid")
        transaction["superseded_reason"] = reason[:2_000]
        transaction["stage_details"]["superseded"] = dict(row.get("details") or {})
        transaction["updated_at"] = row["at"]
    else:
        raise NativeDecisionJournalError(f"unsupported native decision event: {event}")
    projection["sequence"] = int(row["sequence"])
    projection["updated_at"] = row["at"]


def replay(contract_path: Path, rows: list[dict[str, Any]]) -> dict[str, Any]:
    if type(rows) is not list or not _is_plain_json(rows):
        raise NativeDecisionJournalError("native decision journal rows must be plain JSON")
    projection = _empty(contract_path)
    previous_event_id = ""
    for sequence, raw in enumerate(rows, 1):
        if (
            type(raw) is not dict
            or raw.get("schema") != EVENT_SCHEMA
            or raw.get("contract_sha256") != projection["contract_sha256"]
            or type(raw.get("sequence")) is not int
            or raw.get("sequence") != sequence
            or type(raw.get("at")) is not str
            or not raw.get("at")
            or type(raw.get("previous_event_id")) is not str
            or raw.get("previous_event_id") != previous_event_id
        ):
            raise NativeDecisionJournalError("native decision journal row is invalid")
        expected = hashlib.sha256(
            _canonical({key: value for key, value in raw.items() if key != "event_id"}).encode(
                "utf-8"
            )
        ).hexdigest()
        if raw.get("event_id") != expected:
            raise NativeDecisionJournalError("native decision journal digest mismatch")
        _apply(projection, raw)
        previous_event_id = expected
    if projection["seals"]:
        with _request_validation_pass(contract_path):
            for seal in projection["seals"].values():
                _verify_request_semantics(
                    contract_path,
                    seal["binding"],
                    seal["card"],
                    seal["request_receipt"],
                )
    return projection


def _decode_rows(payload: bytes) -> list[dict[str, Any]]:
    if payload and not payload.endswith(b"\n"):
        raise NativeDecisionJournalError("native decision journal has an incomplete tail")
    try:
        rows = [json.loads(line) for line in payload.decode("utf-8").splitlines()]
    except (UnicodeError, json.JSONDecodeError) as error:
        raise NativeDecisionJournalError(
            f"invalid native decision journal JSONL: {error}"
        ) from error
    if not all(isinstance(row, dict) for row in rows):
        raise NativeDecisionJournalError("native decision journal row is not an object")
    return rows


def _read_rows(path: Path) -> list[dict[str, Any]]:
    return _decode_rows(path.read_bytes() if path.is_file() else b"")


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            if os.name != "nt":
                os.fchmod(handle.fileno(), 0o600)
            handle.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _read_json_object(path: Path, *, label: str) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise NativeDecisionJournalError(
            f"native decision journal {label} is invalid: {error}"
        ) from error
    if not isinstance(value, dict):
        raise NativeDecisionJournalError(
            f"native decision journal {label} is not an object"
        )
    return value


def _head_value(
    contract_path: Path, payload: bytes, rows: list[dict[str, Any]]
) -> dict[str, Any]:
    return {
        "schema": HEAD_ANCHOR_SCHEMA,
        "contract_sha256": _contract_digest(contract_path),
        "sequence": len(rows),
        "event_id": str(rows[-1].get("event_id") or "") if rows else "",
        "journal_sha256": hashlib.sha256(payload).hexdigest(),
    }


def _validate_head_object(
    contract_path: Path, value: Any, *, label: str
) -> dict[str, Any]:
    expected_fields = {
        "schema",
        "contract_sha256",
        "sequence",
        "event_id",
        "journal_sha256",
    }
    if not isinstance(value, dict) or set(value) != expected_fields:
        raise NativeDecisionJournalError(
            f"native decision journal {label} fields are invalid"
        )
    sequence = value.get("sequence")
    if type(sequence) is not int:
        raise NativeDecisionJournalError(
            f"native decision journal {label} sequence is invalid"
        )
    normalized = dict(value, sequence=sequence)
    if (
        normalized["schema"] != HEAD_ANCHOR_SCHEMA
        or normalized["contract_sha256"] != _contract_digest(contract_path)
        or sequence < 0
        or not _is_sha256(normalized["journal_sha256"])
        or (sequence == 0 and normalized["event_id"] != "")
        or (sequence > 0 and not _is_sha256(normalized["event_id"]))
    ):
        raise NativeDecisionJournalError(
            f"native decision journal {label} values are invalid"
        )
    return normalized


def _validate_pending_anchor(
    contract_path: Path, value: Any
) -> tuple[dict[str, Any], str]:
    expected_fields = {
        "schema",
        "contract_sha256",
        "sequence",
        "event_id",
        "journal_sha256",
        "pending_sha256",
    }
    if not isinstance(value, dict) or set(value) != expected_fields:
        raise NativeDecisionJournalError(
            "native decision journal pending anchor fields are invalid"
        )
    supplied = str(value.get("pending_sha256") or "")
    prior = dict(value)
    prior.pop("pending_sha256")
    prior["schema"] = HEAD_ANCHOR_SCHEMA
    if value.get("schema") != HEAD_PENDING_ANCHOR_SCHEMA or not _is_sha256(supplied):
        raise NativeDecisionJournalError(
            "native decision journal pending anchor values are invalid"
        )
    return _validate_head_object(
        contract_path, prior, label="pending anchor prior head"
    ), supplied


def _heads_equal(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return all(
        left.get(key) == right.get(key)
        for key in (
            "schema",
            "contract_sha256",
            "sequence",
            "event_id",
            "journal_sha256",
        )
    )


def _recover_anchored_rows(
    contract_path: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any], bytes, dict[str, Any] | None]:
    store = journal_path(contract_path)
    anchor_path = head_anchor_path(contract_path)
    pending_path = _head_pending_path(contract_path)
    payload = store.read_bytes() if store.is_file() else b""
    rows = _decode_rows(payload)
    projection = replay(contract_path, rows)
    current = _head_value(contract_path, payload, rows)
    stable_raw = _read_json_object(anchor_path, label="head anchor")
    stable: dict[str, Any] | None = None
    pending_anchor_sha256 = ""
    if stable_raw is not None:
        if stable_raw.get("schema") == HEAD_PENDING_ANCHOR_SCHEMA:
            stable, pending_anchor_sha256 = _validate_pending_anchor(
                contract_path, stable_raw
            )
        else:
            stable = _validate_head_object(
                contract_path, stable_raw, label="head anchor"
            )
    pending = _read_json_object(pending_path, label="pending head update")
    if pending is not None:
        expected_fields = {
            "schema",
            "contract_sha256",
            "prior_head",
            "next_head",
            "append_payload",
            "pending_sha256",
        }
        supplied = str(pending.get("pending_sha256") or "")
        unsigned = {
            key: value for key, value in pending.items() if key != "pending_sha256"
        }
        if (
            set(pending) != expected_fields
            or pending.get("schema") != HEAD_PENDING_SCHEMA
            or pending.get("contract_sha256") != _contract_digest(contract_path)
            or not _is_sha256(supplied)
            or hashlib.sha256(_canonical(unsigned).encode("utf-8")).hexdigest()
            != supplied
            or not isinstance(pending.get("append_payload"), str)
        ):
            raise NativeDecisionJournalError(
                "native decision journal pending head update is invalid"
            )
        if pending_anchor_sha256 != supplied:
            # The sidecar is not authoritative until its digest is durably
            # installed in the head anchor.  A crash before that point leaves
            # an orphan that must never be replayed.
            if stable is not None and not _heads_equal(stable, current):
                raise NativeDecisionJournalError(
                    "native decision journal changed beside an uncommitted pending head"
                )
            if stable is None and rows:
                raise NativeDecisionJournalError(
                    "native decision journal has unanchored rows beside a pending head"
                )
            try:
                pending_path.unlink()
            except FileNotFoundError:
                pass
            _fsync_directory(pending_path.parent)
            pending = None
    if pending is not None:
        supplied = str(pending["pending_sha256"])
        prior = _validate_head_object(
            contract_path, pending.get("prior_head"), label="pending prior head"
        )
        following = _validate_head_object(
            contract_path, pending.get("next_head"), label="pending next head"
        )
        if stable is not None and not _heads_equal(stable, prior) and not _heads_equal(
            stable, following
        ):
            raise NativeDecisionJournalError(
                "native decision journal anchor conflicts with pending update"
            )
        if _heads_equal(current, prior):
            append_payload = pending["append_payload"].encode("utf-8")
            descriptor = os.open(store, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
            if os.name != "nt":
                os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "ab") as handle:
                handle.write(append_payload)
                handle.flush()
                os.fsync(handle.fileno())
            payload += append_payload
            rows = _decode_rows(payload)
            projection = replay(contract_path, rows)
            current = _head_value(contract_path, payload, rows)
        if not _heads_equal(current, following):
            raise NativeDecisionJournalError(
                "native decision journal does not match pending head update"
            )
        _atomic_write_json(anchor_path, following)
        try:
            pending_path.unlink()
        except FileNotFoundError:
            pass
        _fsync_directory(pending_path.parent)
        stable = following
        pending_anchor_sha256 = ""
    elif pending_anchor_sha256:
        raise NativeDecisionJournalError(
            "native decision journal pending anchor has no matching update"
        )
    if stable is not None and not _heads_equal(stable, current):
        raise NativeDecisionJournalError(
            "native decision journal durable head anchor mismatch"
        )
    if stable is None and rows:
        transactions = projection["transactions"].values()
        if projection["seals"] or any(
            transaction.get("sealed") is True for transaction in transactions
        ):
            raise NativeDecisionJournalError(
                "sealed native decision journal has no durable head anchor"
            )
    local_consistency_verified = stable is not None and _heads_equal(stable, current)
    for transaction in projection["transactions"].values():
        transaction["local_consistency_verified"] = local_consistency_verified
        transaction["external_authority_verified"] = False
    return rows, projection, payload, stable


def load_projection(contract_path: Path) -> dict[str, Any]:
    store = journal_path(contract_path)
    with _store_lock(store):
        _rows, projection, _payload, _anchor = _recover_anchored_rows(contract_path)
        return projection


def _read_anchored_rows_read_only(
    contract_path: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any], bytes, dict[str, Any] | None]:
    """Read one stable journal without lock creation or crash recovery writes.

    A pending head/append requires the ordinary recovery owner and therefore
    fails this read-only view closed instead of repairing or deleting files.
    """
    store = journal_path(contract_path)
    payload = store.read_bytes() if store.is_file() else b""
    rows = _decode_rows(payload)
    projection = replay(contract_path, rows)
    current = _head_value(contract_path, payload, rows)
    pending_path = _head_pending_path(contract_path)
    if pending_path.is_file():
        raise NativeDecisionJournalError(
            "native decision journal has a pending update requiring recovery"
        )
    anchor_path = head_anchor_path(contract_path)
    stable_raw = _read_json_object(anchor_path, label="head anchor")
    stable: dict[str, Any] | None = None
    if stable_raw is not None:
        if stable_raw.get("schema") == HEAD_PENDING_ANCHOR_SCHEMA:
            raise NativeDecisionJournalError(
                "native decision journal has a pending anchor requiring recovery"
            )
        stable = _validate_head_object(
            contract_path,
            stable_raw,
            label="head anchor",
        )
        if not _heads_equal(stable, current):
            raise NativeDecisionJournalError(
                "native decision journal durable head anchor mismatch"
            )
    elif rows:
        transactions = projection["transactions"].values()
        if projection["seals"] or any(
            transaction.get("sealed") is True for transaction in transactions
        ):
            raise NativeDecisionJournalError(
                "sealed native decision journal has no durable head anchor"
            )
    local_consistency_verified = stable is not None and _heads_equal(stable, current)
    for transaction in projection["transactions"].values():
        transaction["local_consistency_verified"] = local_consistency_verified
        transaction["external_authority_verified"] = False
    # Do not combine a journal from one append with the anchor from another.
    # Concurrent publication is inconclusive here; only the writer recovers it.
    if (
        pending_path.is_file()
        or (store.read_bytes() if store.is_file() else b"") != payload
        or _read_json_object(anchor_path, label="head anchor") != stable_raw
    ):
        raise NativeDecisionJournalError("native decision journal changed during read")
    return rows, projection, payload, stable


def load_projection_read_only(contract_path: Path) -> dict[str, Any]:
    """Replay one stable journal without acquiring a write/recovery lock."""
    _rows, projection, _payload, _anchor = _read_anchored_rows_read_only(contract_path)
    return projection


def head_proof_read_only(contract_path: Path) -> JournalHeadProof:
    """Return the same head proof without locks, recovery or sidecar writes."""
    rows, _projection, payload, anchor = _read_anchored_rows_read_only(contract_path)
    return _build_head_proof(contract_path, rows, payload, anchor)


def head_proof(contract_path: Path) -> JournalHeadProof:
    """Return a complete local head for T06's independent anchor comparison.

    This component can establish only local consistency.  A synchronized
    rollback of the journal and sidecar remains indistinguishable from an old
    valid head until T06 compares this value with authority held elsewhere.
    """
    store = journal_path(contract_path)
    with _store_lock(store):
        rows, _projection, payload, anchor = _recover_anchored_rows(contract_path)
        return _build_head_proof(contract_path, rows, payload, anchor)


def _build_head_proof(
    contract_path: Path, rows: list[dict[str, Any]], payload: bytes,
    anchor: dict[str, Any] | None,
) -> JournalHeadProof:
    head = _head_value(contract_path, payload, rows)
    local_consistency_verified = anchor is not None and _heads_equal(anchor, head)
    anchor_sha256 = (
        hashlib.sha256(_canonical(anchor).encode("utf-8")).hexdigest()
        if anchor is not None
        else ""
    )
    proof: JournalHeadProof = {
        "schema": HEAD_PROOF_SCHEMA,
        "contract_sha256": head["contract_sha256"],
        "generation": head["sequence"],
        "sequence": head["sequence"],
        "event_id": head["event_id"],
        "event_sha256": head["event_id"],
        "journal_sha256": head["journal_sha256"],
        "anchor_sha256": anchor_sha256,
        "local_consistency_verified": local_consistency_verified,
        "external_authority_verified": False,
        "external_authority_status": "external_authority_unverified",
        "recovery_status": "pending",
        "external_anchor_required": True,
        "external_anchor_boundary": (
            "T03 verifies local consistency only; T06 must compare generation, "
            "sequence, event id/hash, journal digest, and anchor digest with an "
            "independent external anchor because synchronized local rollback or "
            "deletion is not detectable here"
        ),
        "proof_sha256": "",
    }
    proof["proof_sha256"] = hashlib.sha256(
        _canonical({key: value for key, value in proof.items() if key != "proof_sha256"}).encode("utf-8")
    ).hexdigest()
    return proof


Mutation = Callable[[dict[str, Any]], tuple[list[dict[str, Any]], Any]]


def _mutate(contract_path: Path, mutation: Mutation) -> tuple[dict[str, Any], Any]:
    store = journal_path(contract_path)
    with _store_lock(store):
        rows, projection, payload, _anchor = _recover_anchored_rows(contract_path)
        specs, result = mutation(projection)
        if specs:
            store.parent.mkdir(parents=True, exist_ok=True)
            appended: list[bytes] = []
            for spec in specs:
                row = {
                    "schema": EVENT_SCHEMA,
                    "contract_sha256": projection["contract_sha256"],
                    "sequence": len(rows) + 1,
                    "at": _now(),
                    "previous_event_id": (
                        str(rows[-1].get("event_id") or "") if rows else ""
                    ),
                    **spec,
                }
                row["event_id"] = hashlib.sha256(
                    _canonical(row).encode("utf-8")
                ).hexdigest()
                _apply(projection, row)
                rows.append(row)
                appended.append(
                    (json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n").encode(
                        "utf-8"
                    )
                )
            append_payload = b"".join(appended)
            prior_head = _head_value(
                contract_path, payload, rows[: len(rows) - len(specs)]
            )
            next_head = _head_value(contract_path, payload + append_payload, rows)
            pending = {
                "schema": HEAD_PENDING_SCHEMA,
                "contract_sha256": projection["contract_sha256"],
                "prior_head": prior_head,
                "next_head": next_head,
                "append_payload": append_payload.decode("utf-8"),
            }
            pending["pending_sha256"] = hashlib.sha256(
                _canonical(pending).encode("utf-8")
            ).hexdigest()
            _atomic_write_json(_head_pending_path(contract_path), pending)
            pending_anchor = dict(prior_head)
            pending_anchor["schema"] = HEAD_PENDING_ANCHOR_SCHEMA
            pending_anchor["pending_sha256"] = pending["pending_sha256"]
            _atomic_write_json(head_anchor_path(contract_path), pending_anchor)
            descriptor = os.open(store, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
            if os.name != "nt":
                os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "ab") as handle:
                handle.write(append_payload)
                handle.flush()
                os.fsync(handle.fileno())
            _atomic_write_json(head_anchor_path(contract_path), next_head)
            try:
                _head_pending_path(contract_path).unlink()
            except FileNotFoundError:
                pass
            _fsync_directory(store.parent)
            for transaction in projection["transactions"].values():
                transaction["local_consistency_verified"] = True
                transaction["external_authority_verified"] = False
        return projection, result


def prepare(
    contract_path: Path,
    binding: dict[str, Any],
    *,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if details is not None and (type(details) is not dict or not _is_plain_json(details)):
        raise NativeDecisionJournalError("native prepare details must be plain JSON")
    normalized = _validate_binding(binding)
    if _binding_operation(normalized) is None:
        raise NativeDecisionJournalError(
            "legacy native decision bindings are read-only; prepare requires one "
            "exact durable sealed authority"
        )
    tx_id = transaction_id(normalized)

    def mutation(projection: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
        existing = projection["transactions"].get(tx_id)
        if existing is not None:
            if existing.get("binding") != normalized:
                raise NativeDecisionJournalError("native transaction binding collision")
            return [], tx_id
        if _binding_operation(normalized) is not None:
            seal = projection["seals"].get(normalized["seal_id"])
            if (
                not isinstance(seal, dict)
                or seal["seal_event_id"] != normalized["seal_event_id"]
                or seal["binding"] != normalized
            ):
                raise NativeDecisionJournalError(
                    "native prepare binding does not match its durable seal"
                )
            if seal["consumed_by"] is not None:
                raise NativeDecisionJournalError("native durable seal was already consumed")
            _verify_request_semantics(
                contract_path,
                seal["binding"],
                seal["card"],
                seal["request_receipt"],
            )
        return [{
            "event": "prepared",
            "transaction_id": tx_id,
            "binding": normalized,
            "expected_seal_event_id": (
                normalized["seal_event_id"]
                if _binding_operation(normalized) is not None
                else None
            ),
            "details": _plain_json_copy(details or {}),
        }], tx_id

    projection, selected = _mutate(contract_path, mutation)
    return dict(projection["transactions"][selected])


def _advance_event(
    contract_path: Path,
    tx_id: str,
    *,
    stage: str,
    details: dict[str, Any] | None = None,
    allow_sealed: bool,
) -> dict[str, Any]:
    if type(tx_id) is not str or not tx_id.startswith("ndt-"):
        raise NativeDecisionJournalError("native decision transaction id is invalid")
    if type(stage) is not str or stage not in STAGES[1:]:
        raise NativeDecisionJournalError("unsupported native decision stage")
    if details is not None and (type(details) is not dict or not _is_plain_json(details)):
        raise NativeDecisionJournalError("native decision stage details must be plain JSON")

    def mutation(projection: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
        transaction = projection["transactions"].get(tx_id)
        if not isinstance(transaction, dict):
            raise NativeDecisionJournalError("unknown native decision transaction")
        _require_durable_seal_origin(projection, transaction)
        current = transaction["stage"]
        if current in STAGES and STAGES.index(stage) > STAGES.index(current) + 1:
            raise NativeDecisionJournalError(
                f"native decision cannot skip {current} -> {stage}"
            )
        if transaction.get("sealed") and not allow_sealed:
            raise NativeDecisionJournalError(
                "sealed native decision advancement requires approval authority"
            )
        if transaction["status"] == "superseded":
            return [], tx_id
        if STAGES.index(current) >= STAGES.index(stage):
            return [], tx_id
        return [{
            "event": "advanced",
            "transaction_id": tx_id,
            "expected_stage": current,
            "stage": stage,
            "details": _plain_json_copy(details or {}),
        }], tx_id

    projection, selected = _mutate(contract_path, mutation)
    return dict(projection["transactions"][selected])


def advance(
    contract_path: Path,
    tx_id: str,
    *,
    stage: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Reject caller-driven semantic advancement for every transaction format.

    T03 has no typed T06 adapter and no independent authority-store readers.
    Historical rows remain replayable, but neither legacy schema nor a sealed
    binding lets caller parameters write a semantic stage.
    """
    if type(tx_id) is not str or not tx_id.startswith("ndt-"):
        raise NativeDecisionJournalError("native decision transaction id is invalid")
    if type(stage) is not str or stage not in STAGES[1:]:
        raise NativeDecisionJournalError("unsupported native decision stage")
    if details is not None and (type(details) is not dict or not _is_plain_json(details)):
        raise NativeDecisionJournalError("native decision stage details must be plain JSON")
    projection = load_projection(contract_path)
    transaction = projection["transactions"].get(tx_id)
    if not isinstance(transaction, dict):
        raise NativeDecisionJournalError("unknown native decision transaction")
    _require_durable_seal_origin(projection, transaction)
    raise NativeDecisionJournalError(
        "external_authority_unverified: public native decision advancement is "
        "unavailable until T06 supplies typed adapter and independently verified "
        "approval, effect, contract, and external head-anchor receipts"
    )


def supersede(contract_path: Path, tx_id: str, *, reason: str) -> dict[str, Any]:
    if type(tx_id) is not str or not tx_id.startswith("ndt-"):
        raise NativeDecisionJournalError("native decision supersession values are invalid")
    projection = load_projection(contract_path)
    current = projection["transactions"].get(tx_id)
    if not isinstance(current, dict):
        raise NativeDecisionJournalError("unknown native decision transaction")
    binding = _require_durable_seal_origin(projection, current)
    if type(reason) is not str:
        raise NativeDecisionJournalError("native decision supersession values are invalid")
    clean = reason.strip()
    if not clean:
        raise NativeDecisionJournalError("native decision supersession requires a reason")
    details: dict[str, Any] = {}
    recorded: tuple[str, str] | None = None
    if current.get("stage") != "prepared":
        recorded = _recorded_authority(
            current,
            terminal_stage=(
                "superseded" if current.get("status") == "superseded" else None
            ),
        )
    decision_receipt = _verify_sealed_approval(
        contract_path,
        binding,
        decision_sha256=(recorded[0] if recorded else None),
        authority_sha256=(recorded[1] if recorded else None),
    )
    details = {
        "request_binding_sha256": binding["request_binding_sha256"],
        "decision_sha256": decision_receipt["decision_sha256"],
        "authority_sha256": _authority_sha256(binding, decision_receipt),
    }

    def mutation(projection: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
        transaction = projection["transactions"].get(tx_id)
        if not isinstance(transaction, dict):
            raise NativeDecisionJournalError("unknown native decision transaction")
        _require_durable_seal_origin(projection, transaction)
        if _historical_terminal(transaction):
            return [], tx_id
        return [{
            "event": "superseded",
            "transaction_id": tx_id,
            "reason": clean[:2_000],
            "details": details,
        }], tx_id

    projection, selected = _mutate(contract_path, mutation)
    return dict(projection["transactions"][selected])


def pending(contract_path: Path) -> list[dict[str, Any]]:
    projection = load_projection(contract_path)
    return [
        dict(row)
        for row in projection["transactions"].values()
        if row.get("status") == "active"
    ]


def authoritative_store_bytes(contract_path: Path) -> bytes:
    store = journal_path(contract_path)
    return store.read_bytes() if store.is_file() else b""


@dataclass(frozen=True)
class InternalRecoveryStep:
    """Untrusted, data-only caller observation retained for diagnostics.

    A name, class identity, boolean, token, or self-hash in this envelope is
    never adapter authority.  T03 does not use it to advance journal state.
    """

    schema: str
    plan: Mapping[str, Any]
    stage: str
    adapter: str
    adapter_contract_sha256: str
    observation: Mapping[str, Any]
    result: Mapping[str, Any]
    proof_sha256: str
    authority_status: str = "authority_unverified"


def _is_plain_json(value: Any) -> bool:
    if value is None or type(value) in {str, int, bool}:
        return True
    if type(value) is float:
        try:
            _canonical(value)
        except NativeDecisionJournalError:
            return False
        return True
    if type(value) is list:
        return all(_is_plain_json(nested) for nested in value)
    if type(value) is dict:
        return all(
            type(key) is str and _is_plain_json(nested)
            for key, nested in value.items()
        )
    return False


_NATIVE_PATH_TYPE = type(Path())
def _transaction_world_sha256(
    contract_path: Path,
    transaction: dict[str, Any],
    binding: dict[str, Any],
    decision_receipt: dict[str, Any],
) -> str:
    """Stable transaction world fence shared by all four external stores."""
    return hashlib.sha256(
        _canonical(
            {
                "contract_sha256": _contract_digest(contract_path),
                "transaction_id": transaction["transaction_id"],
                "operation": _binding_operation(binding),
                "request_id": binding["request_id"],
                "request_binding_sha256": binding["request_binding_sha256"],
                "card_sha256": binding["card_sha256"],
                "binding_sha256": _binding_sha256(binding),
                "decision_sha256": decision_receipt["decision_sha256"],
                "authority_sha256": _authority_sha256(binding, decision_receipt),
            }
        ).encode("utf-8")
    ).hexdigest()


def approval_authority_store_path(contract_path: Path) -> Path:
    """Return the sole canonical T12 source store for a contract."""
    name = contract_path.name
    stem = name[:-5] if name.endswith(".json") else name
    return contract_path.with_name(f"{stem}.approvals.jsonl")


def effect_authority_store_path(contract_path: Path) -> Path:
    """Return the sole canonical T10 source store for a contract."""
    name = contract_path.name
    stem = name[:-5] if name.endswith(".json") else name
    return contract_path.with_name(f"{stem}.interventions.jsonl")


def effect_receipt_store_path(contract_path: Path) -> Path:
    """Return the fixed append-only operation-effect receipt store."""
    name = contract_path.name
    stem = name[:-5] if name.endswith(".json") else name
    return contract_path.with_name(f".{stem}.native-effect-receipts.jsonl")


def contract_receipt_store_path(contract_path: Path) -> Path:
    """Return the fixed append-only formal-contract receipt store."""
    name = contract_path.name
    stem = name[:-5] if name.endswith(".json") else name
    return contract_path.with_name(f".{stem}.native-contract-receipts.jsonl")


def external_head_receipt_store_path(contract_path: Path) -> Path:
    """Return the fixed anchor store, separate from journal and local sidecar."""
    name = contract_path.name
    stem = name[:-5] if name.endswith(".json") else name
    return contract_path.with_name(f".{stem}.native-external-heads.jsonl")


def _source_control_error(label: str, detail: str) -> NativeDecisionJournalError:
    return NativeDecisionJournalError(
        f"native {label} canonical authority store control failed: {detail}"
    )


def _stable_read_source_bytes(path: Path, *, label: str) -> bytes:
    """Open a derived source path component-by-component without following links."""
    if type(path) is not _NATIVE_PATH_TYPE:
        raise _source_control_error(label, "source path was not internally derived")
    absolute = Path(os.path.abspath(path))
    if not absolute.is_absolute() or absolute.name != path.name:
        raise _source_control_error(label, "source path escaped its contract directory")
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    directory = getattr(os, "O_DIRECTORY", 0)
    cloexec = getattr(os, "O_CLOEXEC", 0)
    current_uid = os.geteuid() if hasattr(os, "geteuid") else os.getuid()
    descriptor = -1
    try:
        ancestors = list(reversed(absolute.parent.parents)) + [absolute.parent]
        for ancestor_path in ancestors:
            try:
                ancestor = os.lstat(ancestor_path)
            except OSError as error:
                raise _source_control_error(
                    label, f"nofollow ancestor lookup failed: {error}"
                ) from error
            if not stat.S_ISDIR(ancestor.st_mode):
                raise _source_control_error(
                    label, "symlink or non-directory ancestor"
                )
            if ancestor.st_uid not in {0, current_uid}:
                raise _source_control_error(label, "ancestor owner is not trusted")
            sticky_root = bool(
                ancestor.st_uid == 0 and ancestor.st_mode & stat.S_ISVTX
            )
            if ancestor.st_mode & 0o022 and not sticky_root:
                raise _source_control_error(label, "ancestor is group/world writable")
            try:
                ancestor_descriptor = os.open(
                    ancestor_path,
                    os.O_RDONLY | directory | nofollow | cloexec,
                )
            except PermissionError as error:
                # The managed macOS sandbox denies descriptor access to some
                # root-owned ancestors even though lstat is allowed.  Only that
                # immutable/root-controlled case may use the lstat identity;
                # the contract-owned directory is always opened below.
                if ancestor.st_uid != 0:
                    raise _source_control_error(
                        label, f"nofollow ancestor open failed: {error}"
                    ) from error
            except OSError as error:
                raise _source_control_error(
                    label, f"nofollow ancestor open failed: {error}"
                ) from error
            else:
                opened = os.fstat(ancestor_descriptor)
                os.close(ancestor_descriptor)
                if (
                    opened.st_dev != ancestor.st_dev
                    or opened.st_ino != ancestor.st_ino
                    or not stat.S_ISDIR(opened.st_mode)
                ):
                    raise _source_control_error(
                        label, "ancestor descriptor identity changed"
                    )
        try:
            parent_descriptor = os.open(
                absolute.parent,
                os.O_RDONLY | directory | nofollow | cloexec,
            )
            descriptor = os.open(
                absolute.name,
                os.O_RDONLY | nofollow | cloexec,
                dir_fd=parent_descriptor,
            )
        except OSError as error:
            raise _source_control_error(
                label, f"nofollow leaf open failed: {error}"
            ) from error

        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise _source_control_error(label, "source leaf is not regular")
        if before.st_uid != current_uid:
            raise _source_control_error(label, "source leaf owner is not current user")
        if before.st_mode & 0o022:
            raise _source_control_error(label, "source leaf is group/world writable")
        if before.st_nlink != 1:
            raise _source_control_error(label, "source leaf must have exactly one link")

        def path_identity() -> os.stat_result:
            try:
                return os.stat(
                    absolute.name,
                    dir_fd=parent_descriptor,
                    follow_symlinks=False,
                )
            except OSError as error:
                raise _source_control_error(label, f"source leaf lookup failed: {error}") from error

        def read_all() -> bytes:
            os.lseek(descriptor, 0, os.SEEK_SET)
            chunks: list[bytes] = []
            while True:
                chunk = os.read(descriptor, 64 * 1024)
                if not chunk:
                    return b"".join(chunks)
                chunks.append(chunk)

        path_before = path_identity()
        first = read_all()
        middle = os.fstat(descriptor)
        path_middle = path_identity()
        second = read_all()
        after = os.fstat(descriptor)
        path_after = path_identity()
        identities = {
            (item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns)
            for item in (
                before,
                path_before,
                middle,
                path_middle,
                after,
                path_after,
            )
        }
        if len(identities) != 1 or first != second:
            raise _source_control_error(label, "source changed during stable read")
        return first
    finally:
        try:
            if descriptor >= 0:
                os.close(descriptor)
        except OSError:
            pass
        parent = locals().get("parent_descriptor")
        if type(parent) is int:
            try:
                os.close(parent)
            except OSError:
                pass


def _decode_source_rows(payload: bytes, *, label: str) -> list[dict[str, Any]]:
    if not payload:
        raise NativeDecisionJournalError(
            f"native {label} canonical authority store is missing or empty"
        )
    if not payload.endswith(b"\n"):
        raise NativeDecisionJournalError(
            f"native {label} canonical authority store has an incomplete tail"
        )
    try:
        rows = [json.loads(line) for line in payload.decode("utf-8").splitlines()]
    except (UnicodeError, json.JSONDecodeError) as error:
        raise NativeDecisionJournalError(
            f"native {label} canonical authority store is invalid JSONL: {error}"
        ) from error
    if not rows or any(type(row) is not dict or not _is_plain_json(row) for row in rows):
        raise NativeDecisionJournalError(
            f"native {label} canonical authority rows must be exact plain JSON"
        )
    return rows


def _source_event_digest(row: dict[str, Any]) -> str:
    return hashlib.sha256(
        _canonical({key: value for key, value in row.items() if key != "event_id"}).encode(
            "utf-8"
        )
    ).hexdigest()


def _authority_world_sha256(
    contract_path: Path,
    transaction: dict[str, Any],
    binding: dict[str, Any],
) -> str:
    """Fence the sealed transaction without importing a legacy T03 decision."""
    return hashlib.sha256(
        _canonical(
            {
                "contract_sha256": _contract_digest(contract_path),
                "transaction_id": transaction["transaction_id"],
                "operation": _binding_operation(binding),
                "request_id": binding["request_id"],
                "request_binding_sha256": binding["request_binding_sha256"],
                "card_sha256": binding["card_sha256"],
                "binding_sha256": _binding_sha256(binding),
            }
        ).encode("utf-8")
    ).hexdigest()


def _t11_canonical_identity(kind: str, document: Any) -> str:
    """Execute the accepted T11 identity-envelope algorithm."""
    envelope = {
        "document": document,
        "kind": kind,
        "schema": "sulde-approval-cas-identity-v1",
    }
    return "sha256:" + hashlib.sha256(
        _canonical(envelope).encode("utf-8")
    ).hexdigest()


def _t11_parse_timestamp(value: Any) -> datetime | None:
    if type(value) is not str or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _t11_timeout_refresh_identity(
    previous_request_identity: str,
    replacement_request_identity: str,
    previous_expires_at: str,
) -> str:
    return _t11_canonical_identity(
        "approval-timeout-refresh",
        {
            "previous_request_identity": previous_request_identity,
            "replacement_request_identity": replacement_request_identity,
            "previous_expires_at": previous_expires_at,
        },
    )


def _t11_snapshot(
    contract_path: Path,
    transaction: dict[str, Any],
    binding: dict[str, Any],
    proof: JournalHeadProof,
) -> dict[str, Any]:
    """Map the sealed transaction onto the nine accepted T11 domains."""
    return {
        "card_sha256": binding["card_sha256"],
        "provider": binding["provider"],
        "session_id": binding["session_id"],
        "lane_sha256": _lane_digest(binding["provider"], binding["session_id"]),
        "target_sha256": _digest(binding["target"]),
        "revision": binding["intent_revision"],
        "journal_sha256": proof["journal_sha256"],
        "effect_sha256": _digest(binding["action"]),
        "world_state_sha256": _authority_world_sha256(
            contract_path, transaction, binding
        ),
    }


def _t11_prompt_snapshot(
    contract_path: Path,
    transaction: dict[str, Any],
    binding: dict[str, Any],
) -> dict[str, Any]:
    """Reconstruct the snapshot shown before the durable seal was appended."""
    rows, projection, payload, _anchor = _recover_anchored_rows(contract_path)
    seal = projection["seals"].get(binding["seal_id"])
    if (
        not isinstance(seal, dict)
        or seal.get("seal_event_id") != binding["seal_event_id"]
        or seal.get("consumed_by") != transaction["transaction_id"]
    ):
        raise NativeDecisionJournalError(
            "native approval_decided has no exact durable seal origin"
        )
    seal_sequence = seal.get("seal_sequence")
    if type(seal_sequence) is not int or not 1 <= seal_sequence <= len(rows):
        raise NativeDecisionJournalError(
            "native approval_decided durable seal sequence is invalid"
        )
    raw_lines = payload.splitlines(keepends=True)
    if len(raw_lines) != len(rows):
        raise NativeDecisionJournalError(
            "native approval_decided journal framing is invalid"
        )
    prompt_journal_sha256 = hashlib.sha256(
        b"".join(raw_lines[: seal_sequence - 1])
    ).hexdigest()
    return {
        "card_sha256": binding["card_sha256"],
        "provider": binding["provider"],
        "session_id": binding["session_id"],
        "lane_sha256": _lane_digest(binding["provider"], binding["session_id"]),
        "target_sha256": _digest(binding["target"]),
        "revision": binding["intent_revision"],
        "journal_sha256": prompt_journal_sha256,
        "effect_sha256": _digest(binding["action"]),
        "world_state_sha256": _workspace_digest(binding["workspace"]),
    }


def _t11_receipt_identities(receipt: dict[str, Any]) -> tuple[str, str, str]:
    snapshot_identity = _t11_canonical_identity(
        "approval-snapshot", receipt["snapshot"]
    )
    request_identity = _t11_canonical_identity(
        "approval-request",
        {
            "request_id": receipt["request_id"],
            "snapshot": receipt["snapshot"],
        },
    )
    decision_identity = _t11_canonical_identity(
        "approval-decision",
        {
            "request_id": receipt["request_id"],
            "receipt_id": receipt["receipt_id"],
            "outcome": receipt["outcome"],
            "snapshot": receipt["snapshot"],
        },
    )
    return snapshot_identity, request_identity, decision_identity


def _t10_resource_set_identity(resources: Any) -> str:
    return hashlib.sha256(_canonical(resources).encode("utf-8")).hexdigest()


def _t10_batch_semantics(row: dict[str, Any]) -> dict[str, Any]:
    return {
        key: row[key]
        for key in (
            "batch_id",
            "call_id",
            "idempotency_key",
            "intent_id",
            "intent_revision",
            "fingerprint",
            "source_event_id",
            "capability",
            "effect",
            "provider",
            "session_id",
            "task_id",
            "operation_arguments_digest",
            "resources",
        )
    }


def _t10_batch_semantics_identity(row: dict[str, Any]) -> str:
    return hashlib.sha256(
        _canonical(_t10_batch_semantics(row)).encode("utf-8")
    ).hexdigest()


def _read_t12_approval_authority(
    contract_path: Path,
    transaction: dict[str, Any],
    binding: dict[str, Any],
    proof: JournalHeadProof,
) -> tuple[dict[str, Any], str]:
    payload = _stable_read_source_bytes(
        approval_authority_store_path(contract_path), label="approval_decided"
    )
    rows = _decode_source_rows(payload, label="approval_decided")
    contract_sha256 = _contract_digest(contract_path)
    expected_snapshot = _t11_snapshot(contract_path, transaction, binding, proof)
    expected_prompt_snapshot = _t11_prompt_snapshot(
        contract_path, transaction, binding
    )
    requests: dict[str, dict[str, Any]] = {}
    pending_replacements: dict[str, dict[str, str]] = {}
    event_fields = {
        "approval.asked": {
            "at",
            "card_sha256",
            "contract_sha256",
            "decision_owner",
            "expires_at",
            "intent_id_sha256",
            "intent_revision",
            "kind",
            "lane_sha256",
            "prompt_shown",
            "proposal_sha256",
            "provider",
            "reassess_at",
            "replaced_request_id",
            "replacement_identity",
            "request_id",
            "request_identity",
            "route",
            "schema",
            "sequence",
            "snapshot",
            "snapshot_identity",
            "source",
            "target_sha256",
            "type",
            "typed",
            "workspace_sha256",
        },
        "approval.prompt-observed": {
            "at",
            "contract_sha256",
            "decision_owner",
            "lane_sha256",
            "prompt_shown",
            "provider",
            "request_id",
            "schema",
            "sequence",
            "snapshot_identity",
            "type",
            "typed",
        },
        "approval.replaced": {
            "at",
            "contract_sha256",
            "replacement_identity",
            "replacement_request_id",
            "request_id",
            "schema",
            "sequence",
            "type",
            "typed",
        },
        "approval.decided": {
            "actor",
            "at",
            "contract_sha256",
            "decision_owner",
            "lane_sha256",
            "outcome",
            "provider",
            "receipt_sha256",
            "request_id",
            "schema",
            "sequence",
            "type",
            "typed",
            "typed_receipt",
        },
    }
    for sequence, row in enumerate(rows, 1):
        if row.get("contract_sha256") != contract_sha256:
            raise NativeDecisionJournalError(
                "native approval_decided source row belongs to another contract"
            )
        if row.get("sequence") != sequence or type(row.get("sequence")) is not int:
            raise NativeDecisionJournalError(
                "native approval_decided source sequence is not contiguous"
            )
        if type(row.get("at")) is not str or not row["at"].strip():
            raise NativeDecisionJournalError(
                "native approval_decided source timestamp is invalid"
            )
        schema = row.get("schema")
        if schema == "sulde-approval-pair-event-v1":
            continue
        if schema != APPROVAL_CAS_EVENT_SCHEMA:
            raise NativeDecisionJournalError(
                "native approval_decided source schema is unknown"
            )
        if row.get("typed") is not True:
            continue
        event_type = row.get("type")
        if event_type not in event_fields:
            raise NativeDecisionJournalError(
                "native approval_decided typed source event is invalid"
            )
        if (
            set(row) != event_fields[event_type]
            or row.get("typed") is not True
            or not _is_request_id(row.get("request_id"))
        ):
            raise NativeDecisionJournalError(
                f"native approval_decided typed {event_type} payload is malformed"
            )
        request_id = row["request_id"]
        if pending_replacements and (
            event_type != "approval.asked"
            or request_id not in pending_replacements
        ):
            raise NativeDecisionJournalError(
                "native approval_decided replacement has no exact following fresh request"
            )
        if event_type == "approval.asked":
            provider = row["provider"]
            lane_sha256 = row["lane_sha256"]
            snapshot = row.get("snapshot")
            if (
                type(provider) is not str
                or not provider
                or type(lane_sha256) is not str
                or type(snapshot) is not dict
                or not _is_plain_json(snapshot)
                or set(snapshot) != {
                    "card_sha256",
                    "provider",
                    "session_id",
                    "lane_sha256",
                    "target_sha256",
                    "revision",
                    "journal_sha256",
                    "effect_sha256",
                    "world_state_sha256",
                }
            ):
                raise NativeDecisionJournalError(
                    "native approval_decided asked snapshot fields are invalid"
                )
            expected_snapshot_identity = _t11_canonical_identity(
                "approval-snapshot", snapshot
            )
            expected_request_identity = _t11_canonical_identity(
                "approval-request",
                {"request_id": request_id, "snapshot": snapshot},
            )
            if (
                request_id in requests
                or row.get("snapshot_identity") != expected_snapshot_identity
                or row.get("request_identity") != expected_request_identity
                or snapshot.get("provider") != provider
                or snapshot.get("lane_sha256") != lane_sha256
                or row.get("card_sha256") != snapshot.get("card_sha256")
                or row.get("target_sha256") != snapshot.get("target_sha256")
                or row.get("intent_revision") != snapshot.get("revision")
                or row.get("route") != "human"
                or row.get("decision_owner") != "human"
                or row.get("prompt_shown") is not False
                or _t11_parse_timestamp(row.get("expires_at")) is None
            ):
                raise NativeDecisionJournalError(
                    "native approval_decided asked lifecycle payload is invalid"
                )
            replaced_request_id = row["replaced_request_id"]
            replacement_identity = row["replacement_identity"]
            if (
                type(replaced_request_id) is not str
                or type(replacement_identity) is not str
            ):
                raise NativeDecisionJournalError(
                    "native approval_decided asked replacement lineage is invalid"
                )
            pending = pending_replacements.get(request_id)
            if pending is None:
                if replaced_request_id != "" or replacement_identity != "":
                    raise NativeDecisionJournalError(
                        "native approval_decided asked replacement lineage is invalid"
                    )
            else:
                previous_request_id = pending["replaced_request_id"]
                previous = requests[previous_request_id]
                same_snapshot = snapshot == previous["snapshot"]
                if same_snapshot:
                    previous_expires_at = previous["expires_at"]
                    expired_at = _t11_parse_timestamp(previous_expires_at)
                    replaced_at = _t11_parse_timestamp(
                        pending["replacement_at"]
                    )
                    if (
                        expired_at is None
                        or replaced_at is None
                        or expired_at > replaced_at
                    ):
                        raise NativeDecisionJournalError(
                            "native approval_decided timeout refresh predecessor was not expired"
                        )
                    expected_replacement_identity = (
                        _t11_timeout_refresh_identity(
                            previous["request_identity"],
                            expected_request_identity,
                            previous_expires_at,
                        )
                    )
                else:
                    expected_replacement_identity = _t11_canonical_identity(
                        "approval-fresh-replacement",
                        {
                            "previous_request_identity": previous["request_identity"],
                            "replacement_request_identity": expected_request_identity,
                        },
                    )
                if (
                    replaced_request_id != previous_request_id
                    or replacement_identity != expected_replacement_identity
                    or pending["replacement_identity"]
                    != expected_replacement_identity
                    or request_id == previous_request_id
                    or (
                        not same_snapshot
                        and snapshot.get("card_sha256")
                        == previous["snapshot"].get("card_sha256")
                    )
                    or snapshot not in (
                        expected_snapshot,
                        expected_prompt_snapshot,
                    )
                ):
                    raise NativeDecisionJournalError(
                        "native approval_decided asked replacement lineage is invalid"
                    )
                pending_replacements.pop(request_id)
            requests[request_id] = {
                "request_row": dict(row),
                "snapshot": snapshot,
                "snapshot_identity": expected_snapshot_identity,
                "request_identity": expected_request_identity,
                "provider": provider,
                "lane_sha256": lane_sha256,
                "prompt_observed": False,
                "terminal": False,
                "replaced": False,
                "replaced_request_id": replaced_request_id,
                "replacement_identity": replacement_identity,
                "expires_at": row["expires_at"],
            }
            continue

        state = requests.get(request_id)
        if state is None:
            raise NativeDecisionJournalError(
                f"native approval_decided {event_type} is orphaned"
            )
        if event_type == "approval.prompt-observed":
            if (
                state["terminal"] is True
                or state["prompt_observed"] is True
                or row.get("provider") != state["provider"]
                or row.get("lane_sha256") != state["lane_sha256"]
                or row.get("snapshot_identity") != state["snapshot_identity"]
                or row.get("prompt_shown") is not True
                or row.get("decision_owner") != "human"
            ):
                raise NativeDecisionJournalError(
                    "native approval_decided prompt lifecycle payload is invalid"
                )
            state["prompt_observed"] = True
            continue

        if event_type == "approval.replaced":
            replacement_request_id = row.get("replacement_request_id")
            replacement_identity = row.get("replacement_identity")
            if (
                state["terminal"] is True
                or not _is_request_id(replacement_request_id)
                or replacement_request_id == request_id
                or type(replacement_identity) is not str
                or not replacement_identity.startswith("sha256:")
                or replacement_request_id in requests
                or replacement_request_id in pending_replacements
            ):
                raise NativeDecisionJournalError(
                    "native approval_decided replacement lifecycle payload is invalid"
                )
            pending_replacements[replacement_request_id] = {
                "replaced_request_id": request_id,
                "replacement_identity": replacement_identity,
                "replacement_at": row["at"],
            }
            state["terminal"] = True
            state["replaced"] = True
            continue

        if (
            state["terminal"] is True
            or state["prompt_observed"] is not True
            or state["replaced"] is True
        ):
            raise NativeDecisionJournalError(
                "native approval_decided decision is not for one open prompted request"
            )
        receipt = row.get("typed_receipt")
        required = {
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
        if (
            type(receipt) is not dict
            or not _is_plain_json(receipt)
            or set(receipt) != required
        ):
            raise NativeDecisionJournalError(
                "native approval_decided T12 receipt fields are invalid"
            )
        snapshot = receipt.get("snapshot")
        if type(snapshot) is not dict or set(snapshot) != {
            "card_sha256",
            "provider",
            "session_id",
            "lane_sha256",
            "target_sha256",
            "revision",
            "journal_sha256",
            "effect_sha256",
            "world_state_sha256",
        }:
            raise NativeDecisionJournalError(
                "native approval_decided T11 snapshot fields are invalid"
            )
        identities = _t11_receipt_identities(receipt)
        expected_receipt_lineage = (
            state["replacement_identity"]
            if state["replacement_identity"]
            else None
        )
        if (
            receipt.get("schema") != APPROVAL_CAS_RECEIPT_SCHEMA
            or receipt.get("request_id") != request_id
            or row.get("provider") != state["provider"]
            or row.get("lane_sha256") != state["lane_sha256"]
            or receipt.get("snapshot") != state["snapshot"]
            or receipt.get("snapshot_identity") != identities[0]
            or receipt.get("request_identity") != identities[1]
            or receipt.get("decision_identity") != identities[2]
            or receipt.get("replacement_identity")
            != expected_receipt_lineage
            or receipt.get("execution_authorized") is not False
            or receipt.get("outcome") not in {"allow", "deny"}
            or type(receipt.get("receipt_id")) is not str
            or not receipt["receipt_id"]
            or row.get("outcome") != receipt["outcome"]
            or row.get("decision_owner") != "human"
            or type(row.get("actor")) is not str
            or not row["actor"].strip()
            or row.get("receipt_sha256") != _digest(receipt["receipt_id"])
        ):
            raise NativeDecisionJournalError(
                "native approval_decided T12 decision correlation is invalid"
            )
        state["terminal"] = True
        state["receipt"] = receipt
        state["decision_row"] = row

    if pending_replacements:
        raise NativeDecisionJournalError(
            "native approval_decided replacement has no exact fresh request"
        )
    binding_states = [
        state
        for request_id, state in requests.items()
        if request_id == binding["request_id"]
    ]
    exact_selected = [
        state
        for state in binding_states
        if state.get("terminal") is True
        and state.get("replaced") is False
        and type(state.get("receipt")) is dict
        and state["receipt"].get("outcome") == "allow"
        and state["receipt"].get("snapshot") == expected_prompt_snapshot
        and state["request_row"].get("kind") == binding["approval_kind"]
        and state["request_row"].get("source") == binding["source"]
        and state["request_row"].get("intent_id_sha256")
        == _digest(binding["intent_id"])
        and state["request_row"].get("proposal_sha256")
        == (
            _digest(binding["target"])
            if binding["approval_kind"] == "proposal"
            else ""
        )
        and state["request_row"].get("workspace_sha256")
        == _workspace_digest(binding["workspace"])
    ]
    bridged_selected = [
        state
        for state in requests.values()
        if state.get("terminal") is True
        and state.get("replaced") is False
        and type(state.get("receipt")) is dict
        and state["receipt"].get("outcome") == "allow"
        and state["receipt"].get("snapshot") == expected_snapshot
    ]
    selected = exact_selected if binding_states else bridged_selected
    if len(selected) != 1:
        raise NativeDecisionJournalError(
            "native approval_decided canonical store has no unique current T12 receipt"
        )
    state = selected[0]
    receipt = state["receipt"]
    row = state["decision_row"]
    return receipt, _source_event_digest(row)


def _read_t10_dispatch_boundary(
    contract_path: Path,
    transaction: dict[str, Any],
    binding: dict[str, Any],
) -> tuple[str, str]:
    payload = _stable_read_source_bytes(
        effect_authority_store_path(contract_path), label="effect_applied"
    )
    rows = _decode_source_rows(payload, label="effect_applied")
    contract_sha256 = _contract_digest(contract_path)
    approval = transaction.get("stage_details", {}).get("approval_decided", {})
    source_event_id = (
        approval.get("source_event_id") if type(approval) is dict else None
    )
    if not _is_sha256(source_event_id):
        raise NativeDecisionJournalError(
            "native effect_applied has no accepted T12 source-row identity"
        )
    prepared: list[dict[str, Any]] = []
    dispatched: list[dict[str, Any]] = []
    v2_seen = False
    for sequence, row in enumerate(rows, 1):
        if (
            type(row.get("sequence")) is not int
            or row.get("sequence") != sequence
            or row.get("contract_sha256") != contract_sha256
            or type(row.get("at")) is not str
            or not row["at"].strip()
        ):
            raise NativeDecisionJournalError(
                "native effect_applied T10 source identity or sequence is invalid"
            )
        if row.get("schema") == "sulde-intervention-event-v1":
            if v2_seen:
                raise NativeDecisionJournalError(
                    "native effect_applied legacy rows must be a v1 prefix"
                )
            continue
        if row.get("schema") != T10_BATCH_EVENT_SCHEMA:
            raise NativeDecisionJournalError(
                "native effect_applied source schema is unknown"
            )
        v2_seen = True
        if not _is_sha256(row.get("event_id")) or row["event_id"] != _source_event_digest(row):
            raise NativeDecisionJournalError(
                "native effect_applied T10 event identity is invalid"
            )
        if row.get("type") == "effect.batch_prepared":
            required = {
                "schema",
                "contract_sha256",
                "sequence",
                "at",
                "type",
                "event_id",
                "batch_id",
                "call_id",
                "idempotency_key",
                "intent_id",
                "intent_revision",
                "fingerprint",
                "source_event_id",
                "capability",
                "effect",
                "provider",
                "session_id",
                "task_id",
                "operation_arguments_digest",
                "resources",
                "resource_set_sha256",
                "batch_semantics_sha256",
            }
            if set(row) != required:
                raise NativeDecisionJournalError(
                    "native effect_applied T10 prepared fields are invalid"
                )
            if row.get("source_event_id") == source_event_id:
                prepared.append(row)
        elif row.get("type") == "effect.batch_dispatched":
            required = {
                "schema",
                "contract_sha256",
                "sequence",
                "at",
                "type",
                "event_id",
                "batch_id",
                "call_id",
                "idempotency_key",
                "prepared_event_id",
                "resource_set_sha256",
                "batch_semantics_sha256",
            }
            if set(row) != required:
                raise NativeDecisionJournalError(
                    "native effect_applied T10 dispatched fields are invalid"
                )
            dispatched.append(row)
        else:
            raise NativeDecisionJournalError(
                "native effect_applied T10 typed event is unsupported"
            )
    if len(prepared) == 1:
        dispatched = [
            row
            for row in dispatched
            if row.get("prepared_event_id") == prepared[0].get("event_id")
        ]
    if len(prepared) != 1 or len(dispatched) != 1:
        raise NativeDecisionJournalError(
            "native effect_applied requires one exact prepare and one exact one-shot dispatch"
        )
    before, after = prepared[0], dispatched[0]
    string_fields = {
        "batch_id",
        "call_id",
        "idempotency_key",
        "intent_id",
        "fingerprint",
        "source_event_id",
        "capability",
        "effect",
        "provider",
        "session_id",
        "task_id",
        "operation_arguments_digest",
        "resource_set_sha256",
        "batch_semantics_sha256",
    }
    if (
        type(before.get("intent_revision")) is not int
        or any(type(before.get(field)) is not str or not before[field] for field in string_fields)
        or type(before.get("resources")) is not list
        or not before["resources"]
        or not _is_plain_json(before["resources"])
    ):
        raise NativeDecisionJournalError(
            "native effect_applied T10 prepared payload is malformed"
        )
    if (
        before["resource_set_sha256"] != _t10_resource_set_identity(before["resources"])
        or before["batch_semantics_sha256"] != _t10_batch_semantics_identity(before)
        or before.get("batch_id") != after.get("batch_id")
        or before.get("call_id") != after.get("call_id")
        or before.get("idempotency_key") != after.get("idempotency_key")
        or before.get("resource_set_sha256") != after.get("resource_set_sha256")
        or before.get("batch_semantics_sha256") != after.get("batch_semantics_sha256")
        or after.get("prepared_event_id") != before.get("event_id")
    ):
        raise NativeDecisionJournalError(
            "native effect_applied T10 call/resource/batch dispatch CAS is invalid"
        )
    expected = {
        "intent_id": binding["intent_id"],
        "intent_revision": binding["intent_revision"],
        "source_event_id": source_event_id,
        "provider": binding["provider"],
        "session_id": binding["session_id"],
    }
    mismatches = [key for key, value in expected.items() if before.get(key) != value]
    if mismatches:
        raise NativeDecisionJournalError(
            "native effect_applied T10 sealed semantics mismatch: "
            + ", ".join(mismatches)
        )
    raise NativeDecisionJournalError(
        "native effect_applied requires an upstream contract that seals the "
        "original T10 resources and operation arguments; the T03 binding "
        "cannot prove that semantic match"
    )


_AUTHORITY_RECEIPT_FIELDS = {
    "schema",
    "receipt_id",
    "contract_sha256",
    "transaction_id",
    "operation",
    "decision",
    "request_id",
    "request_binding_sha256",
    "card_sha256",
    "binding_sha256",
    "prior_stage",
    "prior_source_event_id",
    "journal_generation",
    "journal_event_id",
    "journal_sha256",
    "source_kind",
    "source_sha256",
    "source_event_id",
    "postcondition",
    "postcondition_sha256",
    "receipt_sha256",
}
_AUTHORITY_EVENT_FIELDS = {
    "schema",
    "contract_sha256",
    "sequence",
    "at",
    "stage",
    "transaction_id",
    "previous_event_id",
    "receipt",
    "event_id",
}
_STAGE_RECEIPT_SPECS = {
    "effect_applied": (
        "approval_decided",
        EFFECT_POSTCONDITION_RECEIPT_SCHEMA,
        effect_receipt_store_path,
        "canonical-operation-postcondition",
    ),
    "contract_applied": (
        "effect_applied",
        CONTRACT_POSTCONDITION_RECEIPT_SCHEMA,
        contract_receipt_store_path,
        "canonical-intent-contract",
    ),
    "committed": (
        "contract_applied",
        EXTERNAL_HEAD_RECEIPT_SCHEMA,
        external_head_receipt_store_path,
        "independent-native-head-anchor",
    ),
}


def _read_contract_document(contract_path: Path) -> tuple[dict[str, Any], bytes]:
    payload = _stable_read_source_bytes(contract_path, label="contract_applied")
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise NativeDecisionJournalError(
            f"native canonical intent contract is invalid JSON: {error}"
        ) from error
    if type(value) is not dict or not _is_plain_json(value):
        raise NativeDecisionJournalError(
            "native canonical intent contract must be an exact plain JSON object"
        )
    if value.get("schema") != "sulde-intent-contract-v1":
        raise NativeDecisionJournalError(
            "native canonical intent contract schema is unknown"
        )
    return value, payload


def _matching_contract_receipt(
    document: dict[str, Any], binding: dict[str, Any]
) -> dict[str, Any]:
    runtime = document.get("runtime")
    receipts = runtime.get("approval_receipts") if type(runtime) is dict else None
    if type(receipts) is not list:
        raise NativeDecisionJournalError(
            "native contract postcondition has no formal approval receipt projection"
        )
    matches = [
        row
        for row in receipts
        if type(row) is dict
        and row.get("schema") == "sulde-decision-receipt-v2"
        and row.get("approval_request_id") == binding["request_id"]
        and row.get("action") == binding["action"]
        and row.get("target") == binding["target"]
        and row.get("intent_id") == binding["intent_id"]
        and row.get("provider") == binding["provider"]
        and row.get("session_id") == binding["session_id"]
        and row.get("channel") == "codex-native-permission"
        and row.get("actor") == "permission-request:codex"
        and type(row.get("receipt_id")) is str
        and _is_sha256(row.get("receipt_id"))
        and type(row.get("consumed_at")) is str
        and bool(row.get("consumed_at"))
        and row.get("consumed_by") == "native-permission-control-executor"
    ]
    if len(matches) != 1:
        raise NativeDecisionJournalError(
            "native contract postcondition requires one exact consumed receipt"
        )
    return matches[0]


def _contract_postcondition(
    contract_path: Path, binding: dict[str, Any]
) -> tuple[dict[str, Any], str, str]:
    document, payload = _read_contract_document(contract_path)
    if (
        document.get("intent_id") != binding["intent_id"]
        or document.get("workspace_root") != binding["workspace"]
        or type(document.get("revision")) is not int
        or int(document["revision"]) < int(binding["intent_revision"])
    ):
        raise NativeDecisionJournalError(
            "native contract postcondition belongs to another sealed intent world"
        )
    receipt = _matching_contract_receipt(document, binding)
    operation = _binding_operation(binding)
    runtime = document["runtime"]
    postcondition: dict[str, Any]
    if operation == "proposal":
        verdict = "approve" if binding["decision"] == "approve" else "reject"
        decisions = runtime.get("proposal_decisions")
        if type(decisions) is not list:
            decisions = []
        matches = [
            row
            for row in decisions
            if type(row) is dict
            and row.get("schema") == "sulde-intent-proposal-decision-v1"
            and row.get("proposal_digest") == binding["target"]
            and row.get("authority") == "human"
            and row.get("verdict") == verdict
            and row.get("provider") == binding["provider"]
            and row.get("session_id") == binding["session_id"]
            and row.get("receipt_id") == receipt["receipt_id"]
            and _is_sha256(row.get("decision_id"))
        ]
        applied = document.get("applied_proposal_digest")
        if len(matches) != 1 or (
            verdict == "approve" and applied != binding["target"]
        ) or (
            verdict == "reject"
            and (
                runtime.get("pending_proposal_digest") == binding["target"]
                or applied == binding["target"]
            )
        ):
            raise NativeDecisionJournalError(
                f"native proposal {verdict} postcondition is not proven"
            )
        postcondition = {
            "kind": "proposal",
            "verdict": verdict,
            "proposal_digest": binding["target"],
            "decision_id": matches[0]["decision_id"],
            "receipt_id": receipt["receipt_id"],
            "revision": document["revision"],
        }
    elif operation == "resume":
        resumed = document.get("resumed_lane")
        lanes = runtime.get("task_lanes")
        if type(resumed) is not dict or type(lanes) is not list:
            raise NativeDecisionJournalError(
                "native resume postcondition has no formal lane projection"
            )
        paused = [
            row
            for row in lanes
            if type(row) is dict
            and row.get("provider") == binding["provider"]
            and row.get("session_id") == binding["session_id"]
            and row.get("state") == "paused"
        ]
        if (
            resumed.get("provider") != binding["provider"]
            or resumed.get("session_id") != binding["session_id"]
            or resumed.get("task_epoch") != document.get("task_epoch")
            or paused
        ):
            raise NativeDecisionJournalError(
                "native resume postcondition is not proven for the sealed lane"
            )
        postcondition = {
            "kind": "resume",
            "provider": binding["provider"],
            "session_id": binding["session_id"],
            "task_epoch": resumed["task_epoch"],
            "receipt_id": receipt["receipt_id"],
            "revision": document["revision"],
        }
    elif operation == "task-continuation" and document.get("task_continuation_selection") is not None:
        try:
            postcondition = verify_selected_task_route(document, binding, receipt)
        except (ValueError, KeyError, OSError, TypeError) as error:
            raise NativeDecisionJournalError("selected task route postcondition is not proven") from error
    elif operation == "task-continuation":
        lanes = runtime.get("task_lanes")
        continuations = runtime.get("task_continuations")
        if type(lanes) is not list or type(continuations) is not list:
            raise NativeDecisionJournalError(
                "native task continuation has no formal lane projection"
            )
        lane_matches = [
            row
            for row in lanes
            if type(row) is dict
            and row.get("provider") == binding["provider"]
            and row.get("session_id") == binding["session_id"]
            and row.get("task_epoch") == binding["task_epoch"]
            and row.get("state") == "bound"
            and row.get("source") == "native_session_continuation"
        ]
        continuation_matches = [
            row
            for row in continuations
            if type(row) is dict
            and row.get("schema") == "sulde-task-continuation-v1"
            and row.get("target") == binding["target"]
            and row.get("provider") == binding["provider"]
            and row.get("session_id") == binding["session_id"]
            and row.get("task_epoch") == binding["task_epoch"]
            and row.get("receipt_id") == receipt["receipt_id"]
            and row.get("authority_transferred") is False
        ]
        if len(lane_matches) != 1 or len(continuation_matches) != 1:
            raise NativeDecisionJournalError(
                "native task continuation postcondition is not proven"
            )
        postcondition = {
            "kind": "task-continuation",
            "provider": binding["provider"],
            "session_id": binding["session_id"],
            "task_epoch": binding["task_epoch"],
            "continuation_id": continuation_matches[0]["continuation_id"],
            "receipt_id": receipt["receipt_id"],
            "authority_transferred": False,
            "revision": document["revision"],
        }
    elif operation == "effect":
        if receipt.get("decision") != binding["decision"]:
            raise NativeDecisionJournalError(
                "native effect-intervention contract decision is not projected"
            )
        postcondition = {
            "kind": "effect-intervention",
            "intervention_id": binding["target"],
            "decision": binding["decision"],
            "receipt_id": receipt["receipt_id"],
            "revision": document["revision"],
        }
    else:
        raise NativeDecisionJournalError(
            "native operation has no accepted contract postcondition producer"
        )
    source_sha256 = hashlib.sha256(payload).hexdigest()
    return postcondition, source_sha256, source_sha256


def _effect_postcondition(
    contract_path: Path, binding: dict[str, Any]
) -> tuple[dict[str, Any], str, str, str]:
    operation = _binding_operation(binding)
    if operation != "effect":
        postcondition, source_sha256, source_event_id = _contract_postcondition(
            contract_path, binding
        )
        return (
            postcondition,
            "canonical-intent-contract",
            source_sha256,
            source_event_id,
        )
    payload = _stable_read_source_bytes(
        effect_authority_store_path(contract_path), label="effect completion"
    )
    rows = _decode_source_rows(payload, label="effect completion")
    selected: list[dict[str, Any]] = []
    v2_seen = False
    for sequence, row in enumerate(rows, 1):
        if row.get("schema") == "sulde-intervention-event-v1":
            if v2_seen:
                raise NativeDecisionJournalError(
                    "native effect completion legacy rows must be a v1 prefix"
                )
            continue
        v2_seen = True
        if (
            row.get("schema") != T10_BATCH_EVENT_SCHEMA
            or row.get("contract_sha256") != _contract_digest(contract_path)
            or type(row.get("sequence")) is not int
            or row.get("sequence") != sequence
            or not _is_sha256(row.get("event_id"))
            or row["event_id"] != _source_event_digest(row)
        ):
            raise NativeDecisionJournalError(
                "native effect completion source chain is invalid"
            )
        subject_matches = (
            row.get("attempt_id") == binding["effect_attempt_id"]
            and row.get("intent_revision")
            == binding["effect_subject_intent_revision"]
            if binding.get("schema") == BINDING_SCHEMA
            else True
        )
        if (
            row.get("type") == "intent.intervention_resolved"
            and row.get("intervention_id") == binding["target"]
            and subject_matches
            and row.get("intent_id") == binding["intent_id"]
            and row.get("provider") == binding["provider"]
            and row.get("session_id") == binding["session_id"]
            and row.get("decision") == binding["decision"]
            and row.get("actor") == "permission-request:codex"
            and (
                binding["decision"] == "abort"
                or (
                    row.get("takeover_provider") == binding["provider"]
                    and row.get("takeover_session_id") == binding["session_id"]
                )
            )
        ):
            selected.append(row)
    if len(selected) != 1:
        raise NativeDecisionJournalError(
            "native effect-intervention completion requires one exact resolved source event"
        )
    row = selected[0]
    postcondition = {
        "kind": "effect-intervention",
        "intervention_id": binding["target"],
        "attempt_id": str(row.get("attempt_id") or ""),
        "subject_intent_revision": int(row.get("intent_revision") or 0),
        "decision": binding["decision"],
        "provider": binding["provider"],
        "session_id": binding["session_id"],
    }
    return (
        postcondition,
        "canonical-intervention-jsonl",
        hashlib.sha256(payload).hexdigest(),
        row["event_id"],
    )


def _prior_source_event_id(transaction: dict[str, Any], prior_stage: str) -> str:
    details = transaction.get("stage_details", {}).get(prior_stage)
    value = details.get("source_event_id") if type(details) is dict else None
    if not _is_sha256(value):
        raise NativeDecisionJournalError(
            f"native {prior_stage} has no exact source event identity"
        )
    return value


def _build_authority_receipt(
    contract_path: Path,
    transaction: dict[str, Any],
    binding: dict[str, Any],
    *,
    stage: str,
    proof: JournalHeadProof,
) -> dict[str, Any]:
    prior_stage, receipt_schema, _path, source_kind = _STAGE_RECEIPT_SPECS[stage]
    if transaction.get("stage") != prior_stage:
        raise NativeDecisionJournalError(
            f"native {stage} producer requires prior stage {prior_stage}"
        )
    prior_source_event_id = _prior_source_event_id(transaction, prior_stage)
    if stage == "effect_applied":
        postcondition, source_kind, source_sha256, source_event_id = (
            _effect_postcondition(contract_path, binding)
        )
    elif stage == "contract_applied":
        postcondition, source_sha256, source_event_id = _contract_postcondition(
            contract_path, binding
        )
    else:
        source_sha256 = proof["proof_sha256"]
        source_event_id = proof["event_id"]
        postcondition = {
            "kind": "external-head",
            "generation": proof["generation"],
            "event_id": proof["event_id"],
            "journal_sha256": proof["journal_sha256"],
            "anchor_sha256": proof["anchor_sha256"],
            "local_consistency_verified": proof["local_consistency_verified"],
        }
        if not proof["local_consistency_verified"] or not _is_sha256(
            proof["event_id"]
        ):
            raise NativeDecisionJournalError(
                "native external head producer requires one locally consistent non-empty head"
            )
    base = {
        "schema": receipt_schema,
        "contract_sha256": _contract_digest(contract_path),
        "transaction_id": transaction["transaction_id"],
        "operation": _binding_operation(binding),
        "decision": binding["decision"],
        "request_id": binding["request_id"],
        "request_binding_sha256": binding["request_binding_sha256"],
        "card_sha256": binding["card_sha256"],
        "binding_sha256": _binding_sha256(binding),
        "prior_stage": prior_stage,
        "prior_source_event_id": prior_source_event_id,
        "journal_generation": proof["generation"],
        "journal_event_id": proof["event_id"],
        "journal_sha256": proof["journal_sha256"],
        "source_kind": source_kind,
        "source_sha256": source_sha256,
        "source_event_id": source_event_id,
        "postcondition": postcondition,
        "postcondition_sha256": hashlib.sha256(
            _canonical(postcondition).encode("utf-8")
        ).hexdigest(),
    }
    receipt_id = "nar-" + hashlib.sha256(
        _canonical(base).encode("utf-8")
    ).hexdigest()[:32]
    receipt = dict(base, receipt_id=receipt_id)
    receipt["receipt_sha256"] = hashlib.sha256(
        _canonical(receipt).encode("utf-8")
    ).hexdigest()
    return receipt


def _validate_authority_receipt(
    contract_path: Path, receipt: Any, *, stage: str
) -> dict[str, Any]:
    prior_stage, receipt_schema, _path, _kind = _STAGE_RECEIPT_SPECS[stage]
    if (
        type(receipt) is not dict
        or not _is_plain_json(receipt)
        or set(receipt) != _AUTHORITY_RECEIPT_FIELDS
        or receipt.get("schema") != receipt_schema
        or receipt.get("contract_sha256") != _contract_digest(contract_path)
        or receipt.get("prior_stage") != prior_stage
        or type(receipt.get("journal_generation")) is not int
        or receipt["journal_generation"] < 1
        or type(receipt.get("receipt_id")) is not str
        or not receipt["receipt_id"].startswith("nar-")
        or any(
            not _is_sha256(receipt.get(field))
            for field in (
                "request_binding_sha256",
                "card_sha256",
                "binding_sha256",
                "prior_source_event_id",
                "journal_event_id",
                "journal_sha256",
                "source_sha256",
                "source_event_id",
                "postcondition_sha256",
                "receipt_sha256",
            )
        )
        or type(receipt.get("postcondition")) is not dict
        or hashlib.sha256(
            _canonical(receipt.get("postcondition")).encode("utf-8")
        ).hexdigest()
        != receipt.get("postcondition_sha256")
    ):
        raise NativeDecisionJournalError(
            f"native {stage} authority receipt fields or values are invalid"
        )
    unsigned = dict(receipt)
    supplied_sha256 = unsigned.pop("receipt_sha256")
    if hashlib.sha256(_canonical(unsigned).encode("utf-8")).hexdigest() != supplied_sha256:
        raise NativeDecisionJournalError(
            f"native {stage} authority receipt digest is invalid"
        )
    base = dict(unsigned)
    supplied_id = base.pop("receipt_id")
    expected_id = "nar-" + hashlib.sha256(
        _canonical(base).encode("utf-8")
    ).hexdigest()[:32]
    if supplied_id != expected_id:
        raise NativeDecisionJournalError(
            f"native {stage} authority receipt id is invalid"
        )
    return dict(receipt)


def _decode_authority_events(
    contract_path: Path, payload: bytes, *, stage: str
) -> list[dict[str, Any]]:
    if not payload:
        return []
    if not payload.endswith(b"\n"):
        raise NativeDecisionJournalError(
            f"native {stage} authority store has an incomplete tail"
        )
    try:
        rows = [json.loads(line) for line in payload.decode("utf-8").splitlines()]
    except (UnicodeError, json.JSONDecodeError) as error:
        raise NativeDecisionJournalError(
            f"native {stage} authority store is invalid JSONL: {error}"
        ) from error
    previous_event_id = ""
    for sequence, row in enumerate(rows, 1):
        if (
            type(row) is not dict
            or not _is_plain_json(row)
            or set(row) != _AUTHORITY_EVENT_FIELDS
            or row.get("schema") != AUTHORITY_RECEIPT_EVENT_SCHEMA
            or row.get("contract_sha256") != _contract_digest(contract_path)
            or type(row.get("sequence")) is not int
            or row.get("sequence") != sequence
            or row.get("stage") != stage
            or row.get("previous_event_id") != previous_event_id
            or not _is_sha256(row.get("event_id"))
            or row["event_id"] != _source_event_digest(row)
            or row.get("transaction_id")
            != row.get("receipt", {}).get("transaction_id")
        ):
            raise NativeDecisionJournalError(
                f"native {stage} authority event chain is invalid"
            )
        _validate_authority_receipt(contract_path, row.get("receipt"), stage=stage)
        previous_event_id = row["event_id"]
    return rows


def _append_authority_receipt(
    contract_path: Path, receipt: dict[str, Any], *, stage: str
) -> dict[str, Any]:
    _prior, _schema, path_factory, _kind = _STAGE_RECEIPT_SPECS[stage]
    path = path_factory(contract_path)
    with _store_lock(path):
        payload = (
            _stable_read_source_bytes(path, label=f"{stage} producer")
            if path.is_file()
            else b""
        )
        rows = _decode_authority_events(contract_path, payload, stage=stage)
        matching = [
            row
            for row in rows
            if row["transaction_id"] == receipt["transaction_id"]
        ]
        if matching:
            if len(matching) == 1 and matching[0]["receipt"] == receipt:
                return dict(receipt)
            raise NativeDecisionJournalError(
                f"native {stage} authority receipt is duplicated or conflicting"
            )
        row = {
            "schema": AUTHORITY_RECEIPT_EVENT_SCHEMA,
            "contract_sha256": _contract_digest(contract_path),
            "sequence": len(rows) + 1,
            "at": _now(),
            "stage": stage,
            "transaction_id": receipt["transaction_id"],
            "previous_event_id": rows[-1]["event_id"] if rows else "",
            "receipt": receipt,
        }
        row["event_id"] = _source_event_digest(row)
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(
            path,
            os.O_APPEND
            | os.O_CREAT
            | os.O_WRONLY
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
            0o600,
        )
        if os.name != "nt":
            os.fchmod(descriptor, 0o600)
        opened = os.fstat(descriptor)
        leaf = os.lstat(path)
        current_uid = os.geteuid() if hasattr(os, "geteuid") else os.getuid()
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_uid != current_uid
            or opened.st_nlink != 1
            or opened.st_dev != leaf.st_dev
            or opened.st_ino != leaf.st_ino
        ):
            os.close(descriptor)
            raise _source_control_error(
                stage, "authority receipt leaf identity is not trusted"
            )
        with os.fdopen(descriptor, "ab") as handle:
            handle.write((json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        _fsync_directory(path.parent)
        return dict(receipt)


def _reverify_recorded_receipt(
    contract_path: Path,
    transaction: dict[str, Any],
    binding: dict[str, Any],
    *,
    stage: str,
) -> None:
    """Reprove a consumed source receipt without requiring its old journal head."""
    _prior, _schema, path_factory, _kind = _STAGE_RECEIPT_SPECS[stage]
    details = transaction.get("stage_details", {}).get(stage)
    if type(details) is not dict or type(details.get("authority_receipt")) is not dict:
        raise NativeDecisionJournalError(
            f"native {stage} has no recorded authority receipt"
        )
    recorded = _validate_authority_receipt(
        contract_path, details["authority_receipt"], stage=stage
    )
    if (
        recorded.get("transaction_id") != transaction.get("transaction_id")
        or recorded.get("operation") != _binding_operation(binding)
        or recorded.get("decision") != binding["decision"]
        or recorded.get("request_id") != binding["request_id"]
        or recorded.get("request_binding_sha256")
        != binding["request_binding_sha256"]
        or recorded.get("card_sha256") != binding["card_sha256"]
        or recorded.get("binding_sha256") != _binding_sha256(binding)
    ):
        raise NativeDecisionJournalError(
            f"native recorded {stage} receipt binding was substituted"
        )
    path = path_factory(contract_path)
    rows = _decode_authority_events(
        contract_path,
        _stable_read_source_bytes(path, label=f"recorded {stage}"),
        stage=stage,
    )
    matching = [
        row
        for row in rows
        if row["transaction_id"] == transaction["transaction_id"]
    ]
    if (
        len(matching) != 1
        or matching[0]["receipt"] != recorded
        or matching[0]["event_id"] != details.get("source_event_id")
    ):
        raise NativeDecisionJournalError(
            f"native recorded {stage} source event was truncated, duplicated, or substituted"
        )
    if stage == "effect_applied":
        postcondition, source_kind, source_sha256, source_event_id = (
            _effect_postcondition(contract_path, binding)
        )
    elif stage == "contract_applied":
        postcondition, source_sha256, source_event_id = _contract_postcondition(
            contract_path, binding
        )
        source_kind = "canonical-intent-contract"
    else:
        return
    if (
        recorded["source_kind"] != source_kind
        or recorded["source_sha256"] != source_sha256
        or recorded["source_event_id"] != source_event_id
        or recorded["postcondition"] != postcondition
    ):
        raise NativeDecisionJournalError(
            f"native recorded {stage} upstream postcondition changed"
        )


def _produce_stage_receipt(
    contract_path: Path, tx_id: str, *, stage: str
) -> dict[str, Any]:
    if type(tx_id) is not str or not tx_id.startswith("ndt-"):
        raise NativeDecisionJournalError("native decision transaction id is invalid")
    with _recovery_lock(contract_path, tx_id):
        projection = load_projection(contract_path)
        transaction = projection["transactions"].get(tx_id)
        if not isinstance(transaction, dict):
            raise NativeDecisionJournalError("unknown native decision transaction")
        binding = _require_durable_seal_origin(projection, transaction)
        if stage == "contract_applied":
            _reverify_recorded_receipt(
                contract_path, transaction, binding, stage="effect_applied"
            )
        elif stage == "committed":
            _reverify_recorded_receipt(
                contract_path, transaction, binding, stage="contract_applied"
            )
        proof = head_proof(contract_path)
        receipt = _build_authority_receipt(
            contract_path, transaction, binding, stage=stage, proof=proof
        )
        return _append_authority_receipt(contract_path, receipt, stage=stage)


def produce_effect_receipt(contract_path: Path, tx_id: str) -> NativeEffectReceipt:
    """Observe one formal operation postcondition and append its effect receipt."""
    return _produce_stage_receipt(contract_path, tx_id, stage="effect_applied")  # type: ignore[return-value]


def produce_contract_receipt(
    contract_path: Path, tx_id: str
) -> NativeContractReceipt:
    """Observe the formal intent projection and append its contract receipt."""
    return _produce_stage_receipt(contract_path, tx_id, stage="contract_applied")  # type: ignore[return-value]


def produce_external_head_receipt(
    contract_path: Path, tx_id: str
) -> NativeExternalHeadReceipt:
    """Append the current contract-stage head to the separate anchor store."""
    return _produce_stage_receipt(contract_path, tx_id, stage="committed")  # type: ignore[return-value]


def _verify_stage_receipt(
    contract_path: Path, tx_id: str, *, stage: str
) -> tuple[dict[str, Any], str]:
    prior_stage, _schema, _path_factory, _kind = _STAGE_RECEIPT_SPECS[stage]
    projection = load_projection(contract_path)
    transaction = projection["transactions"].get(tx_id)
    if not isinstance(transaction, dict):
        raise NativeDecisionJournalError("unknown native decision transaction")
    binding = _require_durable_seal_origin(projection, transaction)
    proof = head_proof(contract_path)
    if transaction.get("stage") != prior_stage:
        raise NativeDecisionJournalError(
            f"native {stage} verifier requires prior stage {prior_stage}"
        )
    return _read_stage_receipt_against(
        contract_path,
        transaction,
        binding,
        proof,
        stage=stage,
    )


def _read_stage_receipt_against(
    contract_path: Path,
    transaction: dict[str, Any],
    binding: dict[str, Any],
    proof: JournalHeadProof,
    *,
    stage: str,
) -> tuple[dict[str, Any], str]:
    _prior_stage, _schema, path_factory, _kind = _STAGE_RECEIPT_SPECS[stage]
    if stage == "contract_applied":
        _reverify_recorded_receipt(
            contract_path, transaction, binding, stage="effect_applied"
        )
    elif stage == "committed":
        _reverify_recorded_receipt(
            contract_path, transaction, binding, stage="contract_applied"
        )
    path = path_factory(contract_path)
    payload = _stable_read_source_bytes(path, label=stage)
    rows = _decode_authority_events(contract_path, payload, stage=stage)
    tx_id = transaction["transaction_id"]
    matching = [row for row in rows if row["transaction_id"] == tx_id]
    if len(matching) != 1:
        raise NativeDecisionJournalError(
            f"native {stage} requires one exact one-shot authority receipt"
        )
    receipt = _validate_authority_receipt(
        contract_path, matching[0]["receipt"], stage=stage
    )
    expected = _build_authority_receipt(
        contract_path, transaction, binding, stage=stage, proof=proof
    )
    if receipt != expected:
        raise NativeDecisionJournalError(
            f"native {stage} receipt is stale or bound to another transaction world"
        )
    return receipt, matching[0]["event_id"]


def verify_effect_receipt(
    contract_path: Path, tx_id: str
) -> NativeEffectReceipt:
    """Independently verify the unique current operation-effect receipt."""
    receipt, _event_id = _verify_stage_receipt(
        contract_path, tx_id, stage="effect_applied"
    )
    return receipt  # type: ignore[return-value]


def verify_contract_receipt(
    contract_path: Path, tx_id: str
) -> NativeContractReceipt:
    """Independently verify the unique current contract-projection receipt."""
    receipt, _event_id = _verify_stage_receipt(
        contract_path, tx_id, stage="contract_applied"
    )
    return receipt  # type: ignore[return-value]


def verify_external_head_receipt(
    contract_path: Path, tx_id: str
) -> NativeExternalHeadReceipt:
    """Independently verify the unique separate-store head receipt."""
    receipt, _event_id = _verify_stage_receipt(
        contract_path, tx_id, stage="committed"
    )
    return receipt  # type: ignore[return-value]


def verify_recorded_external_head_receipt(
    contract_path: Path, tx_id: str
) -> NativeExternalHeadReceipt:
    """Replay the durable external-head receipt after the transaction committed.

    ``verify_external_head_receipt`` is the pre-CAS verifier for a transaction
    still at ``contract_applied``.  Doctor/readiness runs after the CAS and must
    instead verify the exact receipt copied into the committed journal event
    against the separate append-only external-head store.
    """
    projection = load_projection(contract_path)
    transaction = projection["transactions"].get(tx_id)
    if not isinstance(transaction, dict):
        raise NativeDecisionJournalError("unknown native decision transaction")
    if (
        transaction.get("stage") != "committed"
        or transaction.get("historical_status") != "committed"
        or transaction.get("historical_terminal_seen") is not True
    ):
        raise NativeDecisionJournalError(
            "native recorded external head verifier requires committed transaction"
        )
    binding = _require_durable_seal_origin(projection, transaction)
    _reverify_recorded_receipt(
        contract_path,
        transaction,
        binding,
        stage="committed",
    )
    receipt = transaction.get("stage_details", {}).get("committed", {}).get(
        "authority_receipt"
    )
    if not isinstance(receipt, dict):
        raise NativeDecisionJournalError(
            "native committed transaction has no recorded external head receipt"
        )
    return dict(receipt)  # type: ignore[return-value]


@_request_validation_scope()
def _advance_receipt_chain_locked(
    path: Path,
    transaction: dict[str, Any],
    readers: NativeAuthorityReaders,
    *,
    failpoint: Callable[[str], None] | None = None,
    error_type: type[Exception] = NativeDecisionJournalError,
) -> dict[str, Any]:
    """Receipt-only tail; caller must hold the existing non-reentrant contract lock.

    No operation adapter or approval mutation runs here. Lock order remains
    contract -> native recovery/journal. Exact receipt bytes, one-stage CAS and
    terminal-history semantics are unchanged. Request validation reuse observes
    the independent approval source before AND after every replay pass; the
    contract lock is never treated as a lock on that source.
    """
    tx_id = str(transaction["transaction_id"])
    latest = load_projection(path)["transactions"].get(tx_id)
    if not isinstance(latest, dict) or latest.get("binding") != transaction.get("binding"):
        raise error_type("native receipt tail transaction binding changed")
    transaction = latest  # A competing recoverer may already have advanced.
    if transaction["stage"] in {"committed", "superseded"}:
        return transaction  # Observation only; never a new execution ticket.
    producers = {
        "approval_decided": produce_effect_receipt,
        "effect_applied": produce_contract_receipt,
        "contract_applied": produce_external_head_receipt,
    }
    failpoints = {
        "effect_applied": "after_effect_applied",
        "contract_applied": "after_contract_applied",
        "committed": "after_committed",
    }
    while transaction["stage"] != "committed":
        stage = transaction["stage"]
        if stage not in producers:
            raise error_type(f"unsupported native receipt tail stage: {stage}")
        if stage == "approval_decided" and transaction["binding"]["kind"] == "effect-intervention":
            raise error_type("effect resolution must precede the receipt-only tail")
        producers[stage](path, tx_id)
        if stage == "contract_applied" and failpoint is not None:
            failpoint("after_anchor_receipt")
        result = advance_with_authority(path, tx_id, readers=readers)
        if not result["advanced"]:
            return dict(transaction, advancement_reason=result["reason"])
        transaction = dict(transaction, stage=result["stage"])
        if transaction["stage"] == "committed":
            transaction["status"] = "committed"
        if failpoint is not None:
            failpoint(failpoints[transaction["stage"]])
    return transaction


def recovery_plan(
    contract_path: Path, tx_id: str, *, operation: str
) -> dict[str, Any]:
    """Return a data-only plan for T06; no recovery step is executed here."""
    if type(tx_id) is not str or not tx_id.startswith("ndt-"):
        raise NativeDecisionJournalError("native decision transaction id is invalid")
    selected_operation = _operation(operation)
    projection = load_projection(contract_path)
    transaction = projection["transactions"].get(tx_id)
    if not isinstance(transaction, dict):
        raise NativeDecisionJournalError("unknown native decision transaction")
    binding = _validate_binding(transaction["binding"])
    if _binding_operation(binding) != selected_operation:
        raise NativeDecisionJournalError(
            "native recovery operation does not match sealed binding"
        )
    decision_receipt = _verify_sealed_approval(contract_path, binding)
    local_head = head_proof(contract_path)
    world_sha256 = _transaction_world_sha256(
        contract_path, transaction, binding, decision_receipt
    )
    required_postconditions = {
        "effect": {
            "receipt_schema": EFFECT_POSTCONDITION_RECEIPT_SCHEMA,
            "authority_store": "fixed canonical operation-effect receipt store",
            "journal_verifier": "verify_effect_receipt",
            "producer": "produce_effect_receipt",
        },
        "contract": {
            "receipt_schema": CONTRACT_POSTCONDITION_RECEIPT_SCHEMA,
            "authority_store": "fixed canonical contract receipt store",
            "journal_verifier": "verify_contract_receipt",
            "producer": "produce_contract_receipt",
            "must_anchor_journal_head": True,
        },
        "head": {
            "receipt_schema": EXTERNAL_HEAD_RECEIPT_SCHEMA,
            "authority_store": "fixed separate external-head receipt store",
            "journal_verifier": "verify_external_head_receipt",
            "producer": "produce_external_head_receipt",
        },
    }
    plan = {
        "schema": RECOVERY_PLAN_SCHEMA,
        "contract_sha256": _contract_digest(contract_path),
        "transaction_id": tx_id,
        "operation": selected_operation,
        "binding_sha256": _binding_sha256(binding),
        "request_binding_sha256": binding["request_binding_sha256"],
        "decision_sha256": decision_receipt["decision_sha256"],
        "authority_sha256": _authority_sha256(binding, decision_receipt),
        "world_sha256": world_sha256,
        "journal_head_proof": local_head,
        "journal_head_proof_sha256": local_head["proof_sha256"],
        "journal_head_external_anchor_required": local_head[
            "external_anchor_required"
        ],
        "required_adapter_receipt_schema": T06_ADAPTER_RECEIPT_SCHEMA,
        "required_postcondition_receipt_schema": T06_POSTCONDITION_RECEIPT_SCHEMA,
        "required_postconditions": required_postconditions,
        "authority_advancement": {
            "public_api": "advance_with_authority",
            "reader_type": "NativeAuthorityReaders",
            "caller_reader_values": "data-only",
            "source_paths": "derived-from-contract",
            "approval_event_schema": APPROVAL_CAS_EVENT_SCHEMA,
            "approval_receipt_schema": APPROVAL_CAS_RECEIPT_SCHEMA,
            "effect_event_schema": T10_BATCH_EVENT_SCHEMA,
            "effect_boundary": "dispatch-is-not-completion",
            "effect_producer": "produce_effect_receipt",
            "contract_producer": "produce_contract_receipt",
            "head_anchor_producer": "produce_external_head_receipt",
            "producer_inputs": "contract-path-and-transaction-id-only",
            "one_stage_per_call": True,
        },
        "approval_authority_status": "verified",
        "authority_status": "authority_unverified",
        "local_consistency_verified": local_head["local_consistency_verified"],
        "external_authority_verified": False,
        "external_authority_status": "external_authority_unverified",
        "journal_state": "pending",
        "execution_authority": "independent-read-back-only",
        "t06_seam": (
            "T06 writes no journal stage directly. T13 derives and replays the "
            "canonical T12/T10/contract paths and fixed append-only receipt stores; "
            "NativeAuthorityReaders values cannot select a source. T10 dispatch is "
            "never completion. T06 may call the public producer seams only after its "
            "operation; each producer independently proves the formal postcondition "
            "and accepts no caller success claim."
        ),
    }
    plan["plan_sha256"] = hashlib.sha256(
        _canonical(plan).encode("utf-8")
    ).hexdigest()
    return plan


def internal_recovery_result(
    plan: Mapping[str, Any],
    *,
    stage: str,
    adapter: str,
    adapter_contract_sha256: str,
    observation: Mapping[str, Any],
    result: Mapping[str, Any],
) -> InternalRecoveryStep:
    """Package a caller claim for diagnostics; it is never authority."""
    if (
        type(plan) is not dict
        or type(observation) is not dict
        or type(result) is not dict
        or type(stage) is not str
        or type(adapter) is not str
        or type(adapter_contract_sha256) is not str
        or not _is_plain_json(plan)
        or not _is_plain_json(observation)
        or not _is_plain_json(result)
    ):
        raise NativeDecisionJournalError(
            "native recovery result must contain plain JSON objects"
        )
    values = {
        "schema": RECOVERY_RESULT_SCHEMA,
        "plan": _plain_json_copy(plan),
        "stage": stage,
        "adapter": adapter,
        "adapter_contract_sha256": adapter_contract_sha256,
        "observation": _plain_json_copy(observation),
        "result": _plain_json_copy(result),
    }
    if not _is_plain_json(values):
        raise NativeDecisionJournalError(
            "native recovery result cannot contain executable values"
        )
    proof_sha256 = hashlib.sha256(_canonical(values).encode("utf-8")).hexdigest()
    return InternalRecoveryStep(
        **values,
        proof_sha256=proof_sha256,
        authority_status="authority_unverified",
    )


def _verify_sealed_approval(
    contract_path: Path,
    binding: dict[str, Any],
    *,
    decision_sha256: str | None = None,
    authority_sha256: str | None = None,
) -> dict[str, Any]:
    operation = _binding_operation(binding)
    if operation is None:
        raise NativeDecisionJournalError(
            "legacy native transaction is unsealed and requires explicit handling"
        )
    try:
        receipt = request_binding_receipt(contract_path, binding["request_id"])
        if receipt["binding_sha256"] != binding["request_binding_sha256"]:
            raise NativeDecisionJournalError(
                "native approval request receipt was substituted"
            )
        request = verify_request_binding_receipt(contract_path, receipt)
        spec = OPERATION_SPECS[operation]
        expected = {
            "intent_id_sha256": _digest(binding["intent_id"]),
            "intent_revision": int(binding["intent_revision"]),
            "kind": spec["approval_kind"],
            "target_sha256": _digest(binding["target"]),
            "card_sha256": binding["card_sha256"],
            "workspace_sha256": _workspace_digest(binding["workspace"]),
            "proposal_sha256": (
                _digest(binding["target"])
                if spec["approval_kind"] == "proposal"
                else ""
            ),
            "route": "human",
            "provider": binding["provider"],
            "lane_sha256": _lane_digest(
                binding["provider"], binding["session_id"]
            ),
            "source": binding["source"],
        }
        mismatches = [
            key for key, value in expected.items() if request.get(key) != value
        ]
        if mismatches:
            raise NativeDecisionJournalError(
                "sealed native approval binding mismatch: " + ", ".join(mismatches)
            )
        decision_receipt = decided_request_receipt(
            contract_path,
            receipt,
            outcome=("allow" if request.get("typed") is True else "approved"),
            provider=binding["provider"],
            session_id=binding["session_id"],
            actor="permission-request:codex",
        )
        if (
            decision_sha256 is not None
            and decision_receipt["decision_sha256"] != decision_sha256
        ):
            raise NativeDecisionJournalError(
                "native approval decision receipt was substituted"
            )
        if (
            authority_sha256 is not None
            and _authority_sha256(binding, decision_receipt) != authority_sha256
        ):
            raise NativeDecisionJournalError(
                "native approval authority binding digest was substituted"
            )
        return decision_receipt
    except (ApprovalInvariantError, TypeError) as error:
        raise NativeDecisionJournalError(
            f"native approval is not durably decided: {error}"
        ) from error


@contextmanager
def _recovery_lock(contract_path: Path, tx_id: str) -> Iterator[None]:
    store = journal_path(contract_path)
    recovery = store.with_name(f".{store.name}.{tx_id}.recovery")
    with _store_lock(recovery):
        yield


def _recorded_authority(
    transaction: dict[str, Any], *, terminal_stage: str | None = None
) -> tuple[str, str]:
    stages = transaction.get("stage_details")
    selected = None
    if isinstance(stages, dict):
        if terminal_stage is not None:
            selected = stages.get(terminal_stage)
        if not isinstance(selected, dict):
            selected = stages.get("approval_decided")
    decision_digest = (
        str(selected.get("decision_sha256") or "")
        if isinstance(selected, dict)
        else ""
    )
    authority_digest = (
        str(selected.get("authority_sha256") or "")
        if isinstance(selected, dict)
        else ""
    )
    if not _is_sha256(decision_digest) or not _is_sha256(authority_digest):
        raise NativeDecisionJournalError(
            "sealed native transaction has no valid recorded approval authority"
        )
    return decision_digest, authority_digest


def _legacy_binding_matches_operation(
    binding: dict[str, Any], operation: str
) -> bool:
    spec = OPERATION_SPECS[operation]
    return (
        binding.get("kind") == spec["kind"]
        and binding.get("approval_kind") == spec["approval_kind"]
        and spec["decisions"].get(binding.get("decision")) == binding.get("action")
    )


def _advancement_result(
    *,
    transaction: dict[str, Any],
    operation: str,
    prior_stage: str,
    stage: str,
    status: str,
    reason: str,
    advanced: bool,
    external_authority_verified: bool,
    receipt: dict[str, Any] | None,
    proof: JournalHeadProof,
) -> AuthorityAdvancementResult:
    receipt_digest = ""
    if type(receipt) is dict:
        if (
            receipt.get("schema") == APPROVAL_CAS_RECEIPT_SCHEMA
            and type(receipt.get("receipt_id")) is str
        ):
            receipt_digest = _digest(receipt["receipt_id"])
        else:
            receipt_digest = str(receipt.get("receipt_sha256") or "")
    return {
        "schema": AUTHORITY_ADVANCEMENT_RESULT_SCHEMA,
        "transaction_id": str(transaction.get("transaction_id") or ""),
        "operation": operation,
        "prior_stage": prior_stage,
        "stage": stage,
        "status": status,
        "reason": reason,
        "advanced": advanced,
        "local_consistency_verified": proof["local_consistency_verified"],
        "external_authority_verified": external_authority_verified,
        "authority_status": (
            "verified"
            if external_authority_verified
            else ("stage_verified" if advanced else "authority_unverified")
        ),
        "receipt_schema": str((receipt or {}).get("schema") or ""),
        "receipt_sha256": receipt_digest,
        "journal_head_proof": proof,
    }


def advance_with_authority(
    contract_path: Path,
    tx_id: str,
    *,
    readers: NativeAuthorityReaders,
    failpoint: Optional[str] = None,
) -> AuthorityAdvancementResult:
    """Advance at most one stage from independent, source-specific read-backs.

    This function never creates or decides an approval request and never calls
    an external adapter or tool.  Each call reads exactly the receipt needed by
    the current stage and performs the CAS expressible by the accepted producer
    envelope.  Missing or caller-shaped authority is returned as typed
    ``pending``.
    """
    if type(tx_id) is not str or not tx_id.startswith("ndt-"):
        raise NativeDecisionJournalError("native decision transaction id is invalid")
    allowed_failpoints = {
        None,
        "after_prepared",
        "after_approval",
        "after_effect",
        "after_contract",
        "after_anchor",
    }
    if type(failpoint) is not str and failpoint is not None:
        failpoint = "invalid"
    with _recovery_lock(contract_path, tx_id):
        projection = load_projection(contract_path)
        transaction = projection["transactions"].get(tx_id)
        if not isinstance(transaction, dict):
            raise NativeDecisionJournalError("unknown native decision transaction")
        proof = head_proof(contract_path)
        prior_stage = str(transaction.get("stage") or "")
        binding = _validate_binding(transaction["binding"])
        operation = _binding_operation(binding)
        if operation is None:
            return _advancement_result(
                transaction=transaction,
                operation="",
                prior_stage=prior_stage,
                stage=prior_stage,
                status="pending",
                reason="legacy or unsealed transaction is diagnostic read-only",
                advanced=False,
                external_authority_verified=False,
                receipt=None,
                proof=proof,
            )
        try:
            _require_durable_seal_origin(projection, transaction)
        except NativeDecisionJournalError as error:
            return _advancement_result(
                transaction=transaction,
                operation=operation,
                prior_stage=prior_stage,
                stage=prior_stage,
                status="pending",
                reason=str(error),
                advanced=False,
                external_authority_verified=False,
                receipt=None,
                proof=proof,
            )
        if type(readers) is not NativeAuthorityReaders:
            return _advancement_result(
                transaction=transaction,
                operation=operation,
                prior_stage=prior_stage,
                stage=prior_stage,
                status="pending",
                reason="typed authority seam is required; caller values remain data-only",
                advanced=False,
                external_authority_verified=False,
                receipt=None,
                proof=proof,
            )
        if failpoint not in allowed_failpoints:
            return _advancement_result(
                transaction=transaction,
                operation=operation,
                prior_stage=prior_stage,
                stage=prior_stage,
                status="pending",
                reason="invalid failure token is data-only and cannot grant authority",
                advanced=False,
                external_authority_verified=False,
                receipt=None,
                proof=proof,
            )
        if prior_stage == "prepared":
            if failpoint == "after_prepared":
                raise NativeDecisionAdvancementInterrupted("after_prepared")
            try:
                receipt, source_event_id = _read_t12_approval_authority(
                    contract_path, transaction, binding, proof
                )
            except NativeDecisionJournalError as error:
                return _advancement_result(
                    transaction=transaction,
                    operation=operation,
                    prior_stage=prior_stage,
                    stage=prior_stage,
                    status="pending",
                    reason=str(error),
                    advanced=False,
                    external_authority_verified=False,
                    receipt=None,
                    proof=proof,
                )
            if failpoint == "after_approval":
                raise NativeDecisionAdvancementInterrupted("after_approval")
            receipt_sha256 = _digest(receipt["receipt_id"])
            sealed_decision = _verify_sealed_approval(contract_path, binding)
            decision_sha256 = sealed_decision["decision_sha256"]
            details = {
                "authority_receipt": _plain_json_copy(receipt),
                "authority_receipt_sha256": receipt_sha256,
                "authority_source": "canonical-t12-approval-jsonl",
                "source_event_id": source_event_id,
                "typed_request_id": receipt["request_id"],
                "request_binding_sha256": binding["request_binding_sha256"],
                "decision_sha256": decision_sha256,
                "authority_sha256": _authority_sha256(binding, sealed_decision),
                "world_sha256": receipt["snapshot"]["world_state_sha256"],
                "expected_generation": proof["generation"],
                "journal_executed_adapter": False,
                "journal_executed_external_tool": False,
            }

            def mutation(
                current_projection: dict[str, Any],
            ) -> tuple[list[dict[str, Any]], str]:
                current = current_projection["transactions"].get(tx_id)
                if not isinstance(current, dict):
                    raise NativeDecisionJournalError(
                        "unknown native decision transaction"
                    )
                current_binding = _require_durable_seal_origin(
                    current_projection, current
                )
                if (
                    current_projection.get("sequence") != proof["generation"]
                    or current.get("stage") != "prepared"
                    or current.get("status") != "active"
                ):
                    return [], tx_id
                current_proof = dict(proof)
                current_proof["generation"] = int(current_projection["sequence"])
                current_proof["sequence"] = int(current_projection["sequence"])
                current_receipt, current_event_id = _read_t12_approval_authority(
                    contract_path, current, current_binding, current_proof
                )
                if (
                    current_event_id != source_event_id
                    or current_receipt != receipt
                ):
                    return [], tx_id
                return [
                    {
                        "event": "advanced",
                        "transaction_id": tx_id,
                        "expected_stage": "prepared",
                        "stage": "approval_decided",
                        "details": details,
                    }
                ], tx_id

            advanced_projection, _selected = _mutate(contract_path, mutation)
            current = advanced_projection["transactions"][tx_id]
            after_proof = head_proof(contract_path)
            if current.get("stage") != "approval_decided":
                return _advancement_result(
                    transaction=current,
                    operation=operation,
                    prior_stage=prior_stage,
                    stage=str(current.get("stage") or ""),
                    status="pending",
                    reason="native source event, stage, or generation changed before CAS",
                    advanced=False,
                    external_authority_verified=False,
                    receipt=None,
                    proof=after_proof,
                )
            return _advancement_result(
                transaction=current,
                operation=operation,
                prior_stage=prior_stage,
                stage="approval_decided",
                status="advanced",
                reason="canonical T12 human allow row independently replayed",
                advanced=True,
                external_authority_verified=False,
                receipt=receipt,
                proof=after_proof,
            )

        next_stage = {
            "approval_decided": "effect_applied",
            "effect_applied": "contract_applied",
            "contract_applied": "committed",
        }.get(prior_stage)
        if next_stage is not None:
            try:
                receipt, source_event_id = _read_stage_receipt_against(
                    contract_path,
                    transaction,
                    binding,
                    proof,
                    stage=next_stage,
                )
            except NativeDecisionJournalError as error:
                reason = (
                    f"canonical {next_stage} receipt producer pending: {error}"
                )
                if prior_stage == "approval_decided" and effect_authority_store_path(
                    contract_path
                ).is_file():
                    try:
                        _read_t10_dispatch_boundary(
                            contract_path, transaction, binding
                        )
                    except NativeDecisionJournalError as dispatch_error:
                        reason = str(dispatch_error)
                return _advancement_result(
                    transaction=transaction,
                    operation=operation,
                    prior_stage=prior_stage,
                    stage=prior_stage,
                    status="pending",
                    reason=reason,
                    advanced=False,
                    external_authority_verified=False,
                    receipt=None,
                    proof=proof,
                )
            failpoint_for_stage = {
                "effect_applied": "after_effect",
                "contract_applied": "after_contract",
                "committed": "after_anchor",
            }[next_stage]
            if failpoint == failpoint_for_stage:
                raise NativeDecisionAdvancementInterrupted(failpoint_for_stage)
            details = {
                "authority_receipt": _plain_json_copy(receipt),
                "authority_receipt_sha256": receipt["receipt_sha256"],
                "authority_source": receipt["source_kind"],
                "source_event_id": source_event_id,
                "source_receipt_id": receipt["receipt_id"],
                "prior_source_event_id": receipt["prior_source_event_id"],
                "request_binding_sha256": binding["request_binding_sha256"],
                "binding_sha256": receipt["binding_sha256"],
                "operation": operation,
                "decision": binding["decision"],
                "expected_generation": proof["generation"],
                "journal_executed_adapter": False,
                "journal_executed_external_tool": False,
            }

            def mutation(
                current_projection: dict[str, Any],
            ) -> tuple[list[dict[str, Any]], str]:
                current = current_projection["transactions"].get(tx_id)
                if not isinstance(current, dict):
                    raise NativeDecisionJournalError(
                        "unknown native decision transaction"
                    )
                current_binding = _require_durable_seal_origin(
                    current_projection, current
                )
                if (
                    current_projection.get("sequence") != proof["generation"]
                    or current.get("stage") != prior_stage
                    or current.get("status") != "active"
                ):
                    return [], tx_id
                current_proof = dict(proof)
                current_proof["generation"] = int(current_projection["sequence"])
                current_proof["sequence"] = int(current_projection["sequence"])
                current_receipt, current_event_id = _read_stage_receipt_against(
                    contract_path,
                    current,
                    current_binding,
                    current_proof,  # type: ignore[arg-type]
                    stage=next_stage,
                )
                if current_receipt != receipt or current_event_id != source_event_id:
                    return [], tx_id
                return [{
                    "event": "advanced",
                    "transaction_id": tx_id,
                    "expected_stage": prior_stage,
                    "stage": next_stage,
                    "details": details,
                }], tx_id

            try:
                advanced_projection, _selected = _mutate(contract_path, mutation)
            except NativeDecisionJournalError as error:
                after_proof = head_proof(contract_path)
                return _advancement_result(
                    transaction=load_projection(contract_path)["transactions"][tx_id],
                    operation=operation,
                    prior_stage=prior_stage,
                    stage=prior_stage,
                    status="pending",
                    reason=f"native authority changed before CAS: {error}",
                    advanced=False,
                    external_authority_verified=False,
                    receipt=None,
                    proof=after_proof,
                )
            current = advanced_projection["transactions"][tx_id]
            after_proof = head_proof(contract_path)
            if current.get("stage") != next_stage:
                return _advancement_result(
                    transaction=current,
                    operation=operation,
                    prior_stage=prior_stage,
                    stage=str(current.get("stage") or ""),
                    status="pending",
                    reason="native source event, stage, or generation changed before CAS",
                    advanced=False,
                    external_authority_verified=False,
                    receipt=None,
                    proof=after_proof,
                )
            terminal = next_stage == "committed"
            return _advancement_result(
                transaction=current,
                operation=operation,
                prior_stage=prior_stage,
                stage=next_stage,
                status="advanced",
                reason=(
                    "independent external head receipt verified"
                    if terminal
                    else f"canonical {next_stage} postcondition receipt independently replayed"
                ),
                advanced=True,
                external_authority_verified=terminal,
                receipt=receipt,
                proof=after_proof,
            )

        if prior_stage == "committed":
            try:
                _reverify_recorded_receipt(
                    contract_path, transaction, binding, stage="committed"
                )
                recorded = transaction["stage_details"]["committed"][
                    "authority_receipt"
                ]
            except (KeyError, NativeDecisionJournalError) as error:
                return _advancement_result(
                    transaction=transaction,
                    operation=operation,
                    prior_stage=prior_stage,
                    stage=prior_stage,
                    status="pending",
                    reason=f"recorded external head authority is unavailable: {error}",
                    advanced=False,
                    external_authority_verified=False,
                    receipt=None,
                    proof=proof,
                )
            return _advancement_result(
                transaction=transaction,
                operation=operation,
                prior_stage=prior_stage,
                stage=prior_stage,
                status="already_advanced",
                reason="recorded external head receipt independently replayed",
                advanced=False,
                external_authority_verified=True,
                receipt=recorded,
                proof=proof,
            )

        obligation = {
            "superseded": "superseded transaction cannot advance",
        }.get(prior_stage, "native transaction stage is not advanceable")
        return _advancement_result(
            transaction=transaction,
            operation=operation,
            prior_stage=prior_stage,
            stage=prior_stage,
            status="pending",
            reason=obligation,
            advanced=False,
            external_authority_verified=False,
            receipt=None,
            proof=proof,
        )


def _terminal_replay_diagnostic(
    contract_path: Path,
    transaction: dict[str, Any],
    *,
    operation: str,
    sealed_approval_verified: bool,
) -> dict[str, Any]:
    """Expose historical terminal state without converting it to authority."""
    local_head = head_proof(contract_path)
    return {
        "schema": TERMINAL_REPLAY_SCHEMA,
        "contract_sha256": _contract_digest(contract_path),
        "transaction_id": transaction["transaction_id"],
        "operation": operation,
        "sealed": transaction.get("sealed") is True,
        "legacy_authority": (
            "not-legacy" if transaction.get("sealed") is True else "read-only"
        ),
        "historical_terminal_seen": True,
        "historical_stage": transaction["stage"],
        "historical_status": transaction.get("historical_status")
        or transaction["stage"],
        "terminal_receipt_digest_verified": sealed_approval_verified,
        "local_consistency_verified": local_head["local_consistency_verified"],
        "external_authority_verified": False,
        "external_authority_status": "external_authority_unverified",
        "journal_state": "pending",
        "recovery_status": "pending",
        "journal_head_proof": local_head,
        "journal_head_proof_sha256": local_head["proof_sha256"],
        "t06_seam": (
            "T06 must compare the complete head proof with an independent external "
            "anchor and establish new sealed authority before any execution"
        ),
    }


def recover_transaction(
    contract_path: Path,
    tx_id: str,
    *,
    operation: str,
    effect: Any = None,
    contract: Any = None,
    failpoint: Any = None,
) -> dict[str, Any]:
    """Return the T06 plan, or reject every caller-claimed advancement proof.

    The owned T03 surface has no operation-specific adapter or independent
    readers for authoritative effect/contract stores.  Consequently this seam
    never emits ``approval_decided``, ``effect_applied``, ``contract_applied``,
    or ``committed``.  A future T06 implementation must add typed receipt and
    postcondition verifiers before any such transition can be enabled.
    """
    if type(tx_id) is not str or not tx_id.startswith("ndt-"):
        raise NativeDecisionJournalError("native decision transaction id is invalid")
    selected_operation = _operation(operation)

    with _recovery_lock(contract_path, tx_id):
        projection = load_projection(contract_path)
        transaction = projection["transactions"].get(tx_id)
        if not isinstance(transaction, dict):
            raise NativeDecisionJournalError("unknown native decision transaction")
        binding = _validate_binding(transaction["binding"])
        actual_operation = _binding_operation(binding)
        if _historical_terminal(transaction):
            if actual_operation is None:
                if not _legacy_binding_matches_operation(binding, selected_operation):
                    raise NativeDecisionJournalError(
                        "legacy terminal operation does not match historical binding"
                    )
                return _terminal_replay_diagnostic(
                    contract_path,
                    transaction,
                    operation=selected_operation,
                    sealed_approval_verified=False,
                )
            if actual_operation != selected_operation:
                raise NativeDecisionJournalError(
                    "native recovery operation does not match sealed binding"
                )
            terminal = str(transaction["stage"])
            decision_digest, authority_digest = _recorded_authority(
                transaction,
                terminal_stage=("superseded" if terminal == "superseded" else None),
            )
            _verify_sealed_approval(
                contract_path,
                binding,
                decision_sha256=decision_digest,
                authority_sha256=authority_digest,
            )
            return _terminal_replay_diagnostic(
                contract_path,
                transaction,
                operation=selected_operation,
                sealed_approval_verified=True,
            )
        if actual_operation is None:
            raise NativeDecisionJournalError(
                "legacy native transaction is unsealed and requires explicit handling"
            )
        if actual_operation != selected_operation:
            raise NativeDecisionJournalError(
                "native recovery operation does not match sealed binding"
            )
        _verify_sealed_approval(contract_path, binding)
        if effect is not None or contract is not None or failpoint is not None:
            raise NativeDecisionJournalError(
                "authority_unverified: caller claims, adapter names, tokens, "
                "booleans, self-hashes, and unverified receipts cannot advance "
                "a native decision transaction"
            )
        return recovery_plan(
            contract_path,
            tx_id,
            operation=selected_operation,
        )


def _recover_operation(
    expected: str,
    contract_path: Path,
    tx_id: str,
    *,
    effect: Any = None,
    contract: Any = None,
    failpoint: Any = None,
) -> dict[str, Any]:
    return recover_transaction(
        contract_path,
        tx_id,
        operation=expected,
        effect=effect,
        contract=contract,
        failpoint=failpoint,
    )


def recover_proposal(contract_path: Path, tx_id: str, **kwargs: Any) -> dict[str, Any]:
    return _recover_operation("proposal", contract_path, tx_id, **kwargs)


def recover_resume(contract_path: Path, tx_id: str, **kwargs: Any) -> dict[str, Any]:
    return _recover_operation("resume", contract_path, tx_id, **kwargs)


def recover_effect(contract_path: Path, tx_id: str, **kwargs: Any) -> dict[str, Any]:
    return _recover_operation("effect", contract_path, tx_id, **kwargs)


def recover_intent(contract_path: Path, tx_id: str, **kwargs: Any) -> dict[str, Any]:
    return _recover_operation("intent", contract_path, tx_id, **kwargs)


def recover_observation_export(
    contract_path: Path, tx_id: str, **kwargs: Any
) -> dict[str, Any]:
    return _recover_operation("observation-export", contract_path, tx_id, **kwargs)


def grant_broker_projection(contract_path: Path) -> dict[str, Any]:
    """Read the versioned H02 ledger without touching legacy journal rows."""
    from grant_broker import load_projection_read_only

    return {
        "schema": GRANT_BROKER_ADAPTER_SCHEMA,
        "protocol": GRANT_BROKER_PROTOCOL_SCHEMA,
        "legacy_journal_reinterpreted": False,
        "projection": load_projection_read_only(contract_path),
    }


def pending_grant_broker_transactions(contract_path: Path) -> list[dict[str, Any]]:
    """Expose pending H02 transactions on an explicit, non-legacy API."""
    from grant_broker import pending as broker_pending

    return broker_pending(contract_path)
