#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Distill recent session memories into graph annotations and lesson candidates."""

from __future__ import annotations

import argparse
import json
import os
import runpy
import sqlite3
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
kb_cli = SimpleNamespace(
    **runpy.run_path(str(REPO_ROOT / "hooks" / "lib" / "kb_cli.py"))
)
_command_template = runpy.run_path(str(Path(__file__).with_name("command_template.py")))
split_command_template = _command_template["split_command_template"]
DEFAULT_LLM_CMD = _command_template["default_llm_command"]()
WINDOWS_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
MAX_ENTRIES = 300
MAX_CHARS = 40_000
MIN_ENTRIES = 20
ROLES = ("user", "assistant", "summary")

EXTRACTION_INSTRUCTIONS = """\
对窗口内容做三类提炼，只输出一个 JSON：
{"entities":[{"name":"实体中文短名词","type":"类型"}],"edges":[{"src":"源实体","rel":"关系","dst":"目标实体","entry_id":123,"confidence":0.95}],"lessons":[{"text":"下次会再用到的通用教训","problem_type":"bug-fix|regression|performance|intent-drift|skill-mcp-misuse|host-inconsistency|workflow|platform-fact|design-decision|other","task_context":"什么任务和约束下发生","symptom":"可观察症状及期望/实际差异","root_cause":"已确认根因；不足时明确写 inconclusive 和缺失证据","evidence_status":"verified|inconclusive","evidence_entry_ids":[123],"route_positive":{"text":"应该召回的输入","reason":"命中哪些必要条件","source":"observed|constructed"},"route_negative":{"text":"最相似但不应召回的输入","reason":"缺少哪个必要条件","source":"observed|constructed"},"outcome_positive":{"text":"真正完成的做法或输出","reason":"满足哪些验收不变量","source":"observed|constructed"},"outcome_negative":{"text":"看似完成但仍错误的做法或输出","reason":"违反哪个验收不变量","source":"observed|constructed"}}]}
抽取纪律：
- 实体用中文短名词，同一事物全窗口统一叫法，做好共指消解。
- 边必须能从原文支撑，entry_id 标出处；推断的边 confidence 不高于 0.7。
- 宁缺毋滥，一次蒸馏 5-15 条边是健康量，不要为凑数建边。
- lessons 只收“下次会再用到”的内容，一次不超过 5 条；每条必须按 Layer1 问题卡结构输出。
- evidence_entry_ids 只引用本窗口 id。没有一手证据时 evidence_status=inconclusive，禁止猜根因。
- 四类样本不可混用：route 决定 apply/skip，outcome 决定 pass/fail；真实样本标 observed，
  为划边界构造的样本标 constructed，不得把 constructed 写成真实事故。
- 顶层必须且只能包含 entities、edges、lessons；只输出裸 JSON，不要解释。
"""

PROBLEM_TYPES = {
    "bug-fix", "regression", "performance", "intent-drift", "skill-mcp-misuse",
    "host-inconsistency", "workflow", "platform-fact", "design-decision", "other",
}
EVIDENCE_STATUSES = {"verified", "inconclusive"}
SAMPLE_SOURCES = {"observed", "constructed"}
LESSON_FIELDS = {
    "text", "problem_type", "task_context", "symptom", "root_cause",
    "evidence_status", "evidence_entry_ids", "route_positive", "route_negative",
    "outcome_positive", "outcome_negative",
}
SAMPLE_FIELDS = {"text", "reason", "source"}


class DistillError(RuntimeError):
    """A controlled failure that must leave the watermark unchanged."""


@dataclass(frozen=True)
class Entry:
    id: int
    role: str
    content: str


@dataclass(frozen=True)
class Window:
    entries: list[Entry]
    skipped: tuple[int, int] | None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def kb_home() -> Path:
    configured = os.environ.get("SULDE_KB_HOME")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".sulde" / "data" / "kb"


def append_log(home: Path, message: str) -> None:
    home.mkdir(parents=True, exist_ok=True)
    with (home / "auto-distill.log").open("a", encoding="utf-8") as handle:
        handle.write(f"{utc_now()} {message}\n")


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"last_id": 0}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("state must be an object")
        value = payload.get("last_id")
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError("last_id must be a non-negative integer")
        return payload
    except (OSError, UnicodeError, json.JSONDecodeError, AttributeError, ValueError) as error:
        raise DistillError(f"invalid distill state: {error}") from error


