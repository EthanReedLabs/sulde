#!/usr/bin/env python3
"""Mine recent recall logs and draft human-reviewable memory golden candidates."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import runpy
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


_command_template = runpy.run_path(str(Path(__file__).with_name("command_template.py")))
split_command_template = _command_template["split_command_template"]
_recall_log = runpy.run_path(
    str(Path(__file__).resolve().parents[2] / "hooks" / "lib" / "recall_log.py")
)
classify_recall_source = _recall_log["classify_recall_source"]
RECALL_LOG_FILENAME = _recall_log["LOG_FILENAME"]


DEFAULT_LLM_CMD = _command_template["default_llm_command"]()
THRESHOLDS = {"mem": 0.50, "kb": 0.55}
CATEGORIES = (
    "cross_group_blocked",
    "borderline_injection",
    "repeated_injection",
    "suspected_miss",
)
SKIP_EVIDENCE_RE = re.compile(r"^- [a-z_]+ evidence=([0-9a-f]{16}):")


class ExpandError(RuntimeError):
    """A controlled input or headless-judgment failure."""


@dataclass(frozen=True)
class Recall:
    timestamp: datetime
    cwd: str
    query: str
    scores: tuple[float, ...]
    injected: tuple[str, ...]
    source: str

    @property
    def project(self) -> str:
        return Path(self.cwd).name if self.cwd else "unknown"


@dataclass(frozen=True)
class Finding:
    category: str
    recall: Recall
    evidence: str

    @property
    def fingerprint(self) -> str:
        if self.category == "repeated_injection":
            # Frequency and representative query evolve as new log rows arrive.  The
            # injected entry identity is the stable dedupe key across weekly reruns.
            identity = self.evidence.split(maxsplit=1)[0]
            material = "\0".join((self.category, self.recall.source, identity))
        else:
            material = "\0".join(
                (self.category, self.recall.source, self.recall.project, self.recall.query, self.evidence)
            )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


def kb_home() -> Path:
    configured = os.environ.get("SULDE_KB_HOME")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".sulde" / "data" / "kb"


def parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def read_recalls(path: Path, cutoff: datetime) -> tuple[list[Recall], int]:
    recalls: list[Recall] = []
    invalid = 0
    try:
        handle = path.open(encoding="utf-8")
    except OSError as error:
        raise ExpandError(f"cannot read recall log: {error}") from error
    with handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                invalid += 1
                continue
            timestamp = parse_timestamp(row.get("ts")) if isinstance(row, dict) else None
            if not isinstance(row, dict) or timestamp is None:
                invalid += 1
                continue
            if timestamp < cutoff:
                continue
            source = classify_recall_source(row)
            if source is None:
                invalid += 1
                continue
            query = row.get("query_head")
            scores = row.get("top_scores")
            injected = row.get("injected")
            if not isinstance(query, str) or not isinstance(scores, list) or not isinstance(injected, list):
                invalid += 1
                continue
            numeric_scores = tuple(
                float(value)
                for value in scores
                if isinstance(value, (int, float)) and not isinstance(value, bool)
            )
            injection_ids = tuple(
                str(value) for value in injected if isinstance(value, (str, int)) and not isinstance(value, bool)
            )
            recalls.append(
                Recall(
                    timestamp=timestamp,
                    cwd=str(row.get("cwd") or ""),
                    query=query.strip(),
                    scores=numeric_scores,
                    injected=injection_ids,
                    source=source,
                )
            )
    return recalls, invalid


def find_suspicions(recalls: list[Recall], margin: float, repeat_min: int) -> list[Finding]:
    findings: list[Finding] = []
    occurrences: dict[tuple[str, str], list[Recall]] = defaultdict(list)
    for recall in recalls:
        threshold = THRESHOLDS[recall.source]
        top = recall.scores[0] if recall.scores else None
        if recall.query and not recall.injected and top is not None:
            if recall.source == "mem" and top >= threshold:
                findings.append(
                    Finding("cross_group_blocked", recall, f"top1={top:.6f} threshold={threshold:.2f}")
                )
            elif threshold - margin <= top <= threshold + margin:
                findings.append(
                    Finding("suspected_miss", recall, f"top1={top:.6f} threshold={threshold:.2f}")
                )
        if recall.injected and top is not None and threshold <= top <= threshold + margin:
            findings.append(
                Finding(
                    "borderline_injection",
                    recall,
                    f"top1={top:.6f} threshold={threshold:.2f} injected={','.join(recall.injected)}",
                )
            )
        for injected_id in set(recall.injected):
            occurrences[(recall.source, injected_id)].append(recall)

    for (source, injected_id), rows in sorted(occurrences.items()):
        if len(rows) < repeat_min:
            continue
        representative = max(rows, key=lambda item: item.timestamp)
        findings.append(
            Finding(
                "repeated_injection",
                representative,
                f"injected={injected_id} occurrences={len(rows)} window_rows={len(recalls)} source={source}",
            )
        )
    return findings


def run_llm(command_template: str, prompt: str) -> str:
    try:
        arguments = split_command_template(command_template)
    except ValueError as error:
        raise ExpandError(f"invalid --llm-cmd: {error}") from error
    if not arguments:
        raise ExpandError("--llm-cmd cannot be empty")
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
            check=False,
        )
    except OSError as error:
        raise ExpandError(f"LLM command failed to start: {error}") from error
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise ExpandError(f"LLM command exited {completed.returncode}: {detail[:500]}")
    return completed.stdout


def build_prompt(finding: Finding, retry: bool = False) -> str:
    prompt = f"""你是 memory golden 扩充官。只判断是否值得草拟回归用例，不执行任何写库或删除。
