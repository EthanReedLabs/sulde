"""Deterministic, best-effort SessionStart situation brief."""

from __future__ import annotations

import importlib.util
import os
import re
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


MAX_BRIEF_CHARS = 600
MAX_CONCLUSION_CHARS = 160
SQLITE_TIMEOUT_SECONDS = 0.02
PENDING_MARKERS = (
    "（待 /sediment 处理）",
    "（待 /sediment 人工处理）",  # legacy read compatibility
)


def _home() -> Path:
    configured = os.environ.get("SULDE_KB_HOME")
    return (
        Path(configured).expanduser()
        if configured
        else Path.home() / ".sulde" / "data" / "kb"
    )


def _clean(value: Any, maximum: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= maximum:
        return text
    return text[: max(0, maximum - 1)].rstrip() + "…"


def _active(cwd: Path) -> list[str]:
    try:
        lines = (cwd / ".codex-agent" / "ACTIVE.md").read_text(
            encoding="utf-8", errors="replace"
        ).splitlines()
        slugs = []
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            fields = [field.strip() for field in stripped.split("|")]
            if any(field == "完成" or field.startswith("完成(") for field in fields[1:]):
                continue
            slug = re.sub(r"^(?:[-*+]\s+|\[[ xX]\]\s*)+", "", fields[0]).strip()
            if slug:
                slugs.append(_clean(slug, 28))
        return slugs
    except Exception:
        return []


def _memory(cwd: Path) -> tuple[str, str, list[str]]:
    database = _home() / "memory.db"
    if not database.is_file():
        return "", "", []
    connection: sqlite3.Connection | None = None
    try:
        uri = database.resolve().as_uri() + "?mode=ro"
        connection = sqlite3.connect(uri, uri=True, timeout=SQLITE_TIMEOUT_SECONDS)
        connection.execute("PRAGMA query_only = ON")
        connection.execute("PRAGMA busy_timeout = 20")
        projects = (cwd.name, str(cwd))
        try:
            latest = connection.execute(
                """
                SELECT content, ts
                FROM mem_entries
                WHERE project IN (?, ?) AND role = 'assistant'
                ORDER BY ts DESC, id DESC
                LIMIT 1
                """,
                projects,
            ).fetchone()
        except sqlite3.OperationalError as error:
            if "locked" in str(error).lower():
                return "", "", []
            latest = None
        try:
            edges = connection.execute(
                """
                SELECT g.src, g.rel, g.dst
                FROM mem_edges g
                JOIN mem_entries e ON e.id = g.entry_id
                WHERE e.project IN (?, ?)
                ORDER BY g.ts DESC, g.id DESC
                LIMIT 3
                """,
                projects,
            ).fetchall()
        except sqlite3.Error:
            edges = []
        conclusion = _clean(latest[0], MAX_CONCLUSION_CHARS) if latest else ""
        timestamp = str(latest[1]) if latest else ""
        decisions = [_clean(f"{src}-{rel}->{dst}", 48) for src, rel, dst in edges]
        return conclusion, timestamp, decisions
    except Exception:
        return "", "", []
    finally:
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass


def _pending_candidates() -> int:
    try:
        return sum(
            1
            for line in (_home() / "distill-candidates.md").read_text(
                encoding="utf-8", errors="replace"
            ).splitlines()
            if line.lstrip().startswith("- ")
            and any(line.rstrip().endswith(marker) for marker in PENDING_MARKERS)
        )
    except Exception:
        return 0


def _fleet_stalled() -> int:
    try:
        root = Path(__file__).resolve().parents[2]
        path = root / "scripts" / "kb" / "fleet.py"
        spec = importlib.util.spec_from_file_location("_sulde_session_brief_fleet", path)
        if spec is None or spec.loader is None:
            return 0
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return max(0, int(module.collect_task_summary().get("fleet_stalled", 0)))
    except Exception:
        return 0


def _relative_time(value: str) -> str:
    if not value:
        return "无"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        seconds = max(0, int((datetime.now(timezone.utc) - parsed).total_seconds()))
        if seconds < 60:
            return "刚刚"
        if seconds < 3600:
            return f"{seconds // 60}分钟前"
        if seconds < 86400:
            return f"{seconds // 3600}小时前"
        return f"{seconds // 86400}天前"
    except Exception:
        return "未知"


def _active_text(slugs: list[str]) -> str:
    if not slugs:
        return "无"
    counts = Counter(slugs)
    values = [f"{slug}×{count}" for slug, count in counts.items()]
    if len(values) > 4:
        return ",".join(values[:4]) + f",另{len(values) - 4}项"
    return ",".join(values)


def build(cwd: str | os.PathLike[str]) -> str:
    """Build a compact brief; every source fails closed and independently."""
    try:
        project = Path(cwd).expanduser().resolve()
    except Exception:
        project = Path.cwd()

    active = _active(project)
    conclusion, timestamp, decisions = _memory(project)
    candidates = _pending_candidates()
    stalled = _fleet_stalled()
    # 安静原则:项目维度三源(委托/结论/决策)全空即闭嘴——候选/滞留是全局信号,
    # 不该让一个陌生项目替全世界开口
    if not (active or conclusion or decisions):
        return ""

    brief = (
        f"[sulde-brief] 项目 {_clean(project.name or str(project), 48)}"
        f" | 上次({_relative_time(timestamp)}): {conclusion or '无'}"
        f" | 未完结: {_active_text(active)}"
        f" | 近期决策: {';'.join(decisions) if decisions else '无'}"
        f" | 待办: 候选{candidates}条·滞留{stalled}"
    )
    if len(brief) <= MAX_BRIEF_CHARS:
        return brief
    return brief[: MAX_BRIEF_CHARS - 1].rstrip() + "…"
