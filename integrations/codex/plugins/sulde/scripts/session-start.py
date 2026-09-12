#!/usr/bin/env python3
"""Expose the existing Sulde status line through the Codex hook schema."""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True

import json
import os
import re
import subprocess
from pathlib import Path

from _adapter_common import configure_utf8_stdio, run_runtime, runtime_root


configure_utf8_stdio()

STATUS_SCRIPT = runtime_root() / "scripts" / "kb" / "sulde-statusline.py"
CANON_PATH = runtime_root() / "CANON.md"
BRIEF_LIB = runtime_root() / "hooks" / "lib"
KB_LIB = runtime_root() / "scripts" / "kb"
# codex TUI 会剥掉 ANSI 颜色(控制序列被过滤),emoji 是字符能存活但占 2 格且不可缩小。
# 折中:健康用小圆点保持安静,告警/故障才用大 emoji——异常时醒目是优点
PLAIN_LIGHTS = {
    "32": "🟢",
    "33": "🟡",
    "31": "🔴",
}


def _strip_ansi(value: str) -> str:
    for color, light in PLAIN_LIGHTS.items():
        value = value.replace(f"\033[{color}m●\033[0m", light)
    return re.sub(r"\033\[[0-9;]*m", "", value).strip()


def _payload() -> dict[str, object]:
    try:
        raw_payload = sys.stdin.read()
        payload = json.loads(raw_payload) if raw_payload.strip() else {}
        return payload if isinstance(payload, dict) else {}
    except (UnicodeError, json.JSONDecodeError):
        return {}


def _brief(payload: dict[str, object]) -> str:
    try:
        cwd = payload.get("cwd") if isinstance(payload, dict) else None
        sys.path.insert(0, str(BRIEF_LIB))
        import session_brief

        return session_brief.build(cwd if isinstance(cwd, str) else os.getcwd())
    except Exception:
        return ""


def _prewarm_memory() -> None:
    """Start the bounded single-writer embedding actor off the Hook hot path."""
    try:
        sys.path.insert(0, str(BRIEF_LIB))
        import mem_recall

        mem_recall.prewarm()
    except Exception:
        return


def _continuation(payload: dict[str, object]) -> str:
    try:
        sys.path.insert(0, str(KB_LIB))
        from intent_guardian import continuation_context, kb_home

        cwd = payload.get("cwd")
        session_id = payload.get("session_id") or payload.get("sessionId")
        return continuation_context(
            kb_home(),
            Path(cwd if isinstance(cwd, str) else os.getcwd()),
            provider="codex",
            session_id=str(session_id or os.environ.get("CODEX_THREAD_ID") or ""),
        )
    except Exception:
        return ""


def _decision_request(payload: dict[str, object]) -> str:
    try:
        sys.path.insert(0, str(KB_LIB))
        from intent_guardian import decision_request_context, kb_home

        cwd = payload.get("cwd")
        session_id = payload.get("session_id") or payload.get("sessionId")
        return decision_request_context(
            kb_home(),
            Path(cwd if isinstance(cwd, str) else os.getcwd()),
            provider="codex",
            session_id=str(session_id or os.environ.get("CODEX_THREAD_ID") or ""),
        )
    except Exception:
        return ""


def _observe(payload: dict[str, object]) -> None:
    try:
        sys.path.insert(0, str(KB_LIB))
        from host_capabilities import record_hook_observation

        record_hook_observation(
            payload,
            provider="codex",
            hook_event="SessionStart",
        )
    except Exception:
        # Readiness telemetry is deliberately non-authorizing and must not
        # break SessionStart context injection.
        return


def main() -> int:
    payload = _payload()
    _observe(payload)
    _prewarm_memory()
    try:
        completed = run_runtime(STATUS_SCRIPT, timeout=1.0, args=("--statusline",))
        if completed.stderr:
            sys.stderr.write(completed.stderr)
        # An unhealthy status probe deliberately exits non-zero, but its
        # red/degraded line is still the most precise diagnosis for the host.
        raw_line = completed.stdout.strip()
    except subprocess.TimeoutExpired:
        raw_line = "sulde \033[33m●\033[0m 状态快照读取超时"
    except OSError:
        raw_line = "sulde \033[31m●\033[0m 状态入口不可用"

    # stderr 一行 = codex TUI 会话开头的可见状态灯(cognee 同款机制)
    line = _strip_ansi(raw_line) or "sulde 🟡(状态快照无输出)"
    print(line, file=sys.stderr)

    # 法典:任何项目每个会话无条件注入(与 CC 端 canon_inject 对等)
    context = line
    try:
        canon = CANON_PATH.read_text(encoding="utf-8").strip()[:4000]
        if canon:
            context = f"{line}\n\n[sulde-canon]\n{canon}"
    except OSError:
        pass

    continuation = _continuation(payload)
    if continuation:
        context = f"{context}\n\n{continuation}"

    decision_request = _decision_request(payload)
    if decision_request:
        context = f"{context}\n\n{decision_request}"

    brief = _brief(payload)
    if brief:
        context = f"{context}\n\n{brief}"

    output = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": context,
        }
    }
    print(json.dumps(output, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
