#!/usr/bin/env python3
"""Run one Sulde heartbeat and ask the L2 organ to draft one repair brief."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import runpy
import re
from contextlib import closing
from sulde_paths import kb_home as canonical_kb_home
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any

from file_lock import lock_exclusive_nonblocking, unlock


REPO_ROOT = Path(__file__).resolve().parents[2]
_command_template = runpy.run_path(str(Path(__file__).with_name("command_template.py")))
split_command_template = _command_template["split_command_template"]
SELF_TEMPLATE = REPO_ROOT / "templates" / "SELF.md"
GOVERNANCE_SCRIPT = Path(__file__).with_name("governance-report.py")
SELF_REPAIR_SCRIPT = Path(__file__).with_name("self-repair.py")
L2_REGISTRY_SCRIPT = Path(__file__).with_name("l2-draft.py")
LIFE_CYCLE_SCRIPT = Path(__file__).with_name("life-cycle.py")
STATE_NAME = "heartbeat-state.json"
LOG_NAMES = ("recall-log.jsonl", "auto-distill.log", "auto-sediment.log")
DEFAULT_LLM_CMD = _command_template["default_llm_command"]()
MAX_SELF_CHARS = 8_000


class HeartbeatError(RuntimeError):
    """A controlled heartbeat failure."""


def kb_home() -> Path:
    return canonical_kb_home()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    atomic_write(path, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def load_state(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"sequence": 0, "last_ts": None, "log_lines": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise HeartbeatError(f"invalid heartbeat state: {error}") from error
    if not isinstance(payload, dict):
        raise HeartbeatError("invalid heartbeat state: root must be an object")
    sequence = payload.get("sequence")
    last_ts = payload.get("last_ts")
    log_lines = payload.get("log_lines", {})
    if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0:
        raise HeartbeatError("invalid heartbeat state: sequence must be a non-negative integer")
    if last_ts is not None and not isinstance(last_ts, str):
        raise HeartbeatError("invalid heartbeat state: last_ts must be a string or null")
    if not isinstance(log_lines, dict) or any(
        not isinstance(name, str)
        or isinstance(count, bool)
        or not isinstance(count, int)
        or count < 0
        for name, count in log_lines.items()
    ):
        raise HeartbeatError("invalid heartbeat state: log_lines must contain non-negative integers")
    return payload


def acquire_lock(home: Path):
    digest = hashlib.sha256(str(home.resolve()).encode("utf-8")).hexdigest()[:16]
    path = Path(tempfile.gettempdir()) / f"sulde-heartbeat-{digest}.lock"
    handle = path.open("a+", encoding="utf-8")
    try:
        lock_exclusive_nonblocking(handle)
    except BlockingIOError as error:
        handle.close()
        raise HeartbeatError("another heartbeat instance is running") from error
    return handle


def database_increment(database: Path, since: str | None) -> dict[str, Any]:
    meta = {"scope": "ts > since" if since else "all rows (first beat)", "since": since,
            "collected_at": utc_now(), "source": "memory.db:mem_entries,mem_edges",
            "semantics": "window_increment_not_inventory"}
    if not database.is_file():
        return {
            **meta,
            "status": "unavailable",
            "error": "memory_database_missing",
            "mem_entries": {"count": None, "projects": {}},
            "mem_edges": {"count": None}, "total_entries": None, "total_edges": None,
        }
    try:
        with closing(sqlite3.connect(f"file:{database}?mode=ro", uri=True, timeout=0.2)) as connection:
            connection.execute("BEGIN")
            where = " WHERE ts > ?" if since else ""
            parameters: tuple[str, ...] = (since,) if since else ()
            rows = connection.execute(
                f"SELECT project, COUNT(*) FROM mem_entries{where} GROUP BY project ORDER BY project",
                parameters,
            ).fetchall()
            edge_count = connection.execute(
                f"SELECT COUNT(*) FROM mem_edges{where}", parameters
            ).fetchone()[0]
            total_entries = connection.execute("SELECT COUNT(*) FROM mem_entries").fetchone()[0]
            total_edges = connection.execute("SELECT COUNT(*) FROM mem_edges").fetchone()[0]
        projects = {str(project): int(count) for project, count in rows}
        return {
            **meta,
            "status": "available",
            "total_entries": total_entries, "total_edges": total_edges,
            "mem_entries": {"count": sum(projects.values()), "projects": projects},
            "mem_edges": {"count": int(edge_count)},
        }
    except sqlite3.Error as error:
        return {
            **meta,
            "status": "unavailable",
            "error": type(error).__name__,
            "mem_entries": {"count": None, "projects": {}},
            "mem_edges": {"count": None}, "total_entries": None, "total_edges": None,
        }


def line_count(path: Path) -> int:
    try:
        with path.open(encoding="utf-8", errors="replace") as handle:
            return sum(1 for _ in handle)
    except FileNotFoundError:
        return 0


def collect_log_increments(home: Path, previous: dict[str, int]) -> tuple[dict[str, Any], dict[str, int]]:
    result: dict[str, Any] = {}
    totals: dict[str, int] = {}
    for name in LOG_NAMES:
        total = line_count(home / name)
        old = previous.get(name, 0)
        totals[name] = total
        result[name] = {"new_lines": max(0, total - old), "total_lines": total}
    return result, totals


def load_governance_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("sulde_governance_report", GOVERNANCE_SCRIPT)
    if spec is None or spec.loader is None:
        raise HeartbeatError(f"cannot load governance collector: {GOVERNANCE_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except (OSError, ImportError) as error:
        raise HeartbeatError(f"cannot load governance collector: {error}") from error
    return module


def latest_governance_report(home: Path) -> str | None:
    candidates = sorted((home / "governance").glob("report-*.md"), reverse=True)
    return str(candidates[0]) if candidates else None


def collect_governance(home: Path) -> dict[str, Any]:
    try:
        module = load_governance_module()
        now = datetime.now().astimezone()
        skipped = {
            "status": "unavailable",
            "error": "observer mode skips active golden evaluation",
        }
        snapshot = {
            "collected_at": now.isoformat(),
            "kb_home": str(home),
            "sources": {
                "status": module.source(lambda: module.collect_status(home)),
                "fleet": module.source(module.collect_fleet),
                # mem-golden can embed pending entries. Both golden suites belong
                # to the governance cycle, not to an observer-only heartbeat.
                "kb_golden": dict(skipped),
                "mem_golden": dict(skipped),
                "calibrate": module.source(lambda: module.read_calibrate(home)),
                "recall": module.source(
                    lambda: module.collect_recall(home / "recall-log.jsonl", now)
                ),
                "auto_distill": module.source(
                    lambda: module.collect_distill(home / "auto-distill.log", now)
                ),
                "auto_sediment": module.source(
                    lambda: module.collect_sediment(home / "auto-sediment.log", now)
                ),
                "candidates": module.source(
                    lambda: module.collect_candidates(home / "distill-candidates.md")
                ),
                "mem_edges": module.source(
                    lambda: module.collect_edges(home / "memory.db", now)
                ),
                "sync_export": module.source(
                    lambda: module.collect_export_age(home / "mem-sync-state.json", now)
                ),
                "previous_report": module.source(lambda: module.collect_previous(home)),
            },
        }
        # Use the governance registry for completeness, while golden evaluations
        # remain explicitly skipped by this observer-only collector.
        for name, collector in module.collectors(home, now).items():
            if name not in snapshot["sources"]:
                snapshot["sources"][name] = module.source(collector, name=name, scope="heartbeat", collected_at=now.isoformat())
        for name, item in snapshot["sources"].items():
            item.update(source=name, scope="heartbeat", collected_at=now.isoformat())
        thresholds = module.load_thresholds()
        lights = module.prejudge(snapshot, thresholds)
        status_source = snapshot.get("sources", {}).get("status", {})
        status_data = status_source.get("data", {}) if status_source.get("status") == "available" else {}
        status_summary = {
            key: status_data.get(key)
            for key in (
                "ok",
                "warn",
                "missing_sources",
                "mem_total",
                "mem_today",
                "mem_pending_embedding",
                "fleet_running",
                "fleet_stalled",
            )
            if key in status_data
        }
        return {
            "status": "available",
            "latest_report": latest_governance_report(home),
            "sulde_status": status_summary,
            "kpi_lights": [
                {
                    "metric": row.get("metric"),
                    "current": row.get("current"),
                    "op": row.get("op"),
                    "threshold": row.get("threshold_value"),
                    "light": row.get("light"),
                }
                for row in lights
            ],
            "source_status": {
                name: item.get("status")
                for name, item in snapshot.get("sources", {}).items()
                if isinstance(item, dict)
            },
            "source_details": {
                name: {key: item.get(key) for key in ("status", "source", "scope", "collected_at", "error")}
                for name, item in snapshot["sources"].items()
            },
        }
    except Exception as error:
        return {
            "status": "unavailable",
            "error": f"{type(error).__name__}: {error}"[:500],
            "latest_report": latest_governance_report(home),
            "sulde_status": {},
            "kpi_lights": [],
            "source_status": {},
        }


def sense(home: Path, state: dict[str, Any], observed_at: str) -> tuple[dict[str, Any], dict[str, int]]:
    database = database_increment(home / "memory.db", state.get("last_ts"))
    previous_lines = state.get("log_lines", {})
    if not isinstance(previous_lines, dict):
        previous_lines = {}
    logs, totals = collect_log_increments(home, previous_lines)
    observation = {
        "observed_at": observed_at,
        "since": state.get("last_ts"),
        "first_beat": state.get("last_ts") is None,
        "memory": database,
        "logs": logs,
        "governance": collect_governance(home),
    }
    return observation, totals


def fixed_self(text: str) -> str:
    match = re.search(r"(?m)^## (?:目标栈|观察清单|自评)\s*$", text)
    return text[:match.start()] if match else text


def self_budget(text: str) -> dict[str, int]:
    fixed = len(fixed_self(text))
    return {"total": MAX_SELF_CHARS, "fixed_chars": fixed,
            "variable_budget": max(0, MAX_SELF_CHARS - fixed - 1)}


def compression_prompt(current: str, candidate: dict[str, str]) -> str:
    fixed = fixed_self(current)
    variable = candidate["self_md"][len(fixed_self(candidate["self_md"])):]
    return ("执行唯一一次有界压缩。固定部分逐字保留，不得截断；仅压缩目标栈、观察清单、自评。"
            f"可变预算 {self_budget(current)['variable_budget']} 字符。只输出 self_md 和 observation 的 JSON。"
            "禁止新增事实、隐藏推理、完整提示词、原始工具输出、秘密或私人路径。\n"
            + json.dumps({"fixed": fixed, "variable": variable, "observation": candidate["observation"]}, ensure_ascii=False))


def build_prompt(self_md: str, increment: dict[str, Any]) -> str:
    budget = self_budget(self_md)
    return f"""你是 sulde 的 headless 心智。下面是你每搏首载的完整 SELF：

