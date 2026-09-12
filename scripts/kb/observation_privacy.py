#!/usr/bin/env python3
"""Privacy policy and one-shot export authority for event observation.

The authoritative event logs are deliberately outside this control plane.
Privacy modes govern only the derived projection, its cache, and portable
redacted exports.  A portable export requires a live host approval paired to
one immutable proposal and is consumed before the output file is published.
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
import tempfile
import time
from typing import Any, Iterator, Mapping, Sequence
from types import SimpleNamespace
from functools import wraps


_approval = SimpleNamespace(
    **runpy.run_path(
        str(Path(__file__).resolve().with_name("approval_invariant.py"))
    )
)
_file_lock = SimpleNamespace(
    **runpy.run_path(str(Path(__file__).resolve().with_name("file_lock.py")))
)
ApprovalInvariantError = _approval.ApprovalInvariantError
ask_approval = _approval.ask_approval
decide_approval = _approval.decide_approval
load_approval_projection = _approval.load_projection
lock_exclusive_nonblocking = _file_lock.lock_exclusive_nonblocking
unlock = _file_lock.unlock


POLICY_SCHEMA = "sulde-observation-privacy-policy-v1"
PROPOSAL_SCHEMA = "sulde-observation-export-proposal-v1"
EXPORT_SCHEMA = "sulde-observation-export-v1"
LEDGER_EVENT_SCHEMA = "sulde-observation-export-event-v1"
MODES = {"local", "approved-export", "disabled"}
EXPORT_APPROVAL_KIND = "observation-export"
MAX_POLICY_BYTES = 64 * 1024
MAX_PROPOSAL_BYTES = 64 * 1024 * 1024
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


class ObservationPrivacyError(RuntimeError):
    """A privacy policy or approved-export invariant was not satisfied."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _digest(value: Any) -> str:
    material = value if isinstance(value, bytes) else str(value).encode(
        "utf-8", errors="replace"
    )
    return hashlib.sha256(material).hexdigest()


def _contract_digest(path: Path) -> str:
    try:
        identity = str(path.expanduser().resolve())
    except OSError:
        identity = str(path.expanduser().absolute())
    return _digest(identity)


def policy_path(home: Path) -> Path:
    return home / "privacy" / "observation-policy.json"


def export_root(home: Path) -> Path:
    return home / "privacy" / "observation-exports"


def export_ledger_path(home: Path) -> Path:
    return export_root(home) / "events.jsonl"


def export_proposal_path(home: Path, proposal_digest: str) -> Path:
    if not _DIGEST_RE.fullmatch(proposal_digest):
        raise ObservationPrivacyError("export proposal digest must be 64 lowercase hex chars")
    return export_root(home) / "proposals" / f"{proposal_digest}.json"


def _safe_private_path(home: Path, path: Path) -> bool:
    """Return false for any symlink or lexical escape under the KB home."""
    root = home.expanduser().absolute()
    target = path.expanduser().absolute()
    if not target.is_relative_to(root):
        return False
    current = root
    if current.is_symlink():
        return False
    for part in target.relative_to(root).parts:
        current = current / part
        if current.is_symlink():
            return False
    return True


@contextmanager
def _privacy_control_lock(home: Path, *, timeout: float = 3.0) -> Iterator[None]:
    lock_path = home / "privacy" / ".observation-control.lock"
    if not _safe_private_path(home, lock_path):
        raise ObservationPrivacyError("observation privacy control lock path is unsafe")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout
    with lock_path.open("a+", encoding="utf-8") as handle:
        while True:
            try:
                lock_exclusive_nonblocking(handle)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise ObservationPrivacyError("observation privacy control is busy")
                time.sleep(0.01)
        try:
            yield
        finally:
            unlock(handle)


def _serialized_privacy_control(function):
    @wraps(function)
    def wrapped(home: Path, *args, **kwargs):
        with _privacy_control_lock(home):
            return function(home, *args, **kwargs)

    return wrapped


def _default_policy() -> dict[str, Any]:
    return {
        "schema": POLICY_SCHEMA,
        "mode": "local",
        "source": "default",
        "healthy": True,
        "error": None,
        "updatedAt": None,
    }


