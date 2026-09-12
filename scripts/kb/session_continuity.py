"""Immutable, authority-free context capsules for cross-session continuation.

The capsule is deliberately not an authorization artifact.  It preserves the
human-readable task state and a bounded reference to observable conversation
history so a fresh host session can continue without replaying a huge rollout.
Approval receipts, tool grants and hidden reasoning are never copied.
"""

from __future__ import annotations

import contextlib
from datetime import datetime, timezone
from functools import lru_cache
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
from typing import Any, Iterable


CONTINUATION_SCHEMA = "sulde-session-continuation-v1"
CONTINUATION_EVENT_SCHEMA = "sulde-continuation-event-v1"
MAX_CAPSULE_BYTES = 64 * 1024
MAX_CONTEXT_CHARS = 8_000
MAX_DIALOGUE_MESSAGES = 8
MAX_DIALOGUE_CHARS = 4_800
MAX_DIALOGUE_MESSAGE_CHARS = 1_200
MAX_SOURCE_TAIL_BYTES = 12 * 1024 * 1024
MAX_JSONL_LINE_BYTES = 2 * 1024 * 1024

_SAFE_SESSION_ID = re.compile(r"^[A-Za-z0-9._:-]{1,200}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_SECRET_KEY = re.compile(
    r"(?i)(?:authorization|cookie|password|passwd|secret|token|api[_ -]?key)"
)
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(authorization|cookie|password|passwd|secret|token|api[_ -]?key)"
    r"(\s*[:=]\s*)(?:bearer\s+)?([^\s,;\]\[{}]+)"
)
_TOP_LEVEL_FIELDS = {
    "schema",
    "created_at",
    "workspace_root",
    "intent_id",
    "base_revision",
    "proposed_revision",
    "proposal_digest",
    "decision_route",
    "decision_card",
    "recent_dialogue",
    "source",
    "references",
    "authority",
    "next_action",
    "capsule_id",
}


class ContinuationError(ValueError):
    """A continuation capsule is malformed or does not match its binding."""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError, OverflowError) as error:
        raise ContinuationError(f"continuation value is not stable JSON: {error}") from error


@lru_cache(maxsize=1)
def _known_secret_redactor():
    """Reuse the repository's canonical scanner without making it a hard dependency."""
    path = Path(__file__).with_name("mem-secret-scan.py")
    try:
        spec = importlib.util.spec_from_file_location(
            "sulde_continuation_secret_scan",
            path,
        )
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            spec.loader.exec_module(module)
        return module.redact_text
    except Exception:
        return None