--- SELF BEGIN ---
{self_md}
--- SELF END ---

固定部分预算 {budget['fixed_chars']} 字符，逐字保留；可变部分预算 {budget['variable_budget']} 字符。
mem_entries/mem_edges 是 since 窗口增量，不是库存；total_entries/total_edges 才是全库总量。null 表示采集未知，禁止补零。
本搏增量观察（机器采集，不得篡改数字）：
{json.dumps(increment, ensure_ascii=False, indent=2)}

观察员纪律：你只能思考与记录，不得执行、建议执行或安排任何写操作；不得修改法典，亦不得删改「我是什么／我的能力阶梯／我能自主做什么／我永远不能自己做的五件事」四节定义骨架（可在其中如实更新自己的阶梯现状标记）。你可以依据观察更新目标栈的排序、内容与自评，但必须给出可追溯到本搏观察的依据。输出完整的新 SELF，不要省略未改章节。

只输出一个裸 JSON 对象，顶层必须且只能包含：
{{"self_md":"完整新 SELF（不超过 8000 字符）","observation":"本搏观察日志条目"}}
不要输出 Markdown 代码围栏或 JSON 之外的文字。"""


def run_llm(command_template: str, prompt: str, timeout: int = 180) -> str:
    try:
        arguments = split_command_template(command_template)
    except ValueError as error:
        raise HeartbeatError(f"invalid --llm-cmd: {error}") from error
    if not arguments:
        raise HeartbeatError("--llm-cmd cannot be empty")
    stdin_prompt: str | None = prompt
    expanded: list[str] = []
    for argument in arguments:
        if argument == "{prompt}":
            continue
        if "{prompt}" in argument:
            argument = argument.replace("{prompt}", prompt)
            stdin_prompt = None
        expanded.append(argument)
    try:
        completed = subprocess.run(
            expanded,
            input=stdin_prompt,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise HeartbeatError(f"LLM command failed: {type(error).__name__}") from error
    if completed.returncode != 0:
        raise HeartbeatError(f"LLM command exited {completed.returncode}")
    return completed.stdout


def strip_json_fence(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```") and text.endswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3 and lines[0].strip().lower() in {"```", "```json"}:
            return "\n".join(lines[1:-1]).strip()
    return text


def parse_llm_result(raw: str) -> dict[str, str]:
    try:
        payload = json.loads(strip_json_fence(raw))
    except json.JSONDecodeError as error:
        raise HeartbeatError(f"invalid LLM JSON: {error}") from error
    if not isinstance(payload, dict) or set(payload) != {"self_md", "observation"}:
        raise HeartbeatError("LLM JSON must contain only self_md and observation")
    if not all(isinstance(payload[key], str) and payload[key].strip() for key in payload):
        raise HeartbeatError("LLM self_md and observation must be non-empty strings")
    return {key: payload[key].strip() for key in ("self_md", "observation")}


def self_guard(text: str) -> str | None:
    if len(text.rstrip()) + 1 > MAX_SELF_CHARS:
        return f"self_md exceeds {MAX_SELF_CHARS} characters ({len(text)})"
    if "# SELF" not in text:
        return 'self_md is missing "# SELF"'
    if "法典" not in text:
        return 'self_md is missing "法典"'
    # 生命体定义(身份/能力阶梯/自主权/五禁区)属宪法级内容——心跳可更新目标栈与
    # 自评,但不得删改这四节骨架,否则自我认知可被逐搏漂移抹除
    for section in (
        "## 我是什么",
        "## 我的能力阶梯",
        "## 我能自主做什么",
        "## 我永远不能自己做的",
    ):
        if section not in text:
            return f"self_md is missing definition section: {section}"
    return None


def machine_observation(increment: dict[str, Any], degraded: str) -> str:
    memory = increment["memory"]
    entries = memory["mem_entries"]
    edges = memory["mem_edges"]
    projects = ",".join(f"{name}:{count}" for name, count in entries["projects"].items()) or "none"
    logs = ",".join(
        f"{name}:{value['new_lines']}" for name, value in increment["logs"].items()
    )
    status = increment["governance"].get("sulde_status", {})
    return (
        f"机器观察（degraded）：window_entries={entries['count']} projects={projects}; "
        f"window_edges={edges['count']}; total_entries={memory.get('total_entries')}; "
        f"total_edges={memory.get('total_edges')}; new_log_lines={logs}; "
        f"status_ok={status.get('ok', 'unavailable')}; reason={degraded}"
    )


def append_observation(home: Path, sequence: int, timestamp: str, text: str) -> Path:
    observed = datetime.fromisoformat(timestamp.replace("Z", "+00:00")).astimezone()
    path = home / "heartbeat" / f"observations-{observed:%Y%m}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"\n## Beat {sequence} — {timestamp}\n\n{text.strip()}\n")
        handle.flush()
        os.fsync(handle.fileno())
    return path


def print_summary(mode: str, sequence: int, increment: dict[str, Any], details: Path | None) -> None:
    memory = increment["memory"]
    new_logs = sum(item["new_lines"] for item in increment["logs"].values())
    print("HEARTBEAT RESULT: PASS")
    print(f"mode: {mode.lower()}")
    print(
        "counts: "
        f"sequence={sequence} window_entries={memory['mem_entries']['count']} "
        f"window_edges={memory['mem_edges']['count']} total_entries={memory.get('total_entries')} "
        f"total_edges={memory.get('total_edges')} new_log_lines={new_logs}"
    )
    if mode == "DEGRADED":
        print("WARN heartbeat completed with machine observation; SELF was not changed")
    if details is not None:
        print(f"details: {details}")


def draft_self_repair(llm_cmd: str) -> None:
    """Invoke only the draft action; the automatic marker hard-blocks decisions."""
    environment = os.environ.copy()
    environment["SULDE_SELF_REPAIR_AUTO"] = "heartbeat"
    try:
        completed = subprocess.run(
            [sys.executable, str(SELF_REPAIR_SCRIPT), "--draft", "--llm-cmd", llm_cmd],
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError as error:
        print(f"WARN L2 draft unavailable: {error}")
        return
    output = completed.stdout.strip() or completed.stderr.strip()
    if output:
        print(output)
    if completed.returncode != 0:
        print(f"WARN L2 draft failed exit={completed.returncode}")


def refresh_l2_registry() -> None:
    """Refresh the four-channel L2 truth after the WP drafter has run."""
    try:
        completed = subprocess.run(
            [sys.executable, str(L2_REGISTRY_SCRIPT), "--refresh"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError as error:
        print(f"WARN L2 registry unavailable: {error}")
        return
    output = completed.stdout.strip() or completed.stderr.strip()
    if output:
        print(output)
    if completed.returncode != 0:
        print(f"WARN L2 registry degraded exit={completed.returncode}")


def run_life_cycle() -> None:
    """Close L2-L4 state after producers have emitted this beat's evidence."""
    try:
        completed = subprocess.run(
            [sys.executable, str(LIFE_CYCLE_SCRIPT), "--run"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError as error:
        print(f"WARN life cycle unavailable: {error}")
        return
    output = completed.stdout.strip() or completed.stderr.strip()
    if output:
        print(output)
    if completed.returncode != 0:
        print(f"WARN life cycle degraded exit={completed.returncode}")


def run_beat(home: Path, args: argparse.Namespace) -> int:
    state_path = home / STATE_NAME
    state = load_state(state_path)
    sequence = int(state["sequence"]) + 1
    observed_at = utc_now()
    increment, log_totals = sense(home, state, observed_at)

    if args.dry_run:
        print_summary("DRY-RUN", sequence, increment, None)
        print(json.dumps(increment, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    self_path = home / "SELF.md"
    if not self_path.is_file():
        try:
            seed = SELF_TEMPLATE.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            raise HeartbeatError(f"cannot read SELF template: {error}") from error
        atomic_write(self_path, seed)
    try:
        current_self = self_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise HeartbeatError(f"cannot read SELF: {error}") from error

    mode = "RESULT"
    degraded_reason: str | None = None
    observation_text: str
    compression_attempts = 0
    try:
        result = parse_llm_result(run_llm(args.llm_cmd, build_prompt(current_self, increment)))
        if len(result["self_md"].rstrip()) + 1 > MAX_SELF_CHARS and self_budget(current_self)["variable_budget"] > 0:
            compression_attempts = 1
            result = parse_llm_result(run_llm(args.llm_cmd, compression_prompt(current_self, result), timeout=60))
        degraded_reason = self_guard(result["self_md"])
        if degraded_reason is None and fixed_self(result["self_md"]) != fixed_self(current_self):
            degraded_reason = "self_fixed_sections_changed"
        if degraded_reason is None:
            atomic_write(self_path, result["self_md"].rstrip() + "\n")
            observation_text = result["observation"]
        else:
            mode = "DEGRADED"
            observation_text = machine_observation(increment, degraded_reason)
    except HeartbeatError as error:
        mode = "DEGRADED"
        degraded_reason = str(error)
        observation_text = machine_observation(increment, degraded_reason)

    observation_path = append_observation(home, sequence, observed_at, observation_text)
    next_state = {
        "sequence": sequence,
        "last_ts": observed_at,
        "log_lines": log_totals,
        "last_mode": mode.lower(),
        "self_budget": self_budget(current_self),
        "compression_attempts": compression_attempts,
        "collection_status": increment["memory"]["status"],
        "governance_source_status": increment["governance"].get("source_status", {}),
    }
    if degraded_reason is not None:
        next_state["last_degraded_reason"] = degraded_reason
    atomic_json(state_path, next_state)
    print_summary(mode, sequence, increment, observation_path)
    if not getattr(args, "observe_only", False):
        draft_self_repair(args.llm_cmd)
        refresh_l2_registry()
        run_life_cycle()
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--beat", action="store_true", help="run one heartbeat")
    modes.add_argument("--dry-run", action="store_true", help="sense and print without writing or invoking the LLM")
    parser.add_argument("--observe-only", action="store_true", help="omit downstream draft/lifecycle actions")
    parser.add_argument(
        "--llm-cmd",
        default=DEFAULT_LLM_CMD,
        help="command template; a standalone {prompt} is supplied over stdin",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    home = kb_home()
    lock_handle = None
    try:
        lock_handle = acquire_lock(home)
        return run_beat(home, args)
    except HeartbeatError as error:
        print("HEARTBEAT RESULT: FAIL", file=sys.stderr)
        print("failed: 1 passed: 0", file=sys.stderr)
        print(f"ERROR heartbeat: {error}", file=sys.stderr)
        return 75 if "another heartbeat instance" in str(error) else 2
    except (OSError, UnicodeError) as error:
        print("HEARTBEAT RESULT: FAIL", file=sys.stderr)
        print("failed: 1 passed: 0", file=sys.stderr)
        print(f"ERROR heartbeat: {error}", file=sys.stderr)
        return 2
    finally:
        if lock_handle is not None:
            try:
                unlock(lock_handle)
                lock_handle.close()
            except OSError:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