def _disabled_policy(error: str) -> dict[str, Any]:
    return {
        "schema": POLICY_SCHEMA,
        "mode": "disabled",
        "source": "invalid",
        "healthy": False,
        "error": error,
        "updatedAt": None,
    }


def load_policy(home: Path) -> dict[str, Any]:
    """Load the local policy; malformed policy fails closed as disabled."""
    path = policy_path(home)
    if not path.exists() and not path.is_symlink():
        return _default_policy()
    if not _safe_private_path(home, path):
        return _disabled_policy("unsafe_policy_path")
    try:
        if not path.is_file() or path.stat().st_size > MAX_POLICY_BYTES:
            return _disabled_policy("invalid_policy_file")
        value = json.loads(path.read_text(encoding="utf-8", errors="strict"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return _disabled_policy("unreadable_policy")
    if not isinstance(value, dict) or value.get("schema") != POLICY_SCHEMA:
        return _disabled_policy("unsupported_policy_schema")
    mode = str(value.get("mode") or "")
    if mode not in MODES:
        return _disabled_policy("unsupported_privacy_mode")
    updated_at = value.get("updatedAt")
    if updated_at is not None and not isinstance(updated_at, str):
        return _disabled_policy("invalid_policy_timestamp")
    return {
        "schema": POLICY_SCHEMA,
        "mode": mode,
        "source": "configured",
        "healthy": True,
        "error": None,
        "updatedAt": updated_at,
    }


def privacy_envelope(policy: Mapping[str, Any]) -> dict[str, Any]:
    mode = str(policy.get("mode") or "disabled")
    envelope = {
        "schema": POLICY_SCHEMA,
        "mode": mode,
        "policySource": str(policy.get("source") or "invalid"),
        "policyHealthy": policy.get("healthy") is True,
        "policyError": policy.get("error"),
        "observationEnabled": mode != "disabled" and policy.get("healthy") is True,
        "portableExportEnabled": mode == "approved-export" and policy.get("healthy") is True,
        "portableExportRequiresLiveApproval": True,
        "authoritativeLogsAffected": False,
    }
    if isinstance(policy.get("cleanup"), dict):
        envelope["cleanup"] = dict(policy["cleanup"])
    return envelope


def _atomic_private_write(path: Path, payload: bytes, *, replace: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            if os.name != "nt":
                os.fchmod(handle.fileno(), 0o600)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if replace:
            os.replace(temporary, path)
        else:
            try:
                os.link(temporary, path)
            except FileExistsError as error:
                raise ObservationPrivacyError(f"refusing to overwrite existing file: {path}") from error
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


@_serialized_privacy_control
def set_mode(home: Path, mode: str) -> dict[str, Any]:
    """Persist a mode choice.  Enabling export never grants an export approval."""
    if mode not in MODES:
        raise ObservationPrivacyError(f"privacy mode must be one of {sorted(MODES)}")
    path = policy_path(home)
    if not _safe_private_path(home, path):
        raise ObservationPrivacyError("privacy policy path is unsafe")
    payload = {
        "schema": POLICY_SCHEMA,
        "mode": mode,
        "updatedAt": _now(),
    }
    _atomic_private_write(path, _canonical(payload) + b"\n", replace=True)
    policy = load_policy(home)
    if mode == "disabled":
        policy["cleanup"] = _purge_derived_observation_data(home)
    return policy


def _load_contract_identity(contract_path: Path) -> tuple[str, int]:
    try:
        value = json.loads(contract_path.read_text(encoding="utf-8", errors="strict"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ObservationPrivacyError(f"cannot read intent contract: {type(error).__name__}") from error
    if not isinstance(value, dict):
        raise ObservationPrivacyError("intent contract must be an object")
    intent_id = str(value.get("intent_id") or "").strip()
    try:
        revision = int(value.get("revision") or 0)
    except (TypeError, ValueError) as error:
        raise ObservationPrivacyError("intent contract revision is invalid") from error
    if not intent_id or revision < 1:
        raise ObservationPrivacyError("intent contract identity is incomplete")
    return intent_id, revision


def _normal_query(
    *,
    workspaces: Sequence[Path],
    domains: Sequence[str],
    providers: Sequence[str],
    correlations: Mapping[str, str],
    limit: int | None,
) -> dict[str, Any]:
    return {
        "workspaces": [str(path.expanduser().absolute()) for path in workspaces],
        "domains": sorted(set(domains)),
        "providers": sorted(set(providers)),
        "correlations": dict(sorted(correlations.items())),
        "limit": limit,
    }


def _load_proposal_file(path: Path) -> dict[str, Any]:
    try:
        if not path.is_file() or path.stat().st_size > MAX_PROPOSAL_BYTES:
            raise ObservationPrivacyError("export proposal file is missing or oversized")
        value = json.loads(path.read_text(encoding="utf-8", errors="strict"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ObservationPrivacyError(f"cannot read export proposal: {type(error).__name__}") from error
    if not isinstance(value, dict) or value.get("schema") != PROPOSAL_SCHEMA:
        raise ObservationPrivacyError("unsupported export proposal schema")
    digest = str(value.get("proposalDigest") or "")
    material = dict(value)
    material.pop("proposalDigest", None)
    if not _DIGEST_RE.fullmatch(digest) or _digest(_canonical(material)) != digest:
        raise ObservationPrivacyError("export proposal digest does not match its content")
    return value


def load_export_proposal(home: Path, proposal_digest: str) -> dict[str, Any]:
    path = export_proposal_path(home, proposal_digest)
    if not _safe_private_path(home, path):
        raise ObservationPrivacyError("export proposal path is unsafe")
    value = _load_proposal_file(path)
    if value["proposalDigest"] != proposal_digest:
        raise ObservationPrivacyError("export proposal filename/content mismatch")
    return value


def _proposal_for_target_hash(home: Path, target_sha256: str) -> dict[str, Any]:
    root = export_root(home) / "proposals"
    if not root.is_dir() or not _safe_private_path(home, root):
        raise ObservationPrivacyError("no readable observation export proposal exists")
    matches: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.json")):
        digest = path.stem
        if _DIGEST_RE.fullmatch(digest) and _digest(digest) == target_sha256:
            matches.append(load_export_proposal(home, digest))
    if len(matches) != 1:
        raise ObservationPrivacyError("approval does not bind exactly one export proposal")
    return matches[0]


def _open_export_requests(contract_path: Path) -> list[dict[str, Any]]:
    try:
        projection = load_approval_projection(contract_path)
    except (ApprovalInvariantError, OSError, UnicodeError) as error:
        raise ObservationPrivacyError(f"cannot replay export approvals: {error}") from error
    return [
        dict(row)
        for row in projection["requests"].values()
        if row["kind"] == EXPORT_APPROVAL_KIND
        and row["status"] == "asked"
        and row.get("source") == "observation_export_prepare"
    ]


@_serialized_privacy_control
def prepare_export(
    home: Path,
    contract_path: Path,
    *,
    output: Path,
    snapshot: Mapping[str, Any],
    workspaces: Sequence[Path] = (),
    domains: Sequence[str] = (),
    providers: Sequence[str] = (),
    correlations: Mapping[str, str] | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Freeze a readable, cut-bound proposal without creating export data."""
    policy = load_policy(home)
    if policy["healthy"] is not True or policy["mode"] != "approved-export":
        raise ObservationPrivacyError("portable export requires approved-export privacy mode")
    if _open_export_requests(contract_path):
        raise ObservationPrivacyError("an observation export already awaits a human decision")
    if snapshot.get("privacy", {}).get("mode") != "approved-export":
        raise ObservationPrivacyError("snapshot was not collected under approved-export mode")
    source_revision = str(snapshot.get("sourceRevision") or "")
    as_of_seq = snapshot.get("asOfSeq")
    events = snapshot.get("events")
    summary = snapshot.get("summary")
    if (
        not _DIGEST_RE.fullmatch(source_revision)
        or isinstance(as_of_seq, bool)
        or not isinstance(as_of_seq, int)
        or not isinstance(events, list)
        or not isinstance(summary, dict)
    ):
        raise ObservationPrivacyError("snapshot is incomplete and cannot be exported")
    if not events:
        raise ObservationPrivacyError(
            "no matching observation events; no export proposal was created"
        )
    requested_destination = output.expanduser().absolute()
    if requested_destination.exists() or requested_destination.is_symlink():
        raise ObservationPrivacyError("export destination already exists")
    if not requested_destination.parent.is_dir():
        raise ObservationPrivacyError("export destination parent does not exist")
    try:
        destination = (
            requested_destination.parent.resolve(strict=True)
            / requested_destination.name
        )
    except OSError as error:
        raise ObservationPrivacyError("export destination parent is unreadable") from error
    intent_id, intent_revision = _load_contract_identity(contract_path)
    material: dict[str, Any] = {
        "schema": PROPOSAL_SCHEMA,
        "createdAt": _now(),
        "contractSha256": _contract_digest(contract_path),
        "contractPath": str(contract_path.expanduser().absolute()),
        "intentIdSha256": _digest(intent_id),
        "intentRevision": intent_revision,
        "stateVersion": snapshot.get("stateVersion"),
        "asOfSeq": as_of_seq,
        "sourceRevision": source_revision,
        "matchedEvents": int(summary.get("events_total") or 0),
        "returnedEvents": len(events),
        "query": _normal_query(
            workspaces=workspaces,
            domains=domains,
            providers=providers,
            correlations=correlations or {},
            limit=limit,
        ),
        "destination": str(destination),
        "destinationSha256": _digest(str(destination)),
        "redactedProjectionOnly": True,
        "networkTransmissionAuthorized": False,
        "frozenSnapshot": {
            "stateVersion": snapshot.get("stateVersion"),
            "asOfSeq": as_of_seq,
            "sourceRevision": source_revision,
            "generatedAt": snapshot.get("generated_at"),
            "summary": summary,
            "events": events,
        },
    }
    proposal_digest = _digest(_canonical(material))
    proposal = {**material, "proposalDigest": proposal_digest}
    path = export_proposal_path(home, proposal_digest)
    if not _safe_private_path(home, path):
        raise ObservationPrivacyError("export proposal path is unsafe")
    encoded_proposal = _canonical(proposal) + b"\n"
    if len(encoded_proposal) > MAX_PROPOSAL_BYTES:
        raise ObservationPrivacyError("export proposal exceeds the local 64 MiB limit")
    _atomic_private_write(path, encoded_proposal, replace=False)
    try:
        request = ask_approval(
            contract_path,
            intent_id=intent_id,
            intent_revision=intent_revision,
            kind=EXPORT_APPROVAL_KIND,
            target=proposal_digest,
            provider="unknown",
            session_id="",
            source="observation_export_prepare",
        )
    except (ApprovalInvariantError, OSError, UnicodeError) as error:
        try:
            path.unlink()
        except OSError:
            pass
        raise ObservationPrivacyError(f"cannot register export approval question: {error}") from error
    return {
        "schema": "sulde-observation-export-decision-card-v1",
        "proposalDigest": proposal_digest,
        "requestId": request["request_id"],
        "privacyMode": "approved-export",
        "scope": {
            "workspaceCount": len(workspaces),
            "domains": list(material["query"]["domains"]),
            "providers": list(material["query"]["providers"]),
            "correlationKeys": sorted(material["query"]["correlations"]),
            "limit": limit,
        },
        "dataCut": {
            "stateVersion": material["stateVersion"],
            "asOfSeq": as_of_seq,
            "sourceRevision": source_revision,
            "matchedEvents": material["matchedEvents"],
            "returnedEvents": material["returnedEvents"],
        },
        "destination": str(destination),
        "contains": "统一事件观察器已经脱敏的派生事件与汇总",
        "excludes": "权威原始日志、原始提示词、原始工具结果、隐藏思维与任何网络发送授权",
        "oneShot": True,
        "decisionSurface": {
            "codex": {
                "type": "PermissionRequest",
                "choices": ["Allow", "Deny"],
                "textAuthority": False,
            },
            "fallbackHosts": {
                "type": "readable-approve-reject-choice",
            },
        },
    }


def decide_current_export(
    home: Path,
    contract_path: Path,
    *,
    outcome: str,
    provider: str,
    session_id: str,
    actor: str,
    receipt_id: str,
) -> dict[str, Any]:
    if outcome not in {"approved", "rejected"}:
        raise ObservationPrivacyError("export decision must be approved or rejected")
    open_requests = _open_export_requests(contract_path)
    if len(open_requests) != 1:
        raise ObservationPrivacyError("human decision must match exactly one open export question")
    proposal = _proposal_for_target_hash(home, open_requests[0]["target_sha256"])
    if proposal["contractSha256"] != _contract_digest(contract_path):
        raise ObservationPrivacyError("export proposal belongs to another intent contract")
    try:
        decision = decide_approval(
            contract_path,
            kind=EXPORT_APPROVAL_KIND,
            target=proposal["proposalDigest"],
            outcome=outcome,
            provider=provider,
            session_id=session_id,
            actor=actor,
            receipt_id=receipt_id,
        )
    except (ApprovalInvariantError, OSError, UnicodeError) as error:
        raise ObservationPrivacyError(f"cannot persist export decision: {error}") from error
    cleanup = "retained_for_approved_export"
    if outcome == "rejected":
        cleanup = _remove_proposal_payload(home, proposal["proposalDigest"])
    return {"proposal": proposal, "decision": decision, "cleanup": cleanup}


def current_export_proposal(home: Path, contract_path: Path) -> dict[str, Any]:
    """Resolve the one human-readable proposal currently awaiting a decision."""
    open_requests = _open_export_requests(contract_path)
    if len(open_requests) != 1:
        raise ObservationPrivacyError(
            "human decision must match exactly one open export question"
        )
    proposal = _proposal_for_target_hash(home, open_requests[0]["target_sha256"])
    if proposal["contractSha256"] != _contract_digest(contract_path):
        raise ObservationPrivacyError("export proposal belongs to another intent contract")
    return proposal


def _remove_proposal_payload(home: Path, proposal_digest: str) -> str:
    try:
        path = export_proposal_path(home, proposal_digest)
        if not _safe_private_path(home, path):
            return "unsafe_path_retained"
        path.unlink()
        return "deleted"
    except FileNotFoundError:
        return "already_absent"
    except OSError:
        return "delete_failed"


def _purge_derived_observation_data(home: Path) -> dict[str, Any]:
    """Delete only rebuildable cache/proposal payloads when observation is disabled."""
    removed = 0
    failed = 0
    cache = home / "projections" / "event-observer-v1.json"
    if cache.exists() or cache.is_symlink():
        if _safe_private_path(home, cache) and cache.is_file():
            try:
                cache.unlink()
                removed += 1
            except OSError:
                failed += 1
        else:
            failed += 1
    proposals = export_root(home) / "proposals"
    if proposals.exists() or proposals.is_symlink():
        if not proposals.is_dir() or not _safe_private_path(home, proposals):
            failed += 1
        else:
            for path in sorted(proposals.glob("*.json")):
                if not _safe_private_path(home, path) or not path.is_file():
                    failed += 1
                    continue
                try:
                    proposal = _load_proposal_file(path)
                    contract_path = Path(str(proposal.get("contractPath") or ""))
                    if _contract_digest(contract_path) == proposal["contractSha256"]:
                        try:
                            decide_approval(
                                contract_path,
                                kind=EXPORT_APPROVAL_KIND,
                                target=proposal["proposalDigest"],
                                outcome="cancelled",
                                provider="unknown",
                                session_id="",
                                actor="observation-privacy-disabled",
                            )
                        except (ApprovalInvariantError, OSError, UnicodeError):
                            # Already-decided approval needs no second decision;
                            # deleting the frozen payload still revokes execution.
                            pass
                    path.unlink()
                    removed += 1
                except (OSError, ObservationPrivacyError):
                    failed += 1
    return {
        "status": "completed" if failed == 0 else "incomplete",
        "derivedFilesRemoved": removed,
        "derivedFilesFailed": failed,
        "authoritativeLogsRemoved": 0,
        "externalExportsRemoved": 0,
    }


@contextmanager
def _ledger_lock(home: Path, *, timeout: float = 3.0) -> Iterator[None]:
    path = export_ledger_path(home)
    lock_path = path.with_name(f".{path.name}.lock")
    if not _safe_private_path(home, lock_path):
        raise ObservationPrivacyError("export ledger lock path is unsafe")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout
    with lock_path.open("a+", encoding="utf-8") as handle:
        while True:
            try:
                lock_exclusive_nonblocking(handle)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise ObservationPrivacyError("export ledger lock is busy")
                time.sleep(0.01)
        try:
            yield
        finally:
            unlock(handle)


@contextmanager
def _intent_contract_lock(
    home: Path,
    contract_path: Path,
    *,
    timeout: float = 3.0,
) -> Iterator[None]:
    del home  # Intent contracts may legitimately live in a managed L3 worktree.
    contract_path = contract_path.expanduser().absolute()
    lock_path = contract_path.with_name(f".{contract_path.name}.lock")
    if (
        contract_path.is_symlink()
        or not contract_path.is_file()
        or lock_path.is_symlink()
    ):
        raise ObservationPrivacyError("intent contract or lock path is unsafe")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout
    with lock_path.open("a+", encoding="utf-8") as handle:
        while True:
            try:
                lock_exclusive_nonblocking(handle)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise ObservationPrivacyError("intent contract lock is busy")
                time.sleep(0.01)
        try:
            yield
        finally:
            unlock(handle)


def _consume_export_receipt(
    home: Path,
    contract_path: Path,
    proposal_digest: str,
    approval: Mapping[str, Any],
) -> None:
    """Spend the live prompt receipt when the approved export starts."""
    with _intent_contract_lock(home, contract_path):
        try:
            contract = json.loads(contract_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise ObservationPrivacyError(
                f"cannot consume export receipt: {type(error).__name__}"
            ) from error
        runtime = contract.get("runtime") if isinstance(contract, dict) else None
        receipts = runtime.get("approval_receipts") if isinstance(runtime, dict) else None
        if not isinstance(receipts, list):
            raise ObservationPrivacyError("intent contract has no approval receipts")
        matches = [
            row
            for row in receipts
            if isinstance(row, dict)
            and row.get("action") == "approve-observation-export"
            and row.get("target") == proposal_digest
            and isinstance(row.get("receipt_id"), str)
            and _digest(row["receipt_id"]) == approval.get("receipt_sha256")
        ]
        if len(matches) != 1:
            raise ObservationPrivacyError("export approval has no unique live receipt")
        receipt = matches[0]
        if receipt.get("consumed_at"):
            raise ObservationPrivacyError("export approval receipt was already consumed")
        receipt["consumed_at"] = _now()
        receipt["consumed_by"] = "observation-export-executor"
        payload = (
            json.dumps(contract, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
        _atomic_private_write(contract_path, payload, replace=True)


def _read_ledger(home: Path) -> list[dict[str, Any]]:
    path = export_ledger_path(home)
    if not path.is_file():
        return []
    if not _safe_private_path(home, path):
        raise ObservationPrivacyError("export ledger path is unsafe")
    try:
        payload = path.read_bytes()
        if payload and not payload.endswith(b"\n"):
            raise ObservationPrivacyError("export ledger has an incomplete tail")
        rows = [json.loads(line) for line in payload.decode("utf-8").splitlines()]
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ObservationPrivacyError(f"cannot replay export ledger: {type(error).__name__}") from error
    for sequence, row in enumerate(rows, 1):
        if (
            not isinstance(row, dict)
            or row.get("schema") != LEDGER_EVENT_SCHEMA
            or row.get("sequence") != sequence
            or row.get("state") not in {"reserved", "completed", "failed"}
            or not _DIGEST_RE.fullmatch(str(row.get("proposalDigest") or ""))
        ):
            raise ObservationPrivacyError("export ledger contains an invalid row")
    return rows


def _append_ledger_locked(home: Path, rows: list[dict[str, Any]], spec: Mapping[str, Any]) -> dict[str, Any]:
    path = export_ledger_path(home)
    row = {
        "schema": LEDGER_EVENT_SCHEMA,
        "sequence": len(rows) + 1,
        "at": _now(),
        **dict(spec),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        if os.name != "nt":
            os.fchmod(handle.fileno(), 0o600)
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    rows.append(row)
    return row


def _approved_request(contract_path: Path, proposal_digest: str) -> dict[str, Any]:
    try:
        projection = load_approval_projection(contract_path)
    except (ApprovalInvariantError, OSError, UnicodeError) as error:
        raise ObservationPrivacyError(f"cannot replay export approval: {error}") from error
    target_sha256 = _digest(proposal_digest)
    matches = [
        dict(row)
        for row in projection["requests"].values()
        if row["kind"] == EXPORT_APPROVAL_KIND
        and row["target_sha256"] == target_sha256
        and row.get("source") in {
            "observation_export_prepare",
            "session_start_restore",
            "user_prompt_restore",
        }
        and row["status"] == "decided"
        and row["outcome"] == "approved"
    ]
    if len(matches) != 1:
        raise ObservationPrivacyError("export has no unique approved decision")
    request = matches[0]
    provider = str(request.get("decision_provider") or "")
    expected_actor = (
        "permission-request:codex"
        if provider == "codex"
        else f"user-prompt:{provider}"
    )
    expected_channel = (
        "codex-native-permission" if provider == "codex" else "user-prompt"
    )
    expected_event = "permission_request" if provider == "codex" else "user_prompt_submit"
    if (
        provider not in {"claude", "codex"}
        or request.get("decision_actor") != expected_actor
        or not str(request.get("decision_lane_sha256") or "")
        or not _DIGEST_RE.fullmatch(str(request.get("receipt_sha256") or ""))
    ):
        raise ObservationPrivacyError("export approval lacks live host prompt evidence")
    try:
        contract = json.loads(
            contract_path.read_text(encoding="utf-8", errors="strict")
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ObservationPrivacyError(
            f"cannot verify live export receipt: {type(error).__name__}"
        ) from error
    runtime = contract.get("runtime") if isinstance(contract, dict) else None
    receipts = runtime.get("approval_receipts") if isinstance(runtime, dict) else None
    observations = runtime.get("host_observations") if isinstance(runtime, dict) else None
    if not isinstance(receipts, list) or not isinstance(observations, list):
        raise ObservationPrivacyError("intent contract has no live approval evidence")
    receipt_matches = [
        row
        for row in receipts
        if isinstance(row, dict)
        and row.get("action") == "approve-observation-export"
        and row.get("target") == proposal_digest
        and row.get("provider") == provider
        and row.get("actor") == expected_actor
        and row.get("channel") == expected_channel
        and row.get("observation_source") == "live_host_hook"
        and isinstance(row.get("receipt_id"), str)
        and _digest(row["receipt_id"]) == request["receipt_sha256"]
    ]
    if len(receipt_matches) != 1:
        raise ObservationPrivacyError("export approval has no unique live receipt")
    receipt = receipt_matches[0]
    observation_matches = [
        row
        for row in observations
        if isinstance(row, dict)
        and row.get("event") == expected_event
        and row.get("provider") == provider
        and row.get("session_id") == receipt.get("session_id")
        and row.get("source") == "live_host_hook"
        and row.get("status") == "control_recorded"
        and row.get("control_action") == "approve-observation-export"
        and row.get("control_target") == proposal_digest
        and row.get("receipt_id") == receipt.get("receipt_id")
    ]
    if len(observation_matches) != 1:
        raise ObservationPrivacyError("export approval has no matching live host observation")
    return request


def _export_payload(
    proposal: Mapping[str, Any],
    approval: Mapping[str, Any],
) -> dict[str, Any]:
    snapshot = proposal.get("frozenSnapshot")
    if not isinstance(snapshot, dict):
        raise ObservationPrivacyError("export proposal has no frozen snapshot")
    events = snapshot.get("events")
    summary = snapshot.get("summary")
    if not isinstance(events, list) or not isinstance(summary, dict):
        raise ObservationPrivacyError("export snapshot has no event data")
    public_query = dict(proposal["query"])
    public_query["workspaces"] = [
        "sha256:" + _digest(value)[:24] for value in public_query["workspaces"]
    ]
    public_query["correlations"] = {
        key: "sha256:" + _digest(value)[:24]
        for key, value in public_query["correlations"].items()
    }
    return {
        "schema": EXPORT_SCHEMA,
        "exportedAt": _now(),
        "proposalDigest": proposal["proposalDigest"],
        "stateVersion": snapshot["stateVersion"],
        "asOfSeq": snapshot["asOfSeq"],
        "sourceRevision": snapshot["sourceRevision"],
        "query": public_query,
        "summary": summary,
        "events": events,
        "privacy": {
            "mode": "approved-export",
            "redactedProjectionOnly": True,
            "oneShotApprovalConsumed": True,
            "approvalRequestSha256": _digest(approval["request_id"]),
            "networkTransmissionAuthorized": False,
            "authoritativeLogsAffected": False,
        },
    }


@_serialized_privacy_control
def export_approved(
    home: Path,
    contract_path: Path,
    proposal_digest: str,
) -> dict[str, Any]:
    """Consume one live approval and atomically publish one redacted file."""
    policy = load_policy(home)
    if policy["healthy"] is not True or policy["mode"] != "approved-export":
        raise ObservationPrivacyError("privacy mode no longer permits portable export")
    approval = _approved_request(contract_path, proposal_digest)
    try:
        proposal = load_export_proposal(home, proposal_digest)
    except ObservationPrivacyError as error:
        with _ledger_lock(home):
            rows = _read_ledger(home)
        if any(row["proposalDigest"] == proposal_digest for row in rows):
            raise ObservationPrivacyError(
                "one-shot export approval was already consumed"
            ) from error
        raise
    if proposal["contractSha256"] != _contract_digest(contract_path):
        raise ObservationPrivacyError("export proposal belongs to another intent contract")
    snapshot = proposal.get("frozenSnapshot")
    if not isinstance(snapshot, dict):
        raise ObservationPrivacyError("export proposal has no frozen snapshot")
    if (
        snapshot.get("stateVersion") != proposal["stateVersion"]
        or snapshot.get("asOfSeq") != proposal["asOfSeq"]
        or snapshot.get("sourceRevision") != proposal["sourceRevision"]
    ):
        raise ObservationPrivacyError("frozen export snapshot does not match its proposal")
    events = snapshot.get("events")
    summary = snapshot.get("summary")
    if (
        not isinstance(events, list)
        or not isinstance(summary, dict)
        or len(events) != proposal["returnedEvents"]
        or int(summary.get("events_total") or 0) != proposal["matchedEvents"]
    ):
        raise ObservationPrivacyError("export rows no longer match the approved data cut")
    destination = Path(str(proposal["destination"])).expanduser().absolute()
    if _digest(str(destination)) != proposal["destinationSha256"]:
        raise ObservationPrivacyError("export destination binding is invalid")
    try:
        if destination.parent.resolve(strict=True) != destination.parent:
            raise ObservationPrivacyError("export destination parent changed after approval")
    except OSError as error:
        raise ObservationPrivacyError("export destination parent is no longer available") from error
    payload = _canonical(_export_payload(proposal, approval)) + b"\n"

    _consume_export_receipt(
        home,
        contract_path,
        proposal_digest,
        approval,
    )

    with _ledger_lock(home):
        rows = _read_ledger(home)
        if any(row["proposalDigest"] == proposal_digest for row in rows):
            raise ObservationPrivacyError("one-shot export approval was already consumed")
        _append_ledger_locked(
            home,
            rows,
            {
                "proposalDigest": proposal_digest,
                "state": "reserved",
                "destinationSha256": proposal["destinationSha256"],
                "payloadSha256": _digest(payload),
                "approvalRequestSha256": _digest(approval["request_id"]),
            },
        )
    try:
        _atomic_private_write(destination, payload, replace=False)
    except (OSError, ObservationPrivacyError) as error:
        with _ledger_lock(home):
            rows = _read_ledger(home)
            _append_ledger_locked(
                home,
                rows,
                {
                    "proposalDigest": proposal_digest,
                    "state": "failed",
                    "destinationSha256": proposal["destinationSha256"],
                    "error": type(error).__name__,
                },
            )
        _remove_proposal_payload(home, proposal_digest)
        raise ObservationPrivacyError(f"export write failed after approval was consumed: {type(error).__name__}") from error
    with _ledger_lock(home):
        rows = _read_ledger(home)
        _append_ledger_locked(
            home,
            rows,
            {
                "proposalDigest": proposal_digest,
                "state": "completed",
                "destinationSha256": proposal["destinationSha256"],
                "payloadSha256": _digest(payload),
            },
        )
    proposal_cleanup = _remove_proposal_payload(home, proposal_digest)
    return {
        "schema": "sulde-observation-export-result-v1",
        "status": "completed",
        "proposalDigest": proposal_digest,
        "destination": str(destination),
        "bytes": len(payload),
        "payloadSha256": _digest(payload),
        "events": len(events),
        "networkTransmissionAuthorized": False,
        "proposalCleanup": proposal_cleanup,
    }
