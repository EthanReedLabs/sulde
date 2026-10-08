"""Persistence-backed dispatch-request identity for managed runs.

One dispatch request maps to one content digest forever, and its *completed*
attempt is final: resubmitting the same request id with the same content
after completion returns the original attempt/result — completion never
invalidates idempotency, and N submissions of one request produce exactly
one effective launch, whenever the duplicates arrive.

New executions are explicit new attempts with their own identity, linked to
what they retry:

- an active (non-closed) attempt is resumed, never re-dispatched;
- a closed attempt with a retryable stop reason is retried through
  :func:`open_retry`, which opens attempt N+1 and records the run id it
  retries;
- a closed attempt that completed successfully has no retry path — callers
  report the existing result.

The registry is an append-only, fsynced JSONL journal under the workspace
state directory; it never replaces the run ledger (which stays the only
execution fact authority — stop reasons, liveness, and recovery are read
from ledgers).  A same-request-id submission whose content digest differs is
a hard conflict, whether the bound attempt is active, terminal, or complete.
Request ids are scoped to one slug; sharing an id across slugs is a
conflict.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any


DISPATCH_REGISTRY_SCHEMA = "sulde-dispatch-registry-v2"
DISPATCH_ROW_TYPES = frozenset(
    {"dispatch.opened", "dispatch.launched", "dispatch.closed", "dispatch.retry"}
)
REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
RUN_ID_RE = re.compile(r"^run-[0-9a-f]{24}$")
CLOSE_OUTCOMES = frozenset({"terminal", "superseded"})
# awaiting_human is deliberately NOT auto-retried: a human gate must not be
# bypassed by an automatic relaunch (no blind retry of unresolved effects).
RETRYABLE_STOP_REASONS = frozenset(
    {"error", "aborted", "timeout", "policy_paused"}
)


class DispatchRegistryError(RuntimeError):
    """The dispatch registry cannot be read or appended safely."""


class DispatchConflictError(DispatchRegistryError):
    """The same request id was submitted with different content or slug."""


def derive_request_id(*parts: str) -> str:
    """Derive a deterministic request id from the request content."""
    joined = "\0".join(part.strip() for part in parts)
    return "req-" + hashlib.sha256(
        joined.encode("utf-8", errors="replace")
    ).hexdigest()[:24]


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _append_row(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = _canonical(row) + b"\n"
    descriptor = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        written = os.write(descriptor, encoded)
        if written != len(encoded):
            raise OSError("dispatch registry append was partial")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def read_registry(path: Path) -> list[dict[str, Any]]:
    """Read all registry rows; a torn or invalid journal fails closed."""
    if not path.is_file():
        return []
    try:
        payload = path.read_bytes()
        text = payload.decode("utf-8")
    except (OSError, UnicodeError) as error:
        raise DispatchRegistryError(
            f"dispatch registry cannot be read: {error}"
        ) from error
    if payload and not payload.endswith(b"\n"):
        raise DispatchRegistryError(
            "dispatch registry has an incomplete tail; preserve it for human recovery"
        )
    rows: list[dict[str, Any]] = []
    for line_number, raw in enumerate(text.splitlines(), 1):
        if not raw.strip():
            raise DispatchRegistryError(
                f"dispatch registry has a blank row at line {line_number}"
            )
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as error:
            raise DispatchRegistryError(
                f"dispatch registry has invalid JSON at line {line_number}: {error}"
            ) from error
        if not isinstance(value, dict) or value.get("schema") != DISPATCH_REGISTRY_SCHEMA:
            raise DispatchRegistryError(
                f"dispatch registry row {line_number} has an unsupported schema"
            )
        if value.get("type") not in DISPATCH_ROW_TYPES:
            raise DispatchRegistryError(
                f"dispatch registry row {line_number} has an unsupported type"
            )
        rows.append(value)
    return rows


def _project_attempts(
    rows: list[dict[str, Any]], request_id: str
) -> dict[int, dict[str, Any]]:
    """Project every attempt's state segment for one request."""
    attempts: dict[int, dict[str, Any]] = {}
    for row in rows:
        if row.get("request_id") != request_id:
            continue
        row_type = row["type"]
        if row_type == "dispatch.retry":
            # R3-04 retry-operation metadata: binds an op id to an attempt;
            # not part of the attempt-state chain itself.
            continue
        if row_type == "dispatch.opened":
            try:
                attempt = int(row.get("attempt"))
            except (TypeError, ValueError) as error:
                raise DispatchRegistryError(
                    "dispatch opened row has an invalid attempt number"
                ) from error
            if attempt in attempts:
                raise DispatchRegistryError(
                    "dispatch attempt numbers regress or repeat"
                )
            attempts[attempt] = {
                "request_id": request_id,
                "request_sha256": row.get("request_sha256"),
                "attempt": attempt,
                "retries_of_run_id": row.get("retries_of_run_id"),
                "state": "opened",
                "run_id": None,
                "stop_reason": None,
                "task_status": None,
                "task_returncode": None,
            }
        elif row_type in ("dispatch.launched", "dispatch.closed"):
            try:
                attempt = int(row.get("attempt"))
            except (TypeError, ValueError) as error:
                raise DispatchRegistryError(
                    "dispatch row has an invalid attempt number"
                ) from error
            segment = attempts.get(attempt)
            if segment is None:
                raise DispatchRegistryError(
                    f"dispatch {row_type} row has no matching open attempt"
                )
            if row_type == "dispatch.launched":
                if segment["state"] != "opened":
                    raise DispatchRegistryError(
                        "dispatch launched row is out of order"
                    )
                segment["state"] = "launched"
                segment["run_id"] = row.get("run_id")
            else:
                if segment["state"] == "closed":
                    continue  # duplicate close rows are idempotent no-ops
                segment["state"] = "closed"
                segment["outcome"] = row.get("outcome")
                segment["run_id"] = row.get("run_id")
                segment["stop_reason"] = row.get("stop_reason")
                segment["task_status"] = row.get("task_status")
                segment["task_returncode"] = row.get("task_returncode")
    return attempts


