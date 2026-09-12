#!/usr/bin/env python3
"""Typed durable GrantBroker transaction/outbox.

Only an exact versioned human callback can create decision authority. Display,
timeout, silence, chat and recovery remain observations. The append-only hash
chain records every mechanical boundary without inferring external truth.
"""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import fcntl
import json
import math
import os
from pathlib import Path
import re
import stat
from typing import Any, Iterator

from human_grant import (
    HumanGrantError,
    canonical_digest,
    consume_human_grant,
    consumption_identity,
    create_human_grant,
    grant_binding_identity,
)

PROTOCOL_SCHEMA = "sulde-grant-broker-v1"
EVENT_SCHEMA = "sulde-grant-broker-event-v1"
PROJECTION_SCHEMA = "sulde-grant-broker-projection-v1"
QUESTION_SCHEMA = "sulde-grant-broker-question-v1"
OBSERVATION_SCHEMA = "sulde-grant-broker-observation-v1"
DECISION_SCHEMA = "sulde-grant-broker-human-decision-v1"
EFFECT_RECEIPT_SCHEMA = "sulde-grant-broker-effect-receipt-v1"
VERIFIER_RECEIPT_SCHEMA = "sulde-grant-broker-verifier-receipt-v1"
SETTLEMENT_SCHEMA = "sulde-grant-broker-settlement-v1"
CONTROL_ROUTE_SCHEMA = "sulde-grant-broker-control-route-v1"
RESULT_SCHEMA = "sulde-grant-broker-result-v1"
DISPATCH_REPROBE_SCHEMA = "sulde-grant-broker-dispatch-reprobe-v1"

SPEC_FIELDS = frozenset({
    "schema", "provider", "session_id", "task_epoch", "lane", "subject",
    "capability", "effect", "constraints", "world_state", "verifier",
    "readable_card", "requested_at", "reassess_at", "expires_at",
})
OBSERVATION_FIELDS = frozenset({
    "schema", "transaction_id", "request_id", "provider", "session_id",
    "task_epoch", "kind", "observed_at", "detail",
})
DECISION_FIELDS = frozenset({
    "schema", "transaction_id", "request_id", "receipt_id", "provider",
    "session_id", "task_epoch", "outcome", "decided_at", "authority",
    "channel", "question_sha256",
})
EFFECT_FIELDS = frozenset({
    "schema", "transaction_id", "dispatch_id", "receipt_id", "provider",
    "session_id", "task_epoch", "authority_sha256", "status", "observed_at",
    "result",
})
VERIFIER_FIELDS = frozenset({
    "schema", "transaction_id", "effect_receipt_sha256", "receipt_id",
    "verifier", "status", "verified_at", "evidence",
})
ROUTE_FIELDS = frozenset({
    "schema", "protocol", "kind", "operation", "transaction_id", "request_id",
    "provider", "session_id", "task_epoch", "source_event_sha256",
    "control_only", "destructive", "route_sha256",
})
OBSERVATIONS = frozenset({
    "displayed", "timeout", "silence", "ordinary_chat", "fixed_phrase",
    "copied_digest", "retry", "reprobe", "inspect_diff", "later",
})
TERMINAL = frozenset({
    "succeeded", "denied", "expired", "replaced", "fresh_decision_required",
    "effect_failed", "effect_unknown", "verification_failed",
    "verification_inconclusive",
})
_SHA = re.compile(r"^sha256:[0-9a-f]{64}$")
_EPOCH = re.compile(r"^[0-9a-f]{24}$")


class GrantBrokerError(RuntimeError):
    """Broker input or durable state is not trustworthy."""


def _failpoint(boundary: str) -> None:
    """Deterministic test seam around each durable append."""
    del boundary


def _plain(value: Any, name: str) -> None:
    kind = type(value)
    if kind in {type(None), str, int, bool}:
        return
    if kind is float:
        if math.isfinite(value):
            return
        raise GrantBrokerError(f"{name} contains a non-finite number")
    if kind is list:
        for index, child in enumerate(value):
            _plain(child, f"{name}[{index}]")
        return
    if kind is dict:
        for key, child in value.items():
            if type(key) is not str:
                raise GrantBrokerError(f"{name} contains a non-string key")
            _plain(child, f"{name}.{key}")
        return
    raise GrantBrokerError(f"{name} must contain only exact plain JSON types")


def _object(value: Any, name: str, fields: frozenset[str] | None = None) -> dict:
    _plain(value, name)
    if type(value) is not dict:
        raise GrantBrokerError(f"{name} must be an exact object")
    if fields is not None and frozenset(value) != fields:
        missing = sorted(fields - frozenset(value))
        extra = sorted(frozenset(value) - fields)
        raise GrantBrokerError(f"{name} fields invalid: missing={missing}; extra={extra}")
    return value


def _text(value: Any, name: str) -> str:
    if type(value) is not str or not value.strip():
        raise GrantBrokerError(f"{name} must be an exact non-empty string")
    return value


def _time(value: Any, name: str) -> datetime:
    raw = _text(value, name)
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("missing timezone")
        return parsed.astimezone(timezone.utc)
    except (ValueError, OverflowError) as error:
        raise GrantBrokerError(f"{name} must be timezone-aware ISO-8601") from error


def _id(prefix: str, value: Any, domain: str) -> str:
    return prefix + canonical_digest(domain, value).split(":", 1)[1][:32]


def _binding(spec: dict) -> dict:
    return {
        "provider": spec["provider"], "session_id": spec["session_id"],
        "task_epoch": spec["task_epoch"], "subject": deepcopy(spec["subject"]),
        "capability": deepcopy(spec["capability"]), "effect": deepcopy(spec["effect"]),
        "constraints": deepcopy(spec["constraints"]),
        "world_state": deepcopy(spec["world_state"]),
        "expires_at": spec["expires_at"], "verifier": deepcopy(spec["verifier"]),
    }


def validate_spec(value: Any) -> dict:
    spec = _object(value, "transaction spec", SPEC_FIELDS)
    if spec["schema"] != PROTOCOL_SCHEMA:
        raise GrantBrokerError("transaction protocol schema is invalid")
    _text(spec["provider"], "provider")
    if len(_text(spec["session_id"], "session_id")) > 256:
        raise GrantBrokerError("session_id is too long")
    if type(spec["task_epoch"]) is not str or not _EPOCH.fullmatch(spec["task_epoch"]):
        raise GrantBrokerError("task_epoch must be 24 lowercase hex")
    _text(spec["lane"], "lane")
    for field in ("subject", "capability", "effect", "constraints",
                  "world_state", "verifier", "readable_card"):
        selected = _object(spec[field], field)
        if field not in {"constraints", "world_state"} and not selected:
            raise GrantBrokerError(f"{field} must not be empty")
    requested = _time(spec["requested_at"], "requested_at")
    reassess = _time(spec["reassess_at"], "reassess_at")
    expires = _time(spec["expires_at"], "expires_at")
    if not requested < reassess < expires:
        raise GrantBrokerError("requested_at < reassess_at < expires_at is required")
    try:
        grant_binding_identity(_binding(spec))
    except HumanGrantError as error:
        raise GrantBrokerError(f"H01 binding rejected: {error}") from error
    return deepcopy(spec)


