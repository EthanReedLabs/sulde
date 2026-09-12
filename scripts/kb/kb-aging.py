#!/usr/bin/env python3
"""Report old KB documents and old documents with no adoption signal."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "kb-index"))
from knowledge_history import HistoryError, load_history


CONTAINER_DIRS = {"anti-patterns", "platform-kb", "tech-docs", "work-model"}
EXCLUDED_BASENAMES = {"INDEX.md", "README.md"}
DOC_ID_RE = re.compile(r"^doc_id:\s*(.*?)\s*$")


class AgingError(RuntimeError):
    """A controlled failure suitable for concise CLI output."""


@dataclass(frozen=True)
class AgingEntry:
    doc_id: str
    source_path: str
    modified_at: datetime
    age_days: int
    adoption_count: int


def kb_home() -> Path:
    configured = os.environ.get("SULDE_KB_HOME")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".sulde" / "data" / "kb"


def tracked_documents(repo: Path) -> list[Path]:
    try:
        completed = subprocess.run(
            ["git", "ls-files", "-z", "--", "knowledge"],
            cwd=repo,
            capture_output=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        detail = getattr(error, "stderr", b"")
        rendered = detail.decode("utf-8", errors="replace").strip() if detail else str(error)
        raise AgingError(f"cannot enumerate tracked knowledge documents: {rendered}") from error
    candidates = [Path(raw.decode("utf-8")) for raw in completed.stdout.split(b"\0") if raw]
    return sorted(
        (
            path
            for path in candidates
            if path.suffix.lower() == ".md"
            and path.name not in EXCLUDED_BASENAMES
            and len(path.parts) >= 3
            and path.parts[0] == "knowledge"
            and path.parts[1] in CONTAINER_DIRS
        ),
        key=lambda item: item.as_posix(),
    )


def decode_scalar(value: str) -> str:
    value = value.strip()
    if value.startswith('"'):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError as error:
            raise AgingError(f"invalid quoted doc_id: {value}") from error
        return decoded if isinstance(decoded, str) else str(decoded)
    if len(value) >= 2 and value.startswith("'") and value.endswith("'"):
        return value[1:-1].replace("''", "'")
    return value


def read_doc_id(path: Path) -> str:
    try:
        with path.open(encoding="utf-8") as handle:
            if handle.readline().strip() != "---":
                raise AgingError(f"{path}: missing frontmatter")
            for line in handle:
                if line.strip() == "---":
                    break
                match = DOC_ID_RE.match(line.rstrip("\n"))
                if match:
                    value = decode_scalar(match.group(1))
                    if value:
                        return value
    except (OSError, UnicodeError) as error:
        raise AgingError(f"cannot read {path}: {error}") from error
    raise AgingError(f"{path}: missing or empty doc_id")


def last_modified(repo: Path, relative: Path) -> datetime:
    command = [
        "git",
        "-c",
        "core.quotePath=false",
        "log",
        "-1",
        "--format=%cI",
        "--",
        relative.as_posix(),
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=repo,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        detail = getattr(error, "stderr", "").strip() or str(error)
        raise AgingError(f"git history failed for {relative}: {detail}") from error
    value = completed.stdout.strip()
    if not value:
        raise AgingError(f"no git history for tracked document {relative}")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise AgingError(f"invalid git timestamp for {relative}: {value}") from error
    if parsed.tzinfo is None:
        raise AgingError(f"git timestamp lacks timezone for {relative}: {value}")
    return parsed


def document_history(repo: Path) -> list[tuple[Path, datetime]]:
    """Use local Git in source trees, otherwise require sealed packaged history."""
    if (repo / ".git").exists():
        return [
            (relative, last_modified(repo, relative))
            for relative in tracked_documents(repo)
        ]
    try:
        history = load_history(repo)
    except HistoryError as error:
        raise AgingError(f"packaged knowledge history is invalid: {error}") from error
    return [
        (Path(document.path), datetime.fromisoformat(document.last_commit_at))
        for document in history.documents
    ]


def adoption_counts(path: Path) -> tuple[Counter[str], bool]:
    counts: Counter[str] = Counter()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return counts, False
    except (OSError, UnicodeError) as error:
        raise AgingError(f"cannot read feedback log {path}: {error}") from error
    for line in lines:
        if not line.strip():
            continue
        try:
            record: Any = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(record, dict) or record.get("event") != "read_after_inject":
            continue
        doc_id = record.get("doc_id")
        if isinstance(doc_id, str) and doc_id:
            counts[doc_id] += 1
    return counts, bool(counts)


def analyze(repo: Path, home: Path, days: int, report_date: date) -> tuple[list[AgingEntry], list[AgingEntry], int, bool]:
    counts, feedback_sufficient = adoption_counts(home / "feedback-log.jsonl")
    cutoff = report_date - timedelta(days=days)
    entries: list[AgingEntry] = []
    documents = document_history(repo)
    for relative, modified in documents:
        doc_id = read_doc_id(repo / relative)
        age_days = max(0, (report_date - modified.date()).days)
        if modified.date() <= cutoff:
            entries.append(
                AgingEntry(
                    doc_id=doc_id,
                    source_path=relative.as_posix(),
                    modified_at=modified,
                    age_days=age_days,
                    adoption_count=counts[doc_id],
                )
            )
    stale = sorted(entries, key=lambda item: (-item.age_days, item.source_path))
    zero_adoption = [entry for entry in stale if entry.adoption_count == 0]
    return zero_adoption, stale, len(documents), feedback_sufficient


def table(entries: list[AgingEntry]) -> str:
    if not entries:
        return "_无_"
    rows = [
        "| doc_id | source_path | 末次提交 | 年龄(天) | 采纳次数 |",
        "|---|---|---:|---:|---:|",
    ]
    for entry in entries:
        rows.append(
            f"| `{entry.doc_id}` | `{entry.source_path}` | "
            f"{entry.modified_at.date().isoformat()} | {entry.age_days} | {entry.adoption_count} |"
        )
    return "\n".join(rows)


def render_report(
    *,
    report_date: date,
    days: int,
    document_count: int,
    feedback_sufficient: bool,
    zero_adoption: list[AgingEntry],
    stale: list[AgingEntry],
) -> str:
    signal = "充足" if feedback_sufficient else "不足"
    lines = [
        f"# KB 老化审查报告（{report_date.isoformat()}）",
        "",
        "> 观察员模式：本报告只提供更新/废弃候选，不修改或删除知识库内容。",
        "",
        "## 摘要",
        "",
        f"- 审查文档：{document_count}",
        f"- 老化阈值：≥ {days} 天",
        f"- 零采纳且超龄：{len(zero_adoption)}",
        f"- 超龄未更新：{len(stale)}",
        f"- 采纳信号：{signal}",
    ]
    if not feedback_sufficient:
        lines.append("- ⚠️ 采纳信号不足,仅按文件年龄")
    lines.extend(
        [
            "",
            "## 零采纳且超龄",
            "",
            table(zero_adoption),
            "",
            "## 超龄未更新",
            "",
            table(stale),
            "",
            "## 口径",
            "",
            "- 采纳仅统计 `feedback-log.jsonl` 中的 `read_after_inject` 事件。",
            "- 文件年龄取该知识文件在 git 中的末次提交时间；达到阈值当天即纳入。",
            "- 两类清单允许重叠；本报告不自动判定废弃，也不执行任何写库或删除动作。",
            "",
        ]
    )
    return "\n".join(lines)


def positive_days(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be an integer") from error
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=positive_days, default=90, help="age threshold in days (default: 90)")
    parser.add_argument("--dry-run", action="store_true", help="analyze and print counts without writing the report")
    parser.add_argument("--repo", type=Path, default=REPO_ROOT, help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    home = kb_home()
    report_date = datetime.now().astimezone().date()
    try:
        zero_adoption, stale, document_count, feedback_sufficient = analyze(
            args.repo.resolve(), home, args.days, report_date
        )
        report = render_report(
            report_date=report_date,
            days=args.days,
            document_count=document_count,
            feedback_sufficient=feedback_sufficient,
            zero_adoption=zero_adoption,
            stale=stale,
        )
        output = home / "governance" / f"aging-{report_date.isoformat()}.md"
        if not args.dry_run:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(report, encoding="utf-8")
    except AgingError as error:
        print("KB AGING RESULT: FAIL", file=sys.stderr)
        print(f"ERROR kb-aging: {error}", file=sys.stderr)
        return 2

    print("KB AGING RESULT: PASS")
    print(f"documents: {document_count}")
    print(f"zero_adoption_aged: {len(zero_adoption)}")
    print(f"stale_unupdated: {len(stale)}")
    print(f"feedback_signal: {'sufficient' if feedback_sufficient else 'insufficient'}")
    print(f"details: {output if not args.dry_run else 'dry-run (not written)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
