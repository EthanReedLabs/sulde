#!/usr/bin/env python3
"""Scan memory.db for secrets and optionally redact explicitly selected entries."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import runpy
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterable
from urllib.parse import quote


REPO_ROOT = Path(__file__).resolve().parents[2]
_HOOK_LIB = REPO_ROOT / "hooks" / "lib"
kb_cli = SimpleNamespace(**runpy.run_path(str(_HOOK_LIB / "kb_cli.py")))
REDACTION_MARKER = "****[已脱敏]"
EXAMPLE_LIMIT = 8
PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "bailian_workspace_key",
        re.compile(r"sk-(?:sp|ws)-[A-Za-z0-9._-]{16,}"),
    ),
    ("generic_sk_key", re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    (
        "private_key_header",
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    ),
    (
        "jwt",
        re.compile(
            r"\beyJ[A-Za-z0-9_-]*\.eyJ[A-Za-z0-9_-]*\.[A-Za-z0-9_-]+\b"
        ),
    ),
    (
        "password_assignment",
        re.compile(r"(?:password|passwd|密码)\s*[=:：]\s*\S{6,}", re.IGNORECASE),
    ),
    (
        "authorization_bearer",
        re.compile(
            r"authorization:\s*bearer\s+[A-Za-z0-9._-]{16,}", re.IGNORECASE
        ),
    ),
)


class ScanError(RuntimeError):
    """An expected CLI/runtime error that should produce exit code 2."""


def kb_home() -> Path:
    configured = os.environ.get("SULDE_KB_HOME")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".sulde" / "data" / "kb"


def default_db_path() -> Path:
    return kb_home() / "memory.db"


def parse_ids(value: str) -> list[int]:
    try:
        identifiers = [int(part.strip()) for part in value.split(",") if part.strip()]
    except ValueError as error:
        raise argparse.ArgumentTypeError("--ids must be comma-separated integers") from error
    if not identifiers or any(identifier <= 0 for identifier in identifiers):
        raise argparse.ArgumentTypeError("--ids must contain positive integers")
    return list(dict.fromkeys(identifiers))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scan memory.db for secrets; redact only explicitly selected IDs."
    )
    parser.add_argument("--redact", action="store_true", help="redact selected entries")
    parser.add_argument("--ids", type=parse_ids, help="comma-separated entry IDs")
    parser.add_argument("--db", type=Path, default=default_db_path())
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = parser.parse_args()
    if args.redact and not args.ids:
        parser.error("--redact requires explicit --ids")
    if args.ids and not args.redact:
        parser.error("--ids is only valid with --redact")
    return args


def ensure_redact_interpreter() -> None:
    if importlib.util.find_spec("jieba") is not None:
        return
    venv_python = kb_cli.resolve_venv_python(
        kb_home(), require_executable=True
    )
    if venv_python is None:
        raise ScanError(
            f"--redact requires jieba; kb venv python not found under: {kb_home() / 'venv'}"
        )
    try:
        os.execv(
            str(venv_python),
            [str(venv_python), str(Path(__file__).resolve()), *sys.argv[1:]],
        )
    except OSError as error:
        raise ScanError(f"failed to re-exec kb venv python {venv_python}: {error}") from error


def require_database(path: Path) -> Path:
    try:
        resolved = path.expanduser().resolve()
        if not resolved.is_file():
            raise ScanError(f"database does not exist or is not a file: {resolved}")
        return resolved
    except OSError as error:
        raise ScanError(f"cannot access database {path}: {error}") from error


def connect_read_only(path: Path) -> sqlite3.Connection:
    uri = f"file:{quote(str(path), safe='/')}?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=1.0)
    connection.row_factory = sqlite3.Row
    return connection


def connect_writable(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path, timeout=1.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def fetch_entries(
    connection: sqlite3.Connection, identifiers: Iterable[int] | None = None
) -> list[sqlite3.Row]:
    fields = "id, project, role, ts, content"
    if identifiers is None:
        return connection.execute(
            f"SELECT {fields} FROM mem_entries ORDER BY id"
        ).fetchall()
    ids = list(identifiers)
    placeholders = ",".join("?" for _ in ids)
    return connection.execute(
        f"SELECT {fields} FROM mem_entries WHERE id IN ({placeholders}) ORDER BY id",
        ids,
    ).fetchall()


def safe_sample(secret: str) -> str:
    return f"{secret[:10]}…({len(secret)}字符)"


def matches_by_pattern(content: str) -> dict[str, list[str]]:
    return {
        name: [match.group(0) for match in pattern.finditer(content)]
        for name, pattern in PATTERNS
        if pattern.search(content)
    }


def scan_rows(rows: Iterable[sqlite3.Row], db_path: Path) -> dict[str, Any]:
    pattern_results: dict[str, dict[str, Any]] = {
        name: {"match_count": 0, "entry_count": 0, "examples": []}
        for name, _ in PATTERNS
    }
    matched_entries: set[int] = set()
    projects: Counter[str] = Counter()

    for row in rows:
        found = matches_by_pattern(str(row["content"]))
        if not found:
            continue
        entry_id = int(row["id"])
        matched_entries.add(entry_id)
        projects[str(row["project"])] += 1
        for name, secrets in found.items():
            result = pattern_results[name]
            result["match_count"] += len(secrets)
            result["entry_count"] += 1
            for secret in secrets:
                if len(result["examples"]) >= EXAMPLE_LIMIT:
                    break
                result["examples"].append(
                    {
                        "id": entry_id,
                        "project": str(row["project"]),
                        "role": str(row["role"]),
                        "ts": str(row["ts"]),
                        "sample": safe_sample(secret),
                    }
                )

    return {
        "database": str(db_path),
        "clean": not matched_entries,
        "matched_entry_count": len(matched_entries),
        "projects": dict(sorted(projects.items())),
        "patterns": {
            name: result
            for name, result in pattern_results.items()
            if result["match_count"]
        },
    }


def scan_database(path: Path) -> dict[str, Any]:
    connection = connect_read_only(path)
    try:
        return scan_rows(fetch_entries(connection), path)
    finally:
        connection.close()


def redact_text(content: str) -> str:
    redacted = content
    for _, pattern in PATTERNS:
        redacted = pattern.sub(
            lambda match: match.group(0)[:6] + REDACTION_MARKER, redacted
        )
    return redacted


def redact_entries(path: Path, identifiers: list[int]) -> dict[str, Any]:
    sys.path.insert(0, str(REPO_ROOT / "tools" / "kb-index"))
    import memory  # type: ignore  # pylint: disable=import-error,import-outside-toplevel

    connection = connect_writable(path)
    try:
        rows = fetch_entries(connection, identifiers)
        found_ids = {int(row["id"]) for row in rows}
        missing = [identifier for identifier in identifiers if identifier not in found_ids]
        if missing:
            raise ScanError(f"entry IDs not found; no changes made: {missing}")

        changed_ids: list[int] = []
        for row in rows:
            original = str(row["content"])
            redacted = redact_text(original)
            if redacted == original:
                continue
            entry_id = int(row["id"])
            with connection:
                connection.execute(
                    "UPDATE mem_entries SET content = ?, embedded = 0 WHERE id = ?",
                    (redacted, entry_id),
                )
                connection.execute("DELETE FROM mem_fts WHERE rowid = ?", (entry_id,))
                connection.execute(
                    "INSERT INTO mem_fts(rowid, seg_text) VALUES (?, ?)",
                    (entry_id, memory.segmented(redacted)),
                )
                connection.execute("DELETE FROM mem_vectors WHERE id = ?", (entry_id,))
            changed_ids.append(entry_id)
    finally:
        connection.close()

    result = scan_database(path)
    result["redaction"] = {
        "requested_ids": identifiers,
        "changed_ids": changed_ids,
        "changed_count": len(changed_ids),
    }
    return result


def print_human(result: dict[str, Any]) -> None:
    redaction = result.get("redaction")
    if redaction:
        print(
            f"Redacted {redaction['changed_count']} entries: "
            f"{redaction['changed_ids']}"
        )
    if not result["patterns"]:
        print("No secrets found.")
    for name, summary in result["patterns"].items():
        print(
            f"[{name}] matches={summary['match_count']} "
            f"entries={summary['entry_count']}"
        )
        for example in summary["examples"]:
            print(
                "  id={id} project={project} role={role} ts={ts} sample={sample}".format(
                    **example
                )
            )
    print(f"Matched entries: {result['matched_entry_count']}")
    if result["projects"]:
        print("Projects: " + ", ".join(f"{key}={value}" for key, value in result["projects"].items()))
    else:
        print("Projects: none")


def emit_error(message: str, json_output: bool) -> None:
    if json_output:
        print(json.dumps({"error": message}, ensure_ascii=False, sort_keys=True))
    else:
        print(f"error: {message}", file=sys.stderr)


def main() -> int:
    args = parse_args()
    try:
        path = require_database(args.db)
        if args.redact:
            ensure_redact_interpreter()
            result = redact_entries(path, args.ids)
        else:
            result = scan_database(path)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        else:
            print_human(result)
        return 0 if result["clean"] else 1
    except (ScanError, OSError, sqlite3.Error, UnicodeError) as error:
        emit_error(str(error), args.json)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