def transaction_id(spec: Any) -> str:
    return _id("gbt-", validate_spec(spec), "grant-broker-transaction")


def _canonical_contract_path(contract_path: Path | str) -> Path:
    lexical = Path(os.path.abspath(os.path.expanduser(os.fspath(contract_path))))
    if not lexical.is_absolute():
        raise GrantBrokerError("broker contract identity is not absolute")
    try:
        canonical = lexical.resolve(strict=True)
        parent_status = os.stat(canonical.parent, follow_symlinks=False)
    except (OSError, RuntimeError) as error:
        raise GrantBrokerError(
            f"cannot resolve existing broker contract identity: {error}"
        ) from error
    if not canonical.is_absolute() or not stat.S_ISDIR(parent_status.st_mode):
        raise GrantBrokerError(
            "canonical broker contract parent must be an existing absolute directory"
        )
    return canonical


def journal_path(contract_path: Path | str) -> Path:
    contract = _canonical_contract_path(contract_path)
    stem = contract.name[:-5] if contract.name.endswith(".json") else contract.name
    return contract.with_name(f".{stem}.grant-broker.jsonl")


_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
_DIRECTORY = getattr(os, "O_DIRECTORY", 0)


class _LockedStore:
    def __init__(self, parent_fd: int, ledger_name: str, lock_name: str,
                 lock_fd: int) -> None:
        self.parent_fd = parent_fd
        self.ledger_name = ledger_name
        self.lock_name = lock_name
        self.lock_fd = lock_fd
        self.ledger_identity: tuple[int, int] | None = None
        self.ledger_observed = False


def _open_parent(contract_path: Path | str) -> tuple[int, str, str]:
    contract = _canonical_contract_path(contract_path)
    parent = contract.parent
    parts = parent.parts
    if not parent.is_absolute() or not parts or parts[0] != os.path.sep:
        raise GrantBrokerError("broker ledger parent identity is not absolute")
    flags = os.O_RDONLY | _DIRECTORY | _CLOEXEC | _NOFOLLOW
    descriptor = -1
    try:
        descriptor = os.open(os.path.sep, flags)
        for component in parts[1:]:
            child = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        opened_parent = os.fstat(descriptor)
        named_parent = os.stat(parent, follow_symlinks=False)
        opened_contract = os.stat(
            contract.name, dir_fd=descriptor, follow_symlinks=False
        )
        named_contract = os.stat(contract, follow_symlinks=False)
        if (
            not stat.S_ISDIR(opened_parent.st_mode)
            or not stat.S_ISDIR(named_parent.st_mode)
            or (opened_parent.st_dev, opened_parent.st_ino)
            != (named_parent.st_dev, named_parent.st_ino)
        ):
            raise GrantBrokerError(
                "canonical broker parent descriptor identity changed"
            )
        if (opened_contract.st_dev, opened_contract.st_ino) != (
            named_contract.st_dev, named_contract.st_ino
        ):
            raise GrantBrokerError("canonical broker contract identity changed")
    except (OSError, GrantBrokerError) as error:
        if descriptor >= 0:
            os.close(descriptor)
        if isinstance(error, GrantBrokerError):
            raise
        raise GrantBrokerError(
            f"cannot open canonical broker ledger parent without links: {error}"
        ) from error
    stem = contract.name[:-5] if contract.name.endswith(".json") else contract.name
    ledger_name = f".{stem}.grant-broker.jsonl"
    lock_name = f".{ledger_name}.lock"
    return descriptor, ledger_name, lock_name


def _leaf_identity(value: os.stat_result) -> tuple[int, int]:
    return value.st_dev, value.st_ino


def _validate_leaf(descriptor: int, parent_fd: int, name: str,
                   *, label: str) -> tuple[int, int]:
    try:
        opened = os.fstat(descriptor)
        named = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except OSError as error:
        raise GrantBrokerError(f"cannot verify broker {label} identity: {error}") from error
    trusted_uid = os.geteuid() if hasattr(os, "geteuid") else os.getuid()
    if not stat.S_ISREG(opened.st_mode) or not stat.S_ISREG(named.st_mode):
        raise GrantBrokerError(f"broker {label} must be a regular file")
    if opened.st_uid != trusted_uid or named.st_uid != trusted_uid:
        raise GrantBrokerError(f"broker {label} owner is not trusted")
    if (stat.S_IMODE(opened.st_mode) & ~0o600) or (
        stat.S_IMODE(named.st_mode) & ~0o600
    ):
        raise GrantBrokerError(f"broker {label} mode is broader than 0600")
    if opened.st_nlink != 1 or named.st_nlink != 1:
        raise GrantBrokerError(f"broker {label} must have exactly one hard link")
    if _leaf_identity(opened) != _leaf_identity(named):
        raise GrantBrokerError(f"broker {label} pathname identity changed")
    return _leaf_identity(opened)


def _open_leaf(parent_fd: int, name: str, flags: int, *, label: str,
               create: bool = False) -> tuple[int, tuple[int, int]]:
    selected = flags | _NOFOLLOW | _CLOEXEC
    if create:
        selected |= os.O_CREAT | os.O_EXCL
    try:
        descriptor = os.open(name, selected, 0o600, dir_fd=parent_fd)
    except OSError as error:
        raise GrantBrokerError(
            f"cannot open broker {label} without links: {error}"
        ) from error
    try:
        identity = _validate_leaf(descriptor, parent_fd, name, label=label)
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor, identity


def _open_existing_or_create(parent_fd: int, name: str, flags: int,
                             *, label: str) -> tuple[int, tuple[int, int], bool]:
    try:
        descriptor, identity = _open_leaf(
            parent_fd, name, flags, label=label, create=False
        )
        return descriptor, identity, False
    except GrantBrokerError as existing_error:
        try:
            os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            descriptor, identity = _open_leaf(
                parent_fd, name, flags, label=label, create=True
            )
            return descriptor, identity, True
        except OSError as error:
            raise GrantBrokerError(
                f"cannot inspect broker {label} pathname: {error}"
            ) from error
        raise existing_error


@contextmanager
def _locked(contract_path: Path | str) -> Iterator[_LockedStore]:
    parent_fd, ledger_name, lock_name = _open_parent(contract_path)
    descriptor = -1
    try:
        descriptor, _identity, _created = _open_existing_or_create(
            parent_fd, lock_name, os.O_RDWR, label="lock"
        )
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        _validate_leaf(descriptor, parent_fd, lock_name, label="lock")
        selected = _LockedStore(parent_fd, ledger_name, lock_name, descriptor)
        yield selected
        _validate_leaf(descriptor, parent_fd, lock_name, label="lock")
    finally:
        if descriptor >= 0:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)
        os.close(parent_fd)


