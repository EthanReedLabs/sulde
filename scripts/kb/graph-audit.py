#!/usr/bin/env python3
"""Audit sampled memory-graph edges against their source entries."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import runpy
import sqlite3
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any


_command_template = runpy.run_path(str(Path(__file__).with_name("command_template.py")))
split_command_template = _command_template["split_command_template"]


DEFAULT_LLM_CMD = _command_template["default_llm_command"]()
DEFAULT_SAMPLE = 20
_truth = runpy.run_path(str(Path(__file__).resolve().parents[2] / "tools/kb-index/memory.py"))
source_truth = _truth["source_truth"]
source_review_hint = _truth["source_review_hint"]
correction_candidate = _truth["correction_candidate"]
VERDICTS = ("supported", "unsupported", "uncertain")

AUDIT_INSTRUCTIONS = """\
你是 Sulde 图谱质检官。只根据给出的来源条目原文，判断该图谱边是否被原文支撑。
判定规则：
- supported：原文明确陈述该关系，允许不改变含义的同义改写。
- unsupported：原文与关系矛盾，或关系是原文没有依据的捏造/过度推断。
- uncertain：原文信息不足以可靠判断、指代不清，或只能弱推断。
- temporal_modal 独立核查时间/模态：目标、计划、提案、反事实、PLANNED/NOT_READY 不能判为当前已达成事实。
- predicate_object 独立核查完整谓词及宾语：因果结果的关键限定不可丢失，词语重合不等于关系成立。
- 例如 SyntheticApplication —定位为→ 示例检索系统，来源末尾为 PLANNED/NOT_READY，temporal_modal 必须 unsupported。
- 例如 stale build —导致→ iOS walkthrough probe，来源为旧 app 让 probe 未携带最新 marker，宾语丢失关键谓词，predicate_object 必须 unsupported 或 uncertain。
- verdict 只有两个独立维度都 supported 才能 supported；任一 unsupported 则 unsupported，否则 uncertain。
- 关键词启发式只产生 inconclusive 待审提示，不代表人工裁决，也不可据此隐藏边。\n- 不使用外部知识补足证据；宁可 uncertain，不把推测判为 supported。
只输出一个裸 JSON，字段必须且只能是：
{"edge_id":123,"verdict":"supported|unsupported|uncertain","temporal_modal":"supported|unsupported|uncertain","predicate_object":"supported|unsupported|uncertain","reason":"分别说明时间/模态与完整谓词的原文证据"}
"""


class AuditError(RuntimeError):
    """A controlled audit failure."""


@dataclass(frozen=True)
class Edge:
    id: int
    src: str
    rel: str
    dst: str
    entry_id: int | None
    extracted_by: str
    confidence: float
    content: str | None
    truth_status: str = "unverified"
    truth_source_sha256: str | None = None
    ts: str | None = None


@dataclass(frozen=True)
class Judgment:
    edge: Edge
    verdict: str
    reason: str
    temporal_modal: str = "uncertain"
    predicate_object: str = "uncertain"


def kb_home() -> Path:
    configured = os.environ.get("SULDE_KB_HOME")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".sulde" / "data" / "kb"


def load_edges(database: Path) -> tuple[list[Edge], list[Edge]]:
    """Return sourced and NULL-lineage edges without mutating the database."""
    if not database.is_file():
        raise AuditError(f"memory database not found: {database}")
    try:
        connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            columns = {row[1] for row in connection.execute("PRAGMA table_info(mem_edges)")}
            truth_column = "g.truth_status" if "truth_status" in columns else "'unverified'"
            digest_column = "g.truth_source_sha256" if "truth_source_sha256" in columns else "NULL"
            rows = connection.execute(
                f"""
                SELECT g.id, g.src, g.rel, g.dst, g.entry_id,
                       g.extracted_by, g.confidence, e.content, g.ts, {truth_column} AS truth_status, {digest_column} AS truth_source_sha256
                FROM mem_edges AS g
                LEFT JOIN mem_entries AS e ON e.id = g.entry_id
                ORDER BY g.id
                """
            ).fetchall()
        finally:
            connection.close()
    except sqlite3.Error as error:
        raise AuditError(f"cannot read memory database: {error}") from error

    edges = [
        Edge(
            id=int(row["id"]),
            src=str(row["src"]),
            rel=str(row["rel"]),
            dst=str(row["dst"]),
            entry_id=int(row["entry_id"]) if row["entry_id"] is not None else None,
            extracted_by=str(row["extracted_by"]),
            confidence=float(row["confidence"]),
            content=str(row["content"]) if row["content"] is not None else None,
            truth_status=str(row["truth_status"]),
            truth_source_sha256=row["truth_source_sha256"], ts=row["ts"],
        )
        for row in rows
    ]
    return (
        [edge for edge in edges if edge.entry_id is not None],
        [edge for edge in edges if edge.entry_id is None],
    )


def select_edges(edges: list[Edge], sample: int | None, audit_date: date) -> list[Edge]:
    if sample is None or sample >= len(edges):
        return list(edges)
    seed = audit_date.isoformat()
    ranked = sorted(
        edges,
        key=lambda edge: hashlib.sha256(f"{seed}:{edge.id}".encode("utf-8")).digest(),
    )
    return sorted(ranked[:sample], key=lambda edge: edge.id)


def build_prompt(edge: Edge, retry: bool = False) -> str:
    payload = {
        "edge": {
            "id": edge.id,
            "src": edge.src,
            "rel": edge.rel,
            "dst": edge.dst,
            "entry_id": edge.entry_id,
            "truth_status": edge.truth_status,
        },
        "source_entry": edge.content,
    }
    prompt = f"{AUDIT_INSTRUCTIONS}\n待审计数据：\n{json.dumps(payload, ensure_ascii=False, indent=2)}"
    if retry:
        prompt += "\n上次输出无法解析。只输出符合指定 schema 的裸 JSON。"
    return prompt


def run_llm(command_template: str, prompt: str) -> str:
    try:
        arguments = split_command_template(command_template)
    except ValueError as error:
        raise AuditError(f"invalid --llm-cmd: {error}") from error
    if not arguments:
        raise AuditError("--llm-cmd cannot be empty")

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
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=180,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise AuditError(f"LLM command failed: {error}") from error
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise AuditError(f"LLM command exited {completed.returncode}: {detail[:500]}")
    return completed.stdout


def strip_json_fence(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```") and text.endswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3 and lines[0].strip().lower() in {"```", "```json"}:
            return "\n".join(lines[1:-1]).strip()
    return text


def parse_judgment(raw: str, expected_edge_id: int) -> tuple[str, str, str, str]:
    try:
        payload: Any = json.loads(strip_json_fence(raw))
    except json.JSONDecodeError as error:
        raise AuditError(f"invalid LLM JSON: {error}") from error
    if not isinstance(payload, dict) or set(payload) != {"edge_id", "verdict", "reason", "temporal_modal", "predicate_object"}:
        raise AuditError("LLM JSON must contain edge_id, verdict, reason, temporal_modal, predicate_object")
    edge_id = payload["edge_id"]
    if isinstance(edge_id, bool) or not isinstance(edge_id, int) or edge_id != expected_edge_id:
        raise AuditError(f"LLM edge_id must equal {expected_edge_id}")
    verdict = payload["verdict"]
    if verdict not in VERDICTS:
        raise AuditError("LLM verdict must be supported, unsupported, or uncertain")
    reason = payload["reason"]
    if not isinstance(reason, str) or not reason.strip():
        raise AuditError("LLM reason must be a non-empty string")
    dimensions = [payload["temporal_modal"], payload["predicate_object"]]
    if any(not isinstance(value, str) or value not in VERDICTS for value in dimensions):
        raise AuditError("invalid independent truth dimensions")
    expected = "unsupported" if "unsupported" in dimensions else "uncertain" if "uncertain" in dimensions else "supported"
    if verdict != expected:
        raise AuditError("verdict conflicts with independent truth dimensions")
    return verdict, reason.strip(), *dimensions


def judge_edge(edge: Edge, llm_cmd: str) -> Judgment:
    if edge.content is None:
        return Judgment(edge, "uncertain", "血缘 entry_id 对应的来源条目不存在，无法核验。")
    errors: list[str] = []
    for attempt in range(2):
        try:
            verdict, reason, temporal, predicate = parse_judgment(
                run_llm(llm_cmd, build_prompt(edge, retry=attempt == 1)), edge.id
            )
            hint = source_review_hint(edge.src, edge.rel, edge.dst, edge.content)
            # Hints request review, never establish a semantic correction.
            rank = {"supported": 0, "uncertain": 1, "unsupported": 2}
            if hint:
                temporal = max((temporal, hint["temporal_modal"]), key=rank.get)
                predicate = max((predicate, hint["predicate_object"]), key=rank.get)
                reason += "; " + hint["reason"]
            if (edge.truth_source_sha256 == _truth["graph_digest"](edge.content)
                    and edge.truth_status in {"goal", "planned", "not_ready", "counterfactual", "unsupported"}):
                temporal = "unsupported"
            verdict = max((temporal, predicate), key=rank.get)
            return Judgment(edge, verdict, reason, temporal, predicate)
        except AuditError as error:
            errors.append(str(error))
    return Judgment(edge, "uncertain", f"LLM 判定失败：{'; '.join(errors)}"[:1000])


def markdown_cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def judgment_table(rows: list[Judgment]) -> list[str]:
    lines = [
        "| edge_id | 图谱边 | entry_id | 置信度 | 判定理由 |",
        "|---:|---|---:|---:|---|",
    ]
    if not rows:
        lines.append("| - | 无 | - | - | - |")
    for judgment in rows:
        edge = judgment.edge
        triple = f"{edge.src} —{edge.rel}→ {edge.dst}"
        lines.append(
            f"| {edge.id} | {markdown_cell(triple)} | {edge.entry_id} | "
            f"{edge.confidence:.3f} | {markdown_cell(judgment.reason)} |"
        )
    return lines


def shared_table(edges: list[Edge]) -> list[str]:
    lines = [
        "| edge_id | 图谱边 | extracted_by | 置信度 |",
        "|---:|---|---|---:|",
    ]
    if not edges:
        lines.append("| - | 无 | - | - |")
    for edge in edges:
        triple = f"{edge.src} —{edge.rel}→ {edge.dst}"
        lines.append(
            f"| {edge.id} | {markdown_cell(triple)} | "
            f"{markdown_cell(edge.extracted_by)} | {edge.confidence:.3f} |"
        )
    return lines


def render_report(
    judgments: list[Judgment],
    shared_edges: list[Edge],
    eligible_count: int,
    audit_date: date,
    mode: str,
) -> str:
    grouped = {verdict: [] for verdict in VERDICTS}
    for judgment in judgments:
        grouped[judgment.verdict].append(judgment)
    lines = [
        f"# 图谱边抽检报告（{audit_date.isoformat()}）",
        "",
        f"- 模式：{mode}",
        f"- 有血缘边总数：{eligible_count}",
        f"- 本次判定：{len(judgments)}",
        f"- supported：{len(grouped['supported'])}",
        f"- unsupported：{len(grouped['unsupported'])}",
        f"- uncertain：{len(grouped['uncertain'])}",
        f"- NULL 血缘共享边：{len(shared_edges)}（单独列账，不判定）",
        "",
        "## Supported",
        "",
        *judgment_table(grouped["supported"]),
        "",
        "## Unsupported（待人工处置）",
        "",
        "> 本节仅列出建议人工复核/处置的边 ID；本脚本不修改或删除图谱边。",
        "",
        *judgment_table(grouped["unsupported"]),
        "",
        "## Uncertain",
        "",
        *judgment_table(grouped["uncertain"]),
        "",
        "## NULL 血缘共享边（不判）",
        "",
        *shared_table(shared_edges),
        "",
    ]
    return "\n".join(lines)


def write_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def write_immutable(path: Path, payload: dict[str, Any]) -> None:
    content = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError:
        if path.read_text(encoding="utf-8") != content:
            raise AuditError(f"immutable review candidate collision: {path}")
    if path.read_text(encoding="utf-8") != content:
        raise AuditError(f"review candidate readback mismatch: {path}")


def print_dry_run(eligible: int, selected: int, shared: int) -> None:
    print("GRAPH AUDIT DRY-RUN: PASS")
    print(f"sampled: eligible={eligible} selected={selected} shared_null={shared}")
    print("writes: 0  llm_calls: 0")


def print_summary(judgments: list[Judgment], shared: int, output: Path) -> None:
    counts = {verdict: sum(row.verdict == verdict for row in judgments) for verdict in VERDICTS}
    result = "FAIL" if counts["unsupported"] else "INCONCLUSIVE" if counts["uncertain"] else "PASS"
    print(f"GRAPH AUDIT RESULT: {result}")
    print(
        f"audited: total={len(judgments)} supported={counts['supported']} "
        f"unsupported={counts['unsupported']} uncertain={counts['uncertain']} shared_null={shared}"
    )
    unsupported = [str(row.edge.id) for row in judgments if row.verdict == "unsupported"]
    uncertain = [str(row.edge.id) for row in judgments if row.verdict == "uncertain"]
    if unsupported:
        print("ERROR unsupported edge_ids=" + ",".join(unsupported))
    if uncertain:
        print("WARN uncertain edge_ids=" + ",".join(uncertain))
    print(f"details: {output}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", type=int, default=None, help=f"sample sourced edges (default: {DEFAULT_SAMPLE})")
    parser.add_argument("--all", action="store_true", help="audit all sourced edges")
    parser.add_argument("--dry-run", action="store_true", help="print sample counts without LLM calls or writes")
    parser.add_argument(
        "--llm-cmd",
        default=DEFAULT_LLM_CMD,
        help="command template; a standalone {prompt} is delivered through stdin",
    )
    args = parser.parse_args()
    if args.sample is not None and args.all:
        parser.error("--sample and --all are mutually exclusive")
    if args.sample is not None and args.sample < 0:
        parser.error("--sample must be >= 0")
    if args.sample is None and not args.all:
        args.sample = DEFAULT_SAMPLE
    return args


def main() -> int:
    args = parse_args()
    home = kb_home()
    today = date.today()
    try:
        sourced, shared = load_edges(home / "memory.db")
        selected = select_edges(sourced, None if args.all else args.sample, today)
        if args.dry_run:
            print_dry_run(len(sourced), len(selected), len(shared))
            return 0
        judgments = [judge_edge(edge, args.llm_cmd) for edge in selected]
        mode = "all" if args.all else f"sample={args.sample}"
        report = render_report(judgments, shared, len(sourced), today, mode)
        output = home / "governance" / f"graph-audit-{today.isoformat()}.md"
        candidates = []
        for judgment in judgments:
            if judgment.verdict == "supported":
                continue
            assessment = source_truth(judgment.edge.src, judgment.edge.rel, judgment.edge.dst,
                                      judgment.edge.content, judgment.edge.truth_status)
            assessment.update(verdict=judgment.verdict, temporal_modal=judgment.temporal_modal,
                              predicate_object=judgment.predicate_object, reason=judgment.reason)
            candidate = correction_candidate(asdict(judgment.edge), assessment)
            candidate_path = output.parent / "graph-corrections" / (candidate["candidate_sha256"] + ".json")
            write_immutable(candidate_path, candidate)
            candidates.append(candidate)
        write_atomic(output.with_suffix(".json"), json.dumps({
            "schema": "sulde-graph-audit-v2", "date": today.isoformat(),
            "judgments": [asdict(row) for row in judgments],
            "review_candidates": candidates, "database_mutations": 0,
        }, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
        write_atomic(output, report)
        print_summary(judgments, len(shared), output)
        return 0
    except (AuditError, OSError, UnicodeError) as error:
        print(f"ERROR graph-audit: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
