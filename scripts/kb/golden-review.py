#!/usr/bin/env python3
"""Apply explicit human decisions to memory golden candidates.

The reviewer consumes ``$SULDE_KB_HOME/golden-candidates.jsonl`` and promotes
accepted cases into the repository golden suite.  It never judges candidates
itself: a human-authored decision file is required, and writes require
``--apply``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_GOLDEN = REPO_ROOT / "tools" / "kb-index" / "golden-mem.jsonl"
ASSERTIONS = {"expect_substring", "expect_none", "forbid_project"}


class ReviewError(RuntimeError):
    """A validation or write failure that leaves the review unapplied."""


def kb_home() -> Path:
    configured = os.environ.get("SULDE_KB_HOME")
    return Path(configured).expanduser() if configured else Path.home() / ".sulde/data/kb"


def load_jsonl(path: Path, *, allow_missing: bool = False) -> list[dict[str, Any]]:
    if allow_missing and not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as error:
        raise ReviewError(f"cannot read {path}: {error}") from error
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as error:
            raise ReviewError(f"{path}:{number}: invalid JSON: {error}") from error
        if not isinstance(row, dict):
            raise ReviewError(f"{path}:{number}: row must be an object")
        rows.append(row)
    return rows


def validate_case(case: dict[str, Any], label: str) -> None:
    for field in ("id", "query", "project", "note"):
        if not isinstance(case.get(field), str) or not case[field].strip():
            raise ReviewError(f"{label}: {field} must be a non-empty string")
    assertions = ASSERTIONS.intersection(case)
    if len(assertions) != 1:
        raise ReviewError(f"{label}: exactly one recall assertion is required")
    assertion = next(iter(assertions))
    if assertion == "expect_none":
        if case[assertion] is not True:
            raise ReviewError(f"{label}: expect_none must be true")
    elif not isinstance(case[assertion], str) or not case[assertion].strip():
        raise ReviewError(f"{label}: {assertion} must be a non-empty string")


def invalid_case_ids(rows: list[dict[str, Any]]) -> list[str]:
    invalid: list[str] = []
    for number, row in enumerate(rows, 1):
        try:
            validate_case(row, f"candidate {number}")
        except ReviewError:
            identifier = row.get("id")
            invalid.append(str(identifier) if identifier else f"line:{number}")
    return invalid


def index_unique(rows: list[dict[str, Any]], label: str) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for number, row in enumerate(rows, 1):
        identifier = row.get("id")
        if not isinstance(identifier, str) or not identifier:
            raise ReviewError(f"{label}:{number}: id must be a non-empty string")
        if identifier in indexed:
            raise ReviewError(f"{label}: duplicate id {identifier}")
        indexed[identifier] = row
    return indexed


CANDIDATE_SCHEMA = "sulde-golden-candidate-v2"
REVIEW_SCHEMA = "sulde-golden-review-v2"
CANDIDATE_FIELDS = {"schema", "stage", "id", "query", "project", "note"} | ASSERTIONS
REVIEW_ACTIONS = {"accept", "reject", "ready", "revise"}


def candidate_stage(row: dict[str, Any]) -> str:
    schema = row.get("schema")
    if not isinstance(schema, (str, type(None))) or schema not in (None, "sulde-golden-candidate-v1", CANDIDATE_SCHEMA):
        raise ReviewError("unknown golden candidate schema")
    if schema == CANDIDATE_SCHEMA:
        if set(row) - CANDIDATE_FIELDS or not {"schema", "stage"}.issubset(row):
            raise ReviewError("current candidate schema drift")
        if not isinstance(row["stage"], str) or row["stage"] not in {"generated", "pending_review", "revision_required"}:
            raise ReviewError("current candidate stage requires a human review event")
        validate_case(row, str(row.get("id")))
        return row["stage"]
    # Legacy incomplete cases stay visible as revision work, never promotable.
    try:
        validate_case(row, str(row.get("id")))
    except ReviewError:
        return "revision_required"
    if row.get("stage") not in (None, "pending_review"):
        return "revision_required"
    return "pending_review"


def stage_accounting(candidates: list[dict[str, Any]],
                     reviews: list[dict[str, Any]]) -> dict[str, Any]:
    indexed = index_unique(candidates, "candidates")
    stages = {identifier: candidate_stage(row) for identifier, row in indexed.items()}
    actions: dict[str, str] = {}
    events: dict[str, dict[str, Any]] = {}
    decision_rows = 0
    for event in reviews:
        schema = event.get("schema")
        if not isinstance(schema, (str, type(None))) or schema not in (None, "sulde-golden-review-v1", REVIEW_SCHEMA):
            raise ReviewError("unknown golden review schema")
        required = {"event_id", "reviewed_at", "decisions", "remaining"}
        if not required.issubset(event) or set(event) - (required | {"schema"}):
            raise ReviewError("review event schema drift")
        if (not isinstance(event["event_id"], str) or not event["event_id"]
                or not isinstance(event["reviewed_at"], str)
                or type(event["remaining"]) is not int or event["remaining"] < 0
                or not isinstance(event["decisions"], list) or not event["decisions"]):
            raise ReviewError("malformed review event")
        try:
            timestamp = datetime.fromisoformat(event["reviewed_at"].replace("Z", "+00:00"))
            if timestamp.tzinfo is None:
                raise ValueError("missing timezone")
        except ValueError as error:
            raise ReviewError("invalid review timestamp") from error
        event_id = event["event_id"]
        if event_id in events:
            if events[event_id] != event:
                raise ReviewError("conflicting review event replay")
            continue
        events[event_id] = event
        seen = set()
        for decision in event["decisions"]:
            if (not isinstance(decision, dict) or set(decision) != {"id", "action", "reason"}
                    or not isinstance(decision["id"], str) or not decision["id"]
                    or not isinstance(decision["reason"], str) or not decision["reason"].strip()
                    or not isinstance(decision["action"], str) or decision["action"] not in REVIEW_ACTIONS
                    or decision["id"] in seen):
                raise ReviewError("malformed review decision")
            identifier, action = decision["id"], decision["action"]
            seen.add(identifier)
            decision_rows += 1
            old = actions.get(identifier)
            if old in {"accept", "reject"} and action != old:
                raise ReviewError("conflicting terminal review decision")
            actions[identifier] = action
    for identifier, action in actions.items():
        if action in {"ready", "revise"} and identifier not in indexed:
            raise ReviewError("nonterminal review has no candidate")
        if action == "ready":
            reviewed_case(indexed[identifier], {"reason": "stage validation"})
        stages[identifier] = {"accept": "accepted", "reject": "rejected",
                              "ready": "ready", "revise": "revision_required"}[action]
    counts = {stage: sum(value == stage for value in stages.values())
              for stage in ("generated", "pending_review", "revision_required", "ready", "accepted", "rejected")}
    return {"schema": "sulde-golden-stage-counts-v1",
            "raw_total": len(candidates), "raw_review_total": len(reviews),
            "generated": len(stages), "generated_unsubmitted": counts["generated"],
            "pending": counts["pending_review"], "pending_review": counts["pending_review"],
            "revision_required": counts["revision_required"], "ready_promotable": counts["ready"],
            "terminal_decisions": counts["accepted"] + counts["rejected"],
            "accepted": counts["accepted"], "rejected": counts["rejected"],
            "review_decision_rows": decision_rows, "stages_by_id": stages}


def load_decisions(path: Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ReviewError(f"cannot read decisions {path}: {error}") from error
    if not isinstance(payload, list) or not payload:
        raise ReviewError("decisions must be a non-empty JSON array")
    decisions: list[dict[str, Any]] = []
    seen: set[str] = set()
    for number, decision in enumerate(payload, 1):
        if not isinstance(decision, dict):
            raise ReviewError(f"decision {number}: must be an object")
        unknown = set(decision) - {"id", "action", "reason", "case"}
        if unknown:
            raise ReviewError(f"decision {number}: unknown fields: {', '.join(sorted(unknown))}")
        identifier = decision.get("id")
        action = decision.get("action")
        reason = decision.get("reason")
        if not isinstance(identifier, str) or not identifier:
            raise ReviewError(f"decision {number}: id must be a non-empty string")
        if identifier in seen:
            raise ReviewError(f"decisions contain duplicate id {identifier}")
        if not isinstance(action, str) or action not in REVIEW_ACTIONS:
            raise ReviewError(f"decision {number}: action must be accept, reject, ready, or revise")
        if not isinstance(reason, str) or not reason.strip():
            raise ReviewError(f"decision {number}: reason must be a non-empty string")
        if action in {"reject", "revise"} and "case" in decision:
            raise ReviewError(f"decision {number}: rejected case cannot contain an override")
        if "case" in decision and not isinstance(decision["case"], dict):
            raise ReviewError(f"decision {number}: case must be an object")
        seen.add(identifier)
        decisions.append(decision)
    return decisions


def reviewed_case(candidate: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    if (
        "case" not in decision
        and "接受前需人工确认完整性" in str(candidate.get("note") or "")
    ):
        raise ReviewError(
            f"{candidate.get('id')}: acceptance requires a complete case override"
        )
    result = dict(decision.get("case", candidate))
    if result.get("schema") is not None:
        candidate_stage(result)
    result.pop("schema", None)
    result.pop("stage", None)
    if result.get("id") != candidate.get("id"):
        raise ReviewError(f"{candidate.get('id')}: case override cannot change id")
    validate_case(result, str(candidate.get("id")))
    reason = " ".join(str(decision["reason"]).split())
    result["note"] = f"{result['note'].rstrip()}; 人工复核={reason}"
    return result


def plan_review(
    candidates: list[dict[str, Any]],
    golden: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    candidate_by_id = index_unique(candidates, "candidates")
    for candidate in candidates:
        candidate_stage(candidate)
    golden_by_id = index_unique(golden, "golden")
    accepted: list[str] = []
    rejected: list[str] = []
    replayed: list[str] = []
    decided: set[str] = set()
    additions: list[dict[str, Any]] = []
    for decision in decisions:
        identifier = decision["id"]
        candidate = candidate_by_id.get(identifier)
        if candidate is None:
            raise ReviewError(f"unknown candidate id {identifier}")
        if decision["action"] == "revise":
            continue
        if decision["action"] == "ready":
            candidate_by_id[identifier] = reviewed_case(candidate, decision)
            continue
        decided.add(identifier)
        if decision["action"] == "reject":
            rejected.append(identifier)
            continue
        promoted = reviewed_case(candidate, decision)
        existing = golden_by_id.get(identifier)
        if existing is not None:
            # A prior run may have written the golden suite but failed before
            # removing the candidate.  Matching content makes the retry safe.
            if existing != promoted:
                raise ReviewError(f"golden id collision with different content: {identifier}")
            replayed.append(identifier)
        else:
            additions.append(promoted)
            golden_by_id[identifier] = promoted
        accepted.append(identifier)
    remaining = [candidate_by_id[row["id"]] for row in candidates if row["id"] not in decided]
    updated_golden = golden + additions
    summary = {
        "accepted": accepted,
        "rejected": rejected,
        "replayed": replayed,
        "remaining": len(remaining),
        "invalid": invalid_case_ids(remaining),
        "golden_total": len(updated_golden),
    }
    return remaining, updated_golden, summary


def atomic_write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def review_event(decisions: list[dict[str, Any]], summary: dict[str, Any]) -> dict[str, Any]:
    material = json.dumps(decisions, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    event_id = hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]
    return {
        "schema": REVIEW_SCHEMA,
        "event_id": event_id,
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "decisions": [
            {"id": row["id"], "action": row["action"], "reason": row["reason"]}
            for row in decisions
        ],
        "remaining": summary["remaining"],
    }


def append_audit(path: Path, decisions: list[dict[str, Any]], summary: dict[str, Any]) -> None:
    rows = load_jsonl(path, allow_missing=True)
    event = review_event(decisions, summary)
    if any(row.get("event_id") == event["event_id"] for row in rows):
        return
    atomic_write_jsonl(path, rows + [event])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", type=Path)
    parser.add_argument("--golden", type=Path, default=DEFAULT_GOLDEN)
    parser.add_argument("--decisions", type=Path, help="human-authored JSON decision array")
    parser.add_argument("--apply", action="store_true", help="apply validated decisions; otherwise preview only")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.apply and args.decisions is None:
        parser.error("--apply requires --decisions")
    return args


def main() -> int:
    args = parse_args()
    candidate_path = args.candidates or kb_home() / "golden-candidates.jsonl"
    audit_path = kb_home() / "golden-review-decisions.jsonl"
    try:
        candidates = load_jsonl(candidate_path)
        golden = load_jsonl(args.golden, allow_missing=True)
        accounting = stage_accounting(candidates, load_jsonl(audit_path, allow_missing=True))
        if args.decisions is None:
            result = {
                "status": "ready",
                **accounting,
                "invalid": invalid_case_ids(candidates),
                "writes": 0,
            }
        else:
            decisions = load_decisions(args.decisions)
            remaining, updated_golden, summary = plan_review(candidates, golden, decisions)
            audit = load_jsonl(audit_path, allow_missing=True)
            event = review_event(decisions, summary)
            prospective = audit if any(row["event_id"] == event["event_id"] for row in audit) else audit + [event]
            projected = stage_accounting(remaining, prospective)
            result = {"status": "ready", **summary, "stage_accounting": projected, "writes": 1 if args.apply else 0}
            if args.apply:
                # Golden first makes an interrupted run safely replayable.  The
                # candidate queue remains the source of truth until promotion
                # has durably succeeded.
                atomic_write_jsonl(args.golden, updated_golden)
                append_audit(audit_path, decisions, summary)
                atomic_write_jsonl(candidate_path, remaining)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        else:
            print(
                f"GOLDEN REVIEW: READY pending={result.get('remaining', result.get('pending'))} "
                f"accepted={len(result.get('accepted', []))} rejected={len(result.get('rejected', []))} "
                f"writes={result['writes']}"
            )
        return 0
    except (ReviewError, OSError, UnicodeError) as error:
        print(f"GOLDEN REVIEW: FAIL {error}", file=os.sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