def _empty() -> dict:
    return {"schema": PROJECTION_SCHEMA, "sequence": 0, "head_sha256": None,
            "transactions": {}}


def _event_sha(sequence: int, previous: str | None, event: str, payload: dict) -> str:
    return canonical_digest("grant-broker-event", {
        "sequence": sequence, "previous_sha256": previous,
        "event": event, "payload": payload,
    })


def _public(value: dict | None) -> dict | None:
    if value is None:
        return None
    selected = deepcopy(value)
    selected.pop("source_event_sha256", None)
    return selected


def _apply(projection: dict, row: Any) -> None:
    row = _object(row, "journal row", frozenset({
        "schema", "sequence", "previous_sha256", "event", "payload", "event_sha256",
    }))
    if row["schema"] != EVENT_SCHEMA or type(row["sequence"]) is not int:
        raise GrantBrokerError("journal row schema/types are invalid")
    if row["sequence"] != projection["sequence"] + 1:
        raise GrantBrokerError("journal sequence is ambiguous")
    if row["previous_sha256"] != projection["head_sha256"]:
        raise GrantBrokerError("journal predecessor is invalid")
    event = _text(row["event"], "event")
    payload = _object(row["payload"], "payload")
    expected = _event_sha(row["sequence"], row["previous_sha256"], event, payload)
    if row["event_sha256"] != expected:
        raise GrantBrokerError("journal event digest was tampered")
    tx_id = _text(payload.get("transaction_id"), "transaction_id")
    tx = projection["transactions"].get(tx_id)
    if event == "transaction_created":
        _object(payload, "transaction payload",
                frozenset({"transaction_id", "spec"}))
        if tx is not None:
            raise GrantBrokerError("duplicate transaction source event")
        spec = validate_spec(payload.get("spec"))
        if transaction_id(spec) != tx_id:
            raise GrantBrokerError("transaction identity is not canonical")
        tx = {
            "transaction_id": tx_id, "spec": spec, "question": None,
            "observations": [], "display_event_sha256": None, "decision": None,
            "grant": None, "grant_consumption": None, "dispatch": None,
            "effect_receipt": None, "verifier_receipt": None, "settlement": None,
            "event_sha256s": [expected],
        }
        projection["transactions"][tx_id] = tx
    else:
        if type(tx) is not dict:
            raise GrantBrokerError("event has no unique transaction source event")
        _apply_tx(tx, event, payload, expected)
    projection["sequence"] = row["sequence"]
    projection["head_sha256"] = expected


def _apply_tx(tx: dict, event: str, payload: dict, event_sha: str) -> None:
    if payload.get("transaction_id") != tx["transaction_id"]:
        raise GrantBrokerError("foreign transaction identity")
    if event == "observation_recorded":
        _object(payload, "observation payload",
                frozenset({"transaction_id", "observation"}))
        value = _validate_observation(payload.get("observation"), tx)
        if any(row["observation"] == value for row in tx["observations"]):
            raise GrantBrokerError("duplicate observation event is ambiguous")
        if value["kind"] == "displayed" and tx["display_event_sha256"]:
            raise GrantBrokerError("multiple visible question events")
        tx["observations"].append({"observation": value, "source_event_sha256": event_sha})
        if value["kind"] == "displayed":
            tx["display_event_sha256"] = event_sha
    else:
        slots = {
            "question_published": "question", "human_decided": "decision",
            "grant_consumed": "grant_consumption", "dispatch_claimed": "dispatch",
            "effect_receipt_recorded": "effect_receipt",
            "verifier_receipt_recorded": "verifier_receipt", "settled": "settlement",
        }
        slot = slots.get(event)
        if slot is None:
            raise GrantBrokerError("unsupported broker event")
        expected_fields = {"transaction_id", slot}
        if event == "human_decided":
            expected_fields.add("grant")
        _object(payload, f"{event} payload", frozenset(expected_fields))
        if tx[slot] is not None:
            raise GrantBrokerError(f"duplicate authoritative {slot} event")
        value = _object(payload.get(slot), slot)
        if event == "question_published":
            _validate_question(value, tx)
        elif event == "human_decided":
            _validate_decision(value, tx)
            grant = payload.get("grant")
            if (value["outcome"] == "allow") != (type(grant) is dict):
                raise GrantBrokerError("decision/grant composition is invalid")
            if value["outcome"] == "allow":
                try:
                    expected_grant = _human_grant(tx, value)
                except HumanGrantError as error:
                    raise GrantBrokerError(
                        f"recorded H01 grant is invalid: {error}"
                    ) from error
                if grant != expected_grant:
                    raise GrantBrokerError("recorded H01 grant was tampered")
            tx["grant"] = deepcopy(grant)
        elif event == "grant_consumed":
            if tx["decision"] is None or tx["decision"]["outcome"] != "allow":
                raise GrantBrokerError("consumption has no allow source")
            if type(value.get("grant")) is not dict or type(value.get("authority")) is not dict:
                raise GrantBrokerError("consumption payload is malformed")
            try:
                prior = tx["grant"]
                spec = tx["spec"]
                current = {
                    field: deepcopy(spec[field])
                    for field in (
                        "provider", "session_id", "task_epoch", "subject",
                        "capability", "effect", "constraints", "world_state",
                        "verifier",
                    )
                }
                projected = consume_human_grant(
                    prior,
                    current=current,
                    expected_consumption_sha256=consumption_identity(
                        prior["consumption"]
                    ),
                    now=tx["decision"]["decided_at"],
                )
                expected_consumption = {
                    "grant": projected["grant"], "cas": projected["cas"],
                    "authority": projected["authority"],
                }
            except (HumanGrantError, KeyError, TypeError) as error:
                raise GrantBrokerError(
                    f"recorded H01 consumption is invalid: {error}"
                ) from error
            if value != expected_consumption:
                raise GrantBrokerError("recorded H01 consumption was tampered")
            tx["grant"] = deepcopy(value["grant"])
        elif event == "dispatch_claimed":
            if tx["grant_consumption"] is None:
                raise GrantBrokerError("dispatch has no consumption source")
            _validate_dispatch(value, tx)
        elif event == "effect_receipt_recorded":
            _validate_effect(value, tx)
        elif event == "verifier_receipt_recorded":
            _validate_verifier(value, tx)
        elif event == "settled":
            _validate_settlement(value, tx)
        selected = deepcopy(value)
        selected["source_event_sha256"] = event_sha
        tx[slot] = selected
    tx["event_sha256s"].append(event_sha)