def _latest_segment(
    rows: list[dict[str, Any]], request_id: str
) -> dict[str, Any] | None:
    """Project the latest attempt (highest attempt number) for one request."""
    attempts = _project_attempts(rows, request_id)
    if not attempts:
        return None
    return attempts[max(attempts)]


def lookup(path: Path, request_id: str) -> dict[str, Any] | None:
    return _latest_segment(read_registry(path), request_id)


def lookup_retry_op(
    path: Path, retry_op_id: str, request_id: str
) -> dict[str, Any] | None:
    """Resolve one retry operation to its OWN bound attempt (R3 followup 1).

    The returned segment is the attempt the operation created — never the
    latest attempt of the chain — so a late or repeated retry-op submission
    replays its own conclusion even after newer attempts or retries exist.
    """
    rows = read_registry(path)
    registered = _retry_identity(rows, retry_op_id)
    if registered is None or registered.get("request_id") != request_id:
        return None
    attempts = _project_attempts(rows, request_id)
    to_attempt = int(registered["to_attempt"])
    segment = attempts.get(to_attempt)
    if segment is None:
        raise DispatchRegistryError(
            f"retry operation {retry_op_id!r} references a missing attempt"
        )
    return {
        "retry_op_id": retry_op_id,
        "from_run_id": registered.get("from_run_id"),
        "created": False,
        **segment,
    }


def _check_request(
    row_request_sha256: Any,
    row_slug: Any,
    *,
    request_sha256: str,
    slug: str,
) -> None:
    if row_request_sha256 != request_sha256:
        raise DispatchConflictError(
            "dispatch request id already bound to different content"
        )
    if row_slug != slug:
        raise DispatchConflictError(
            "dispatch request id is already bound to a different slug"
        )


