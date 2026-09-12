#!/usr/bin/env python3
"""Read-only cross-project task and session fleet view."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STALL_MINUTES = 30
MAX_JSONL_BYTES = 256 * 1024
MAX_JSONL_FILES = 8

sys.path.insert(0, str(ROOT / "tools" / "kb-index"))
from common import configure_utf8_stdio  # noqa: E402


def kb_home() -> Path:
    configured = os.environ.get("SULDE_KB_HOME")
    return Path(configured).expanduser() if configured else Path.home() / ".sulde" / "data" / "kb"


def claude_projects_home() -> Path:
    configured = os.environ.get("SULDE_CLAUDE_PROJECTS_HOME")
    return Path(configured).expanduser() if configured else Path.home() / ".claude" / "projects"


def _nested_cwd(value: Any, depth: int = 0) -> str | None:
    if depth > 4:
        return None
    if isinstance(value, dict):
        cwd = value.get("cwd")
        if isinstance(cwd, str) and cwd.startswith("/"):
            return cwd
        for nested in value.values():
            found = _nested_cwd(nested, depth + 1)
            if found:
                return found
    elif isinstance(value, list):
        for nested in value[:20]:
            found = _nested_cwd(nested, depth + 1)
            if found:
                return found
    return None


def _cwd_from_jsonl(path: Path) -> Path | None:
    try:
        consumed = 0
        with path.open(encoding="utf-8", errors="replace") as handle:
            for line in handle:
                consumed += len(line.encode("utf-8", errors="replace"))
                if consumed > MAX_JSONL_BYTES:
                    break
                try:
                    cwd = _nested_cwd(json.loads(line))
                except (json.JSONDecodeError, TypeError, ValueError):
                    continue
                if cwd:
                    candidate = Path(cwd)
                    if candidate.is_dir():
                        return candidate.resolve()
    except (OSError, UnicodeError, ValueError):
        pass
    return None


def _decode_project_dir(directory: Path) -> Path | None:
    try:
        files = sorted(directory.glob("*.jsonl"), key=lambda item: item.stat().st_mtime, reverse=True)
    except (OSError, ValueError):
        files = []
    for path in files[:MAX_JSONL_FILES]:
        cwd = _cwd_from_jsonl(path)
        if cwd:
            return cwd
    try:
        encoded = directory.name
        candidate = Path("/" + encoded[1:].replace("-", "/")) if encoded.startswith("-") else None
        if candidate is not None and candidate.is_dir():
            return candidate.resolve()
    except (OSError, ValueError):
        pass
    return None


def _registered_projects(home: Path) -> Iterable[Path]:
    try:
        payload = json.loads((home / "fleet-projects.json").read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            return []
        projects = []
        for value in payload:
            if isinstance(value, str) and value.startswith("/"):
                candidate = Path(value)
                if candidate.is_dir():
                    projects.append(candidate.resolve())
        return projects
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        return []


def discover_projects(home: Path | None = None) -> list[Path]:
    found: set[Path] = set(_registered_projects(home or kb_home()))
    try:
        directories = list(claude_projects_home().iterdir())
    except (OSError, ValueError):
        directories = []
    for directory in directories:
        try:
            if directory.is_dir():
                project = _decode_project_dir(directory)
                if project:
                    found.add(project)
        except Exception:
            continue
    return sorted(found, key=lambda item: str(item).lower())


def _parse_status(path: Path, now_ts: float, stall_seconds: int) -> dict[str, Any] | None:
    try:
        values = {}
        for token in shlex.split(path.read_text(encoding="utf-8", errors="replace")):
            key, separator, value = token.partition("=")
            if separator and key:
                values[key] = value
        status = values.get("status")
        if not status:
            return None
        modified = path.stat().st_mtime
        age = max(0, int(now_ts - modified))
        return {
            "slug": path.name[: -len(".status")],
            "status": status,
            "age_seconds": age,
            "stalled": status == "running" and age > stall_seconds,
            "updated_at": datetime.fromtimestamp(modified, timezone.utc).isoformat(),
            "fields": values,
        }
    except (OSError, UnicodeError, ValueError, OverflowError):
        return None


def _active_entries(project: Path) -> list[str]:
    try:
        lines = (project / ".codex-agent" / "ACTIVE.md").read_text(encoding="utf-8", errors="replace").splitlines()
        return [line.strip() for line in lines if line.strip() and not line.lstrip().startswith("#")]
    except (OSError, UnicodeError):
        return []


def read_project_tasks(project: Path, now_ts: float, stall_seconds: int) -> dict[str, Any]:
    try:
        status_paths = sorted((project / ".codex-agent").glob("*.status"))
    except (OSError, ValueError):
        status_paths = []
    tasks = [task for path in status_paths if (task := _parse_status(path, now_ts, stall_seconds))]
    running = [task for task in tasks if task["status"] == "running"]
    completed = sorted(
        (task for task in tasks if task["status"] == "success"),
        key=lambda task: task["updated_at"],
        reverse=True,
    )
    return {
        "name": project.name or str(project),
        "path": str(project),
        "tasks": tasks,
        "active_entries": _active_entries(project),
        "running_count": len(running),
        "stalled_count": sum(1 for task in running if task["stalled"]),
        "recent_completed": completed[0]["slug"] if completed else None,
    }


def collect_task_summary(stall_minutes: int = DEFAULT_STALL_MINUTES) -> dict[str, int]:
    """Lightweight statusline summary; deliberately never opens memory.db."""
    now_ts = datetime.now(timezone.utc).timestamp()
    running = stalled = 0
    try:
        for project in discover_projects():
            item = read_project_tasks(project, now_ts, max(0, stall_minutes) * 60)
            running += item["running_count"]
            stalled += item["stalled_count"]
    except Exception:
        pass
    return {"fleet_running": running, "fleet_stalled": stalled}


def _session_activity(database: Path, now: datetime) -> dict[str, dict[str, Any]]:
    activity = {}
    try:
        if not database.is_file():
            return activity
        uri = f"file:{database}?mode=ro"
        with sqlite3.connect(uri, uri=True, timeout=0.05) as connection:
            rows = connection.execute(
                "SELECT project, COUNT(DISTINCT session_id), MAX(ts) FROM mem_entries WHERE ts > ? GROUP BY project",
                ((now - timedelta(hours=24)).isoformat(),),
            ).fetchall()
        for project, sessions, latest in rows:
            if isinstance(project, str):
                activity[project] = {"sessions_24h": int(sessions), "last_capture_ts": latest}
    except (OSError, sqlite3.Error, TypeError, ValueError):
        pass
    return activity


def _activity_for(project: Path, activity: dict[str, dict[str, Any]]) -> dict[str, Any]:
    for key in (str(project), project.name):
        if key in activity:
            return activity[key]
    return {"sessions_24h": 0, "last_capture_ts": None}


def collect(stall_minutes: int = DEFAULT_STALL_MINUTES) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    stall_minutes = max(0, stall_minutes)
    sessions = _session_activity(kb_home() / "memory.db", now)
    projects = []
    for project in discover_projects():
        try:
            item = read_project_tasks(project, now.timestamp(), stall_minutes * 60)
            item.update(_activity_for(project, sessions))
            item["active"] = bool(item["tasks"] or item["active_entries"] or item["sessions_24h"])
            projects.append(item)
        except Exception:
            continue
    active = [project for project in projects if project["active"]]
    return {
        "checked_at": now.isoformat(),
        "stall_minutes": stall_minutes,
        "projects": projects,
        "summary": {
            "running": sum(project["running_count"] for project in projects),
            "stalled": sum(project["stalled_count"] for project in projects),
            "active_projects": len(active),
            "discovered_projects": len(projects),
        },
    }


def format_age(seconds: int) -> str:
    if seconds < 60:
        return "<1m"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m"
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return f"{hours}h{minutes}m" if minutes else f"{hours}h"
    days, hours = divmod(hours, 24)
    return f"{days}d{hours}h" if hours else f"{days}d"


def human_lines(payload: dict[str, Any]) -> list[str]:
    lines = []
    for project in payload["projects"]:
        if not project["active"]:
            continue
        parts = [project["name"]]
        running = [task for task in project["tasks"] if task["status"] == "running"]
        flying = [task for task in running if not task["stalled"]]
        stalled = [task for task in running if task["stalled"]]
        if flying:
            parts.append("在飞:" + " ".join(f"{task['slug']}({format_age(task['age_seconds'])})" for task in flying))
        if stalled:
            parts.append("滞留:" + " ".join(f"{task['slug']}({format_age(task['age_seconds'])})⚠" for task in stalled))
        parts.append(f"24h会话:{project['sessions_24h']}")
        if project["recent_completed"]:
            parts.append(f"最近完成:{project['recent_completed']}")
        lines.append(" | ".join(parts))
    summary = payload["summary"]
    lines.append(f"fleet: {summary['running']} 在飞 / {summary['stalled']} 滞留 / {summary['active_projects']} 项目活跃")
    return lines


def notify(payload: dict[str, Any]) -> None:
    if os.environ.get("SULDE_NOTIFY", "").lower() == "off":
        return
    stalled = [
        f"{project['name']}/{task['slug']}({format_age(task['age_seconds'])})"
        for project in payload["projects"] for task in project["tasks"] if task["stalled"]
    ]
    if not stalled:
        return
    message = "舰队滞留: " + ", ".join(stalled)
    print(f"⚠ {message}")
    try:
        sys.path.insert(0, str(ROOT / "hooks" / "lib"))
        import kb_notify
        kb_notify.run({"message": message})
    except Exception:
        pass


def main() -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--notify", action="store_true")
    parser.add_argument("--stall-minutes", type=int, default=DEFAULT_STALL_MINUTES)
    args = parser.parse_args()
    try:
        payload = collect(args.stall_minutes)
        if args.notify:
            notify(payload)
        elif args.json:
            print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        else:
            print("\n".join(human_lines(payload)))
    except Exception:
        if args.json:
            print(json.dumps({"projects": [], "summary": {"running": 0, "stalled": 0, "active_projects": 0}}, ensure_ascii=False))
        elif not args.notify:
            print("fleet: 0 在飞 / 0 滞留 / 0 项目活跃")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
