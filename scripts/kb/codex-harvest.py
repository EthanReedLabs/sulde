#!/usr/bin/env python3
"""Incrementally harvest Codex rollout messages into the local memory database."""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "kb-index"))
import memory  # noqa: E402
sys.path.insert(0, str(ROOT / "hooks" / "lib"))
from mem_capture import redact_content  # noqa: E402


DEFAULT_DAYS = 7
STATE_NAME = "codex-harvest-state.json"
ROLLOUT_GLOB = "**/rollout-*.jsonl"
SESSION_ID_RE = re.compile(
    r"([0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12})$"
)
FILENAME_TS_RE = re.compile(r"rollout-(\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2})-")
INJECTED_PREFIXES = (
    "<apps_instructions",
    "<codex_internal_context",
    "<developer",
    "<environment_context",
    "<permissions instructions",
    "<plugins_instructions",
    "<recommended_plugins",
    "<skill",
    "<skills_instructions",
    "<system",
    "<turn_aborted",
    "<user_shell_command",
    "# agents.md instructions",
    "# instructions",
    "instructions",
)


def load_state(path: Path) -> dict[str, int]:
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        print(f"warning: ignoring invalid state file {path}: {error}", file=sys.stderr)
        return {}
    if not isinstance(value, dict):
        print(f"warning: ignoring invalid state file {path}: expected object", file=sys.stderr)
        return {}
    return {
        key: line_count
        for key, line_count in value.items()
        if isinstance(key, str)
        and isinstance(line_count, int)
        and not isinstance(line_count, bool)
        and line_count >= 0
    }


def save_state(path: Path, state: dict[str, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(state, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(str(temporary), str(path))
    finally:
        if temporary.exists():
            temporary.unlink()


def fallback_session_id(source: Path) -> str:
    match = SESSION_ID_RE.search(source.stem)
    return match.group(1) if match else source.stem.removeprefix("rollout-")


def fallback_timestamp(source: Path) -> str:
    match = FILENAME_TS_RE.match(source.name)
    if match:
        return datetime.strptime(match.group(1), "%Y-%m-%dT%H-%M-%S").isoformat()
    return datetime.fromtimestamp(source.stat().st_mtime, timezone.utc).isoformat()


def project_name(cwd: Any) -> str:
    if isinstance(cwd, str) and cwd.strip():
        return Path(cwd).name or "unknown"
    return "unknown"


def message_text(content: Any) -> str:
    if not isinstance(content, list):
        return ""
    return "\n".join(
        item["text"]
        for item in content
        if isinstance(item, dict) and isinstance(item.get("text"), str)
    ).strip()


def is_injected(text: str) -> bool:
    normalized = text.lstrip().lower()
    return any(normalized.startswith(prefix) for prefix in INJECTED_PREFIXES)


def metadata(record: Any, source: Path) -> tuple[str, str] | None:
    if not isinstance(record, dict) or record.get("type") != "session_meta":
        return None
    payload = record.get("payload")
    if not isinstance(payload, dict):
        return None
    identifier = payload.get("id") or payload.get("session_id")
    session_id = str(identifier).strip() if identifier is not None else ""
    return session_id or fallback_session_id(source), project_name(payload.get("cwd"))


def parse_file(
    source: Path, processed_lines: int
) -> tuple[list[dict[str, str]], int, int]:
    entries: list[dict[str, str]] = []
    session_id = fallback_session_id(source)
    project = "unknown"
    fallback_ts = fallback_timestamp(source)
    last_complete_line = 0
    parse_errors = 0

    with source.open(encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            try:
                record = json.loads(raw_line)
            except json.JSONDecodeError:
                # An unterminated final line may still be actively written; retry it later.
                if not raw_line.endswith("\n"):
                    break
                last_complete_line = line_number
                parse_errors += 1
                continue

            last_complete_line = line_number
            found_metadata = metadata(record, source)
            if found_metadata is not None:
                session_id, project = found_metadata
            if line_number <= processed_lines:
                continue
            if not isinstance(record, dict) or record.get("type") != "response_item":
                continue
            payload = record.get("payload")
            if not isinstance(payload, dict) or payload.get("type") != "message":
                continue
            role = payload.get("role")
            if role not in {"user", "assistant"}:
                continue
            content = message_text(payload.get("content"))
            if (
                not content
                or is_injected(content)
                or memory.is_noise_content(content, str(role))
            ):
                continue
            timestamp = record.get("timestamp")
            canonical_session_id, source_host = memory.normalize_session_identity(
                session_id, "codex"
            )
            entries.append(
                {
                    "project": project,
                    "session_id": canonical_session_id,
                    "source_host": source_host,
                    "role": str(role),
                    "content": redact_content(content)[: memory.MAX_CONTENT],
                    "ts": str(timestamp) if timestamp else fallback_ts,
                }
            )

    if last_complete_line < processed_lines:
        return parse_file(source, 0)
    return entries, last_complete_line, parse_errors


def rollout_files(sessions_root: Path, days: int) -> list[Path]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    cutoff_timestamp = cutoff.timestamp()
    files: list[Path] = []
    if not sessions_root.is_dir():
        return files
    for candidate in sessions_root.glob(ROLLOUT_GLOB):
        try:
            if candidate.is_file() and candidate.stat().st_mtime >= cutoff_timestamp:
                files.append(candidate.resolve())
        except OSError:
            # Keep discovery tolerant; a concurrently removed file is simply absent.
            continue
    return sorted(files)


def database_connection(dry_run: bool) -> sqlite3.Connection:
    target = memory.memory_db_path()
    if dry_run:
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        if target.is_file():
            source = memory.connect(target)
            try:
                source.backup(connection)
            finally:
                source.close()
        else:
            memory.create_schema(connection)
        return connection
    if target.is_file():
        connection = memory.connect(target)
        memory.create_schema(connection)
        return connection
    target = memory.initialize(target)
    return memory.connect(target)


def run(days: int, dry_run: bool) -> dict[str, int]:
    sessions_root = Path.home() / ".codex" / "sessions"
    state_path = memory.kb_home() / STATE_NAME
    state = load_state(state_path)
    files = rollout_files(sessions_root, days)
    counters = {
        "scanned_files": len(files),
        "new_entries": 0,
        "parse_errors": 0,
        "failed_files": 0,
    }
    connection = database_connection(dry_run)
    try:
        for source in files:
            source_key = str(source)
            try:
                entries, processed_lines, parse_errors = parse_file(
                    source, state.get(source_key, 0)
                )
                counters["parse_errors"] += parse_errors
                connection.execute("BEGIN")
                file_inserted = 0
                for entry in entries:
                    if memory.add_entry(connection, **entry) is not None:
                        file_inserted += 1
                connection.commit()
                counters["new_entries"] += file_inserted
                if not dry_run:
                    state[source_key] = processed_lines
            except (OSError, UnicodeError, sqlite3.Error, ValueError) as error:
                connection.rollback()
                counters["failed_files"] += 1
                print(f"warning: skipped {source}: {error}", file=sys.stderr)
        if not dry_run:
            save_state(state_path, state)
    finally:
        connection.close()
    return counters


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.days < 0:
        parser.error("--days must be zero or greater")
    counters = run(args.days, args.dry_run)
    print(" ".join(f"{key}={value}" for key, value in counters.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