def open_request(
    path: Path,
    *,
    request_id: str,
    request_sha256: str,
    slug: str,
) -> dict[str, Any]:
    """Bind one request id to its attempt, idempotently.

    Returns a projection with ``created`` True only when a brand-new attempt
    1 was opened.  An active attempt is returned for resumption; a closed
    attempt is returned as-is — the caller decides between reporting the
    original result and opening a linked retry via :func:`open_retry`.
    Raises DispatchConflictError when the id carries different content or a
    different slug.
    """
    if REQUEST_ID_RE.fullmatch(request_id) is None:
        raise DispatchRegistryError(f"dispatch request id is invalid: {request_id!r}")
    if (
        not isinstance(request_sha256, str)
        or re.fullmatch(r"[0-9a-f]{64}", request_sha256) is None
    ):
        raise DispatchRegistryError("dispatch request digest is not a sha256 digest")
    rows = read_registry(path)
    segment = _latest_segment(rows, request_id)
    if segment is not None:
        _check_request(
            segment.get("request_sha256"),
            next(
                (
                    row.get("slug")
                    for row in rows
                    if row.get("request_id") == request_id
                ),
                None,
            ),
            request_sha256=request_sha256,
            slug=slug,
        )
        if segment["state"] != "closed":
            return {**segment, "created": False}
        return {**segment, "created": False}
    _append_row(
        path,
        {
            "schema": DISPATCH_REGISTRY_SCHEMA,
            "at": datetime.now(timezone.utc).isoformat(),
            "type": "dispatch.opened",
            "request_id": request_id,
            "request_sha256": request_sha256,
            "slug": slug,
            "attempt": 1,
        },
    )
    return {
        "request_id": request_id,
        "request_sha256": request_sha256,
        "attempt": 1,
        "state": "opened",
        "run_id": None,
        "task_status": None,
        "task_returncode": None,
        "created": True,
    }


def _retry_identity(
    rows: list[dict[str, Any]], retry_op_id: str
) -> dict[str, Any] | None:
    for row in rows:
        if (
            row.get("type") == "dispatch.retry"
            and row.get("retry_op_id") == retry_op_id
        ):
            return row
    return None


def open_retry(
    path: Path,
    *,
    retry_op_id: str,
    request_id: str,
    request_sha256: str,
    slug: str,
    from_run_id: str,
) -> dict[str, Any]:
    """Register or resolve one STABLE retry-operation identity (R3-04).

    The first call binds ``retry_op_id`` to the current closed attempt
    (``from_run_id``) and opens the next attempt; every later call with the
    SAME identity resolves to that same attempt's segment — replaying its
    conclusion if closed, or resuming it if active — even when the retry
    itself failed, timed out, or newer attempts exist.  A genuinely new
    attempt requires a new retry operation identity.
    """
    if REQUEST_ID_RE.fullmatch(retry_op_id) is None:
        raise DispatchRegistryError(
            f"retry operation id is invalid: {retry_op_id!r}"
        )
    if RUN_ID_RE.fullmatch(from_run_id) is None:
        raise DispatchRegistryError(
            f"retry predecessor run id is invalid: {from_run_id!r}"
        )
    rows = read_registry(path)
    registered = _retry_identity(rows, retry_op_id)
    if registered is not None:
        if registered.get("request_sha256") != request_sha256:
            raise DispatchConflictError(
                "retry operation already registered with different content: "
                f"{retry_op_id}"
            )
        if registered.get("from_run_id") != from_run_id:
            raise DispatchConflictError(
                "retry operation already registered with a different "
                f"predecessor: {retry_op_id}"
            )
        to_attempt = int(registered["to_attempt"])
        attempts = _project_attempts(rows, request_id)
        segment = attempts.get(to_attempt)
        if segment is None:
            raise DispatchRegistryError(
                f"retry operation {retry_op_id!r} references a missing attempt"
            )
        return {**segment, "created": False, "retry_op_id": retry_op_id}
    segment = _latest_segment(rows, request_id)
    if segment is None:
        raise DispatchRegistryError(
            f"dispatch retry without an existing request: {request_id}"
        )
    _check_request(
        segment.get("request_sha256"),
        next(
            (
                row.get("slug")
                for row in rows
                if row.get("request_id") == request_id
            ),
            None,
        ),
        request_sha256=request_sha256,
        slug=slug,
    )
    if segment["state"] != "closed":
        raise DispatchRegistryError(
            f"dispatch retry requires a closed attempt: {request_id} is "
            f"{segment['state']}"
        )
    if segment.get("stop_reason") == "completed":
        raise DispatchRegistryError(
            "a completed request has no retry; report its existing result"
        )
    if segment["run_id"] != from_run_id:
        raise DispatchConflictError(
            "retry predecessor does not match the latest attempt: "
            f"{from_run_id!r} != {segment['run_id']!r}"
        )
    next_attempt = int(segment["attempt"]) + 1
    _append_row(
        path,
        {
            "schema": DISPATCH_REGISTRY_SCHEMA,
            "at": datetime.now(timezone.utc).isoformat(),
            "type": "dispatch.retry",
            "retry_op_id": retry_op_id,
            "request_id": request_id,
            "request_sha256": request_sha256,
            "from_attempt": int(segment["attempt"]),
            "from_run_id": from_run_id,
            "to_attempt": next_attempt,
        },
    )
    _append_row(
        path,
        {
            "schema": DISPATCH_REGISTRY_SCHEMA,
            "at": datetime.now(timezone.utc).isoformat(),
            "type": "dispatch.opened",
            "request_id": request_id,
            "request_sha256": request_sha256,
            "slug": slug,
            "attempt": next_attempt,
            "retries_of_run_id": from_run_id,
        },
    )
    return {
        "request_id": request_id,
        "request_sha256": request_sha256,
        "attempt": next_attempt,
        "state": "opened",
        "run_id": None,
        "task_status": None,
        "task_returncode": None,
        "retries_of_run_id": from_run_id,
        "created": True,
    }


