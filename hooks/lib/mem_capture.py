"""Fast raw UserPromptSubmit capture for sulde-mem (no embedding)."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import runpy
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any


_recall_log = runpy.run_path(
    str(Path(__file__).resolve().with_name("recall_log.py"))
)
classify_recall_source = _recall_log["classify_recall_source"]
mem_recall_opportunity_key = _recall_log["mem_recall_opportunity_key"]
RECALL_LOG_FILENAME = _recall_log["LOG_FILENAME"]
_session_identity = runpy.run_path(
    str(Path(__file__).resolve().with_name("session_identity.py"))
)
normalize_session_identity = _session_identity["normalize_session_identity"]


SYSTEM_PREFIXES = (
    "<task-notification",
    "<system-reminder",
    "[task-notification]",
    "[system reminder]",
    "task-notification:",
)
ADOPTION_WINDOW = timedelta(minutes=10)
MIN_ADOPTION_FRAGMENT_CHARS = 12
ANSWER_TOKEN_RE = re.compile(
    r"(?:答案(?:是|为)|(?<![=!<>])(?:=>|->|=|→))\s*"
    r"[`'\"“”‘’]*([A-Za-z_][A-Za-z0-9_.:/+\-]*|\d+(?:\.\d+)?|[\u4e00-\u9fff]{2,20})",
    re.IGNORECASE,
)
ENGLISH_ENTITY_RE = re.compile(r"[A-Za-z][A-Za-z0-9_.+\-]{2,}")
HAN_RUN_RE = re.compile(r"[\u4e00-\u9fff]+")
ENTITY_STOPWORDS = {
    "about", "after", "before", "could", "from", "have", "into", "memory",
    "need", "problem", "question", "recall", "should", "sulde", "system",
    "that", "their", "there", "these", "they", "this", "those", "with",
}
ANSWER_STOPWORDS = ENTITY_STOPWORDS | {
    "false", "none", "null", "true", "unknown", "不是", "问题", "回答",
    "答案", "系统", "记忆", "需要", "召回",
}
HAN_GENERIC_TERMS = (
    "问题", "需要", "系统", "记忆", "召回", "这个", "那个", "一个", "已经",
    "没有", "可以", "进行", "处理", "内容", "结果", "方式", "功能", "如果",
    "因为", "所以", "然后", "以及", "是否", "什么", "怎么", "如何", "必须",
    "应该", "我们", "你们", "他们",
)


@lru_cache(maxsize=1)
def load_secret_module():
    path = Path(__file__).resolve().parents[2] / "scripts" / "kb" / "mem-secret-scan.py"
    spec = importlib.util.spec_from_file_location("sulde_mem_secret_scan", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load secret scanner: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def redact_content(content: str) -> str:
    """Redact known secret forms and report only the matched pattern names."""
    scanner = load_secret_module()
    matched = [name for name, pattern in scanner.PATTERNS if pattern.search(content)]
    if not matched:
        return content
    print(f"sulde-mem: redacted secret pattern={','.join(matched)}", file=sys.stderr)
    return scanner.redact_text(content)


def _memory_module():
    tools_dir = Path(__file__).resolve().parents[2] / "tools" / "kb-index"
    if str(tools_dir) not in sys.path:
        sys.path.insert(0, str(tools_dir))
    import memory

    return memory


def _text_content(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    pieces = []
    for item in content:
        if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str):
            pieces.append(item["text"])
    return "\n".join(pieces).strip()


def _message_text(record: dict[str, Any], role: str | None = None) -> str:
    message = record.get("message")
    if not isinstance(message, dict):
        return ""
    if role and message.get("role") != role:
        return ""
    return _text_content(message.get("content"))


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return None


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                value = json.loads(line)
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(value, dict):
                rows.append(value)
    return rows


def _append_health_event(home: Path, event: dict[str, Any]) -> None:
    """Best-effort observability without storing prompt or response bodies."""
    record = {"ts": datetime.now(timezone.utc).isoformat(), **event}
    try:
        path = home / "mem-adoption-health.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    except OSError as error:
        print(f"sulde-mem: adoption health write failed error={type(error).__name__}", file=sys.stderr)


def _latest_recall(
    path: Path,
    *,
    assistant_ts: str,
    session_id: str,
    cwd: str,
) -> dict[str, Any] | None:
    assistant_time = _parse_timestamp(assistant_ts)
    if assistant_time is None:
        return None
    try:
        rows = _read_jsonl(path)
    except OSError:
        return None
    for row in reversed(rows):
        recall_time = _parse_timestamp(row.get("ts"))
        if recall_time is None or recall_time > assistant_time:
            continue
        if assistant_time - recall_time > ADOPTION_WINDOW:
            break
        recall_session = row.get("session_id")
        if isinstance(recall_session, str) and recall_session and recall_session != session_id:
            continue
        recall_cwd = row.get("cwd")
        if isinstance(recall_cwd, str) and recall_cwd and cwd and recall_cwd != cwd:
            continue
        if classify_recall_source(row) != "mem":
            continue
        if mem_recall_opportunity_key(row) is None:
            continue
        return row
    return None


def _contains_fragment(assistant_text: str, entry_content: str) -> bool:
    if len(assistant_text) < MIN_ADOPTION_FRAGMENT_CHARS or len(entry_content) < MIN_ADOPTION_FRAGMENT_CHARS:
        return False
    assistant_fragments = {
        assistant_text[index : index + MIN_ADOPTION_FRAGMENT_CHARS]
        for index in range(len(assistant_text) - MIN_ADOPTION_FRAGMENT_CHARS + 1)
    }
    return any(
        entry_content[index : index + MIN_ADOPTION_FRAGMENT_CHARS] in assistant_fragments
        for index in range(len(entry_content) - MIN_ADOPTION_FRAGMENT_CHARS + 1)
    )


def _answer_tokens(entry_content: str) -> set[str]:
    tokens: set[str] = set()
    for match in ANSWER_TOKEN_RE.finditer(entry_content):
        token = match.group(1).strip("`'\"“”‘’.,，。:：;；!?！？()（）[]【】")
        if len(token) >= 2 and token.lower() not in ANSWER_STOPWORDS:
            tokens.add(token)
    return tokens


def _contains_token(text: str, token: str) -> bool:
    if token.isascii():
        return bool(
            re.search(
                rf"(?<![A-Za-z0-9_]){re.escape(token)}(?![A-Za-z0-9_])",
                text,
                re.IGNORECASE,
            )
        )
    return token in text


def _significant_han(token: str) -> bool:
    remainder = token
    for generic in HAN_GENERIC_TERMS:
        remainder = remainder.replace(generic, "")
    return len(remainder) >= 3 and len(set(remainder)) > 1


def _han_ngrams(text: str) -> set[str]:
    tokens: set[str] = set()
    for run in HAN_RUN_RE.findall(text):
        for size in range(3, min(len(run), 12) + 1):
            tokens.update(run[index : index + size] for index in range(len(run) - size + 1))
    return tokens


def _shared_entities(entry_content: str, assistant_text: str) -> set[str]:
    entry_english = {token.lower() for token in ENGLISH_ENTITY_RE.findall(entry_content)}
    assistant_english = {token.lower() for token in ENGLISH_ENTITY_RE.findall(assistant_text)}
    shared = {
        token for token in entry_english & assistant_english if token not in ENTITY_STOPWORDS
    }

    candidates = sorted(
        (
            token
            for token in _han_ngrams(entry_content) & _han_ngrams(assistant_text)
            if _significant_han(token)
        ),
        key=lambda token: (-len(token), token),
    )
    accepted: list[str] = []
    occupied_entry: list[tuple[int, int]] = []
    occupied_assistant: list[tuple[int, int]] = []
    for token in candidates:
        if any(token in existing for existing in accepted):
            continue
        entry_start = entry_content.find(token)
        assistant_start = assistant_text.find(token)
        entry_range = (entry_start, entry_start + len(token))
        assistant_range = (assistant_start, assistant_start + len(token))
        if any(entry_range[0] < end and start < entry_range[1] for start, end in occupied_entry):
            continue
        if any(
            assistant_range[0] < end and start < assistant_range[1]
            for start, end in occupied_assistant
        ):
            continue
        accepted.append(token)
        occupied_entry.append(entry_range)
        occupied_assistant.append(assistant_range)
    shared.update(accepted)
    return shared


def _adoption_match(assistant_text: str, entry: sqlite3.Row) -> str | None:
    if _contains_fragment(assistant_text, str(entry["content"])):
        return "exact_span"
    if any(
        isinstance(value, str) and bool(value) and value in assistant_text
        for value in (entry["ts"], entry["project"])
    ):
        return "exact_span"
    if any(_contains_token(assistant_text, token) for token in _answer_tokens(str(entry["content"]))):
        return "answer_token"
    if len(_shared_entities(str(entry["content"]), assistant_text)) >= 3:
        return "entity_overlap"
    return None


def _is_adopted(assistant_text: str, entry: sqlite3.Row) -> bool:
    return _adoption_match(assistant_text, entry) is not None


def detect_adoptions(
    connection: sqlite3.Connection,
    *,
    home: Path,
    assistant_text: str,
    assistant_ts: str,
    session_id: str,
    cwd: str,
    write: bool = True,
) -> list[dict[str, Any]]:
    """Classify the latest eligible mem injection for one assistant response."""
    recall = _latest_recall(
        home / RECALL_LOG_FILENAME,
        assistant_ts=assistant_ts,
        session_id=session_id,
        cwd=cwd,
    )
    if recall is None:
        _append_health_event(home, {
            "status": "skipped", "skip_reason": "no_latest_recall",
            "session_id": session_id,
        })
        return []
    return _classify_recall(
        connection,
        home=home,
        recall=recall,
        assistant_text=assistant_text,
        session_id=session_id,
        write=write,
    )


def _classify_recall(
    connection: sqlite3.Connection,
    *,
    home: Path,
    recall: dict[str, Any],
    assistant_text: str,
    session_id: str,
    write: bool,
) -> list[dict[str, Any]]:
    injected = recall.get("injected")
    if not isinstance(injected, list) or not injected:
        _append_health_event(home, {
            "opportunity_id": recall.get("opportunity_id"), "status": "skipped",
            "skip_reason": "empty_or_invalid_injected", "session_id": session_id,
        })
        return []
    entry_ids = [item for item in injected if isinstance(item, int) and not isinstance(item, bool)]
    if not entry_ids:
        _append_health_event(home, {
            "opportunity_id": recall.get("opportunity_id"), "status": "skipped",
            "skip_reason": "invalid_injected_ids", "session_id": session_id,
        })
        return []
    placeholders = ",".join("?" for _ in entry_ids)
    rows = connection.execute(
        f"SELECT id, project, content, ts FROM mem_entries WHERE id IN ({placeholders})",
        entry_ids,
    ).fetchall()
    entries = {int(row["id"]): row for row in rows}
    detected_at = datetime.now(timezone.utc).isoformat()
    events = []
    for entry_id in entry_ids:
        matched_by = (
            _adoption_match(assistant_text, entries[entry_id]) if entry_id in entries else None
        )
        events.append({
            "ts": detected_at,
            "session_id": session_id,
            "recall_ts": recall.get("ts"),
            "entry_id": entry_id,
            "verdict": "adopted" if matched_by else "ignored",
            "matched_by": matched_by,
            "opportunity_id": recall.get("opportunity_id"),
            "channel": recall.get("channel", "unknown"),
        })
    if write and events:
        try:
            path = home / "mem-adoption-log.jsonl"
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as stream:
                for event in events:
                    stream.write(json.dumps(event, ensure_ascii=False) + "\n")
        except OSError as error:
            _append_health_event(home, {
                "opportunity_id": recall.get("opportunity_id"), "status": "write_failed",
                "error": type(error).__name__, "session_id": session_id,
            })
        else:
            _append_health_event(home, {
                "opportunity_id": recall.get("opportunity_id"), "status": "classified",
                "session_id": session_id, "event_count": len(events),
            })
    return events


def _scan_transcript(
    connection,
    transcript: Path,
    session_id: str,
    project: str,
    memory,
    *,
    source_host: str = "unknown",
    cwd: str = "",
) -> int:
    try:
        file_size = transcript.stat().st_size
        row = connection.execute(
            "SELECT byte_offset FROM mem_capture_state WHERE transcript_path = ?",
            (str(transcript),),
        ).fetchone()
        offset = min(int(row["byte_offset"]) if row else 0, file_size)
        records: list[dict[str, Any]] = []
        with transcript.open("rb") as stream:
            stream.seek(offset)
            for raw_line in stream:
                try:
                    record = json.loads(raw_line.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
                if isinstance(record, dict):
                    records.append(record)
            new_offset = stream.tell()
    except OSError:
        return 0

    inserted = 0
    last_assistant: tuple[str, str] | None = None
    for record in records:
        text = _message_text(record, "assistant")
        if text:
            last_assistant = (text, str(record.get("timestamp") or ""))
        is_summary = bool(record.get("isCompactSummary"))
        message = record.get("message")
        if isinstance(message, dict):
            is_summary = is_summary or bool(message.get("isCompactSummary"))
        if is_summary:
            summary = _message_text(record)
            if (
                summary
                and not memory.is_noise_content(summary, "summary")
                and memory.add_entry(
                    connection,
                    project=project,
                    session_id=session_id,
                    source_host=source_host,
                    role="summary",
                    content=redact_content(summary),
                    ts=str(record.get("timestamp") or datetime.now(timezone.utc).isoformat()),
                )
                is not None
            ):
                inserted += 1
    if (
        last_assistant
        and not memory.is_noise_content(last_assistant[0], "assistant")
        and memory.add_entry(
            connection,
            project=project,
            session_id=session_id,
            source_host=source_host,
            role="assistant",
            content=redact_content(last_assistant[0]),
            ts=last_assistant[1] or datetime.now(timezone.utc).isoformat(),
        )
        is not None
    ):
        inserted += 1
    if last_assistant:
        detect_adoptions(
            connection,
            home=memory.memory_db_path().parent,
            assistant_text=last_assistant[0],
            assistant_ts=last_assistant[1],
            session_id=session_id,
            cwd=cwd,
        )
    connection.execute(
        "INSERT OR REPLACE INTO mem_capture_state(transcript_path, byte_offset) VALUES (?, ?)",
        (str(transcript), new_offset),
    )
    return inserted


def run(payload: dict[str, Any]) -> int:
    """Capture current user prompt, prior assistant text, and compact summaries."""
    try:
        memory = _memory_module()
        database = memory.memory_db_path()
        if not database.is_file():
            return 0
        prompt = str(payload.get("prompt") or "").strip()
        capture_prompt = bool(prompt) and not prompt.lower().startswith(SYSTEM_PREFIXES) and not memory.is_noise_content(prompt, "user")
        raw_session_id = str(
            payload.get("session_id") or payload.get("sessionId") or ""
        )
        session_id, source_host = normalize_session_identity(
            raw_session_id,
            payload.get("client") or "claude",
        )
        if not session_id:
            return 0
        cwd = Path(str(payload.get("cwd") or os.getcwd()))
        project = cwd.name or "unknown"
        now = datetime.now(timezone.utc).isoformat()
        connection = memory.connect(database)
        inserted = 0
        try:
            if capture_prompt and memory.add_entry(
                connection,
                project=project,
                session_id=session_id,
                source_host=source_host,
                role="user",
                content=redact_content(prompt),
                ts=now,
            ) is not None:
                inserted += 1
            transcript_value = payload.get("transcript_path")
            if transcript_value:
                inserted += _scan_transcript(
                    connection,
                    Path(str(transcript_value)).expanduser(),
                    session_id,
                    project,
                    memory,
                    source_host=source_host,
                    cwd=str(cwd),
                )
            else:
                _append_health_event(database.parent, {
                    "status": "skipped", "skip_reason": "no_transcript",
                    "session_id": session_id,
                })
            connection.commit()
        finally:
            connection.close()
        return inserted
    except (OSError, ValueError, TypeError, sqlite3.Error):
        return 0


def replay(home: Path, now: datetime | None = None) -> dict[str, int | float | str | None]:
    """Read-only best-effort replay using the nearest project assistant within ten minutes."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    cutoff = now - timedelta(days=7)
    database = home / "memory.db"
    recalls = [
        row
        for row in _read_jsonl(home / RECALL_LOG_FILENAME)
        if (timestamp := _parse_timestamp(row.get("ts"))) is not None
        and cutoff <= timestamp <= now
        and classify_recall_source(row) == "mem"
        and mem_recall_opportunity_key(row) is not None
        and isinstance(row.get("injected"), list)
        and row["injected"]
    ]
    adopted = ignored = unmatched = 0
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True, timeout=0.2)
    try:
        connection.row_factory = sqlite3.Row
        for recall in recalls:
            recall_time = _parse_timestamp(recall.get("ts"))
            project = Path(str(recall.get("cwd") or "")).name
            assistant = connection.execute(
                """
                SELECT content, ts FROM mem_entries
                WHERE role = 'assistant' AND project = ?
                  AND datetime(ts) >= datetime(?) AND datetime(ts) <= datetime(?)
                ORDER BY ts LIMIT 1
                """,
                (
                    project,
                    recall_time.isoformat() if recall_time else "",
                    (recall_time + ADOPTION_WINDOW).isoformat() if recall_time else "",
                ),
            ).fetchone()
            if assistant is None:
                unmatched += len(recall["injected"])
                continue
            events = _classify_recall(
                connection,
                home=home,
                recall=recall,
                assistant_text=str(assistant["content"]),
                session_id="replay",
                write=False,
            )
            adopted += sum(event["verdict"] == "adopted" for event in events)
            ignored += sum(event["verdict"] == "ignored" for event in events)
    finally:
        connection.close()
    total = adopted + ignored
    return {
        "window_days": 7,
        "adopted": adopted,
        "ignored": ignored,
        "unmatched": unmatched,
        "rate": adopted / total if total else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replay", action="store_true", help="read-only replay for the last seven days")
    parser.add_argument("--home", type=Path, help="KB home override for replay")
    args = parser.parse_args()
    if not args.replay:
        parser.error("--replay is required")
    try:
        print(json.dumps(replay(args.home or _memory_module().kb_home()), ensure_ascii=False, sort_keys=True))
        return 0
    except (OSError, sqlite3.Error, ValueError) as error:
        print(f"ERROR mem replay: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
