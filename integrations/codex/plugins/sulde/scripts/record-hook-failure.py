#!/usr/bin/env python3
"""Write one redacted Hook failure receipt without affecting host execution."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys

sys.dont_write_bytecode = True

from _adapter_common import normalize_codex_session, runtime_root


EVENT_NAMES = {
    "session-start": "SessionStart",
    "user-prompt-submit": "UserPromptSubmit",
    "permission-request": "PermissionRequest",
    "post-tool-use": "PostToolUse",
    "stop": "Stop",
}


def _artifact_identity() -> tuple[str, str]:
    plugin_root = Path(__file__).resolve().parents[1]
    adapter = plugin_root / "scripts" / "_adapter_common.py"
    try:
        loaded = hashlib.sha256(adapter.read_bytes()).hexdigest()
    except OSError:
        loaded = "unknown"
    generation_path = plugin_root / ".codex-plugin" / "generation.json"
    try:
        generation = json.loads(generation_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return loaded, "unknown"
    artifact = str(generation.get("generation") or "").strip()
    return loaded, artifact or "unknown"


def main() -> int:
    if len(sys.argv) != 5 or sys.argv[1] not in EVENT_NAMES:
        return 0
    hook, stage, error_kind, raw_exit_code = sys.argv[1:]
    try:
        exit_code = int(raw_exit_code)
    except ValueError:
        exit_code = None
    payload: dict[str, object] = {}
    normalize_codex_session(payload)
    loaded, artifact = _artifact_identity()
    try:
        runtime_kb = runtime_root() / "scripts" / "kb"
        sys.path.insert(0, str(runtime_kb))
        from host_capabilities import record_hook_failure

        workspace = os.getcwd()
        session_id = str(payload.get("session_id") or "")
        if session_id:
            try:
                from intent_guardian_parts.session_workspace import load_session_workspace

                mapping_home = Path(
                    os.environ.get("SULDE_KB_HOME")
                    or Path.home() / ".sulde" / "data" / "kb"
                ).expanduser()
                mapping = load_session_workspace(
                    mapping_home, "codex", session_id
                )
            except (ImportError, OSError, UnicodeError, ValueError, RuntimeError):
                mapping = None
            if isinstance(mapping, dict) and mapping.get("workspace_root"):
                workspace = str(mapping["workspace_root"])

        record_hook_failure(
            provider="codex",
            hook_event=EVENT_NAMES[hook],
            stage=stage,
            error_kind=error_kind,
            session_id=session_id,
            workspace=workspace,
            exit_code=exit_code,
            loaded_module_generation=loaded,
            artifact_generation=artifact,
        )
    except BaseException:
        # This is the final diagnostic fallback. It must not become a second
        # Hook failure or change the native host decision.
        print("sulde: legacy_hook_failure_delivery_unavailable; action_not_retried", file=sys.stderr)
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