def _validate_dispatch(value: Any, tx: dict) -> dict:
    dispatch = _object(value, "dispatch", frozenset({
        "schema", "transaction_id", "dispatch_id", "consumer_id", "provider",
        "session_id", "task_epoch", "authority_sha256", "effect",
        "execution_authorized", "default_policy_recheck_required",
    }))
    authority = tx["grant_consumption"]["authority"]
    expected_id = _id("gbd-", {
        "transaction_id": tx["transaction_id"],
        "authority_sha256": authority["authority_sha256"],
    }, "grant-broker-dispatch")
    expected = {
        "schema": "sulde-grant-broker-dispatch-intent-v1",
        "transaction_id": tx["transaction_id"], "dispatch_id": expected_id,
        "consumer_id": _text(dispatch["consumer_id"], "consumer_id"),
        "provider": tx["spec"]["provider"],
        "session_id": tx["spec"]["session_id"],
        "task_epoch": tx["spec"]["task_epoch"],
        "authority_sha256": authority["authority_sha256"],
        "effect": deepcopy(tx["spec"]["effect"]),
        "execution_authorized": True,
        "default_policy_recheck_required": False,
    }
    if dispatch != expected:
        raise GrantBrokerError("dispatch intent was tampered or rebound")
    return deepcopy(dispatch)


def _dispatch_reprobe(tx: dict) -> dict:
    dispatch = tx["dispatch"]
    if type(dispatch) is not dict:
        raise GrantBrokerError("dispatch reprobe has no durable claim")
    return {
        "schema": DISPATCH_REPROBE_SCHEMA,
        "transaction_id": tx["transaction_id"],
        "dispatch_id": dispatch["dispatch_id"],
        "execution_authorized": False,
        "next_action": "reprobe_effect_receipt",
        "receipt_schema": EFFECT_RECEIPT_SCHEMA,
        "downstream_idempotency_key": dispatch["dispatch_id"],
    }


def _public_transaction(tx: dict) -> dict:
    selected = deepcopy(tx)
    selected.pop("grant", None)
    selected.pop("grant_consumption", None)
    if tx["dispatch"] is not None:
        selected.pop("dispatch", None)
        selected["dispatch_reprobe"] = _dispatch_reprobe(tx)
        selected["spec"] = {
            field: selected["spec"][field]
            for field in (
                "schema", "provider", "session_id", "task_epoch", "lane",
                "requested_at", "reassess_at", "expires_at",
            )
        }
        if selected.get("question") is not None:
            selected["question"].pop("readable_card", None)
        if selected.get("effect_receipt") is not None:
            selected["effect_receipt"].pop("authority_sha256", None)
    return selected


def _public_projection(projection: dict) -> dict:
    selected = deepcopy(projection)
    selected["transactions"] = {
        tx_id: _public_transaction(tx)
        for tx_id, tx in projection["transactions"].items()
    }
    return selected


def _read_all(descriptor: int) -> bytes:
    os.lseek(descriptor, 0, os.SEEK_SET)
    chunks: list[bytes] = []
    while True:
        chunk = os.read(descriptor, 1024 * 1024)
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)


def _read(contract_path: Path | str, locked: _LockedStore | None = None) -> dict:
    own_parent = locked is None
    if locked is None:
        parent_fd, ledger_name, _lock_name = _open_parent(contract_path)
    else:
        parent_fd, ledger_name = locked.parent_fd, locked.ledger_name
    descriptor = -1
    try:
        try:
            descriptor, identity = _open_leaf(
                parent_fd, ledger_name, os.O_RDONLY, label="ledger"
            )
        except GrantBrokerError as open_error:
            try:
                os.stat(ledger_name, dir_fd=parent_fd, follow_symlinks=False)
            except FileNotFoundError:
                if locked is not None:
                    if locked.ledger_observed and locked.ledger_identity is not None:
                        raise GrantBrokerError(
                            "broker ledger pathname identity changed"
                        ) from open_error
                    locked.ledger_observed = True
                    locked.ledger_identity = None
                return _empty()
            except OSError as error:
                raise GrantBrokerError(
                    f"cannot inspect broker ledger pathname: {error}"
                ) from error
            raise open_error
        if locked is not None:
            if locked.ledger_observed and locked.ledger_identity != identity:
                raise GrantBrokerError("broker ledger pathname identity changed")
            locked.ledger_observed = True
            locked.ledger_identity = identity
        data = _read_all(descriptor)
        current = _validate_leaf(
            descriptor, parent_fd, ledger_name, label="ledger"
        )
        if current != identity or (
            locked is not None and locked.ledger_identity != current
        ):
            raise GrantBrokerError("broker ledger pathname identity changed")
    except OSError as error:
        raise GrantBrokerError(f"cannot read broker ledger: {error}") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if own_parent:
            os.close(parent_fd)
    if data and not data.endswith(b"\n"):
        raise GrantBrokerError("broker ledger has a torn trailing record")
    projection = _empty()
    for number, line in enumerate(data.splitlines(), 1):
        if not line:
            raise GrantBrokerError(f"broker ledger line {number} is empty")
        try:
            _apply(projection, json.loads(line))
        except (UnicodeError, json.JSONDecodeError) as error:
            raise GrantBrokerError(f"broker ledger line {number} is malformed") from error
    return projection


def load_projection_read_only(contract_path: Path | str) -> dict:
    """Replay without creating or repairing any file."""
    return _public_projection(_read(contract_path))


def _write_all(descriptor: int, data: bytes) -> None:
    offset = 0
    while offset < len(data):
        written = os.write(descriptor, data[offset:])
        if written <= 0:
            raise OSError("short broker append")
        offset += written


def _append(
    contract_path: Path | str, projection: dict, event: str, payload: dict,
    *, locked: _LockedStore,
) -> None:
    sequence = projection["sequence"] + 1
    previous = projection["head_sha256"]
    row = {
        "schema": EVENT_SCHEMA, "sequence": sequence, "previous_sha256": previous,
        "event": event, "payload": deepcopy(payload),
        "event_sha256": _event_sha(sequence, previous, event, payload),
    }
    _failpoint(f"before:{event}")
    if not locked.ledger_observed:
        raise GrantBrokerError("broker append requires a stable ledger read")
    _validate_leaf(
        locked.lock_fd, locked.parent_fd, locked.lock_name, label="lock"
    )
    if locked.ledger_identity is None:
        descriptor, identity = _open_leaf(
            locked.parent_fd, locked.ledger_name,
            os.O_WRONLY | os.O_APPEND, label="ledger", create=True,
        )
        locked.ledger_identity = identity
    else:
        descriptor, identity = _open_leaf(
            locked.parent_fd, locked.ledger_name,
            os.O_WRONLY | os.O_APPEND, label="ledger",
        )
        if identity != locked.ledger_identity:
            os.close(descriptor)
            raise GrantBrokerError("broker ledger pathname identity changed")
    try:
        encoded = json.dumps(row, ensure_ascii=False, allow_nan=False,
                             sort_keys=True, separators=(",", ":")).encode() + b"\n"
        _validate_leaf(
            descriptor, locked.parent_fd, locked.ledger_name, label="ledger"
        )
        _validate_leaf(
            locked.lock_fd, locked.parent_fd, locked.lock_name, label="lock"
        )
        _write_all(descriptor, encoded)
        os.fsync(descriptor)
        current = _validate_leaf(
            descriptor, locked.parent_fd, locked.ledger_name, label="ledger"
        )
        if current != locked.ledger_identity:
            raise GrantBrokerError("broker ledger pathname identity changed")
        _validate_leaf(
            locked.lock_fd, locked.parent_fd, locked.lock_name, label="lock"
        )
    except OSError as error:
        raise GrantBrokerError(f"cannot append durable {event}: {error}") from error
    finally:
        os.close(descriptor)
    try:
        os.fsync(locked.parent_fd)
    except OSError as error:
        raise GrantBrokerError(
            f"cannot fsync durable {event} directory: {error}"
        ) from error
    _apply(projection, row)
    _failpoint(f"after:{event}")