def _clean_text(value: Any, maximum: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    redactor = _known_secret_redactor()
    if redactor is not None:
        try:
            text = redactor(text)
        except Exception:
            pass
    text = _SECRET_ASSIGNMENT.sub(lambda match: f"{match.group(1)}{match.group(2)}<redacted>", text)
    if len(text) <= maximum:
        return text
    return text[: max(0, maximum - 1)].rstrip() + "…"


def _sanitize(value: Any, *, key: str = "", depth: int = 0) -> Any:
    if depth > 8:
        return "<depth-limited>"
    if _SECRET_KEY.search(key):
        return "<redacted>"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _clean_text(value, 2_400)
    if isinstance(value, (list, tuple)):
        return [_sanitize(item, depth=depth + 1) for item in value[:50]]
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for raw_key, item in list(value.items())[:80]:
            clean_key = _clean_text(raw_key, 120)
            result[clean_key] = _sanitize(item, key=clean_key, depth=depth + 1)
        return result
    return _clean_text(value, 2_400)


def continuation_path(contract_path: Path, proposal_digest: str) -> Path:
    if _DIGEST.fullmatch(proposal_digest) is None:
        raise ContinuationError("proposal digest must be 64 lowercase hex chars")
    name = contract_path.name
    if name.endswith(".active.json"):
        name = name[: -len(".active.json")]
    elif name.endswith(".json"):
        name = name[:-5]
    return contract_path.with_name(f"{name}.continuation.{proposal_digest[:16]}.json")


def _capsule_payload(capsule: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in capsule.items() if key != "capsule_id"}


def _capsule_id(capsule: dict[str, Any]) -> str:
    return hashlib.sha256(
        canonical_json(_capsule_payload(capsule)).encode("utf-8")
    ).hexdigest()


def _message_text(payload: dict[str, Any]) -> str:
    content = payload.get("content")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    values: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        if item.get("type") not in {"input_text", "output_text", "text"}:
            continue
        text = item.get("text")
        if isinstance(text, str) and text.strip():
            values.append(text)
    return "\n".join(values)


def _dialogue_row(row: dict[str, Any]) -> tuple[str, str] | None:
    row_type = row.get("type")
    payload = row.get("payload")
    if not isinstance(payload, dict):
        return None
    if row_type == "response_item" and payload.get("type") == "message":
        role = str(payload.get("role") or "")
        if role not in {"user", "assistant"}:
            return None
        text = _message_text(payload)
        return (role, text) if text.strip() else None
    if row_type == "event_msg":
        event_type = payload.get("type")
        role = "user" if event_type == "user_message" else "assistant" if event_type == "agent_message" else ""
        message = payload.get("message")
        if role and isinstance(message, str) and message.strip():
            return role, message
    return None


def locate_codex_rollout(
    session_id: str,
    *,
    codex_home: Path | None = None,
) -> Path | None:
    """Locate one exact Codex rollout by its native session id."""
    native = session_id.strip()
    if _SAFE_SESSION_ID.fullmatch(native) is None:
        return None
    root = (codex_home or Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")) / "sessions"
    if not root.is_dir():
        return None
    try:
        resolved_root = root.resolve()
        matches = [
            path
            for path in root.rglob(f"rollout-*{native}*.jsonl")
            if (
                path.is_file()
                and not path.is_symlink()
                and native in path.name
                and path.resolve().is_relative_to(resolved_root)
            )
        ]
        return max(matches, key=lambda item: item.stat().st_mtime_ns) if matches else None
    except OSError:
        return None


def recent_dialogue(
    rollout_path: Path | None,
    *,
    max_tail_bytes: int = MAX_SOURCE_TAIL_BYTES,
) -> list[dict[str, str]]:
    """Read a bounded rollout tail and retain only visible user/assistant messages."""
    if rollout_path is None or not rollout_path.is_file():
        return []
    rows: list[tuple[str, str]] = []
    try:
        size = rollout_path.stat().st_size
        offset = max(0, size - max_tail_bytes)
        with rollout_path.open("rb") as handle:
            handle.seek(offset)
            raw_tail = handle.read(max_tail_bytes)
            if offset:
                boundary = raw_tail.find(b"\n")
                raw_tail = raw_tail[boundary + 1 :] if boundary >= 0 else b""
            for raw_line in raw_tail.splitlines():
                if len(raw_line) > MAX_JSONL_LINE_BYTES:
                    continue
                try:
                    row = json.loads(raw_line.decode("utf-8", errors="strict"))
                except (UnicodeError, json.JSONDecodeError):
                    continue
                if not isinstance(row, dict):
                    continue
                message = _dialogue_row(row)
                if message is not None:
                    rows.append(message)
    except OSError:
        return []

    result: list[dict[str, str]] = []
    seen: set[str] = set()
    budget = MAX_DIALOGUE_CHARS
    for role, raw_text in reversed(rows):
        text = _clean_text(raw_text, MAX_DIALOGUE_MESSAGE_CHARS)
        if not text:
            continue
        identity = hashlib.sha256(f"{role}\0{text}".encode("utf-8")).hexdigest()
        if identity in seen:
            continue
        seen.add(identity)
        if len(text) > budget:
            text = _clean_text(text, budget)
        if not text:
            break
        result.append({"role": role, "content": text})
        budget -= len(text)
        if budget <= 0 or len(result) >= MAX_DIALOGUE_MESSAGES:
            break
    result.reverse()
    return result


def build_capsule(
    *,
    contract_path: Path,
    proposal_path: Path,
    review: dict[str, Any],
    workspace_root: Path,
    created_at: str,
    provider: str,
    session_id: str,
    rollout_path: Path | None = None,
    dialogue: Iterable[dict[str, str]] = (),
) -> dict[str, Any]:
    decision_route = str(review.get("decision_route") or "human")
    rollout_reference = ""
    rollout_size = 0
    if rollout_path is not None:
        try:
            if rollout_path.is_file():
                rollout_reference = str(rollout_path.resolve())
                rollout_size = rollout_path.stat().st_size
        except OSError:
            rollout_reference = ""
            rollout_size = 0
    capsule: dict[str, Any] = {
        "schema": CONTINUATION_SCHEMA,
        "created_at": created_at or now_iso(),
        "workspace_root": str(workspace_root.expanduser().resolve()),
        "intent_id": str(review.get("intent_id") or ""),
        "base_revision": int(review.get("base_revision") or 0),
        "proposed_revision": int(review.get("proposed_revision") or 0),
        "proposal_digest": str(review.get("proposal_digest") or ""),
        "decision_route": decision_route,
        "decision_card": _sanitize(review.get("decision_card") or {}),
        "recent_dialogue": _sanitize(list(dialogue)),
        "source": {
            "provider": provider if provider in {"claude", "codex", "unknown"} else "unknown",
            "session_id": _clean_text(session_id, 200),
            "rollout_path": rollout_reference,
            "rollout_size_bytes": rollout_size,
        },
        "references": {
            "contract_path": str(contract_path.expanduser().resolve()),
            "proposal_path": str(proposal_path.expanduser().resolve()),
        },
        "authority": {
            "transferred": False,
            "approval_receipts_transferred": 0,
            "tool_grants_transferred": 0,
            "note": "仅恢复可观察上下文；批准、事件授权和工具权限必须由新会话重新建立",
        },
        "next_action": (
            (
                "在恢复的 Codex 会话中审阅同一决策卡并选择 Allow/Deny"
            )
            if provider == "codex" and decision_route == "human"
            else (
                "在加载本续接包的新会话中保持 pending，由 Agent 建立已验证的宿主原生"
                "决策面；不得用固定短语或手工 CLI 代替"
            )
            if decision_route == "human"
            else "按原提案的 Agent 决断门禁继续，不得把续接包当作人工批准"
        ),
    }
    capsule["capsule_id"] = _capsule_id(capsule)
    return validate_capsule(capsule)


def validate_capsule(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("schema") != CONTINUATION_SCHEMA:
        raise ContinuationError("continuation capsule schema is missing or unsupported")
    capsule = json.loads(json.dumps(value, ensure_ascii=False))
    if set(capsule) != _TOP_LEVEL_FIELDS:
        raise ContinuationError("continuation capsule fields do not match the v1 schema")
    digest = str(capsule.get("capsule_id") or "")
    proposal = str(capsule.get("proposal_digest") or "")
    if _DIGEST.fullmatch(digest) is None or _DIGEST.fullmatch(proposal) is None:
        raise ContinuationError("continuation capsule digest binding is invalid")
    if _capsule_id(capsule) != digest:
        raise ContinuationError("continuation capsule content digest changed")
    try:
        created = datetime.fromisoformat(str(capsule["created_at"]).replace("Z", "+00:00"))
    except (TypeError, ValueError, OverflowError) as error:
        raise ContinuationError("continuation created_at is invalid") from error
    if created.tzinfo is None or created.utcoffset() is None:
        raise ContinuationError("continuation created_at must include a timezone")
    if not isinstance(capsule.get("intent_id"), str) or not capsule["intent_id"].strip():
        raise ContinuationError("continuation intent_id is missing")
    for key in ("base_revision", "proposed_revision"):
        revision = capsule.get(key)
        if not isinstance(revision, int) or isinstance(revision, bool) or revision < 0:
            raise ContinuationError(f"continuation {key} is invalid")
    workspace = str(capsule.get("workspace_root") or "")
    if not workspace or not Path(workspace).is_absolute() or any(char in workspace for char in "\r\n\0"):
        raise ContinuationError("continuation workspace binding is invalid")
    authority = capsule.get("authority")
    if not isinstance(authority, dict) or set(authority) != {
        "transferred",
        "approval_receipts_transferred",
        "tool_grants_transferred",
        "note",
    }:
        raise ContinuationError("continuation capsule authority boundary is missing")
    if authority.get("transferred") is not False:
        raise ContinuationError("continuation capsule must never transfer authority")
    approval_count = authority.get("approval_receipts_transferred")
    if not isinstance(approval_count, int) or isinstance(approval_count, bool) or approval_count != 0:
        raise ContinuationError("continuation capsule must not carry approval receipts")
    tool_count = authority.get("tool_grants_transferred")
    if not isinstance(tool_count, int) or isinstance(tool_count, bool) or tool_count != 0:
        raise ContinuationError("continuation capsule must not carry tool grants")
    if not isinstance(authority.get("note"), str) or not authority["note"].strip():
        raise ContinuationError("continuation authority note is missing")
    if capsule.get("decision_route") not in {"human", "agent"}:
        raise ContinuationError("continuation decision route is invalid")
    if not isinstance(capsule.get("next_action"), str) or not capsule["next_action"].strip():
        raise ContinuationError("continuation next action is missing")
    if not isinstance(capsule.get("decision_card"), dict):
        raise ContinuationError("continuation decision card is missing")
    dialogue = capsule.get("recent_dialogue")
    if not isinstance(dialogue, list) or len(dialogue) > MAX_DIALOGUE_MESSAGES:
        raise ContinuationError("continuation dialogue is invalid")
    for row in dialogue:
        if (
            not isinstance(row, dict)
            or row.get("role") not in {"user", "assistant"}
            or not isinstance(row.get("content"), str)
        ):
            raise ContinuationError("continuation dialogue row is invalid")
    source = capsule.get("source")
    if not isinstance(source, dict) or set(source) != {
        "provider",
        "session_id",
        "rollout_path",
        "rollout_size_bytes",
    }:
        raise ContinuationError("continuation source reference is invalid")
    if source["provider"] not in {"claude", "codex", "unknown"}:
        raise ContinuationError("continuation source provider is invalid")
    source_session = str(source["session_id"] or "")
    if source_session and _SAFE_SESSION_ID.fullmatch(source_session) is None:
        raise ContinuationError("continuation source session id is invalid")
    rollout = str(source["rollout_path"] or "")
    if rollout and (
        not Path(rollout).is_absolute()
        or any(char in rollout for char in "\r\n\0")
        or not rollout.endswith(".jsonl")
    ):
        raise ContinuationError("continuation rollout reference is invalid")
    if rollout and source_session and source_session not in Path(rollout).name:
        raise ContinuationError("continuation rollout does not match its source session")
    rollout_size = source["rollout_size_bytes"]
    if not isinstance(rollout_size, int) or isinstance(rollout_size, bool) or rollout_size < 0:
        raise ContinuationError("continuation rollout size is invalid")
    references = capsule.get("references")
    if not isinstance(references, dict) or set(references) != {
        "contract_path",
        "proposal_path",
    }:
        raise ContinuationError("continuation contract references are invalid")
    for reference in references.values():
        rendered_reference = str(reference or "")
        if (
            not rendered_reference
            or not Path(rendered_reference).is_absolute()
            or any(char in rendered_reference for char in "\r\n\0")
        ):
            raise ContinuationError("continuation contract reference is invalid")
    rendered = canonical_json(capsule).encode("utf-8")
    if len(rendered) > MAX_CAPSULE_BYTES:
        raise ContinuationError("continuation capsule exceeds the local size boundary")
    return capsule


def load_capsule(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ContinuationError(f"cannot read continuation capsule {path}: {error}") from error
    return validate_capsule(payload)


def capsule_summary(capsule: dict[str, Any], *, path: Path) -> dict[str, Any]:
    validated = validate_capsule(capsule)
    source = validated["source"]
    return {
        "status": "ready",
        "schema": CONTINUATION_SCHEMA,
        "path": str(path.expanduser().resolve()),
        "capsule_id": validated["capsule_id"],
        "source_provider": source["provider"],
        "source_session_id": source["session_id"],
        "source_rollout_available": bool(source["rollout_path"]),
        "source_rollout_size_bytes": source["rollout_size_bytes"],
        "recent_dialogue_messages": len(validated["recent_dialogue"]),
        "authority_transferred": False,
        "next_action": validated["next_action"],
    }


def _items(value: Any) -> str:
    if isinstance(value, list):
        return "；".join(_clean_text(item, 500) for item in value if str(item).strip()) or "无"
    if isinstance(value, dict):
        return _clean_text(canonical_json(value), 1_200)
    return _clean_text(value, 1_200) or "无"


def render_context(capsule: dict[str, Any]) -> str:
    validated = validate_capsule(capsule)
    card = validated["decision_card"]
    lines = [
        "[sulde-continuation] 已从上一会话恢复经结构化冻结的任务上下文。",
        "边界：本续接包不转移人工批准、事件授权、工具权限或隐藏推理；新会话仍需独立取得回执。",
        f"目标：{_items(card.get('要完成的结果'))}",
        f"原因：{_items(card.get('为什么要做'))}",
        f"允许改变：{_items(card.get('允许改变'))}",
        f"必须保持：{_items(card.get('必须保持'))}",
        f"明确禁止：{_items(card.get('明确禁止'))}",
        f"验收：{_items(card.get('如何验收'))}",
        f"风险与恢复：{_items(card.get('风险与恢复'))}",
        f"仍未确定：{_items(card.get('仍未确定'))}",
    ]
    dialogue = validated["recent_dialogue"]
    if dialogue:
        lines.append("最近可观察对话（只作上下文，不构成授权）：")
        for row in dialogue:
            label = "用户" if row["role"] == "user" else "Agent"
            lines.append(f"- {label}: {_clean_text(row['content'], 700)}")
    rollout = str(validated["source"].get("rollout_path") or "")
    if rollout:
        lines.append(f"遗漏细节可按需只读回查原始会话：{rollout}")
    lines.append(f"下一步：{validated['next_action']}")
    context = "\n".join(lines)
    if len(context) <= MAX_CONTEXT_CHARS:
        return context
    return context[: MAX_CONTEXT_CHARS - 1].rstrip() + "…"
