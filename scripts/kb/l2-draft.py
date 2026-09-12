#!/usr/bin/env python3
"""Build the auditable registry for Sulde's four L2 draft channels."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CHANNELS = ("wp_brief", "golden_case", "sediment_draft", "threshold_proposal")
TERMINAL_STATUSES = {"accepted", "rejected", "resolved", "superseded", "executed", "diagnosed"}
ACTIVE_STATUSES = {"pending", "approved", "needs_review", "executing"}
PROPOSAL_RE = re.compile(r"\*\*待审提案\s+(P-\d+)[^*]*\*\*[:：]\s*(.*?)(?=\n---|\n###\s+质疑|\Z)", re.DOTALL)


def kb_home() -> Path:
    configured = os.environ.get("SULDE_KB_HOME")
    return Path(configured).expanduser() if configured else Path.home() / ".sulde" / "data" / "kb"


def read_json(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return default


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.is_file():
        return rows
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def latest(directory: Path, pattern: str) -> Path | None:
    paths = sorted(directory.glob(pattern), reverse=True)
    return paths[0] if paths else None


def stable_id(prefix: str, value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()[:12]
    return f"{prefix}-{digest}"


def collect_wp(home: Path) -> dict[str, Any]:
    path = home / "self-repair" / "pending.json"
    payload = read_json(path, [])
    rows = payload if isinstance(payload, list) else []
    items = [
        {
            "id": str(row.get("slug", "")),
            "status": str(row.get("status", "unknown")),
            "artifact": str(row.get("brief_path", "")),
        }
        for row in rows if isinstance(row, dict) and row.get("slug")
    ]
    return {"available": path.is_file(), "source": str(path), "items": items}


def collect_golden(home: Path) -> dict[str, Any]:
    path = home / "golden-candidates.jsonl"
    items = [
        {"id": str(row.get("id", "")), "status": "pending", "artifact": str(path)}
        for row in read_jsonl(path) if row.get("id")
    ]
    return {"available": path.is_file(), "source": str(path), "items": items}


def collect_sediment(home: Path) -> dict[str, Any]:
    path = home / "distill-candidates.md"
    items: list[dict[str, str]] = []
    if path.is_file():
        for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if not line.startswith("- "):
                continue
            status = "resolved" if "（✅" in line else "needs_review" if "（❓" in line else "pending"
            items.append({
                "id": stable_id("sediment", line),
                "status": status,
                "artifact": f"{path}:{number}",
            })
    return {"available": path.is_file(), "source": str(path), "items": items}


def collect_thresholds(home: Path) -> dict[str, Any]:
    report = latest(home / "governance", "report-*.md")
    items: list[dict[str, str]] = []
    if report is not None:
        text = report.read_text(encoding="utf-8", errors="replace")
        for proposal_id, body in PROPOSAL_RE.findall(text):
            items.append({
                "id": proposal_id,
                "status": "pending",
                "artifact": f"{report}#proposal:{proposal_id}",
                "summary": " ".join(body.split())[:500],
            })
    return {"available": report is not None, "source": str(report or ""), "items": items}


def previous_decisions(home: Path) -> dict[tuple[str, str], dict[str, Any]]:
    previous = read_json(home / "l2" / "registry.json", {})
    decisions: dict[tuple[str, str], dict[str, Any]] = {}
    for name, channel in previous.get("channels", {}).items() if isinstance(previous, dict) else []:
        for item in channel.get("items", []) if isinstance(channel, dict) else []:
            if isinstance(item, dict) and item.get("id") and item.get("status") in TERMINAL_STATUSES:
                decisions[(str(name), str(item["id"]))] = item
    return decisions


def build_registry(home: Path) -> dict[str, Any]:
    channels = {
        "wp_brief": collect_wp(home),
        "golden_case": collect_golden(home),
        "sediment_draft": collect_sediment(home),
        "threshold_proposal": collect_thresholds(home),
    }
    preserved = previous_decisions(home)
    for name, channel in channels.items():
        items = channel["items"]
        for item in items:
            old = preserved.get((name, item["id"]))
            if old:
                item.update({key: old[key] for key in ("status", "decided_at", "reason", "actor") if key in old})
        channel["count"] = len(items)
        channel["pending"] = sum(item["status"] in ACTIVE_STATUSES for item in items)
        channel["terminal"] = sum(item["status"] in TERMINAL_STATUSES for item in items)
    missing = [name for name in CHANNELS if not channels[name]["available"]]
    return {
        "schema": "sulde-l2-registry-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "ready" if not missing else "degraded",
        "missing_channels": missing,
        "channels": channels,
        "loop": {
            "producer": "heartbeat",
            "consumer": "life-cycle",
            "state_model": "pending -> approved/rejected -> executed/diagnosed/resolved",
            "auditable": True,
        },
    }


def transition(home: Path, channel: str, item_id: str, status: str, reason: str, actor: str) -> dict[str, Any]:
    registry = build_registry(home)
    matches = [item for item in registry["channels"][channel]["items"] if item["id"] == item_id]
    if len(matches) != 1:
        raise ValueError(f"expected one item: channel={channel} id={item_id}; found={len(matches)}")
    item = matches[0]
    item["status"] = status
    item["decided_at"] = datetime.now(timezone.utc).isoformat()
    item["reason"] = reason[:1000]
    item["actor"] = actor
    channel_row = registry["channels"][channel]
    channel_row["pending"] = sum(row["status"] in ACTIVE_STATUSES for row in channel_row["items"])
    channel_row["terminal"] = sum(row["status"] in TERMINAL_STATUSES for row in channel_row["items"])
    atomic_json(home / "l2" / "registry.json", registry)
    return registry


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", action="store_true", help="write $SULDE_KB_HOME/l2/registry.json")
    parser.add_argument("--dry-run", action="store_true", help="print status without writing")
    parser.add_argument("--transition", nargs=3, metavar=("CHANNEL", "ID", "STATUS"))
    parser.add_argument("--reason", default="")
    parser.add_argument("--actor", choices=("human", "system"), default="human")
    args = parser.parse_args()
    if sum(bool(value) for value in (args.refresh, args.dry_run, args.transition)) != 1:
        parser.error("choose exactly one of --refresh, --dry-run or --transition")
    home = kb_home()
    if args.transition:
        channel, item_id, status = args.transition
        if channel not in CHANNELS or status not in TERMINAL_STATUSES | ACTIVE_STATUSES:
            parser.error("invalid transition channel or status")
        registry = transition(home, channel, item_id, status, args.reason, args.actor)
    else:
        registry = build_registry(home)
    output = home / "l2" / "registry.json"
    if args.refresh:
        atomic_json(output, registry)
    counts = " ".join(
        f"{name}={registry['channels'][name]['count']}"
        for name in CHANNELS
    )
    print(f"L2 REGISTRY: {registry['status'].upper()} {counts} writes={1 if args.refresh else 0}")
    print(f"registry: {output if (args.refresh or args.transition) else 'unchanged (dry-run)'}")
    return 0 if registry["status"] == "ready" else 1


if __name__ == "__main__":
    raise SystemExit(main())