def _tx(projection: dict, tx_id: Any) -> dict:
    selected = _text(tx_id, "transaction_id")
    value = projection["transactions"].get(selected)
    if type(value) is not dict:
        raise GrantBrokerError("transaction source event is missing")
    return value


def _result(tx_id: str, status: str, reason: str, **extra: Any) -> dict:
    return {"schema": RESULT_SCHEMA, "transaction_id": tx_id, "status": status,
            "reason": reason, **deepcopy(extra)}


def _request_id(tx_id: str) -> str:
    return _id("gbr-", {"transaction_id": tx_id}, "grant-broker-request")


def _question(tx: dict) -> dict:
    spec, tx_id = tx["spec"], tx["transaction_id"]
    question = {
        "schema": QUESTION_SCHEMA,
        "protocol": PROTOCOL_SCHEMA,
        "transaction_id": tx_id,
        "request_id": _request_id(tx_id),
        "provider": spec["provider"],
        "session_id": spec["session_id"],
        "task_epoch": spec["task_epoch"],
        "lane": spec["lane"],
        "binding_sha256": grant_binding_identity(_binding(spec)),
        "readable_card": deepcopy(spec["readable_card"]),
        "requested_at": spec["requested_at"],
        "reassess_at": spec["reassess_at"],
        "expires_at": spec["expires_at"],
        "decision_authority": "human_typed_callback_only",
        "adapter": {
            "surface": "host_permission_request_or_structured_ui",
            "choices": ["allow", "deny", "inspect_diff", "later"],
            "text_response_authoritative": False,
        },
    }
    question["question_sha256"] = canonical_digest("grant-broker-question", question)
    return question


def _validate_question(value: Any, tx: dict) -> dict:
    question = _object(value, "question", frozenset({
        "schema", "protocol", "transaction_id", "request_id", "provider",
        "session_id", "task_epoch", "lane", "binding_sha256", "readable_card",
        "requested_at", "reassess_at", "expires_at", "decision_authority",
        "adapter", "question_sha256",
    }))
    if question != _question(tx):
        raise GrantBrokerError("question does not match its canonical transaction")
    return deepcopy(question)


def _match(value: dict, tx: dict, request: bool = False) -> None:
    spec = tx["spec"]
    expected = {
        "transaction_id": tx["transaction_id"], "provider": spec["provider"],
        "session_id": spec["session_id"], "task_epoch": spec["task_epoch"],
    }
    if request:
        expected["request_id"] = _request_id(tx["transaction_id"])
    for field, wanted in expected.items():
        if type(value.get(field)) is not type(wanted) or value.get(field) != wanted:
            raise GrantBrokerError(f"{field} is foreign to the canonical transaction")


def create_transaction(contract_path: Path | str, spec: Any) -> dict:
    selected = validate_spec(spec)
    tx_id = transaction_id(selected)
    with _locked(contract_path) as locked:
        projection = _read(contract_path, locked)
        existing = projection["transactions"].get(tx_id)
        if existing is not None:
            return _result(tx_id, "already_created", "canonical transaction already exists")
        _append(contract_path, projection, "transaction_created",
                {"transaction_id": tx_id, "spec": selected}, locked=locked)
    return _result(tx_id, "created", "canonical transaction is durable")


def publish_question(contract_path: Path | str, tx_id: str) -> dict:
    with _locked(contract_path) as locked:
        projection = _read(contract_path, locked)
        tx = _tx(projection, tx_id)
        if tx["question"] is not None:
            return _result(tx_id, "already_published", "one question is already durable",
                           question=_public(tx["question"]))
        if tx["settlement"] is not None:
            return _result(tx_id, "terminal", "terminal transaction cannot ask")
        question = _question(tx)
        _append(contract_path, projection, "question_published",
                {"transaction_id": tx_id, "question": question}, locked=locked)
    return _result(tx_id, "published", "one structured question is durable",
                   question=question)


def _validate_observation(value: Any, tx: dict) -> dict:
    observation = _object(value, "observation", OBSERVATION_FIELDS)
    if observation["schema"] != OBSERVATION_SCHEMA:
        raise GrantBrokerError("observation schema is invalid")
    _match(observation, tx, True)
    if type(observation["kind"]) is not str or observation["kind"] not in OBSERVATIONS:
        raise GrantBrokerError("observation kind is outside the closed taxonomy")
    _time(observation["observed_at"], "observed_at")
    _object(observation["detail"], "observation detail")
    return deepcopy(observation)


def record_observation(contract_path: Path | str, observation: Any) -> dict:
    raw = _object(observation, "observation", OBSERVATION_FIELDS)
    with _locked(contract_path) as locked:
        projection = _read(contract_path, locked)
        tx = _tx(projection, raw.get("transaction_id"))
        selected = _validate_observation(raw, tx)
        if tx["question"] is None:
            return _result(tx["transaction_id"], "rejected",
                           "observation has no durable question source")
        if any(row["observation"] == selected for row in tx["observations"]):
            return _result(tx["transaction_id"], "duplicate",
                           "identical observation is already durable")
        if selected["kind"] == "displayed" and tx["display_event_sha256"]:
            return _result(tx["transaction_id"], "already_displayed",
                           "one visible question is already recorded")
        _append(contract_path, projection, "observation_recorded",
                {"transaction_id": tx["transaction_id"], "observation": selected},
                locked=locked)
    return _result(tx["transaction_id"], "recorded",
                   "observation recorded without decision authority")


def _validate_decision(value: Any, tx: dict) -> dict:
    decision = _object(value, "human decision", DECISION_FIELDS)
    if decision["schema"] != DECISION_SCHEMA:
        raise GrantBrokerError("human decision schema is invalid")
    _match(decision, tx, True)
    if type(decision["outcome"]) is not str or decision["outcome"] not in {"allow", "deny"}:
        raise GrantBrokerError("human decision must be exact allow or deny")
    if decision["authority"] != "human" or decision["channel"] != "native_typed_receipt":
        raise GrantBrokerError("human decision authority/channel is invalid")
    _text(decision["receipt_id"], "receipt_id")
    decided = _time(decision["decided_at"], "decided_at")
    if decided < _time(tx["spec"]["requested_at"], "requested_at"):
        raise GrantBrokerError("human decision predates its request")
    if tx["question"] is None or (
        decision["question_sha256"] != tx["question"]["question_sha256"]
    ):
        raise GrantBrokerError("human decision has no exact question source")
    return deepcopy(decision)


