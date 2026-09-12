"""Shared append and classification contract for recall-log.jsonl."""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal


LOG_FILENAME = "recall-log.jsonl"

_COMMON_FIELDS = {
    "ts",
    "cwd",
    "query_head",
    "platform",
    "top_scores",
    "injected",
}
_KB_REQUIRED_FIELDS = _COMMON_FIELDS | {"source", "cli_status"}
_KB_OPTIONAL_FIELDS = {"cli_detail"}
_SOURCE_FIELD = {"source"}
_CLASSIFIED_KB_REQUIRED_FIELDS = _COMMON_FIELDS | _SOURCE_FIELD
_CLASSIFIED_KB_FIELDS = _CLASSIFIED_KB_REQUIRED_FIELDS | {
    "cli_status",
    "cli_detail",
}
_MEM_ENVELOPE_FIELDS = {"session_id", "channel", "opportunity_id"}
_MEM_HOST_FIELD = {"source_host"}
_CLASSIFIED_MEM_REQUIRED_FIELDS = _COMMON_FIELDS | _SOURCE_FIELD
_LEGACY_MEM_FIELDS = _CLASSIFIED_MEM_REQUIRED_FIELDS | _MEM_ENVELOPE_FIELDS
_MEM_FIELDS = _LEGACY_MEM_FIELDS | _MEM_HOST_FIELD
_LEGACY_KB_OPTIONAL_FIELDS = {"cli_status", "cli_detail"}
_OPPORTUNITY_ID_RE = re.compile(r"^[0-9a-f]{20}$")


def _timestamp_is_aware_iso(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError, OverflowError):
        return False
    return (
        parsed.tzinfo is not None
        and parsed.utcoffset() is not None
        and parsed.utcoffset() == timedelta(0)
    )


def _is_finite_number(value: Any) -> bool:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    try:
        return math.isfinite(value)
    except (TypeError, ValueError, OverflowError):
        return False


def _valid_common(row: dict[str, Any]) -> bool:
    return (
        _timestamp_is_aware_iso(row.get("ts"))
        and isinstance(row.get("cwd"), str)
        and isinstance(row.get("query_head"), str)
        and len(row["query_head"]) <= 40
        and (row.get("platform") is None or isinstance(row.get("platform"), str))
        and isinstance(row.get("top_scores"), list)
        and all(_is_finite_number(score) for score in row["top_scores"])
        and isinstance(row.get("injected"), list)
    )


def _valid_cli_fields(row: dict[str, Any], *, required: bool) -> bool:
    status = row.get("cli_status")
    if required and (not isinstance(status, str) or not status):
        return False
    if "cli_status" in row and (not isinstance(status, str) or not status):
        return False
    detail = row.get("cli_detail")
    return "cli_detail" not in row or (
        isinstance(detail, str) and len(detail) <= 500
    )


def _opportunity_id(
    channel: str,
    session_id: str,
    cwd: str,
    timestamp: str,
) -> str:
    return hashlib.sha256(
        f"{channel}\0{session_id}\0{cwd}\0{timestamp}".encode("utf-8")
    ).hexdigest()[:20]


def _valid_mem_envelope(row: dict[str, Any]) -> bool:
    return (
        _MEM_ENVELOPE_FIELDS <= set(row)
        and isinstance(row.get("session_id"), str)
        and isinstance(row.get("channel"), str)
        and isinstance(row.get("opportunity_id"), str)
        and _OPPORTUNITY_ID_RE.fullmatch(row["opportunity_id"]) is not None
        and (
            "source_host" not in row
            or row.get("source_host") in {"claude", "codex", "unknown"}
        )
        and row["opportunity_id"]
        == _opportunity_id(
            row["channel"], row["session_id"], row["cwd"], row["ts"]
        )
    )