def retryable(stop_reason: str | None) -> bool:
    """A closed attempt is retryable unless its run completed successfully."""
    return stop_reason in RETRYABLE_STOP_REASONS or stop_reason is None


def record_launched(
    path: Path,
    *,
    request_id: str,
    attempt: int,
    run_id: str,
) -> None:
    if RUN_ID_RE.fullmatch(run_id) is None:
        raise DispatchRegistryError(f"dispatch run id is invalid: {run_id!r}")
    rows = read_registry(path)
    segment = _latest_segment(rows, request_id)
    if segment is None or segment["attempt"] != attempt:
        raise DispatchRegistryError(
            f"dispatch launched without the open attempt: {request_id}#{attempt}"
        )
    if segment["state"] == "launched":
        if segment["run_id"] == run_id:
            return
        raise DispatchRegistryError(
            "dispatch attempt already launched a different run: "
            f"{request_id}#{attempt}: {segment['run_id']} != {run_id}"
        )
    if segment["state"] == "closed":
        raise DispatchRegistryError(
            f"dispatch launched a closed attempt: {request_id}#{attempt}"
        )
    _append_row(
        path,
        {
            "schema": DISPATCH_REGISTRY_SCHEMA,
            "at": datetime.now(timezone.utc).isoformat(),
            "type": "dispatch.launched",
            "request_id": request_id,
            "attempt": attempt,
            "run_id": run_id,
        },
    )


def record_closed(
    path: Path,
    *,
    request_id: str,
    attempt: int,
    run_id: str,
    outcome: str,
    stop_reason: str | None = None,
    task_status: str | None = None,
    returncode: int | None = None,
) -> None:
    if outcome not in CLOSE_OUTCOMES:
        raise DispatchRegistryError(f"unsupported close outcome: {outcome!r}")
    rows = read_registry(path)
    segment = _latest_segment(rows, request_id)
    if segment is None or segment["attempt"] != attempt or segment["state"] == "closed":
        return
    if segment["state"] == "launched" and segment["run_id"] != run_id:
        raise DispatchRegistryError(
            "dispatch close run id does not match the launched run: "
            f"{request_id}#{attempt}: {segment['run_id']} != {run_id}"
        )
    if stop_reason is not None and not isinstance(stop_reason, str):
        raise DispatchRegistryError("dispatch close stop reason must be a string")
    if task_status is not None and not isinstance(task_status, str):
        raise DispatchRegistryError("dispatch close task status must be a string")
    if returncode is not None and (
        isinstance(returncode, bool) or not isinstance(returncode, int)
    ):
        raise DispatchRegistryError("dispatch close returncode must be an int")
    row = {
        "schema": DISPATCH_REGISTRY_SCHEMA,
        "at": datetime.now(timezone.utc).isoformat(),
        "type": "dispatch.closed",
        "request_id": request_id,
        "attempt": attempt,
        "run_id": run_id,
        "outcome": outcome,
        "stop_reason": stop_reason,
    }
    # R2-01: the authoritative TASK conclusion (not the provider process exit
    # alone) travels with the close so a duplicate replays the original
    # verdict instead of recomputing success from returncode.
    if task_status is not None:
        row["task_status"] = task_status
    if returncode is not None:
        row["task_returncode"] = returncode
    _append_row(path, row)
