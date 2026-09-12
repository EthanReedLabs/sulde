#!/usr/bin/env python3
"""Record explicit human decisions for pending governance proposals.

This consumer changes only the L2 registry.  Accepting a proposal records the
decision; it does not edit thresholds or implement the proposal.  Every batch
is validated before a single atomic registry write is attempted.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


L2_SCRIPT = Path(__file__).with_name("l2-draft.py")
CHANNEL = "threshold_proposal"
ACTIONS = {"accept": "accepted", "reject": "rejected"}


class ReviewError(RuntimeError):
    """A validation failure that leaves the registry unchanged."""


def kb_home() -> Path:
    configured = os.environ.get("SULDE_KB_HOME")
    return Path(configured).expanduser() if configured else Path.home() / ".sulde/data/kb"


def load_l2_module():
    spec = importlib.util.spec_from_file_location("sulde_l2_governance_review", L2_SCRIPT)
    if spec is None or spec.loader is None:
        raise ReviewError(f"cannot load L2 registry module: {L2_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def proposal_digest(item: dict[str, Any]) -> str:
    material = json.dumps(
        {key: item.get(key, "") for key in ("id", "artifact", "summary")},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def review_queue(registry: dict[str, Any]) -> list[dict[str, Any]]:
    channel = registry.get("channels", {}).get(CHANNEL, {})
    rows = channel.get("items", []) if isinstance(channel, dict) else []
    return [
        {
            "id": row.get("id"),
            "status": row.get("status"),
            "artifact": row.get("artifact"),
            "summary": row.get("summary", ""),
            "digest": proposal_digest(row),
        }
        for row in rows
        if isinstance(row, dict)
    ]


def load_decisions(path: Path) -> list[dict[str, str]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ReviewError(f"cannot read decisions {path}: {error}") from error
    if not isinstance(payload, list) or not payload:
        raise ReviewError("decisions must be a non-empty JSON array")

    decisions: list[dict[str, str]] = []
    seen: set[str] = set()
    for number, row in enumerate(payload, 1):
        if not isinstance(row, dict):
            raise ReviewError(f"decision {number}: must be an object")
        unknown = set(row) - {"id", "action", "reason", "digest"}
        if unknown:
            raise ReviewError(f"decision {number}: unknown fields: {', '.join(sorted(unknown))}")
        for field in ("id", "action", "reason", "digest"):
            if not isinstance(row.get(field), str) or not row[field].strip():
                raise ReviewError(f"decision {number}: {field} must be a non-empty string")
        if row["id"] in seen:
            raise ReviewError(f"decisions contain duplicate id {row['id']}")
        if row["action"] not in ACTIONS:
            raise ReviewError(f"decision {number}: action must be accept or reject")
        seen.add(row["id"])
        decisions.append({field: row[field] for field in ("id", "action", "reason", "digest")})
    return decisions


def plan_review(
    registry: dict[str, Any], decisions: list[dict[str, str]], timestamp: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    channel = registry.get("channels", {}).get(CHANNEL)
    if not isinstance(channel, dict) or not isinstance(channel.get("items"), list):
        raise ReviewError("threshold proposal channel is unavailable")
    indexed = {
        str(row.get("id")): row
        for row in channel["items"]
        if isinstance(row, dict) and row.get("id")
    }
    accepted: list[str] = []
    rejected: list[str] = []
    replayed: list[str] = []

    for decision in decisions:
        identifier = decision["id"]
        item = indexed.get(identifier)
        if item is None:
            raise ReviewError(f"unknown proposal id {identifier}")
        if decision["digest"] != proposal_digest(item):
            raise ReviewError(f"stale proposal digest for {identifier}")
        target = ACTIONS[decision["action"]]
        current = str(item.get("status", "pending"))
        if current in {"accepted", "rejected"}:
            if current != target or item.get("reason") != decision["reason"]:
                raise ReviewError(f"conflicting terminal decision for {identifier}")
            replayed.append(identifier)
            continue
        if current not in {"pending", "approved", "needs_review", "executing"}:
            raise ReviewError(f"proposal {identifier} is not reviewable from status {current}")
        item.update(
            status=target,
            decided_at=timestamp,
            reason=decision["reason"][:1000],
            actor="human",
        )
        (accepted if target == "accepted" else rejected).append(identifier)

    active = {"pending", "approved", "needs_review", "executing"}
    terminal = {"accepted", "rejected", "resolved", "superseded", "executed", "diagnosed"}
    channel["pending"] = sum(row.get("status") in active for row in channel["items"] if isinstance(row, dict))
    channel["terminal"] = sum(row.get("status") in terminal for row in channel["items"] if isinstance(row, dict))
    summary = {
        "status": "ready",
        "accepted": accepted,
        "rejected": rejected,
        "replayed": replayed,
        "pending": channel["pending"],
        "terminal": channel["terminal"],
    }
    return registry, summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--decisions", type=Path, help="human-authored JSON decision array")
    parser.add_argument("--apply", action="store_true", help="atomically write validated decisions to L2 registry")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.apply and args.decisions is None:
        parser.error("--apply requires --decisions")
    return args


def main() -> int:
    args = parse_args()
    home = kb_home()
    try:
        l2 = load_l2_module()
        registry = l2.build_registry(home)
        if registry.get("status") != "ready":
            raise ReviewError(f"L2 registry is {registry.get('status', 'invalid')}")
        if args.decisions is None:
            queue = review_queue(registry)
            result: dict[str, Any] = {
                "status": "ready",
                "pending": registry["channels"][CHANNEL]["pending"],
                "items": queue,
                "writes": 0,
            }
        else:
            decisions = load_decisions(args.decisions)
            registry, result = plan_review(registry, decisions, datetime.now(timezone.utc).isoformat())
            result["writes"] = 1 if args.apply else 0
            if args.apply:
                l2.atomic_json(home / "l2" / "registry.json", registry)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        else:
            print(
                f"GOVERNANCE REVIEW: READY pending={result['pending']} "
                f"accepted={len(result.get('accepted', []))} rejected={len(result.get('rejected', []))} "
                f"writes={result['writes']}"
            )
        return 0
    except (ReviewError, OSError, UnicodeError) as error:
        print(f"GOVERNANCE REVIEW: FAIL {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
