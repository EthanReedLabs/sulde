"""Silent read-after-inject feedback collection for the KB recall hook."""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*):(?:\s*(.*))?$")


def _plugin_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _state_dir() -> Path:
    configured = os.environ.get("SULDE_KB_HOME")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".sulde" / "data" / "kb"


def _session_path(session_id: str) -> Path | None:
    if not session_id:
        return None
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", session_id)[:100]
    if not safe or safe in {".", ".."}:
        safe = hashlib.sha256(session_id.encode("utf-8")).hexdigest()
    return _state_dir() / "session-recall" / f"{safe}.json"


def _decode_scalar(value: str) -> str:
    value = value.strip()
    if value.startswith('"'):
        decoded = json.loads(value)
        return decoded if isinstance(decoded, str) else str(decoded)
    if len(value) >= 2 and value.startswith("'") and value.endswith("'"):
        return value[1:-1].replace("''", "'")
    return value


def _doc_id(path: Path) -> str | None:
    with path.open("r", encoding="utf-8") as stream:
        if stream.readline().strip() != "---":
            return None
        for line in stream:
            if line.strip() == "---":
                break
            match = KEY_RE.match(line.rstrip("\n"))
            if match and match.group(1) == "doc_id":
                value = _decode_scalar(match.group(2) or "")
                return value or None
    return None


def run(payload: dict[str, Any]) -> None:
    """Append feedback when a Read targets a document injected in this session."""
    try:
        session_id = str(payload.get("session_id") or "")
        tool_input = payload.get("tool_input")
        if not isinstance(tool_input, dict):
            return
        raw_path = tool_input.get("file_path")
        if not session_id or not isinstance(raw_path, str) or not raw_path:
            return

        candidate = Path(raw_path).expanduser()
        if not candidate.is_absolute():
            candidate = Path(str(payload.get("cwd") or Path.cwd())) / candidate
        candidate = candidate.resolve(strict=True)
        knowledge_root = (_plugin_root() / "knowledge").resolve(strict=True)
        relative = candidate.relative_to(knowledge_root)
        if candidate.suffix.lower() != ".md" or len(relative.parts) < 2:
            return

        doc_id = _doc_id(candidate)
        session_path = _session_path(session_id)
        if not doc_id or session_path is None:
            return
        state = json.loads(session_path.read_text(encoding="utf-8"))
        injected = state.get("injected") if isinstance(state, dict) else None
        if not isinstance(injected, list) or doc_id not in injected:
            return

        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "session_id": session_id,
            "doc_id": doc_id,
            "event": "read_after_inject",
        }
        log_path = _state_dir() / "feedback-log.jsonl"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return
