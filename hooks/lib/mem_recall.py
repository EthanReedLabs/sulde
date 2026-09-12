"""Independent sulde-mem recall channel for UserPromptSubmit."""

from __future__ import annotations

import json
import os
import re
import runpy
import sqlite3
import subprocess
import sys
import time
from functools import lru_cache
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any


# 词面/向量两路对 top1 意见不合时融合分到不了 1.0——0.55 会刮掉此类真命中
# (golden gm-06 实证:正确条目 top1 仅 0.547);内容门+口头禅门+跨项目绝对门仍在
SCORE_MIN = 0.50
# bge-reranker-base 输出未归一化 logit；0 是模型的相关/不相关决策边界。
# 与混合 score 不同，它是绝对相关性证据，不随本轮候选集的 min-max 分布漂移。
RERANK_SCORE_MIN = 0.0
# 2026-08-08 翻案:概率性跨项目门(0.75+余弦0.68)三次实证泄漏而收益零兑现,
# 改为项目组硬隔离——同组(recall-groups.json)按同项目对待,组外一律不注入
# 低于该长度的提示词(口头禅:继续/提交/好的)不值得召回
MIN_PROMPT_CHARS = 6
# 低于该长度的历史条目(本身就是口头禅)不值得注入
MIN_CONTENT_CHARS = 20
MAX_INJECTED = 2
SEARCH_TIMEOUT_SECONDS = 5
SESSION_STATE_MAX_AGE_DAYS = 30
kb_cli = SimpleNamespace(
    **runpy.run_path(str(Path(__file__).resolve().with_name("kb_cli.py")))
)
prompt_noise = SimpleNamespace(
    **runpy.run_path(str(Path(__file__).resolve().with_name("prompt_noise.py")))
)
session_identity = SimpleNamespace(
    **runpy.run_path(str(Path(__file__).resolve().with_name("session_identity.py")))
)
recall_log = SimpleNamespace(
    **runpy.run_path(str(Path(__file__).resolve().with_name("recall_log.py")))
)


def _root() -> Path:
    return Path(__file__).resolve().parents[2]


def _home() -> Path:
    configured = os.environ.get("SULDE_KB_HOME")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".sulde" / "data" / "kb"


def _log(
    prompt: str,
    cwd: str,
    scores: list[float],
    injected: list[int],
    session_id: str,
    source_host: str,
) -> None:
    recall_log.append_mem_recall(
        _home(),
        cwd=cwd,
        query=prompt,
        top_scores=scores,
        injected=injected,
        session_id=session_id,
        channel=source_host,
        source_host=source_host,
    )


def _project_group(project: str) -> frozenset[str]:
    """项目所属互通组;无配置或未入组时自成一组(硬隔离默认)。"""
    try:
        config = json.loads((_home() / "recall-groups.json").read_text(encoding="utf-8"))
        for group in config.get("groups", []):
            if isinstance(group, list) and project in group:
                return frozenset(group)
    except (OSError, json.JSONDecodeError, TypeError):
        pass
    return frozenset({project})


def _session_path(session_id: str) -> Path | None:
    if not session_id:
        return None
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", session_id)[:100]
    return _home() / "session-recall" / f"{safe}.json"


def _read_seen(path: Path | None) -> tuple[dict[str, Any], set[str]]:
    if path is None:
        return {}, set()
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        value = {}
    if not isinstance(value, dict):
        value = {}
    injected = value.get("injected")
    seen = {item for item in injected if isinstance(item, str)} if isinstance(injected, list) else set()
    return value, seen


def _write_seen(path: Path | None, value: dict[str, Any], seen: set[str]) -> None:
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        value["injected"] = sorted(seen)
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        temporary.replace(path)
    except OSError:
        pass


def _trace(message: str) -> None:
    """Leave a best-effort diagnostic without making SessionStart fatal."""
    record = f"{datetime.now(timezone.utc).isoformat()} [sulde-mem] {message}\n"
    try:
        path = _home() / "mem-recall.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(record)
    except (OSError, ValueError):
        try:
            sys.stderr.write(record)
        except (OSError, ValueError):
            pass


def prewarm(limit: int = 100) -> None:
    """Start a bounded, non-blocking SessionStart embedding batch."""
    try:
        cutoff = time.time() - SESSION_STATE_MAX_AGE_DAYS * 24 * 60 * 60
        for state_file in (_home() / "session-recall").glob("*.json"):
            try:
                if state_file.stat().st_mtime < cutoff:
                    state_file.unlink()
            except OSError:
                pass
    except OSError:
        pass
    home = _home()
    if not (home / "memory.db").is_file():
        return
    started = kb_cli.spawn_cli(
        _root(),
        home,
        "mem-embed",
        ["--limit", str(limit)],
        timeout=SEARCH_TIMEOUT_SECONDS,
        log_path=home / "mem-recall.log",
    )
    if not started.started:
        _trace(f"embedding launch failed ({started.status})")


