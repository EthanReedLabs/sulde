#!/usr/bin/env python3
"""Normalize shared Claude/Codex session identity and provenance in memory.db."""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "kb-index"))
import memory  # noqa: E402


HOSTS = {"claude", "codex"}
UUID_RE = re.compile(
    r"([0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12})"
)


def _uuid(value: str) -> str | None:
    match = UUID_RE.search(value)
    return match.group(1).lower() if match else None


def codex_session_ids(root: Path) -> set[str]:
    identifiers: set[str] = set()
    if not root.is_dir():
        return identifiers
    for path in root.glob("**/rollout-*.jsonl"):
        fallback = _uuid(path.stem)
        if fallback:
            identifiers.add(fallback)
        try:
            with path.open(encoding="utf-8") as handle:
                for index, line in enumerate(handle):
                    if index >= 50:
                        break
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(record, dict) or record.get("type") != "session_meta":
                        continue
                    payload = record.get("payload")
                    if isinstance(payload, dict):
                        value = str(payload.get("id") or payload.get("session_id") or "")
                        if value:
                            identifiers.add(value.lower())
                    break
        except (OSError, UnicodeError):
            continue
    return identifiers


def claude_session_ids(root: Path) -> set[str]:
    if not root.is_dir():
        return set()
    return {
        identifier
        for path in root.glob("**/*.jsonl")
        if (identifier := _uuid(path.stem)) is not None
    }


def capture_state_ids(connection: sqlite3.Connection) -> tuple[set[str], set[str]]:
    claude: set[str] = set()
    codex: set[str] = set()
    table = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='mem_capture_state'"
    ).fetchone()
    if table is None:
        return claude, codex
    for row in connection.execute("SELECT transcript_path FROM mem_capture_state"):
        path = str(row[0]).replace("\\", "/").lower()
        identifier = _uuid(Path(path).stem)
        if not identifier:
            continue
        if "/.codex/" in path:
            codex.add(identifier)
        elif "/.claude/" in path:
            claude.add(identifier)
    return claude, codex


def canonical_identity(
    session_id: str,
    source_host: str,
    *,
    known_claude: set[str],
    known_codex: set[str],
) -> tuple[str, str]:
    normalized_id, normalized_host = memory.normalize_session_identity(
        session_id, source_host
    )
    if normalized_host in HOSTS:
        return normalized_id, normalized_host

    raw = str(session_id).strip()
    lookup = raw.lower()
    in_claude = lookup in known_claude
    in_codex = lookup in known_codex
    if in_claude != in_codex:
        host = "claude" if in_claude else "codex"
        return memory.normalize_session_identity(raw, host)
    return raw, memory.normalize_source_host(source_host)


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")}


def plan_groups(
    connection: sqlite3.Connection,
    *,
    known_claude: set[str],
    known_codex: set[str],
) -> tuple[dict[tuple[str, str], list[sqlite3.Row]], dict[int, tuple[str, str]]]:
    source_expression = (
        "source_host" if "source_host" in _columns(connection, "mem_entries")
        else "'unknown' AS source_host"
    )
    rows = connection.execute(
        f"""SELECT id,session_id,{source_expression},content_hash,embedded
            FROM mem_entries ORDER BY id"""
    ).fetchall()
    groups: dict[tuple[str, str], list[sqlite3.Row]] = defaultdict(list)
    identities: dict[int, tuple[str, str]] = {}
    for row in rows:
        identity = canonical_identity(
            str(row["session_id"]),
            str(row["source_host"]),
            known_claude=known_claude,
            known_codex=known_codex,
        )
        identities[int(row["id"])] = identity
        groups[(identity[0], str(row["content_hash"]))].append(row)
    return dict(groups), identities


def _copy_search_artifacts(
    connection: sqlite3.Connection, survivor: int, duplicates: Iterable[int]
) -> None:
    duplicate_ids = list(duplicates)
    if not duplicate_ids:
        return
    placeholders = ",".join("?" for _ in duplicate_ids)
    if connection.execute(
        "SELECT 1 FROM mem_vectors WHERE id=?", (survivor,)
    ).fetchone() is None:
        vector = connection.execute(
            f"SELECT dim,vector FROM mem_vectors WHERE id IN ({placeholders}) LIMIT 1",
            duplicate_ids,
        ).fetchone()
        if vector is not None:
            connection.execute(
                "INSERT OR REPLACE INTO mem_vectors(id,dim,vector) VALUES (?,?,?)",
                (survivor, vector[0], vector[1]),
            )
    if connection.execute(
        "SELECT 1 FROM mem_fts WHERE rowid=?", (survivor,)
    ).fetchone() is None:
        fts = connection.execute(
            f"SELECT seg_text FROM mem_fts WHERE rowid IN ({placeholders}) LIMIT 1",
            duplicate_ids,
        ).fetchone()
        if fts is not None:
            connection.execute(
                "INSERT INTO mem_fts(rowid,seg_text) VALUES (?,?)", (survivor, fts[0])
            )