def _human_grant(tx: dict, decision: dict) -> dict:
    spec, question = tx["spec"], tx["question"]
    display_sha = canonical_digest("human-grant-readable-card", spec["readable_card"])
    card_id = _id("gbc-", spec["readable_card"], "human-grant-readable-card")
    return create_human_grant({
        **_binding(spec),
        "card": {
            "schema": "sulde-human-grant-card-v2", "card_id": card_id,
            "binding_sha256": question["binding_sha256"],
            "display_sha256": display_sha,
        },
        "request": {
            "schema": "sulde-human-grant-request-v2",
            "request_id": question["request_id"], "card_id": card_id,
            "binding_sha256": question["binding_sha256"],
            "requested_at": spec["requested_at"],
        },
        "receipt": {
            "schema": "sulde-human-grant-receipt-v2",
            "receipt_id": decision["receipt_id"],
            "request_id": question["request_id"],
            "binding_sha256": question["binding_sha256"], "outcome": "allow",
            "provider": spec["provider"], "session_id": spec["session_id"],
            "task_epoch": spec["task_epoch"], "verifier": deepcopy(spec["verifier"]),
            "decided_at": decision["decided_at"], "authority": "human",
            "channel": "native_typed_receipt",
        },
    })


def record_human_decision(contract_path: Path | str, decision: Any) -> dict:
    raw = _object(decision, "human decision", DECISION_FIELDS)
    with _locked(contract_path) as locked:
        projection = _read(contract_path, locked)
        tx = _tx(projection, raw.get("transaction_id"))
        selected = _validate_decision(raw, tx)
        if tx["display_event_sha256"] is None:
            return _result(tx["transaction_id"], "rejected",
                           "decision has no durable display source event")
        if tx["decision"] is not None:
            status = "duplicate" if _public(tx["decision"]) == selected else "conflict"
            return _result(tx["transaction_id"], status,
                           "one authoritative human receipt already exists")
        if tx["settlement"] is not None:
            return _result(tx["transaction_id"], "terminal",
                           "terminal transaction rejects late callbacks")
        grant = None
        if selected["outcome"] == "allow":
            if _time(selected["decided_at"], "decided_at") >= _time(
                tx["spec"]["expires_at"], "expires_at"
            ):
                return _result(tx["transaction_id"], "expired",
                               "allow arrived at or after expiry")
            try:
                grant = _human_grant(tx, selected)
            except HumanGrantError as error:
                raise GrantBrokerError(f"H01 rejected typed allow: {error}") from error
        _append(contract_path, projection, "human_decided", {
            "transaction_id": tx["transaction_id"], "decision": selected,
            "grant": grant,
        }, locked=locked)
    return _result(tx["transaction_id"], "decided",
                   f"typed human {selected['outcome']} is durable")


def consume_allow(
    contract_path: Path | str, tx_id: str, *, current: Any, now: Any
) -> dict:
    with _locked(contract_path) as locked:
        projection = _read(contract_path, locked)
        tx = _tx(projection, tx_id)
        if tx["settlement"] is not None:
            return _result(tx_id, "terminal", tx["settlement"]["reason"])
        if tx["decision"] is None or tx["decision"]["outcome"] != "allow":
            return _result(tx_id, "rejected", "no typed allow authority")
        if tx["grant_consumption"] is not None:
            return _result(tx_id, "already_consumed",
                           "H01 CAS already has one winner")
        try:
            grant = tx["grant"]
            consumed = consume_human_grant(
                grant, current=current,
                expected_consumption_sha256=consumption_identity(grant["consumption"]),
                now=now,
            )
        except (HumanGrantError, KeyError, TypeError) as error:
            return _result(tx_id, "rejected", f"H01 consumption failed closed: {error}")
        if consumed["status"] == "fresh_decision_required":
            value = _make_settlement(
                tx, "fresh_decision_required",
                "world state changed after the human decision", now,
                {"world_diff": consumed["world_diff"]},
            )
            _append(contract_path, projection, "settled",
                    {"transaction_id": tx_id, "settlement": value},
                    locked=locked)
            return _result(tx_id, "fresh_decision_required", value["reason"],
                           world_diff=consumed["world_diff"])
        value = {"grant": consumed["grant"], "cas": consumed["cas"],
                 "authority": consumed["authority"]}
        _append(contract_path, projection, "grant_consumed",
                {"transaction_id": tx_id, "grant_consumption": value},
                locked=locked)
    return _result(tx_id, "consumed", "H01 CAS committed exactly once")


def claim_dispatch(contract_path: Path | str, tx_id: str, *, consumer_id: Any) -> dict:
    consumer = _text(consumer_id, "consumer_id")
    with _locked(contract_path) as locked:
        projection = _read(contract_path, locked)
        tx = _tx(projection, tx_id)
        if tx["settlement"] is not None:
            return _result(tx_id, "terminal", tx["settlement"]["reason"])
        if tx["grant_consumption"] is None:
            return _result(tx_id, "rejected", "dispatch requires committed H01 CAS")
        if tx["dispatch"] is not None:
            status = ("already_claimed" if tx["dispatch"]["consumer_id"] == consumer
                      else "lost_race")
            return _result(tx_id, status,
                           "dispatch authority already has one claimant",
                           dispatch_reprobe=_dispatch_reprobe(tx))
        authority = tx["grant_consumption"]["authority"]
        dispatch = {
            "schema": "sulde-grant-broker-dispatch-intent-v1",
            "transaction_id": tx_id,
            "dispatch_id": _id("gbd-", {
                "transaction_id": tx_id,
                "authority_sha256": authority["authority_sha256"],
            }, "grant-broker-dispatch"),
            "consumer_id": consumer,
            "provider": tx["spec"]["provider"],
            "session_id": tx["spec"]["session_id"],
            "task_epoch": tx["spec"]["task_epoch"],
            "authority_sha256": authority["authority_sha256"],
            "effect": deepcopy(tx["spec"]["effect"]),
            "execution_authorized": True,
            "default_policy_recheck_required": False,
        }
        _append(contract_path, projection, "dispatch_claimed",
                {"transaction_id": tx_id, "dispatch": dispatch}, locked=locked)
    return _result(tx_id, "claimed",
                   "dispatch claimed without a second default-policy decision",
                   dispatch=dispatch)