def classify_recall_source(row: Any) -> Literal["kb", "mem"] | None:
    """Classify a current or historical row without upgrading its contract.

    Explicit invalid sources never fall back to shape inference.  A historical mem
    v0 row remains a mem row even though it lacks the current adoption envelope.
    Source-less rows are accepted only when they exactly match the old KB writer.
    """
    if not isinstance(row, dict):
        return None
    if "source" in row:
        source = row.get("source")
        if source == "kb":
            if not (
                _CLASSIFIED_KB_REQUIRED_FIELDS
                <= set(row)
                <= _CLASSIFIED_KB_FIELDS
                and _valid_common(row)
                and _valid_cli_fields(row, required=False)
                and all(isinstance(value, str) for value in row["injected"])
            ):
                return None
            return "kb"
        if source == "mem":
            if not (
                _CLASSIFIED_MEM_REQUIRED_FIELDS <= set(row) <= _MEM_FIELDS
                and _valid_common(row)
                and (
                    "source_host" not in row
                    or row.get("source_host") in {"claude", "codex", "unknown"}
                )
                and all(
                    isinstance(value, int) and not isinstance(value, bool)
                    for value in row["injected"]
                )
            ):
                return None
            return "mem"
        return None

    fields = set(row)
    if not (
        _COMMON_FIELDS <= fields <= _COMMON_FIELDS | _LEGACY_KB_OPTIONAL_FIELDS
        and _valid_common(row)
        and _valid_cli_fields(row, required=False)
        and all(isinstance(value, str) for value in row["injected"])
    ):
        return None
    return "kb"


def validate_current_recall_record(row: Any) -> bool:
    """Validate the strict contract emitted by current production writers."""
    if not isinstance(row, dict):
        return False
    if row.get("source") == "kb":
        return (
            _KB_REQUIRED_FIELDS
            <= set(row)
            <= _KB_REQUIRED_FIELDS | _KB_OPTIONAL_FIELDS
            and _valid_common(row)
            and _valid_cli_fields(row, required=True)
            and all(isinstance(value, str) for value in row["injected"])
        )
    if row.get("source") == "mem":
        return (
            set(row) == _MEM_FIELDS
            and _valid_common(row)
            and all(
                isinstance(value, int) and not isinstance(value, bool)
                for value in row["injected"]
            )
            and _valid_mem_envelope(row)
        )
    return False


def mem_recall_opportunity_key(row: Any) -> str | None:
    """Return an eligible v1 ID or the timestamp fallback for a mem v0 row."""
    if classify_recall_source(row) != "mem":
        return None
    envelope_fields = _MEM_ENVELOPE_FIELDS & set(row)
    if not envelope_fields:
        return f"legacy:{row['ts']}"
    if envelope_fields != _MEM_ENVELOPE_FIELDS or not _valid_mem_envelope(row):
        return None
    return row["opportunity_id"]


def _append(home: Any, record: dict[str, Any]) -> bool:
    try:
        if not validate_current_recall_record(record):
            return False
        path = Path(home) / LOG_FILENAME
        path.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(record, ensure_ascii=False, allow_nan=False)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(encoded + "\n")
        return True
    except Exception:
        return False


def append_kb_recall(
    home: Any,
    *,
    cwd: Any,
    query: Any,
    platform: Any,
    top_scores: Any,
    injected: Any,
    cli_status: Any,
    cli_detail: Any = "",
) -> bool:
    """Append one strict KB row without allowing logging failure to escape."""
    try:
        if not isinstance(query, str) or not isinstance(cli_detail, str):
            return False
        record: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "cwd": cwd,
            "query_head": query[:40],
            "platform": platform,
            "top_scores": top_scores,
            "injected": injected,
            "source": "kb",
            "cli_status": cli_status,
        }
        if cli_detail:
            record["cli_detail"] = cli_detail[-500:]
        return _append(home, record)
    except Exception:
        return False


def append_mem_recall(
    home: Any,
    *,
    cwd: Any,
    query: Any,
    top_scores: Any,
    injected: Any,
    session_id: Any,
    channel: Any,
    source_host: Any = "unknown",
) -> bool:
    """Append one strict memory row and preserve its stable opportunity ID scheme."""
    try:
        if not isinstance(query, str) or not all(
            isinstance(value, str)
            for value in (cwd, session_id, channel, source_host)
        ):
            return False
        if source_host == "unknown" and channel in {"claude", "codex"}:
            source_host = channel
        if source_host not in {"claude", "codex", "unknown"}:
            return False
        timestamp = datetime.now(timezone.utc).isoformat()
        record = {
            "ts": timestamp,
            "cwd": cwd,
            "query_head": query[:40],
            "platform": None,
            "top_scores": top_scores,
            "injected": injected,
            "source": "mem",
            "session_id": session_id,
            "channel": channel,
            "source_host": source_host,
            "opportunity_id": _opportunity_id(channel, session_id, cwd, timestamp),
        }
        return _append(home, record)
    except Exception:
        return False