@lru_cache(maxsize=1)
def _memory_association_reader():
    return runpy.run_path(str(_root() / "tools/kb-index/memory.py"))["memory_associations"]


def _associations(
    database: Path, entry_id: Any, project: str, content: str, limit: int = 2
) -> list[str]:
    connection: sqlite3.Connection | None = None
    try:
        numeric_id = int(entry_id)
        connection = sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True, timeout=0.1)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        return _memory_association_reader()(connection, numeric_id, project, limit=limit)
    except (TypeError, ValueError, sqlite3.Error, OSError):
        return []
    finally:
        if connection is not None:
            connection.close()


def select_recall_items(
    prompt: str,
    project: str,
    results: list[Any],
    seen: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Apply the production recall gate and return the injectable items."""
    if (
        len(prompt) < MIN_PROMPT_CHARS
        or prompt.startswith("/")
        or prompt_noise.is_recall_noise(prompt)
    ):
        return []
    seen_ids = seen or set()

    group = _project_group(project) if project else None

    def passes(item: dict[str, Any]) -> bool:
        content = " ".join(str(item.get("content") or "").split())
        if len(content) < MIN_CONTENT_CHARS:
            return False
        # 组硬隔离(2026-08-08):组外记忆一律不注入,组内按同项目分数线
        if group is not None and item.get("project") not in group:
            return False
        rerank_score = item.get("rerank_score")
        if rerank_score is not None:
            return float(rerank_score) >= RERANK_SCORE_MIN
        return float(item.get("score", 0.0)) >= SCORE_MIN

    return [
        item
        for item in results
        if isinstance(item, dict)
        and passes(item)
        and f"mem:{item.get('id')}" not in seen_ids
    ][:MAX_INJECTED]


def run(payload: dict[str, Any]) -> None:
    prompt = str(payload.get("prompt") or "").strip()
    cwd = str(payload.get("cwd") or "")
    home = _home()
    database = home / "memory.db"
    if (
        not database.is_file()
        or len(prompt) < MIN_PROMPT_CHARS
        or prompt.startswith("/")
        or prompt_noise.is_recall_noise(prompt)
    ):
        return
    project = Path(cwd).name if cwd else ""
    session_id, source_host = session_identity.normalize_session_identity(
        payload.get("session_id") or payload.get("sessionId") or "",
        payload.get("client") or "claude",
    )
    search_query = prompt_noise.bounded_recall_query(prompt)
    arguments = [search_query, "-k", "5", "--json", "--skip-pending-embed"]
    if project:
        arguments.extend(["--project", project])
    if session_id:
        arguments.extend(["--session-id", session_id])
    completed = kb_cli.run_cli(
        _root(),
        home,
        "mem-search",
        arguments,
        timeout=SEARCH_TIMEOUT_SECONDS,
    )
    if completed.ok:
        try:
            results = json.loads(completed.stdout)
            if not isinstance(results, list):
                _trace("memory search returned non-list JSON; results ignored")
                results = []
        except (TypeError, ValueError) as error:
            _trace(f"memory search failed: {type(error).__name__}: {error}")
            results = []
    else:
        detail = completed.stderr.strip() or completed.detail
        if len(search_query) != len(prompt):
            bounds = (
                f"prompt_chars={len(prompt)} search_chars={len(search_query)}"
            )
            detail = f"{detail}; {bounds}" if detail else bounds
        suffix = f": {detail[-500:]}" if detail else ""
        if completed.returncode is not None:
            _trace(
                f"memory search failed with exit code {completed.returncode}{suffix}"
            )
        else:
            _trace(f"memory search failed ({completed.status}){suffix}")
        results = []
    valid = [item for item in results if isinstance(item, dict)]
    scores = [round(float(item.get("score", 0.0)), 6) for item in valid[:5]]
    session_path = _session_path(session_id)
    state, seen = _read_seen(session_path)
    selected = select_recall_items(prompt, project, valid, seen)
    injected = [int(item["id"]) for item in selected if "id" in item]
    if injected:
        _write_seen(session_path, state, seen | {f"mem:{entry_id}" for entry_id in injected})
    for item in selected:
        content = " ".join(str(item.get("content") or "").split())[:200]
        suffix = "…" if len(" ".join(str(item.get("content") or "").split())) > 200 else ""
        related = _associations(database, item.get("id"), project, content)
        graph_suffix = f" [关联: {'; '.join(related)}]" if related else ""
        print(
            f"[sulde-mem] 相关历史: {item.get('ts', '')} {item.get('project', '')} | "
            f"{content}{suffix}{graph_suffix}"
        )
    _log(prompt, cwd, scores, injected, session_id, source_host)
