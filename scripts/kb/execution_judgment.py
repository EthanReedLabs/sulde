#!/usr/bin/env python3
"""Agent judgment records at frozen re-judgment trigger nodes (B2).

A judgment is the agent's bounded output at a trigger node: key facts,
assumption changes, risks/counterexamples, next action and evidence refs.
Triggers are frozen in B0 and validated here; budgets (<=2k chars per text
field, frozen trigger set) are enforced mechanically so the ledger itself
proves the overhead contract.  Judgments are append-only and reference the
prediction version they judged.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

JUDGMENT_SCHEMA = "sulde-execution-judgment-v1"

# Frozen in docs/predictive-execution/B0.md; do not extend without a budget
# revision authorized by the coordinator.
FROZEN_TRIGGERS = (
    "before_public_interface_change",
    "after_logical_change_complete",
    "new_dependency_discovered",
    "verification_contradicts_prediction",
    "before_expensive_operation",
)
MAX_FIELD_CHARS = 2000
MAX_LIST_ITEMS = 20


class JudgmentError(ValueError):
    pass


def digest(value: Any) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def _bounded_text(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise JudgmentError(f"{field} must be a non-empty string")
    if len(text) > MAX_FIELD_CHARS:
        raise JudgmentError(f"{field} exceeds the {MAX_FIELD_CHARS}-char frozen budget")
    return text


def _bounded_list(value: Any, field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > MAX_LIST_ITEMS:
        raise JudgmentError(f"{field} must be an array of at most {MAX_LIST_ITEMS} strings")
    return [_bounded_text(item, field) for item in value]


def record_judgment(store_path: Path, payload: dict[str, Any], *, at: str) -> dict[str, Any]:
    trigger = str(payload.get("trigger") or "")
    if trigger not in FROZEN_TRIGGERS:
        raise JudgmentError(f"trigger must be one of the frozen nodes: {FROZEN_TRIGGERS}")
    for field in DIGEST_FIELDS:
        raw = str(payload.get(field) or "").strip()
        if not raw:
            raise JudgmentError(f"{field} must be a non-empty string")
    rows = _read_rows(store_path)
    row = {
        "schema": JUDGMENT_SCHEMA,
        "sequence": len(rows) + 1,
        "at": at,
        "trigger": trigger,
        "task_id_sha256": digest(payload["task_id"]),
        "run_id_sha256": digest(payload["run_id"]),
        "session_id_sha256": digest(payload["session_id"]),
        "prediction_id": str(payload.get("prediction_id") or ""),
        "prediction_version": payload.get("prediction_version"),
        "key_facts": _bounded_list(payload.get("key_facts"), "key_facts"),
        "assumption_changes": _bounded_list(payload.get("assumption_changes"), "assumption_changes"),
        "risks": _bounded_list(payload.get("risks"), "risks"),
        "next_action": _bounded_text(payload.get("next_action"), "next_action"),
        "evidence_refs": _bounded_list(payload.get("evidence_refs"), "evidence_refs"),
        "model_review_used": bool(payload.get("model_review_used", False)),
    }
    _fsync_write(store_path, row)
    return row


DIGEST_FIELDS = ("task_id", "run_id", "session_id")


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
            raise JudgmentError(f"corrupt judgment store {path}: {error}") from error
    for position, row in enumerate(rows, 1):
        if row.get("sequence") != position:
            raise JudgmentError("sequence must be contiguous from 1")
    return rows


def _fsync_write(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def load_judgments(store_path: Path, *, task_id: str | None = None) -> list[dict[str, Any]]:
    rows = _read_rows(store_path)
    if task_id:
        wanted = digest(task_id)
        rows = [row for row in rows if row.get("task_id_sha256") == wanted]
    return rows


def main(argv: list[str] | None = None) -> int:
    import argparse
    from datetime import datetime, timezone
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("record", "list"))
    parser.add_argument("--store", type=Path, required=True)
    parser.add_argument("--task-id", default="")
    parser.add_argument("--payload", type=Path, default=None)
    args = parser.parse_args(argv)
    if args.action == "list":
        print(json.dumps(load_judgments(args.store, task_id=args.task_id or None),
                         ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    raw = (args.payload.read_text(encoding="utf-8") if args.payload
           else sys.stdin.read())
    payload = json.loads(raw or "{}")
    at = datetime.now(timezone.utc).isoformat()
    row = record_judgment(args.store, payload, at=at)
    print(json.dumps(row, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    main()
