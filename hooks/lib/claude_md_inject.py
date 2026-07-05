"""claude_md_inject — SessionStart hook.

Injects the top N lines of the project CLAUDE.md into the session via the
`additionalContext` field of the SessionStart hook payload (Q2 protocol-
verified 2026-05-25; the `statusMessage` field is NOT part of the official
protocol — first WebFetch report was wrong, second WebFetch confirmed).

Also runs optional baseline / health scripts and includes their stdout
prefixed with a banner so the agent can see project state at session
start without polling.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from sulde_common import SuldeConfig

DEFAULT_INJECT_LINES = 60


def run(config: SuldeConfig, payload: dict[str, Any]) -> None:
    _ = payload  # SessionStart payload currently unused but kept for symmetry
    sections: list[str] = []

    claude_md = config.project_root / "CLAUDE.md"
    if claude_md.exists():
        lines_n = _inject_lines_setting(config)
        head = _read_head(claude_md, lines_n)
        sections.append(
            f"# CLAUDE.md head ({lines_n} lines) — for full content cat CLAUDE.md\n"
            f"{head}"
        )

    baseline_out = _run_optional_script(config, "baseline_script")
    if baseline_out:
        sections.append(f"# baseline\n{baseline_out}")

    health_out = _run_optional_script(config, "health_script")
    if health_out:
        sections.append(f"# health\n{health_out}")

    if not sections:
        sys.exit(0)

    additional_context = "\n\n---\n\n".join(sections)
    payload_out = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": additional_context,
        }
    }
    sys.stdout.write(json.dumps(payload_out, ensure_ascii=False) + "\n")
    sys.exit(0)


# ─── helpers ────────────────────────────────────────────────────────────────

def _inject_lines_setting(config: SuldeConfig) -> int:
    raw = config.raw.get("session_baseline", {}) if isinstance(config.raw, dict) else {}
    value = raw.get("claude_md_inject_lines", DEFAULT_INJECT_LINES) if isinstance(raw, dict) else DEFAULT_INJECT_LINES
    try:
        n = int(value)
    except (TypeError, ValueError):
        n = DEFAULT_INJECT_LINES
    return max(1, min(n, 500))


def _read_head(path: Path, n: int) -> str:
    try:
        with path.open("r", encoding="utf-8") as fh:
            head_lines = [next(fh, None) for _ in range(n)]
    except OSError:
        return ""
    return "".join(line for line in head_lines if line is not None)


def _run_optional_script(config: SuldeConfig, key: str) -> str:
    raw = config.raw.get("session_baseline", {}) if isinstance(config.raw, dict) else {}
    if not isinstance(raw, dict):
        return ""
    script = raw.get(key)
    if not script:
        return ""
    script_path = Path(str(script))
    if not script_path.is_absolute():
        script_path = (config.project_root / script_path).resolve()
    if not script_path.exists():
        return ""
    try:
        proc = subprocess.run(
            ["bash", str(script_path)],
            cwd=str(config.project_root),
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"(sulde: {key} failed: {exc})"
    out = proc.stdout.strip()
    if not out and proc.returncode != 0:
        return f"(sulde: {key} returned {proc.returncode})"
    return out