def load_last_id(path: Path) -> int:
    return int(load_state(path)["last_id"])


def select_window(database: Path, last_id: int) -> Window:
    if not database.is_file():
        raise DistillError(f"memory database not found: {database}")
    try:
        connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            rows = connection.execute(
                """
                SELECT id, role, content
                FROM mem_entries
                WHERE id > ? AND role IN (?, ?, ?)
                ORDER BY id DESC
                LIMIT ?
                """,
                (last_id, *ROLES, MAX_ENTRIES + 1),
            ).fetchall()

            selected_desc: list[Entry] = []
            total_chars = 0
            for row in rows:
                if len(selected_desc) >= MAX_ENTRIES:
                    break
                content = str(row["content"])
                if total_chars + len(content) > MAX_CHARS:
                    break
                selected_desc.append(Entry(int(row["id"]), str(row["role"]), content))
                total_chars += len(content)

            skipped = None
            if selected_desc:
                oldest_selected = selected_desc[-1].id
                bounds = connection.execute(
                    """
                    SELECT MIN(id), MAX(id)
                    FROM mem_entries
                    WHERE id > ? AND id < ? AND role IN (?, ?, ?)
                    """,
                    (last_id, oldest_selected, *ROLES),
                ).fetchone()
                if bounds[0] is not None:
                    skipped = (int(bounds[0]), int(bounds[1]))
            return Window(list(reversed(selected_desc)), skipped)
        finally:
            connection.close()
    except sqlite3.Error as error:
        raise DistillError(f"cannot read memory database: {error}") from error


def select_backfill_window(database: Path, cursor: int, end: int) -> Window:
    if not database.is_file():
        raise DistillError(f"memory database not found: {database}")
    try:
        connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            rows = connection.execute(
                """
                SELECT id, role, content
                FROM mem_entries
                WHERE id > ? AND id <= ? AND role IN (?, ?, ?)
                ORDER BY id ASC
                LIMIT ?
                """,
                (cursor, end, *ROLES, MAX_ENTRIES + 1),
            ).fetchall()
            selected: list[Entry] = []
            total_chars = 0
            for row in rows:
                if len(selected) >= MAX_ENTRIES:
                    break
                content = str(row["content"])
                if total_chars + len(content) > MAX_CHARS:
                    if not selected:
                        raise DistillError(
                            f"entry {int(row['id'])} exceeds the {MAX_CHARS}-character window"
                        )
                    break
                selected.append(Entry(int(row["id"]), str(row["role"]), content))
                total_chars += len(content)
            return Window(selected, None)
        finally:
            connection.close()
    except sqlite3.Error as error:
        raise DistillError(f"cannot read memory database: {error}") from error


def build_prompt(entries: list[Entry], retry: bool = False) -> str:
    rendered = "\n\n".join(
        f"[id={entry.id} role={entry.role}]\n{entry.content}" for entry in entries
    )
    prompt = f"{EXTRACTION_INSTRUCTIONS}\n待蒸馏窗口：\n{rendered}"
    if retry:
        prompt += "\n\n上次输出无法解析。只输出裸 JSON，不要 Markdown 围栏或任何解释。"
    return prompt