def _validate_effect(value: Any, tx: dict) -> dict:
    receipt = _object(value, "effect receipt", EFFECT_FIELDS)
    if receipt["schema"] != EFFECT_RECEIPT_SCHEMA:
        raise GrantBrokerError("effect receipt schema is invalid")
    _match(receipt, tx)
    dispatch = tx["dispatch"]
    if dispatch is None or receipt["dispatch_id"] != dispatch["dispatch_id"]:
        raise GrantBrokerError("effect receipt has no exact dispatch source")
    if receipt["authority_sha256"] != dispatch["authority_sha256"]:
        raise GrantBrokerError("effect receipt authority is foreign")
    if type(receipt["status"]) is not str or receipt["status"] not in {
        "succeeded", "failed", "unknown"
    }:
        raise GrantBrokerError("effect status is invalid")
    _text(receipt["receipt_id"], "effect receipt_id")
    _time(receipt["observed_at"], "effect observed_at")
    _object(receipt["result"], "effect result")
    return deepcopy(receipt)


def record_effect_receipt(contract_path: Path | str, receipt: Any) -> dict:
    raw = _object(receipt, "effect receipt", EFFECT_FIELDS)
    with _locked(contract_path) as locked:
        projection = _read(contract_path, locked)
        tx = _tx(projection, raw.get("transaction_id"))
        selected = _validate_effect(raw, tx)
        if tx["effect_receipt"] is not None:
            status = "duplicate" if _public(tx["effect_receipt"]) == selected else "conflict"
            return _result(tx["transaction_id"], status,
                           "effect boundary already has one source")
        if tx["settlement"] is not None:
            return _result(tx["transaction_id"], "terminal",
                           "terminal transaction rejects effect callbacks")
        _append(contract_path, projection, "effect_receipt_recorded", {
            "transaction_id": tx["transaction_id"], "effect_receipt": selected,
        }, locked=locked)
    return _result(tx["transaction_id"], "recorded",
                   "externally supplied effect receipt is durable")


def effect_receipt_identity(receipt: dict) -> str:
    return canonical_digest("grant-broker-effect-receipt", _public(receipt))


def _validate_verifier(value: Any, tx: dict) -> dict:
    receipt = _object(value, "verifier receipt", VERIFIER_FIELDS)
    if receipt["schema"] != VERIFIER_RECEIPT_SCHEMA:
        raise GrantBrokerError("verifier receipt schema is invalid")
    if receipt["transaction_id"] != tx["transaction_id"]:
        raise GrantBrokerError("verifier transaction is foreign")
    if tx["effect_receipt"] is None or (
        receipt["effect_receipt_sha256"] != effect_receipt_identity(tx["effect_receipt"])
    ):
        raise GrantBrokerError("verifier has no exact effect receipt source")
    if type(receipt["verifier"]) is not dict or receipt["verifier"] != tx["spec"]["verifier"]:
        raise GrantBrokerError("verifier is foreign to the sealed transaction")
    if type(receipt["status"]) is not str or receipt["status"] not in {
        "passed", "failed", "inconclusive"
    }:
        raise GrantBrokerError("verifier status is invalid")
    _text(receipt["receipt_id"], "verifier receipt_id")
    _time(receipt["verified_at"], "verified_at")
    _object(receipt["evidence"], "verifier evidence")
    return deepcopy(receipt)


def record_verifier_receipt(contract_path: Path | str, receipt: Any) -> dict:
    raw = _object(receipt, "verifier receipt", VERIFIER_FIELDS)
    with _locked(contract_path) as locked:
        projection = _read(contract_path, locked)
        tx = _tx(projection, raw.get("transaction_id"))
        selected = _validate_verifier(raw, tx)
        if tx["verifier_receipt"] is not None:
            status = ("duplicate" if _public(tx["verifier_receipt"]) == selected
                      else "conflict")
            return _result(tx["transaction_id"], status,
                           "verifier boundary already has one source")
        if tx["settlement"] is not None:
            return _result(tx["transaction_id"], "terminal",
                           "terminal transaction rejects verifier callbacks")
        _append(contract_path, projection, "verifier_receipt_recorded", {
            "transaction_id": tx["transaction_id"], "verifier_receipt": selected,
        }, locked=locked)
    return _result(tx["transaction_id"], "recorded", "verifier result is durable")


def _make_settlement(
    tx: dict, status: str, reason: Any, at: Any, evidence: Any
) -> dict:
    if status not in TERMINAL:
        raise GrantBrokerError("settlement status is invalid")
    value = {
        "schema": SETTLEMENT_SCHEMA, "transaction_id": tx["transaction_id"],
        "status": status, "reason": _text(reason, "settlement reason"),
        "settled_at": _text(at, "settled_at"),
        "evidence": deepcopy(_object(evidence, "settlement evidence")),
    }
    _time(value["settled_at"], "settled_at")
    value["settlement_sha256"] = canonical_digest("grant-broker-settlement", value)
    return value


def _validate_settlement(value: Any, tx: dict) -> dict:
    selected = _object(value, "settlement", frozenset({
        "schema", "transaction_id", "status", "reason", "settled_at",
        "evidence", "settlement_sha256",
    }))
    if selected["schema"] != SETTLEMENT_SCHEMA or (
        selected["transaction_id"] != tx["transaction_id"]
    ) or selected["status"] not in TERMINAL:
        raise GrantBrokerError("settlement identity/status is invalid")
    material = dict(selected)
    digest = material.pop("settlement_sha256")
    if digest != canonical_digest("grant-broker-settlement", material):
        raise GrantBrokerError("settlement digest was tampered")
    return deepcopy(selected)


def settle(contract_path: Path | str, tx_id: str, *, now: Any) -> dict:
    now_text, current = _text(now, "now"), _time(now, "now")
    with _locked(contract_path) as locked:
        projection = _read(contract_path, locked)
        tx = _tx(projection, tx_id)
        if tx["settlement"] is not None:
            return _result(tx_id, "already_settled", tx["settlement"]["reason"],
                           settlement=_public(tx["settlement"]))
        status = reason = None
        evidence = {}
        if tx["decision"] is not None and tx["decision"]["outcome"] == "deny":
            status, reason = "denied", "typed human deny is authoritative"
            evidence = {"receipt_id": tx["decision"]["receipt_id"]}
        elif current >= _time(tx["spec"]["expires_at"], "expires_at") and (
            tx["grant_consumption"] is None
        ):
            status, reason = "expired", "expired without consumed allow authority"
        elif tx["effect_receipt"] is not None and (
            tx["effect_receipt"]["status"] != "succeeded"
        ):
            observed = tx["effect_receipt"]["status"]
            status = "effect_failed" if observed == "failed" else "effect_unknown"
            reason = f"external effect receipt reported {observed}"
            evidence = {"effect_receipt_sha256":
                        effect_receipt_identity(tx["effect_receipt"])}
        elif tx["verifier_receipt"] is not None:
            observed = tx["verifier_receipt"]["status"]
            status = {"passed": "succeeded", "failed": "verification_failed",
                      "inconclusive": "verification_inconclusive"}[observed]
            reason = f"sealed verifier reported {observed}"
            evidence = {"verifier_receipt_id": tx["verifier_receipt"]["receipt_id"]}
        if status is None or reason is None:
            return _result(tx_id, "not_ready",
                           "terminal truth is not yet durably available")
        value = _make_settlement(tx, status, reason, now_text, evidence)
        _append(contract_path, projection, "settled",
                {"transaction_id": tx_id, "settlement": value}, locked=locked)
    return _result(tx_id, status, reason, settlement=value)


