"""Forward Claude Code Notification events to macOS Notification Center."""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_DEFAULT_TITLE = "Claude Code"
_DEDUP_SECONDS = 60


def _state_dir() -> Path:
    configured = os.environ.get("SULDE_KB_HOME")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".sulde" / "data" / "kb"


def _message(payload: dict[str, Any]) -> str:
    value = payload.get("message", "")
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    return ""


def _escape_applescript(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _append_log(home: Path, message: str) -> None:
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "cwd": os.getcwd(),
        "message": message[:60],
    }
    with (home / "notify-log.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _is_duplicate(home: Path, message: str, now: float) -> bool:
    state_path = home / "notify-state.json"
    digest = hashlib.sha256(message.encode("utf-8")).hexdigest()
    duplicate = False
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        duplicate = (
            state.get("message_hash") == digest
            and now - float(state.get("ts", 0)) < _DEDUP_SECONDS
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        pass
    if not duplicate:
        state_path.write_text(
            json.dumps({"message_hash": digest, "ts": now}),
            encoding="utf-8",
        )
    return duplicate


def run(payload: dict[str, Any] | None) -> None:
    """Send one notification; all failures are intentionally ignored."""
    try:
        if os.environ.get("SULDE_NOTIFY", "").lower() == "off":
            return
        if sys.platform != "darwin":
            return
        if not isinstance(payload, dict):
            return
        message = _message(payload)
        if not message:
            return

        home = _state_dir()
        home.mkdir(parents=True, exist_ok=True)
        _append_log(home, message)
        if _is_duplicate(home, message, time.time()):
            return

        script = (
            f'display notification "{_escape_applescript(message[:120])}" '
            f'with title "{_DEFAULT_TITLE}" '
            f'subtitle "{_escape_applescript(Path.cwd().name)}"'
        )
        command = ["osascript", "-e", script]
        if os.environ.get("SULDE_NOTIFY_DRYRUN") == "1":
            print(shlex.join(command))
            return
        subprocess.run(
            command,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        return