def run_llm(command_template: str, prompt: str) -> str:
    try:
        arguments = split_command_template(command_template)
    except ValueError as error:
        raise DistillError(f"invalid --llm-cmd: {error}") from error
    if not arguments:
        raise DistillError("--llm-cmd cannot be empty")

    stdin_prompt: str | None = prompt
    expanded: list[str] = []
    for argument in arguments:
        if argument == "{prompt}":
            # A standalone placeholder is intentionally supplied over stdin.
            continue
        if "{prompt}" in argument:
            argument = argument.replace("{prompt}", prompt)
            stdin_prompt = None
        expanded.append(argument)
    try:
        completed = subprocess.run(
            expanded,
            input=stdin_prompt,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
            creationflags=WINDOWS_CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except OSError as error:
        raise DistillError(f"LLM command failed to start: {error}") from error
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise DistillError(
            f"LLM command exited {completed.returncode}: {detail[:500]}"
        )
    return completed.stdout


def strip_json_fence(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```") and text.endswith("```"):
        lines = text.splitlines()
        if len(lines) >= 2 and lines[0].strip().lower() in {"```", "```json"}:
            return "\n".join(lines[1:-1]).strip()
    return text


def parse_result(raw: str) -> dict[str, Any]:
    try:
        payload = json.loads(strip_json_fence(raw))
    except json.JSONDecodeError as error:
        raise DistillError(f"invalid LLM JSON: {error}") from error
    if not isinstance(payload, dict):
        raise DistillError("LLM JSON must be an object")
    if set(payload) != {"entities", "edges", "lessons"}:
        raise DistillError("LLM JSON must contain only entities, edges, and lessons")
    if not all(isinstance(payload[key], list) for key in payload):
        raise DistillError("entities, edges, and lessons must be arrays")
    for index, entity in enumerate(payload["entities"]):
        if not isinstance(entity, dict) or set(entity) != {"name", "type"}:
            raise DistillError(f"entities[{index}] must contain name and type")
        if not all(isinstance(entity[key], str) and entity[key].strip() for key in entity):
            raise DistillError(f"entities[{index}] fields must be non-empty strings")
    for index, edge in enumerate(payload["edges"]):
        required = {"src", "rel", "dst", "entry_id", "confidence"}
        if not isinstance(edge, dict) or set(edge) != required:
            raise DistillError(f"edges[{index}] has invalid fields")
        if not all(isinstance(edge[key], str) and edge[key].strip() for key in ("src", "rel", "dst")):
            raise DistillError(f"edges[{index}] text fields must be non-empty strings")
        entry_id = edge["entry_id"]
        if entry_id is not None and (isinstance(entry_id, bool) or not isinstance(entry_id, int)):
            raise DistillError(f"edges[{index}].entry_id must be an integer or null")
        confidence = edge["confidence"]
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
            raise DistillError(f"edges[{index}].confidence must be a number")
    for index, lesson in enumerate(payload["lessons"]):
        if not isinstance(lesson, dict) or set(lesson) != LESSON_FIELDS:
            raise DistillError(f"lessons[{index}] must follow the Layer1 problem-card schema")
        for key in ("text", "task_context", "symptom", "root_cause"):
            if not isinstance(lesson[key], str) or not lesson[key].strip():
                raise DistillError(f"lessons[{index}].{key} must be a non-empty string")
        if lesson["problem_type"] not in PROBLEM_TYPES:
            raise DistillError(f"lessons[{index}].problem_type is invalid")
        if lesson["evidence_status"] not in EVIDENCE_STATUSES:
            raise DistillError(f"lessons[{index}].evidence_status is invalid")
        evidence_ids = lesson["evidence_entry_ids"]
        if not isinstance(evidence_ids, list) or any(
            isinstance(item, bool) or not isinstance(item, int) or item < 1
            for item in evidence_ids
        ):
            raise DistillError(f"lessons[{index}].evidence_entry_ids must be positive integers")
        for role in ("route_positive", "route_negative", "outcome_positive", "outcome_negative"):
            sample = lesson[role]
            if not isinstance(sample, dict) or set(sample) != SAMPLE_FIELDS:
                raise DistillError(
                    f"lessons[{index}].{role} must contain text, reason, and source"
                )
            for key in ("text", "reason"):
                if not isinstance(sample[key], str) or not sample[key].strip():
                    raise DistillError(
                        f"lessons[{index}].{role}.{key} must be non-empty"
                    )
            if sample["source"] not in SAMPLE_SOURCES:
                raise DistillError(f"lessons[{index}].{role}.source is invalid")
    return payload


def annotate(payload: dict[str, Any]) -> dict[str, int]:
    # This is a background import of extracted assertions, not an implicitly
    # Claude-owned interactive write. Individual source entries keep their host.
    annotation = {"entities": payload["entities"], "edges": payload["edges"], "extracted_by": "import"}
    completed = kb_cli.run_cli(
        REPO_ROOT,
        kb_home(),
        "mem-annotate",
        [
            "--json",
            json.dumps(annotation, ensure_ascii=False),
        ],
        timeout=120,
    )
    if not completed.ok:
        detail = completed.stderr.strip() or completed.stdout.strip() or completed.detail
        if completed.returncode is not None:
            raise DistillError(
                f"mem-annotate exited {completed.returncode}: {detail[:500]}"
            )
        raise DistillError(
            f"mem-annotate failed ({completed.status}): {detail[:500]}"
        )
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise DistillError(f"invalid mem-annotate response: {error}") from error
    if not isinstance(result, dict):
        raise DistillError("invalid mem-annotate response object")
    return {
        "entities_inserted": int(result.get("entities_inserted", 0)),
        "inserted": int(result.get("inserted", 0)),
    }


def _one_line(value: Any) -> str:
    return " ".join(str(value).strip().split())


def append_candidates(path: Path, lessons: list[dict[str, Any]]) -> None:
    if not lessons:
        return
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"\n## {datetime.now().astimezone().date().isoformat()}\n\n")
        for lesson in lessons:
            ids = ", ".join(str(item) for item in lesson["evidence_entry_ids"]) or "无"
            handle.write("### Layer1 问题卡\n\n")
            handle.write(f"- **问题类型**：{lesson['problem_type']}\n")
            handle.write(f"- **任务与触发场景**：{_one_line(lesson['task_context'])}\n")
            handle.write(f"- **症状与差异**：{_one_line(lesson['symptom'])}\n")
            handle.write(f"- **根因与证据缺口**：{_one_line(lesson['root_cause'])}\n")
            handle.write(f"- **证据状态**：{lesson['evidence_status']}\n")
            handle.write(f"- **一手证据 entry_id**：{ids}\n")
            for label, key in (
                ("路由正例", "route_positive"),
                ("路由反例", "route_negative"),
                ("执行合格例", "outcome_positive"),
                ("执行失败例", "outcome_negative"),
            ):
                sample = lesson[key]
                handle.write(
                    f"- **{label}**（{sample['source']}）：{_one_line(sample['text'])}\n"
                )
                handle.write(f"  - **判定原因**：{_one_line(sample['reason'])}\n")
            handle.write(
                f"- **沉淀候选**：{_one_line(lesson['text'])}"
                "（待 /sediment 处理）\n\n"
            )


def write_state(path: Path, payload: dict[str, Any]) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def notify(message: str) -> None:
    try:
        notifier = runpy.run_path(
            str(REPO_ROOT / "hooks" / "lib" / "kb_notify.py")
        )
        notifier["run"]({"message": message})
    except Exception:
        return


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--llm-cmd",
        default=DEFAULT_LLM_CMD,
        help="command template; a standalone {prompt} is delivered through stdin",
    )
    parser.add_argument(
        "--backfill",
        nargs=2,
        type=int,
        metavar=("START", "END"),
        help="distill the historical interval (START, END] oldest first",
    )
    parser.add_argument(
        "--backfill-batches",
        type=int,
        default=0,
        help="number of backfill windows to process after the normal window (default: 0)",
    )
    args = parser.parse_args()
    if args.backfill_batches < 0:
        parser.error("--backfill-batches must be >= 0")
    if args.backfill is not None:
        start, end = args.backfill
        if start < 0 or end < 0 or start > end:
            parser.error("--backfill requires 0 <= START <= END")
    return args