def replace_transaction(
    contract_path: Path | str, old_tx_id: str, replacement_tx_id: str, *, now: Any
) -> dict:
    with _locked(contract_path) as locked:
        projection = _read(contract_path, locked)
        old, replacement = _tx(projection, old_tx_id), _tx(projection, replacement_tx_id)
        if old["settlement"] is not None:
            return _result(old_tx_id, "already_settled", old["settlement"]["reason"])
        if old_tx_id == replacement_tx_id:
            raise GrantBrokerError("replacement must have a distinct identity")
        value = _make_settlement(
            old, "replaced", "distinct canonical transaction replaced this request",
            now, {"replacement_transaction_id": replacement["transaction_id"]},
        )
        _append(contract_path, projection, "settled",
                {"transaction_id": old_tx_id, "settlement": value},
                locked=locked)
    return _result(old_tx_id, "replaced", value["reason"],
                   replacement_transaction_id=replacement_tx_id)


def next_step(contract_path: Path | str, tx_id: str, *, now: Any) -> dict:
    tx = _tx(_read(contract_path), tx_id)
    current = _time(now, "now")
    if tx["settlement"] is not None:
        return _result(tx_id, "terminal", tx["settlement"]["reason"],
                       settlement=_public(tx["settlement"]))
    if tx["question"] is None:
        return _result(tx_id, "publish_question", "question outbox is next")
    if tx["display_event_sha256"] is None:
        return _result(tx_id, "display_question", "question awaits display",
                       question=_public(tx["question"]),
                       control_route=seal_control_route(contract_path, tx_id,
                                                        kind="question"))
    if tx["decision"] is None:
        if current >= _time(tx["spec"]["expires_at"], "expires_at"):
            return _result(tx_id, "settle_expired",
                           "expiry is an observation, never permission")
        return _result(tx_id, "await_human_decision",
                       "only an exact typed callback can decide",
                       reassess_due=current >= _time(tx["spec"]["reassess_at"],
                                                     "reassess_at"))
    if tx["decision"]["outcome"] == "deny":
        return _result(tx_id, "settle_denied", "durable deny awaits settlement")
    if tx["grant_consumption"] is None:
        return _result(tx_id, "consume_h01_grant",
                       "current world state is required for H01 CAS")
    if tx["dispatch"] is None:
        return _result(tx_id, "claim_dispatch", "one consumer may claim dispatch",
                       control_route=seal_control_route(contract_path, tx_id,
                                                        kind="recovery"))
    if tx["effect_receipt"] is None:
        return _result(tx_id, "await_effect_receipt",
                       "reprobe by stable dispatch ID or supply its receipt",
                       dispatch_reprobe=_dispatch_reprobe(tx))
    if tx["effect_receipt"]["status"] != "succeeded":
        return _result(tx_id, "settle_effect_result",
                       "non-successful external receipt awaits settlement")
    if tx["verifier_receipt"] is None:
        return _result(tx_id, "await_verifier_receipt",
                       "sealed verifier receipt is required")
    return _result(tx_id, "settle_verifier_result",
                   "verifier truth awaits settlement")


def seal_control_route(contract_path: Path | str, tx_id: str, *, kind: str) -> dict:
    tx = _tx(_read(contract_path), tx_id)
    if kind == "question":
        if tx["question"] is None or tx["display_event_sha256"]:
            raise GrantBrokerError("question control route is unreachable")
        operation, source = ("display_question",
                             tx["question"]["source_event_sha256"])
    elif kind == "recovery":
        if tx["grant_consumption"] is None or tx["dispatch"] is not None or (
            tx["settlement"] is not None
        ):
            raise GrantBrokerError("recovery control route is unreachable")
        operation, source = ("recover_transaction",
                             tx["grant_consumption"]["source_event_sha256"])
    else:
        raise GrantBrokerError("control route kind is invalid")
    route = {
        "schema": CONTROL_ROUTE_SCHEMA, "protocol": PROTOCOL_SCHEMA, "kind": kind,
        "operation": operation, "transaction_id": tx_id,
        "request_id": _request_id(tx_id), "provider": tx["spec"]["provider"],
        "session_id": tx["spec"]["session_id"],
        "task_epoch": tx["spec"]["task_epoch"],
        "source_event_sha256": source, "control_only": True, "destructive": False,
    }
    route["route_sha256"] = canonical_digest("grant-broker-control-route", route)
    return route


def verify_control_route(
    contract_path: Path | str, route: Any, *, provider: Any,
    session_id: Any, task_epoch: Any,
) -> dict:
    try:
        selected = _object(route, "control route", ROUTE_FIELDS)
        if selected["schema"] != CONTROL_ROUTE_SCHEMA or (
            selected["protocol"] != PROTOCOL_SCHEMA
        ):
            raise GrantBrokerError("control route protocol is invalid")
        material = dict(selected)
        digest = material.pop("route_sha256")
        if digest != canonical_digest("grant-broker-control-route", material):
            raise GrantBrokerError("control route seal was forged")
        if selected["control_only"] is not True or selected["destructive"] is not False:
            raise GrantBrokerError("broad or destructive bypass refused")
        expected = seal_control_route(contract_path, selected["transaction_id"],
                                      kind=selected["kind"])
        if selected != expected:
            raise GrantBrokerError("control route is stale, foreign, or unbound")
        current = (provider, session_id, task_epoch)
        bound = (selected["provider"], selected["session_id"],
                 selected["task_epoch"])
        if any(type(value) is not str for value in current) or current != bound:
            raise GrantBrokerError("provider/session/task epoch is foreign")
        return {
            "schema": RESULT_SCHEMA, "action": "allow_control_route",
            "reason": "exact sealed broker control route precedes ordinary policy",
            "transaction_id": selected["transaction_id"],
            "operation": selected["operation"],
            "ordinary_pretool_policy_required": False,
        }
    except (GrantBrokerError, HumanGrantError, OSError, UnicodeError,
            KeyError, TypeError) as error:
        return {
            "schema": RESULT_SCHEMA, "action": "deny", "reason": str(error),
            "transaction_id": "", "operation": "",
            "ordinary_pretool_policy_required": True,
        }


def transaction(contract_path: Path | str, tx_id: str) -> dict:
    return _public_transaction(_tx(_read(contract_path), tx_id))


def pending(contract_path: Path | str) -> list[dict]:
    return [_public_transaction(tx) for _, tx in sorted(
        _read(contract_path)["transactions"].items()
    ) if tx["settlement"] is None]
