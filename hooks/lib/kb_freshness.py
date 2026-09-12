"""Stale-while-revalidate KB index freshness check for SessionStart."""

from __future__ import annotations

import json
import os
import runpy
import sqlite3
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any


try:
    kb_cli = SimpleNamespace(
        **runpy.run_path(str(Path(__file__).resolve().with_name("kb_cli.py")))
    )
except (ImportError, OSError) as error:  # pragma: no cover - installation damage
    kb_cli = None  # type: ignore[assignment]
    _KB_CLI_IMPORT_ERROR = f"{type(error).__name__}: {error}"
else:
    _KB_CLI_IMPORT_ERROR = ""

_manifest = runpy.run_path(
    str(Path(__file__).resolve().parents[2] / "tools" / "kb-index" / "corpus_manifest.py")
)
ManifestError = _manifest["ManifestError"]
load_manifest = _manifest["load_manifest"]


LOCK_MAX_AGE_SECONDS = 10 * 60
BUILD_TIMEOUT_SECONDS = 10 * 60
WARMUP_TIMEOUT_SECONDS = 60


def _plugin_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _state_dir() -> Path:
    """Mirror the KB index common module without importing its dependency tree."""
    configured = os.environ.get("SULDE_KB_HOME")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".sulde" / "data" / "kb"


def _indexed_fingerprint(database: Path) -> str | None:
    if not database.is_file():
        return None
    try:
        connection = sqlite3.connect(database)
        row = connection.execute(
            "SELECT value FROM meta WHERE key = 'corpus_fingerprint'"
        ).fetchone()
        connection.close()
        return str(row[0]) if row else None
    except (OSError, sqlite3.Error):
        return None


def _corpus_fingerprint(root: Path) -> str | None:
    try:
        return load_manifest(root, verify_files=True).corpus_sha256
    except (OSError, UnicodeError, ManifestError):
        return None


def _emit_triggered() -> None:
    output = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": "[sulde-kb] KB 索引缺失或陈旧，已触发后台增量重建。",
        }
    }
    sys.stdout.write(json.dumps(output, ensure_ascii=False) + "\n")


def _trace(log_path: Path, status: str, detail: str = "") -> None:
    message = f"[sulde-kb-cli] status={status}"
    if detail:
        message += f" detail={detail[-500:]}"
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as stream:
            stream.write(message + "\n")
    except OSError:
        try:
            sys.stderr.write(message + "\n")
        except (OSError, ValueError):
            return


def _acquire_build_lock(lock: Path) -> bool:
    try:
        if lock.exists():
            if time.time() - lock.stat().st_mtime < LOCK_MAX_AGE_SECONDS:
                return False
            lock.unlink()
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        os.write(descriptor, f"{os.getpid()}\n".encode("ascii"))
        os.close(descriptor)
        return True
    except OSError:
        return False


def run(_payload: dict[str, Any]) -> None:
    root = _plugin_root()
    state = _state_dir()
    database = state / "kb.db"
    log_path = state / "build.log"
    if kb_cli is None:
        _trace(log_path, "module_unavailable", _KB_CLI_IMPORT_ERROR)
        return
    current_fingerprint = _corpus_fingerprint(root)
    stale = current_fingerprint is not None and _indexed_fingerprint(database) != current_fingerprint
    lock = state / "build.lock"
    triggered = False
    if stale and _acquire_build_lock(lock):
        triggered = kb_cli.spawn_cli(
            root,
            state,
            "build",
            timeout=BUILD_TIMEOUT_SECONDS,
            log_path=log_path,
        ).started
        if not triggered:
            try:
                lock.unlink()
            except OSError:
                pass
    kb_cli.spawn_cli(
        root,
        state,
        "search",
        ["warmup", "-k", "1"],
        timeout=WARMUP_TIMEOUT_SECONDS,
        log_path=log_path,
    )
    if triggered:
        _emit_triggered()