def distill_window(home: Path, llm_cmd: str, window: Window) -> tuple[dict[str, int], int]:
    parsed: dict[str, Any] | None = None
    parse_errors: list[str] = []
    for attempt in range(2):
        raw = run_llm(llm_cmd, build_prompt(window.entries, retry=attempt == 1))
        try:
            parsed = parse_result(raw)
            break
        except DistillError as error:
            parse_errors.append(str(error))
            append_log(home, f"LLM parse attempt={attempt + 1} failed: {error}")
    if parsed is None:
        raise DistillError(f"LLM JSON parsing failed twice: {'; '.join(parse_errors)}")

    valid_ids = {entry.id for entry in window.entries}
    for edge in parsed["edges"]:
        if edge["entry_id"] not in valid_ids:
            edge["entry_id"] = None
    for lesson in parsed["lessons"]:
        lesson["evidence_entry_ids"] = [
            entry_id for entry_id in lesson["evidence_entry_ids"] if entry_id in valid_ids
        ]
        if lesson["evidence_status"] == "verified" and not lesson["evidence_entry_ids"]:
            lesson["evidence_status"] = "inconclusive"
            lesson["root_cause"] = (
                f"inconclusive：窗口内没有可回读的一手 entry_id；{lesson['root_cause']}"
            )

    counts = annotate(parsed)
    append_candidates(home / "distill-candidates.md", parsed["lessons"])
    return counts, len(parsed["lessons"])