输入日志只有截断到 40 字的 query_head，不能把它当完整查询。
只输出一个裸 JSON，字段必须严格为：
{{"action":"draft|skip","assertion":"expect_none|expect_substring|forbid_project|null","expected":true或字符串或null,"reason":"简短理由"}}
规则：draft 时 assertion 必须是三种之一；expect_none 的 expected 必须为 true；另两种必须为非空字符串。证据不足就 skip。

分类：{finding.category}
source：{finding.recall.source}
project：{finding.recall.project}
query_head：{finding.recall.query}
top_scores：{json.dumps(finding.recall.scores)}
injected：{json.dumps(finding.recall.injected, ensure_ascii=False)}
evidence：{finding.evidence}
"""
    if retry:
        prompt += "\n上次输出不合法。只输出满足契约的裸 JSON。"
    return prompt


def strip_json_fence(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```") and text.endswith("```"):
        lines = text.splitlines()
        if len(lines) >= 2 and lines[0].strip().lower() in {"```", "```json"}:
            return "\n".join(lines[1:-1]).strip()
    return text


def parse_judgment(raw: str) -> dict[str, Any]:
    try:
        value = json.loads(strip_json_fence(raw))
    except json.JSONDecodeError as error:
        raise ExpandError(f"invalid LLM JSON: {error}") from error
    fields = {"action", "assertion", "expected", "reason"}
    if not isinstance(value, dict) or set(value) != fields:
        raise ExpandError("LLM JSON must contain only action, assertion, expected, and reason")
    if value["action"] not in {"draft", "skip"} or not isinstance(value["reason"], str):
        raise ExpandError("LLM action/reason is invalid")
    if value["action"] == "skip":
        if value["assertion"] is not None or value["expected"] is not None:
            raise ExpandError("skip requires null assertion and expected")
        return value
    if value["assertion"] not in {"expect_none", "expect_substring", "forbid_project"}:
        raise ExpandError("draft assertion is invalid")
    if value["assertion"] == "expect_none":
        if value["expected"] is not True:
            raise ExpandError("expect_none requires expected=true")
    elif not isinstance(value["expected"], str) or not value["expected"].strip():
        raise ExpandError(f"{value['assertion']} requires a non-empty string expected")
    return value


def judge(command_template: str, finding: Finding) -> dict[str, Any]:
    failures: list[str] = []
    for attempt in range(2):
        try:
            return parse_judgment(run_llm(command_template, build_prompt(finding, retry=bool(attempt))))
        except ExpandError as error:
            failures.append(str(error))
    raise ExpandError("LLM output invalid after retry: " + " | ".join(failures))


def load_existing(path: Path) -> tuple[list[dict[str, Any]], set[str], set[str]]:
    if not path.exists():
        return [], set(), set()
    rows: list[dict[str, Any]] = []
    fingerprints: set[str] = set()
    ids: set[str] = set()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as error:
        raise ExpandError(f"cannot read candidates: {error}") from error
    for number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            raise ExpandError(f"{path}:{number}: invalid JSON: {error}") from error
        if not isinstance(value, dict):
            raise ExpandError(f"{path}:{number}: candidate must be an object")
        rows.append(value)
        if isinstance(value.get("id"), str):
            ids.add(value["id"])
        note = value.get("note")
        if isinstance(note, str) and "evidence=" in note:
            fingerprints.add(note.split("evidence=", 1)[1].split()[0].rstrip(";"))
    return rows, fingerprints, ids


def load_reviewed_ids(path: Path) -> set[str]:
    """Return terminal candidate IDs from the append-only human review audit."""
    if not path.exists():
        return set()
    reviewed: set[str] = set()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as error:
        raise ExpandError(f"cannot read review audit: {error}") from error
    for number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as error:
            raise ExpandError(f"{path}:{number}: invalid JSON: {error}") from error
        decisions = event.get("decisions") if isinstance(event, dict) else None
        if not isinstance(decisions, list):
            raise ExpandError(f"{path}:{number}: decisions must be an array")
        for decision in decisions:
            identifier = decision.get("id") if isinstance(decision, dict) else None
            if not isinstance(identifier, str) or not identifier:
                raise ExpandError(f"{path}:{number}: decision id must be a string")
            reviewed.add(identifier)
    return reviewed


def load_skip_cache(path: Path) -> tuple[list[dict[str, Any]], set[str]]:
    if not path.exists():
        return [], set()
    rows: list[dict[str, Any]] = []
    fingerprints: set[str] = set()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as error:
        raise ExpandError(f"cannot read skip cache: {error}") from error
    for number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            raise ExpandError(f"{path}:{number}: invalid JSON: {error}") from error
        if not isinstance(value, dict) or not isinstance(value.get("evidence"), str):
            raise ExpandError(f"{path}:{number}: cached skip must contain string evidence")
        rows.append(value)
        fingerprints.add(value["evidence"])
    return rows, fingerprints


def load_reported_skips(home: Path) -> set[str]:
    """Recover skip decisions made before the structured cache existed."""
    fingerprints: set[str] = set()
    for path in home.glob("golden-expand-report-*.md"):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError) as error:
            raise ExpandError(f"cannot read prior report {path}: {error}") from error
        in_skipped = False
        for line in lines:
            if line == "## Skipped":
                in_skipped = True
                continue
            if in_skipped and line.startswith("## "):
                break
            if in_skipped:
                match = SKIP_EVIDENCE_RE.match(line)
                if match:
                    fingerprints.add(match.group(1))
    return fingerprints


def make_skip_cache_entry(
    finding: Finding, reason: str, reviewed_at: datetime
) -> dict[str, Any]:
    return {
        "evidence": finding.fingerprint,
        "category": finding.category,
        "reason": reason.strip(),
        "reviewed_at": reviewed_at.isoformat(),
    }


def make_candidate(finding: Finding, judgment: dict[str, Any], existing_ids: set[str]) -> dict[str, Any]:
    base_id = f"gm-cand-{finding.fingerprint[:10]}"
    candidate_id = base_id
    suffix = 2
    while candidate_id in existing_ids:
        candidate_id = f"{base_id}-{suffix}"
        suffix += 1
    note = (
        f"候选分类={finding.category}; {judgment['reason'].strip()}; {finding.evidence}; "
        f"evidence={finding.fingerprint}; query_head 为最多 40 字的日志片段；"
        "接受前需人工确认完整性"
    )
    return {
        "id": candidate_id,
        "query": finding.recall.query,
        "project": finding.recall.project,
        judgment["assertion"]: judgment["expected"],
        "note": note,
    }


def atomic_write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def write_report(
    path: Path,
    recalls: list[Recall],
    invalid: int,
    findings: list[Finding],
    drafted: list[dict[str, Any]],
    skipped: list[tuple[Finding, str]],
    duplicates: int,
    errors: list[tuple[Finding, str]],
    excluded_non_memory: int,
) -> None:
    counts = Counter(item.category for item in findings)
    lines = [
        "# Golden expansion report",
        "",
        f"- generated_at: {datetime.now(timezone.utc).isoformat()}",
        f"- recall_rows: {len(recalls)}",
        f"- excluded_non_memory_rows: {excluded_non_memory}",
        f"- invalid_rows: {invalid}",
        "- findings: " + " ".join(f"{key}={counts[key]}" for key in CATEGORIES),
        f"- dispositions: drafted={len(drafted)} duplicate={duplicates} skipped={len(skipped)} errors={len(errors)}",
        "",
        "## Drafted",
        "",
    ]
    lines.extend(f"- `{row['id']}` {row['note']}" for row in drafted)
    if not drafted:
        lines.append("- none")
    lines.extend(["", "## Skipped", ""])
    lines.extend(f"- {item.category} evidence={item.fingerprint}: {reason}" for item, reason in skipped)
    if not skipped:
        lines.append("- none")
    lines.extend(["", "## Errors", ""])
    lines.extend(f"- ERROR {item.category} evidence={item.fingerprint}: {reason}" for item, reason in errors)
    if not errors:
        lines.append("- none")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, help="recall JSONL (default: $SULDE_KB_HOME/recall-log.jsonl)")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--margin", type=float, default=0.05)
    parser.add_argument("--repeat-min", type=int, default=3)
    parser.add_argument("--now", help="ISO timestamp override for deterministic tests")
    parser.add_argument("--llm-cmd", default=DEFAULT_LLM_CMD)
    parser.add_argument("--dry-run", action="store_true", help="count findings without LLM calls or writes")
    args = parser.parse_args()
    if args.days <= 0 or args.margin < 0 or args.repeat_min < 2:
        parser.error("require --days > 0, --margin >= 0, and --repeat-min >= 2")
    if args.now is not None and parse_timestamp(args.now) is None:
        parser.error("--now must be an ISO timestamp")
    return args


def print_summary(
    status: str,
    counts: Counter[str],
    drafted: int,
    duplicates: int,
    skipped: int,
    errors: int,
    cached_skips: int,
    novel_unique: int,
    details: str,
    candidates: str,
    memory_rows: int,
    excluded_non_memory: int,
) -> None:
    print(f"GOLDEN EXPAND RESULT: {status}")
    print("findings: " + " ".join(f"{key}={counts[key]}" for key in CATEGORIES))
    print(
        f"dispositions: drafted={drafted} duplicate={duplicates} "
        f"cached_skip={cached_skips} skipped={skipped} errors={errors} "
        f"novel_unique={novel_unique}"
    )
    print(f"details: {details}")
    print(f"candidates: {candidates}")
    print(f"sources: memory={memory_rows} excluded_non_memory={excluded_non_memory}")


def main() -> int:
    args = parse_args()
    home = kb_home()
    input_path = args.input or home / RECALL_LOG_FILENAME
    now = parse_timestamp(args.now) if args.now else datetime.now(timezone.utc)
    assert now is not None
    try:
        recalls, invalid = read_recalls(input_path, now - timedelta(days=args.days))
        memory_recalls = [recall for recall in recalls if recall.source == "mem"]
        excluded_non_memory = len(recalls) - len(memory_recalls)
        findings = find_suspicions(memory_recalls, args.margin, args.repeat_min)
        counts = Counter(item.category for item in findings)
        candidate_path = home / "golden-candidates.jsonl"
        rows, known_fingerprints, existing_ids = load_existing(candidate_path)
        reviewed_ids = load_reviewed_ids(home / "golden-review-decisions.jsonl")
        skip_cache_path = home / "golden-expand-skips.jsonl"
        skip_cache_rows, cached_fingerprints = load_skip_cache(skip_cache_path)
        cached_fingerprints.update(load_reported_skips(home))
        if args.dry_run:
            duplicates = sum(
                finding.fingerprint in known_fingerprints
                or f"gm-cand-{finding.fingerprint[:10]}" in reviewed_ids
                for finding in findings
            )
            cached_skips = sum(
                finding.fingerprint not in known_fingerprints
                and f"gm-cand-{finding.fingerprint[:10]}" not in reviewed_ids
                and finding.fingerprint in cached_fingerprints
                for finding in findings
            )
            novel_unique = len({
                finding.fingerprint
                for finding in findings
                if finding.fingerprint not in known_fingerprints
                and f"gm-cand-{finding.fingerprint[:10]}" not in reviewed_ids
                and finding.fingerprint not in cached_fingerprints
            })
            print_summary(
                "PASS", counts, 0, duplicates, 0, 0, cached_skips,
                novel_unique, "none (dry-run)", "unchanged (dry-run)",
                len(memory_recalls), excluded_non_memory,
            )
            return 0

        home.mkdir(parents=True, exist_ok=True)
        drafted: list[dict[str, Any]] = []
        skipped: list[tuple[Finding, str]] = []
        errors: list[tuple[Finding, str]] = []
        duplicates = 0
        cached_skips = 0
        judged_fingerprints: set[str] = set()
        for finding in findings:
            base_id = f"gm-cand-{finding.fingerprint[:10]}"
            if (
                finding.fingerprint in known_fingerprints
                or base_id in reviewed_ids
            ):
                duplicates += 1
                continue
            if finding.fingerprint in cached_fingerprints:
                cached_skips += 1
                continue
            try:
                judgment = judge(args.llm_cmd, finding)
            except ExpandError as error:
                errors.append((finding, str(error)))
                continue
            judged_fingerprints.add(finding.fingerprint)
            if judgment["action"] == "skip":
                skipped.append((finding, judgment["reason"]))
                cached_fingerprints.add(finding.fingerprint)
                skip_cache_rows.append(
                    make_skip_cache_entry(finding, judgment["reason"], now)
                )
                continue
            candidate = make_candidate(finding, judgment, existing_ids)
            existing_ids.add(candidate["id"])
            known_fingerprints.add(finding.fingerprint)
            rows.append(candidate)
            drafted.append(candidate)
        if drafted:
            atomic_write_jsonl(candidate_path, rows)
        if skipped:
            atomic_write_jsonl(skip_cache_path, skip_cache_rows)
        report_path = home / f"golden-expand-report-{now.strftime('%Y%m%d-%H%M%S')}.md"
        write_report(
            report_path, memory_recalls, invalid, findings, drafted, skipped,
            duplicates, errors, excluded_non_memory,
        )
        status = "FAIL" if errors else "PASS"
        print_summary(
            status,
            counts,
            len(drafted),
            duplicates,
            len(skipped),
            len(errors),
            cached_skips,
            len(judged_fingerprints),
            str(report_path),
            str(candidate_path),
            len(memory_recalls),
            excluded_non_memory,
        )
        return 1 if errors else 0
    except (ExpandError, OSError, UnicodeError) as error:
        print("GOLDEN EXPAND RESULT: FAIL")
        print("findings: unavailable")
        print(
            "dispositions: drafted=0 duplicate=0 cached_skip=0 "
            "skipped=0 errors=1 novel_unique=0"
        )
        print(f"ERROR golden-expand: {error}")
        print("details: none")
        print("candidates: unchanged")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
