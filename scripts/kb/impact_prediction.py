#!/usr/bin/env python3
"""Versioned impact-prediction artifacts for predictive execution (B1).

A prediction is an append-only, versioned record of what an agent expects a
change to do BEFORE making it: assumptions with basis and confidence, the
semantically expected touch surface, invariants that must hold, new risks with
trigger conditions, alternatives considered, a minimal falsification probe and
a recovery path.  Predictions never overwrite older judgments: every revision
is a new appended event that must cite the new evidence and the reason for the
revision, so actual outcomes can never be retro-fitted into the original
estimate.

Identities (task/run/session/project) are stored as one-way SHA-256 digests
only.  Predictions are not authority: a scope deviation between prediction and
reality is a fact to record, not a violation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

EVENT_SCHEMA = "sulde-impact-prediction-event-v1"
PROJECTION_SCHEMA = "sulde-impact-prediction-projection-v1"

CONFIDENCE_LEVELS = ("high", "medium", "low")
CHECK_VERDICTS = ("as_predicted", "larger_than_predicted", "smaller_than_predicted", "divergent")
KINDS = ("full", "lightweight")
PREDICTION_STATUSES = ("open", "stale", "checked", "superseded", "closed")

DIGEST_FIELDS = ("task_id", "run_id", "session_id", "project_id")
_CONSECUTIVE = "sequence must be contiguous from 1"


def digest(value: Any) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def prediction_id(*, task_id: str, version: int, opened_at: str, sequence: int) -> str:
    raw = f"{digest(task_id)}\0{version}\0{opened_at}\0{sequence}"
    return "pred-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _digest_identities(payload: dict[str, Any]) -> dict[str, str]:
    identities = {}
    for field in DIGEST_FIELDS:
        raw = str(payload.get(field) or "").strip()
        if not raw:
            raise PredictionError(f"{field} must be a non-empty string")
        identities[f"{field}_sha256"] = digest(raw)
    return identities


class PredictionError(ValueError):
    """Raised for malformed or contradictory prediction store operations."""


def _fsync_write(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _read_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as error:
            raise PredictionError(f"corrupt prediction store {path}: {error}") from error
    for position, row in enumerate(rows, 1):
        if row.get("sequence") != position:
            raise PredictionError(_CONSECUTIVE)
    return rows


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise PredictionError(message)


def _require_text_list(payload: dict[str, Any], field: str, *, minimum: int = 0) -> list[str]:
    value = payload.get(field)
    if value is None:
        _require(minimum == 0, f"{field} needs at least {minimum} item(s)")
        return []
    _require(isinstance(value, list) and all(isinstance(item, str) and item.strip() for item in value),
             f"{field} must be an array of non-empty strings")
    _require(len(value) >= minimum, f"{field} needs at least {minimum} item(s)")
    return [item.strip() for item in value]


def _normalize_opened(payload: dict[str, Any], sequence: int, at: str) -> dict[str, Any]:
    kind = payload.get("kind", "full")
    _require(kind in KINDS, f"kind must be one of {KINDS}")
    identities = _digest_identities(payload)
    contract_version = str(payload.get("contract_version") or "").strip()
    _require(bool(contract_version), "contract_version must be a non-empty string")
    source_identities = payload.get("source_identities")
    _require(isinstance(source_identities, dict), "source_identities must be an object")
    for key, value in source_identities.items():
        _require(isinstance(key, str) and key and isinstance(value, str) and len(value) >= 8,
                 f"source identity {key!r} must map to a content digest")
    assumptions = payload.get("assumptions")
    _require(isinstance(assumptions, list) and assumptions, "assumptions must be a non-empty array")
    for item in assumptions:
        _require(isinstance(item, dict), "each assumption must be an object")
        _require(isinstance(item.get("text"), str) and item["text"].strip(), "assumption text required")
        _require(item.get("confidence") in CONFIDENCE_LEVELS,
                 f"assumption confidence must be one of {CONFIDENCE_LEVELS}")
    impact_bounds = payload.get("impact_bounds")
    _require(isinstance(impact_bounds, dict), "impact_bounds must be an object with lower/upper/unknown")
    for bound in ("lower", "upper", "unknown"):
        _require(isinstance(impact_bounds.get(bound), str) and impact_bounds[bound].strip(),
                 f"impact_bounds.{bound} must be a non-empty semantic statement")
    falsification_probe = str(payload.get("falsification_probe") or "").strip()
    recovery_path = str(payload.get("recovery_path") or "").strip()
    if kind == "full":
        _require(bool(falsification_probe), "full predictions need a falsification_probe")
        _require(bool(recovery_path), "full predictions need a recovery_path")
    return {
        "schema": EVENT_SCHEMA,
        "type": "prediction.opened",
        "sequence": sequence,
        "at": at,
        "prediction_id": payload.get("prediction_id"),
        "kind": kind,
        "task_id_sha256": identities["task_id_sha256"],
        "run_id_sha256": identities["run_id_sha256"],
        "session_id_sha256": identities["session_id_sha256"],
        "project_id_sha256": identities["project_id_sha256"],
        "contract_version": contract_version,
        "source_identities": source_identities,
        "objective": str(payload.get("objective") or "").strip(),
        "assumptions": assumptions,
        "unknowns": _require_text_list(payload, "unknowns"),
        "expected_touch": payload.get("expected_touch") if isinstance(payload.get("expected_touch"), dict) else {},
        "invariants": _require_text_list(payload, "invariants"),
        "new_risks": payload.get("new_risks") if isinstance(payload.get("new_risks"), list) else [],
        "alternatives": payload.get("alternatives") if isinstance(payload.get("alternatives"), list) else [],
        "falsification_probe": falsification_probe,
        "recovery_path": recovery_path,
        "impact_bounds": impact_bounds,
        "based_on_experience": _require_text_list(payload, "based_on_experience"),
    }


def open_prediction(store_path: Path, payload: dict[str, Any], *, at: str, task_id: str) -> dict[str, Any]:
    """Append the version-1 prediction.  Fails if the task already has an open thread."""
    rows = _read_rows(store_path)
    sequence = len(rows) + 1
    opened_at = at
    normalized = _normalize_opened(payload, sequence, opened_at)
    normalized["prediction_id"] = prediction_id(task_id=task_id, version=1, opened_at=opened_at, sequence=sequence)
    normalized["version"] = 1
    normalized["supersedes"] = None
    normalized["status"] = "open"
    for row in rows:
        if row.get("type") == "prediction.opened" and row.get("task_id_sha256") == normalized["task_id_sha256"]:
            projection = load_projection(store_path)
            entry = projection["tasks"].get(normalized["task_id_sha256"])
            current = (entry or {}).get("current")
            if current and current.get("status") in {"open", "stale"}:
                raise PredictionError(
                    "task already has an open prediction thread; use revise_prediction or close_prediction"
                )
    _fsync_write(store_path, normalized)
    return normalized


def _thread_state(store_path: Path, task_digest: str) -> tuple[dict[str, Any] | None, str | None]:
    """Authoritative replay: the single source every mutation entry consumes."""
    entry = load_projection(store_path)["tasks"].get(task_digest)
    if entry is None or entry.get("current") is None:
        return None, None
    return entry["current"], entry.get("closed_outcome")


def latest_version(rows: list[dict[str, Any]], task_id_sha256: str) -> dict[str, Any] | None:
    latest = None
    for row in rows:
        if row.get("task_id_sha256") != task_id_sha256:
            continue
        if row.get("type") == "prediction.opened":
            latest = row
        elif row.get("type") == "prediction.revised" and latest is not None:
            latest = {**latest, **{k: v for k, v in row.items() if k not in {"schema", "type", "sequence", "at"}}}
    return latest


def revise_prediction(store_path: Path, payload: dict[str, Any], *, at: str, task_id: str) -> dict[str, Any]:
    """Append a new version.  The prior version stays untouched in the ledger."""
    rows = _read_rows(store_path)
    task_digest = digest(task_id)
    prior, closed_outcome = _thread_state(store_path, task_digest)
    _require(prior is not None, "no prediction thread for this task; open one first")
    if prior.get("status") == "closed":
        raise PredictionError(
            f"prediction thread is closed ({closed_outcome}); start an explicit new "
            "thread with open_prediction instead of revising a settled judgment"
        )
    _require(prior.get("status") in {"open", "stale"}, f"cannot revise a {prior.get('status')} prediction")
    new_evidence = _require_text_list(payload, "new_evidence", minimum=1)
    revision_reason = str(payload.get("revision_reason") or "").strip()
    _require(bool(revision_reason), "revision_reason is required; revisions never overwrite older judgments")
    sequence = len(rows) + 1
    prior_version = int(prior.get("version") or 1)
    revised = {
        **prior,
        "schema": EVENT_SCHEMA,
        "type": "prediction.revised",
        "sequence": sequence,
        "at": at,
        "version": prior_version + 1,
        "supersedes": prior.get("prediction_id"),
        "supersedes_version": prior_version,
        "revision_reason": revision_reason,
        "new_evidence": new_evidence,
        "status": "open",
        "prediction_id": prediction_id(task_id=task_id, version=prior_version + 1, opened_at=at, sequence=sequence),
    }
    for field in ("assumptions", "expected_touch", "invariants", "new_risks",
                  "impact_bounds", "falsification_probe", "recovery_path", "source_identities", "unknowns"):
        if payload.get(field) is not None:
            revised[field] = payload[field]
    _fsync_write(store_path, revised)
    return revised


def mark_stale(store_path: Path, *, task_id: str, input_changed: dict[str, Any], at: str) -> dict[str, Any]:
    """Mechanically mark the open prediction stale when bound input identities change."""
    rows = _read_rows(store_path)
    task_digest = digest(task_id)
    prior, _closed = _thread_state(store_path, task_digest)
    _require(prior is not None, "no prediction thread for this task")
    _require(prior.get("status") == "open", f"cannot stale a {prior.get('status')} prediction")
    _require(isinstance(input_changed, dict) and input_changed, "input_changed must be a non-empty object")
    row = {
        "schema": EVENT_SCHEMA,
        "type": "prediction.staled",
        "sequence": len(rows) + 1,
        "at": at,
        "prediction_id": prior.get("prediction_id"),
        "task_id_sha256": task_digest,
        "input_changed": input_changed,
    }
    _fsync_write(store_path, row)
    return row


def record_check(store_path: Path, payload: dict[str, Any], *, at: str, task_id: str) -> dict[str, Any]:
    """Record an incremental fact check: actual versus predicted, with evidence."""
    rows = _read_rows(store_path)
    task_digest = digest(task_id)
    prior, _closed = _thread_state(store_path, task_digest)
    _require(prior is not None, "no prediction thread for this task")
    _require(prior.get("status") != "closed", "cannot check a closed prediction thread")
    verdict = payload.get("verdict")
    _require(verdict in CHECK_VERDICTS, f"verdict must be one of {CHECK_VERDICTS}")
    facts = _require_text_list(payload, "facts", minimum=1)
    evidence = payload.get("evidence")
    _require(isinstance(evidence, list) and all(isinstance(item, str) and item.strip() for item in evidence),
             "evidence must be an array of non-empty strings")
    row = {
        "schema": EVENT_SCHEMA,
        "type": "prediction.checked",
        "sequence": len(rows) + 1,
        "at": at,
        "prediction_id": prior.get("prediction_id"),
        "prediction_version": prior.get("version"),
        "task_id_sha256": task_digest,
        "verdict": verdict,
        "facts": facts,
        "evidence": evidence,
        "next_action": str(payload.get("next_action") or "").strip(),
    }
    _fsync_write(store_path, row)
    return row


def rebind_attempt(store_path: Path, *, task_id: str, session_id: str,
                   contract_version: str, reason: str, at: str,
                   run_id: str = "") -> dict[str, Any]:
    """Explicitly associate the open prediction with a NEW attempt.

    R2-03: continuations never reuse the old run/session identity and never
    inherit authority — the rebind updates the session binding and records
    who/why.  R3-closeout 一: ``contract_version`` is recorded as the
    ATTEMPT's contract (``attempt_contract_version``) and never overwrites
    the prediction's bound ``contract_version`` — a contract change is a
    fact for the feedback-matching rule to judge, not something a rebind
    blesses silently.  Called at prompt-composition time (run id not yet
    known); call ``confirm_attempt_run`` after spawn to bind the run digest.
    Closed threads cannot be rebound.
    """
    rows = _read_rows(store_path)
    task_digest = digest(task_id)
    prior, _closed = _thread_state(store_path, task_digest)
    _require(prior is not None, "no prediction thread for this task")
    _require(prior.get("status") != "closed", "cannot rebind a closed prediction thread")
    clean_reason = str(reason or "").strip()
    _require(bool(clean_reason), "rebind requires a reason")
    _require(contract_version.strip() != "", "rebind requires the current contract version")
    row = {
        "schema": EVENT_SCHEMA,
        "type": "prediction.rebound",
        "sequence": len(rows) + 1,
        "at": at,
        "prediction_id": prior.get("prediction_id"),
        "task_id_sha256": task_digest,
        "session_id_sha256": digest(session_id),
        "attempt_contract_version": contract_version,
        "run_id_sha256": digest(run_id) if run_id else "pending",
        "reason": clean_reason,
    }
    _fsync_write(store_path, row)
    return row


def confirm_attempt_run(store_path: Path, *, task_id: str, run_id: str,
                        at: str) -> dict[str, Any]:
    """Bind the actual spawned run id to the rebound prediction thread."""
    rows = _read_rows(store_path)
    task_digest = digest(task_id)
    # R3-closeout D4: 无预测线程的任务零写入 —— 不为确认事件创建账本文件。
    if not any(row.get("task_id_sha256") == task_digest for row in rows):
        raise PredictionError("no prediction thread for this task")
    row = {
        "schema": EVENT_SCHEMA,
        "type": "prediction.attempt_started",
        "sequence": len(rows) + 1,
        "at": at,
        "task_id_sha256": task_digest,
        "run_id_sha256": digest(run_id),
    }
    _fsync_write(store_path, row)
    return row


def close_prediction(store_path: Path, *, task_id: str, outcome: str, at: str) -> dict[str, Any]:
    rows = _read_rows(store_path)
    task_digest = digest(task_id)
    prior, _closed = _thread_state(store_path, task_digest)
    _require(prior is not None, "no prediction thread for this task")
    _require(prior.get("status") != "closed", "prediction thread is already closed")
    _require(outcome in {"resolved", "abandoned"}, "outcome must be resolved or abandoned")
    row = {
        "schema": EVENT_SCHEMA,
        "type": "prediction.closed",
        "sequence": len(rows) + 1,
        "at": at,
        "prediction_id": prior.get("prediction_id"),
        "task_id_sha256": task_digest,
        "outcome": outcome,
    }
    _fsync_write(store_path, row)
    return row


def load_projection(store_path: Path) -> dict[str, Any]:
    """Replay the ledger into per-task projections (current + full history)."""
    rows = _read_rows(store_path)
    tasks: dict[str, dict[str, Any]] = {}
    for row in rows:
        task_digest = row.get("task_id_sha256")
        entry = tasks.setdefault(task_digest, {
            "schema": PROJECTION_SCHEMA,
            "task_id_sha256": task_digest,
            "versions": [],
            "checks": [],
            "stales": [],
            "current": None,
            "closed_outcome": None,
        })
        if row["type"] in {"prediction.opened", "prediction.revised"}:
            entry["versions"].append(row)
            entry["current"] = row
            if row["type"] == "prediction.revised":
                entry["current"]["status"] = "open"
        elif row["type"] == "prediction.staled":
            entry["stales"].append(row)
            if entry["current"] is not None:
                entry["current"] = {**entry["current"], "status": "stale"}
        elif row["type"] == "prediction.rebound":
            if entry["current"] is not None:
                updates = {
                    "session_id_sha256": row["session_id_sha256"],
                    "attempt_contract_version": row.get("attempt_contract_version"),
                }
                if row.get("run_id_sha256") and row["run_id_sha256"] != "pending":
                    updates["run_id_sha256"] = row["run_id_sha256"]
                entry["current"] = {**entry["current"], **updates}
                entry.setdefault("rebinds", []).append(row)
        elif row["type"] == "prediction.attempt_started":
            if entry["current"] is not None:
                entry["current"] = {
                    **entry["current"],
                    "run_id_sha256": row["run_id_sha256"],
                }
                entry.setdefault("attempt_starts", []).append(row)
        elif row["type"] == "prediction.checked":
            entry["checks"].append(row)
        elif row["type"] == "prediction.closed":
            entry["closed_outcome"] = row.get("outcome")
            if entry["current"] is not None:
                entry["current"] = {**entry["current"], "status": "closed"}
    return {"schema": PROJECTION_SCHEMA, "tasks": tasks}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("open", "revise", "stale", "check", "close", "show"))
    parser.add_argument("--store", type=Path, required=True)
    parser.add_argument("--task-id", default="")
    parser.add_argument("--payload", type=Path, default=None, help="JSON payload file; '-' for stdin")
    args = parser.parse_args(argv)

    from datetime import datetime, timezone
    at = datetime.now(timezone.utc).isoformat()

    if args.action == "show":
        print(json.dumps(load_projection(args.store), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    _require(bool(args.task_id), "--task-id is required for this action")
    raw = (sys.stdin.read() if args.payload in (None, Path("-")) else args.payload.read_text(encoding="utf-8"))
    payload = json.loads(raw or "{}")
    if args.action == "open":
        row = open_prediction(args.store, payload, at=at, task_id=args.task_id)
    elif args.action == "revise":
        row = revise_prediction(args.store, payload, at=at, task_id=args.task_id)
    elif args.action == "stale":
        row = mark_stale(args.store, task_id=args.task_id, input_changed=payload.get("input_changed") or {}, at=at)
    elif args.action == "check":
        row = record_check(args.store, payload, at=at, task_id=args.task_id)
    else:
        row = close_prediction(args.store, task_id=args.task_id, outcome=payload.get("outcome", "resolved"), at=at)
    print(json.dumps(row, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
