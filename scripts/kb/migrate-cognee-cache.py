#!/usr/bin/env python3
"""One-time idempotent migration from Cognee cache or a Codex rollout."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "kb-index"))
import memory  # noqa: E402


def project_from_context(value: Any) -> str:
    context = value
    if isinstance(context, str):
        try:
            context = json.loads(context)
        except json.JSONDecodeError:
            context = {}
    if isinstance(context, dict) and context.get("cwd"):
        return Path(str(context["cwd"])).name or "unknown"
    return "unknown"


def cognee_entries(source: Path) -> Iterator[dict[str, str]]:
    connection = sqlite3.connect(source)
    connection.row_factory = sqlite3.Row
    try:
        for row in connection.execute(
            "SELECT session_id, payload, created_at FROM cache_qa_entries ORDER BY seq"
        ):
            try:
                payload = json.loads(row["payload"])
            except (TypeError, json.JSONDecodeError):
                continue
            if not isinstance(payload, dict):
                continue
            project = project_from_context(payload.get("context"))
            timestamp = str(payload.get("time") or row["created_at"] or datetime.now(timezone.utc).isoformat())
            qa_id = str(payload.get("qa_id") or "")
            for role, key in (("user", "question"), ("assistant", "answer")):
                content = payload.get(key)
                if isinstance(content, str):
                    yield {
                        "project": project,
                        "session_id": str(row["session_id"]),
                        "source_host": "import",
                        "role": role,
                        "content": content,
                        "ts": timestamp,
                        "dedupe_key": f"cognee:{qa_id}:{role}",
                    }
    finally:
        connection.close()


def text_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            str(item.get("text"))
            for item in content
            if isinstance(item, dict) and isinstance(item.get("text"), str)
        )
    return ""


def codex_entries(source: Path) -> Iterator[dict[str, str]]:
    session_id = source.stem
    project = "unknown"
    for raw_line in source.open(encoding="utf-8"):
        try:
            record = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        payload = record.get("payload") if isinstance(record, dict) else None
        if not isinstance(payload, dict):
            continue
        if record.get("type") == "session_meta":
            session_id = str(payload.get("id") or session_id)
            project = Path(str(payload.get("cwd") or "unknown")).name or "unknown"
            continue
        if record.get("type") != "response_item" or payload.get("type") != "message":
            continue
        role = payload.get("role")
        if role not in {"user", "assistant"}:
            continue
        content = text_content(payload.get("content")).strip()
        if content:
            yield {
                "project": project,
                "session_id": session_id,
                "source_host": "codex",
                "role": str(role),
                "content": content,
                "ts": str(record.get("timestamp") or datetime.now(timezone.utc).isoformat()),
            }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=Path.home() / ".cognee" / "system" / "databases" / "cache.db",
    )
    parser.add_argument("--codex-rollout", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        entries = list(codex_entries(args.codex_rollout)) if args.codex_rollout else list(cognee_entries(args.source))
    except (OSError, sqlite3.Error) as error:
        print(f"migration source unavailable: {error}", file=sys.stderr)
        return 2
    if args.dry_run:
        print(f"dry-run: source_rows={len(entries) // 2 if not args.codex_rollout else 'n/a'} migratable_entries={len(entries)} new_entries=not-evaluated")
        return 0

    target = memory.initialize()
    connection = memory.connect(target)
    inserted = 0
    try:
        with connection:
            for entry in entries:
                if memory.add_entry(connection, **entry) is not None:
                    inserted += 1
    finally:
        connection.close()
    print(f"migration complete: scanned={len(entries)} inserted={inserted} database={target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
