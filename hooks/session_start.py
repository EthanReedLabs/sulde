#!/usr/bin/env python3
"""sulde SessionStart entrypoint.

Injects CLAUDE.md head + optional baseline / health output as
`additionalContext` so the session starts with current project state.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE / "lib"))
sys.path.insert(0, str(_HERE.parent / "scripts" / "kb"))

from sulde_common import read_json_stdin, silent_exit_if_no_config  # noqa: E402

import kb_freshness  # noqa: E402
import kb_stale_session  # noqa: E402
import mem_recall  # noqa: E402
from host_capabilities import record_hook_observation  # noqa: E402

try:
    import yaml  # noqa: F401
    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False

import claude_md_inject  # noqa: E402


def _emit_session_brief(payload: dict[str, object]) -> None:
    """Emit an independent block so brief failures cannot affect other hooks."""
    try:
        import session_brief

        cwd = payload.get("cwd")
        brief = session_brief.build(cwd if isinstance(cwd, str) else os.getcwd())
        if brief:
            output = {
                "hookSpecificOutput": {
                    "hookEventName": "SessionStart",
                    "additionalContext": brief,
                }
            }
            print(json.dumps(output, ensure_ascii=False))
    except Exception:
        pass


def _emit_continuation(payload: dict[str, object]) -> None:
    """Restore bounded task context without treating it as authorization."""
    try:
        from intent_guardian import continuation_context, kb_home

        cwd = payload.get("cwd")
        session_id = payload.get("session_id") or payload.get("sessionId")
        context = continuation_context(
            kb_home(),
            Path(cwd if isinstance(cwd, str) else os.getcwd()),
            provider="claude",
            session_id=str(session_id or ""),
        )
        if context:
            output = {
                "hookSpecificOutput": {
                    "hookEventName": "SessionStart",
                    "additionalContext": context,
                }
            }
            print(json.dumps(output, ensure_ascii=False))
    except Exception:
        # SessionStart remains fail-open for context recovery; authority stays
        # fail-closed in UserPromptSubmit/PreToolUse.
        pass


def _emit_decision_request(payload: dict[str, object]) -> None:
    """Restore the readable question; never restore an approval receipt."""
    try:
        from intent_guardian import decision_request_context, kb_home

        cwd = payload.get("cwd")
        session_id = payload.get("session_id") or payload.get("sessionId")
        context = decision_request_context(
            kb_home(),
            Path(cwd if isinstance(cwd, str) else os.getcwd()),
            provider=str(payload.get("client") or "claude"),
            session_id=str(session_id or ""),
        )
        if context:
            print(
                json.dumps(
                    {
                        "hookSpecificOutput": {
                            "hookEventName": "SessionStart",
                            "additionalContext": context,
                        }
                    },
                    ensure_ascii=False,
                )
            )
    except Exception:
        # The write boundary remains fail-closed even when question rendering
        # is unavailable, so context restoration itself may fail open.
        pass


def main() -> int:
    payload = read_json_stdin()
    record_hook_observation(
        payload,
        provider=str(payload.get("client") or "claude"),
        hook_event="SessionStart",
    )
    mem_recall.prewarm()
    kb_stale_session.run(payload)
    kb_freshness.run(payload)
    _emit_continuation(payload)
    _emit_decision_request(payload)
    _emit_session_brief(payload)
    if not _HAS_YAML:
        return 0
    config = silent_exit_if_no_config()
    claude_md_inject.run(config, payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