def notify_result(counts: dict[str, int], lesson_count: int) -> None:
    notify(
        f"自动蒸馏:{counts['entities_inserted']}实体 "
        f"{counts['inserted']}边入图,{lesson_count}条沉淀候选"
    )


def load_backfill(state: dict[str, Any]) -> tuple[int, int]:
    backfill = state.get("backfill")
    if not isinstance(backfill, dict) or set(backfill) != {"cursor", "end"}:
        raise DistillError("invalid distill state: backfill must contain cursor and end")
    cursor = backfill["cursor"]
    end = backfill["end"]
    if (
        isinstance(cursor, bool)
        or not isinstance(cursor, int)
        or isinstance(end, bool)
        or not isinstance(end, int)
        or cursor < 0
        or end < 0
        or cursor > end
    ):
        raise DistillError("invalid distill state: backfill cursor/end are invalid")
    return cursor, end


def run_backfill_phase(args: argparse.Namespace, home: Path, state_path: Path) -> int:
    """补蒸追加阶段:--backfill 初始化游标;仅 --backfill-batches 时凭状态续跑。"""
    state = load_state(state_path)
    if "backfill" not in state:
        if args.backfill is None:
            if args.backfill_batches:
                append_log(home, "backfill skipped: no backfill state and no --backfill range")
            return 0
        start, end = args.backfill
        state["backfill"] = {"cursor": start, "end": end}
        state["ts"] = utc_now()
        write_state(state_path, state)

    batches = args.backfill_batches or (1 if args.backfill is not None else 0)
    for _ in range(batches):
        cursor, end = load_backfill(state)
        if cursor >= end:
            print("补蒸完成")
            return 0
        window = select_backfill_window(home / "memory.db", cursor, end)
        entry_count = len(window.entries)
        char_count = sum(len(entry.content) for entry in window.entries)
        append_log(
            home,
            f"backfill window cursor={cursor} end={end} "
            f"entries={entry_count} chars={char_count}",
        )
        if not window.entries:
            state["backfill"] = {"cursor": end, "end": end}
            state["ts"] = utc_now()
            write_state(state_path, state)
            append_log(home, f"backfill no eligible entries; cursor={end}")
            continue

        counts, lesson_count = distill_window(home, args.llm_cmd, window)
        max_id = window.entries[-1].id
        state["backfill"] = {"cursor": max_id, "end": end}
        state["ts"] = utc_now()
        write_state(state_path, state)
        notify_result(counts, lesson_count)
        append_log(
            home,
            f"backfill result entities={counts['entities_inserted']} "
            f"edges={counts['inserted']} lessons={lesson_count} cursor={max_id}",
        )
    return 0


def main() -> int:
    args = parse_args()
    home = kb_home()
    home.mkdir(parents=True, exist_ok=True)
    state_path = home / "distill-state.json"
    try:
        state = load_state(state_path)
        last_id = int(state["last_id"])
        window = select_window(home / "memory.db", last_id)
        entry_count = len(window.entries)
        char_count = sum(len(entry.content) for entry in window.entries)
        skipped_text = (
            f" skipped={window.skipped[0]}-{window.skipped[1]}"
            if window.skipped
            else " skipped=none"
        )
        append_log(home, f"window entries={entry_count} chars={char_count}{skipped_text}")
        if entry_count < MIN_ENTRIES:
            append_log(home, f"no work: fewer than {MIN_ENTRIES} entries; watermark unchanged")

        if entry_count >= MIN_ENTRIES:
            counts, lesson_count = distill_window(home, args.llm_cmd, window)
            max_id = window.entries[-1].id
            state["last_id"] = max_id
            state["ts"] = utc_now()
            write_state(state_path, state)
            notify_result(counts, lesson_count)
            append_log(
                home,
                f"result entities={counts['entities_inserted']} edges={counts['inserted']} "
                f"lessons={lesson_count} last_id={max_id}",
            )
        return run_backfill_phase(args, home, state_path)
    except (DistillError, OSError, UnicodeError) as error:
        append_log(home, f"failure: {error}; watermark unchanged")
        print(f"auto-distill: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