def apply_groups(
    connection: sqlite3.Connection,
    groups: dict[tuple[str, str], list[sqlite3.Row]],
    identities: dict[int, tuple[str, str]],
) -> dict[str, int]:
    counters = {
        "entries": sum(len(rows) for rows in groups.values()),
        "relabeled": 0,
        "duplicates_removed": 0,
        "unknown": 0,
    }
    if not connection.in_transaction:
        connection.execute("BEGIN IMMEDIATE")
    try:
        for rows in groups.values():
            survivor = min(int(row["id"]) for row in rows)
            target_session, target_host = identities[survivor]
            duplicate_ids = sorted(
                int(row["id"]) for row in rows if int(row["id"]) != survivor
            )
            if duplicate_ids:
                _copy_search_artifacts(connection, survivor, duplicate_ids)
                placeholders = ",".join("?" for _ in duplicate_ids)
                connection.execute(
                    f"UPDATE mem_edges SET entry_id=? WHERE entry_id IN ({placeholders})",
                    (survivor, *duplicate_ids),
                )
                connection.execute(
                    f"DELETE FROM mem_fts WHERE rowid IN ({placeholders})", duplicate_ids
                )
                connection.execute(
                    f"DELETE FROM mem_vectors WHERE id IN ({placeholders})", duplicate_ids
                )
                connection.execute(
                    f"DELETE FROM mem_entries WHERE id IN ({placeholders})", duplicate_ids
                )
                counters["duplicates_removed"] += len(duplicate_ids)

            original = next(row for row in rows if int(row["id"]) == survivor)
            if (
                str(original["session_id"]) != target_session
                or str(original["source_host"]) != target_host
            ):
                counters["relabeled"] += 1
            connection.execute(
                "UPDATE mem_entries SET session_id=?,source_host=? WHERE id=?",
                (target_session, target_host, survivor),
            )
            embedded = connection.execute(
                "SELECT 1 FROM mem_vectors WHERE id=?", (survivor,)
            ).fetchone()
            connection.execute(
                "UPDATE mem_entries SET embedded=? WHERE id=?",
                (1 if embedded is not None else 0, survivor),
            )
            if target_host == "unknown":
                counters["unknown"] += 1
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    return counters


def backup_database(connection: sqlite3.Connection, database: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = database.with_name(f"{database.name}.session-identity-{stamp}.bak")
    destination = sqlite3.connect(backup)
    try:
        connection.backup(destination)
    finally:
        destination.close()
    os.chmod(backup, database.stat().st_mode & 0o777)
    return backup


def migrate_recall_log(
    path: Path,
    *,
    known_claude: set[str],
    known_codex: set[str],
    apply: bool,
) -> tuple[int, Path | None]:
    if not path.is_file():
        return 0, None
    changed = 0
    output: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            output.append(line)
            continue
        if not isinstance(row, dict) or row.get("source") != "mem" or not all(
            key in row for key in ("session_id", "channel", "opportunity_id")
        ):
            output.append(line)
            continue
        _canonical, host = canonical_identity(
            str(row["session_id"]),
            "unknown",
            known_claude=known_claude,
            known_codex=known_codex,
        )
        if host == "unknown" and row.get("channel") in HOSTS:
            host = str(row["channel"])
        if row.get("source_host") != host:
            row["source_host"] = host
            changed += 1
        output.append(json.dumps(row, ensure_ascii=False, allow_nan=False))
    if not apply or changed == 0:
        return changed, None
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = path.with_name(f"{path.name}.session-identity-{stamp}.bak")
    backup.write_bytes(path.read_bytes())
    os.chmod(backup, path.stat().st_mode & 0o777)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write("\n".join(output) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return changed, backup


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=memory.memory_db_path())
    parser.add_argument("--recall-log", type=Path)
    parser.add_argument(
        "--codex-sessions-root", type=Path, default=Path.home() / ".codex/sessions"
    )
    parser.add_argument(
        "--claude-projects-root", type=Path, default=Path.home() / ".claude/projects"
    )
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    database = args.database.expanduser().resolve()
    if not database.is_file():
        parser.error(f"memory database does not exist: {database}")

    connection = sqlite3.connect(database, timeout=5.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    backup: Path | None = None
    try:
        known_codex = codex_session_ids(args.codex_sessions_root.expanduser())
        known_claude = claude_session_ids(args.claude_projects_root.expanduser())
        captured_claude, captured_codex = capture_state_ids(connection)
        known_claude |= captured_claude
        known_codex |= captured_codex
        if args.apply:
            backup = backup_database(connection, database)
            memory.create_schema(connection)
            connection.commit()
            connection.execute("BEGIN IMMEDIATE")
        groups, identities = plan_groups(
            connection,
            known_claude=known_claude,
            known_codex=known_codex,
        )
        if args.apply:
            counters = apply_groups(connection, groups, identities)
        else:
            counters = {
                "entries": sum(len(rows) for rows in groups.values()),
                "relabeled": sum(
                    1
                    for rows in groups.values()
                    for row in rows[:1]
                    if (
                        str(row["session_id"]), str(row["source_host"])
                    ) != identities[int(row["id"])]
                ),
                "duplicates_removed": sum(max(len(rows) - 1, 0) for rows in groups.values()),
                "unknown": sum(
                    1 for rows in groups.values()
                    if identities[int(rows[0]["id"])][1] == "unknown"
                ),
            }
    finally:
        connection.close()

    recall_log = args.recall_log or database.with_name("recall-log.jsonl")
    recall_changed, recall_backup = migrate_recall_log(
        recall_log.expanduser(),
        known_claude=known_claude,
        known_codex=known_codex,
        apply=args.apply,
    )
    result: dict[str, Any] = {
        **counters,
        "known_claude_sessions": len(known_claude),
        "known_codex_sessions": len(known_codex),
        "ambiguous_known_sessions": len(known_claude & known_codex),
        "recall_rows_attributed": recall_changed,
        "applied": args.apply,
    }
    if backup is not None:
        result["database_backup"] = str(backup)
    if recall_backup is not None:
        result["recall_log_backup"] = str(recall_backup)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
