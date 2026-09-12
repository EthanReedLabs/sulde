#!/usr/bin/env python3
"""Turn pending distill candidates into a reviewable knowledge-base branch."""

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
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
from typing import Any

from file_lock import lock_exclusive_nonblocking, unlock
from sedimentation_schema import validate_document


REPO_ROOT = Path(__file__).resolve().parents[2]
kb_cli = SimpleNamespace(
    **runpy.run_path(str(REPO_ROOT / "hooks" / "lib" / "kb_cli.py"))
)
_command_template = runpy.run_path(str(Path(__file__).with_name("command_template.py")))
split_command_template = _command_template["split_command_template"]
SKILL_PATH = REPO_ROOT / "skills" / "sediment" / "SKILL.md"
KB_INDEX_ROOT = REPO_ROOT / "tools" / "kb-index"
DEFAULT_LLM_CMD = _command_template["default_llm_command"]()
RESULT_FIELDS = {"action", "container", "target_doc_id", "doc_id", "slug", "markdown", "reason"}
ACTIONS = {"new", "merge", "skip", "unsure"}
CONTAINERS = {"anti-patterns", "platform-kb", "tech-docs", "case-studies", "work-model"}
PLATFORMS = {"android", "ios", "flutter", "harmonyos", "web", "cross", "none"}
CANDIDATE_RE = re.compile(
    r"^(?P<prefix>\s*-\s+(?:\*\*沉淀候选\*\*\s*[：:]\s*)?)"
    r"(?P<lesson>.+?)（待 /sediment (?:处理|人工处理)）(?P<trailing>\s*)$"
)
MANUAL_CANDIDATE_RE = re.compile(
    r"^(?P<prefix>\s*-\s+(?:\*\*沉淀候选\*\*\s*[：:]\s*)?)"
    r"(?P<lesson>.+?)（❓ (?:证据不足待裁决|存疑留人工)）(?P<trailing>\s*)$"
)
RESOLVED_CANDIDATE_RE = re.compile(
    r"^(?P<prefix>\s*-\s+(?:\*\*沉淀候选\*\*\s*[：:]\s*)?)(?P<lesson>.+?)"
    r"(?P<marker>（✅ (?:已沉淀|判重放弃:已有) .+?）)(?P<trailing>\s*)$"
)
FRONTMATTER_KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*):(?:\s*(.*))?$")
ANTI_INDEX_RE = re.compile(r"^- ap-(\d{4})\b")
RUN_ID_RE = re.compile(r"^\d{8}-\d{6}$")
ISOLATED_RUN_ENV = "SULDE_AUTO_SEDIMENT_ISOLATED"
MANUAL_ACTIONS = {"new", "merge", "skip"}
MANUAL_RESOLUTION_FIELDS = {
    "candidate_line_index",
    "lesson",
    "action",
    "target",
    "reason",
}


class SedimentError(RuntimeError):
    """Controlled runtime failure (exit 2 unless it is a deny interception)."""


class DenyInterception(SedimentError):
    """Generated knowledge was rejected by the deny lint (exit 1)."""


class CandidateTimeout(SedimentError):
    """One candidate exhausted its LLM time budget."""


@dataclass(frozen=True)
class KbIndexCli:
    home: Path
    root: Path
    python: Path | None = None

    def command(self, name: str, *arguments: str) -> list[str]:
        try:
            return kb_cli.build_command(
                REPO_ROOT,
                self.home,
                name,
                arguments,
                python=self.python,
                entry_root=self.root,
            )
        except (kb_cli.CliUnavailableError, ValueError) as error:
            raise SedimentError(str(error)) from error


@dataclass(frozen=True)
class Candidate:
    line_index: int
    lesson: str
    context: str = ""
    context_sha256: str = ""


@dataclass
class Disposition:
    candidate: Candidate
    action: str
    doc_id: str | None
    reason: str
    changed_paths: tuple[Path, ...] = ()


@dataclass(frozen=True)
class ManualResolution:
    candidate: Candidate
    action: str
    target: str
    reason: str


def kb_home() -> Path:
    configured = os.environ.get("SULDE_KB_HOME")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".sulde" / "data" / "kb"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_run_id() -> str:
    return datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")


def validate_run_id(run_id: str) -> str:
    if RUN_ID_RE.fullmatch(run_id) is None:
        raise SedimentError("run_id must use YYYYmmdd-HHMMSS")
    return run_id


def decisions_path(home: Path, run_id: str) -> Path:
    return home / "sediment-runs" / f"decisions-{validate_run_id(run_id)}.jsonl"


def manual_resolutions_path(home: Path, run_id: str) -> Path:
    return home / "sediment-runs" / f"manual-resolutions-{validate_run_id(run_id)}.json"


def run_command(
    arguments: list[str],
    *,
    cwd: Path = REPO_ROOT,
    input_text: str | None = None,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            arguments,
            cwd=cwd,
            input=input_text,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as error:
        raise CandidateTimeout(
            f"LLM command timed out after {timeout:g}s"
        ) from error
    except OSError as error:
        raise SedimentError(f"command failed to start ({arguments[0]}): {error}") from error


def require_success(arguments: list[str], label: str) -> str:
    completed = run_command(arguments)
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise SedimentError(f"{label} exited {completed.returncode}: {detail[:1000]}")
    if completed.stdout.strip():
        print(completed.stdout.strip())
    return completed.stdout


def run_llm(command_template: str, prompt: str, timeout: float | None = None) -> str:
    try:
        arguments = split_command_template(command_template)
    except ValueError as error:
        raise SedimentError(f"invalid --llm-cmd: {error}") from error
    if not arguments:
        raise SedimentError("--llm-cmd cannot be empty")
    stdin_prompt: str | None = prompt
    expanded: list[str] = []
    for argument in arguments:
        if argument == "{prompt}":
            continue
        if "{prompt}" in argument:
            argument = argument.replace("{prompt}", prompt)
            stdin_prompt = None
        expanded.append(argument)
    completed = run_command(expanded, input_text=stdin_prompt, timeout=timeout)
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise SedimentError(f"LLM command exited {completed.returncode}: {detail[:500]}")
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
        raise SedimentError(f"invalid LLM JSON: {error}") from error
    if not isinstance(payload, dict) or not set(payload) <= RESULT_FIELDS \
            or not (RESULT_FIELDS - {"slug"}) <= set(payload):
        raise SedimentError("LLM JSON has invalid fields")
    payload.setdefault("slug", None)
    if payload["action"] not in ACTIONS:
        raise SedimentError(f"invalid action: {payload['action']}")
    for key in RESULT_FIELDS - {"target_doc_id", "doc_id", "slug"}:
        if not isinstance(payload[key], str):
            raise SedimentError(f"{key} must be a string")
    for key in ("target_doc_id", "doc_id", "slug"):
        if payload.get(key) is not None and not isinstance(payload[key], str):
            raise SedimentError(f"{key} must be a string or null")
    if payload["container"] and payload["container"] not in CONTAINERS:
        raise SedimentError(f"invalid container: {payload['container']}")
    action = payload["action"]
    if action == "new" and (not payload["container"] or not payload["markdown"].strip()):
        raise SedimentError("new requires container and markdown")
    if action in {"merge", "skip"} and not str(payload["target_doc_id"] or "").strip():
        raise SedimentError(f"{action} requires target_doc_id")
    return payload


def call_llm(
    command_template: str,
    prompt: str,
    *,
    deadline: float | None = None,
) -> dict[str, Any]:
    errors: list[str] = []
    for attempt in range(2):
        actual_prompt = prompt
        if attempt:
            actual_prompt += "\n\n上次输出无法解析。只输出满足指定契约的裸 JSON。"
        try:
            timeout = None if deadline is None else deadline - time.monotonic()
            if timeout is not None and timeout <= 0:
                raise CandidateTimeout("candidate LLM time budget exhausted")
            return parse_result(run_llm(command_template, actual_prompt, timeout))
        except CandidateTimeout:
            raise
        except SedimentError as error:
            errors.append(str(error))
    raise SedimentError("LLM output invalid after retry: " + " | ".join(errors))


def load_candidates_from_lines(lines: list[str], maximum: int = sys.maxsize) -> list[Candidate]:
    candidates: list[Candidate] = []
    for index, line in enumerate(lines):
        match = CANDIDATE_RE.match(line.rstrip("\r\n"))
        if match:
            start = index
            for cursor in range(index - 1, -1, -1):
                stripped = lines[cursor].strip()
                if stripped == "### Layer1 问题卡":
                    start = cursor
                    break
                if stripped.startswith(("## ", "### ")):
                    break
            context = "".join(lines[start:index]).strip() if start < index else ""
            digest = hashlib.sha256(context.encode("utf-8")).hexdigest() if context else ""
            candidates.append(
                Candidate(index, match.group("lesson").strip(), context, digest)
            )
            if len(candidates) >= maximum:
                break
    return candidates


def load_candidates(path: Path, maximum: int) -> tuple[list[str], list[Candidate]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    except (OSError, UnicodeError) as error:
        raise SedimentError(f"cannot read candidates: {error}") from error
    return lines, load_candidates_from_lines(lines, maximum)


def append_decision(path: Path, candidate: Candidate, decision: dict[str, Any]) -> None:
    record = {
        "candidate_line_index": candidate.line_index,
        "lesson": candidate.lesson,
        "context_sha256": candidate.context_sha256,
        "decision": decision,
        "ts": utc_now(),
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as error:
        raise SedimentError(f"cannot append decision: {error}") from error


def load_decisions(
    path: Path, *, recover_truncated_tail: bool = False
) -> list[tuple[Candidate, dict[str, Any]]]:
    try:
        chunks = path.read_bytes().splitlines(keepends=True)
    except FileNotFoundError as error:
        raise SedimentError(f"decisions file does not exist: {path}") from error
    except OSError as error:
        raise SedimentError(f"cannot read decisions file: {error}") from error
    decisions: list[tuple[Candidate, dict[str, Any]]] = []
    seen: set[int] = set()
    valid_bytes = 0
    for number, chunk in enumerate(chunks, 1):
        try:
            raw = chunk.decode("utf-8").rstrip("\r\n")
            record = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            is_truncated_tail = number == len(chunks) and not chunk.endswith((b"\n", b"\r"))
            if recover_truncated_tail and is_truncated_tail:
                try:
                    with path.open("r+b") as handle:
                        handle.truncate(valid_bytes)
                        handle.flush()
                        os.fsync(handle.fileno())
                except OSError as truncate_error:
                    raise SedimentError(
                        f"cannot repair truncated decisions tail: {truncate_error}"
                    ) from truncate_error
                break
            raise SedimentError(f"invalid decisions JSONL line {number}: {error}") from error
        allowed_fields = {
            "candidate_line_index", "lesson", "context_sha256", "decision", "ts"
        }
        legacy_fields = allowed_fields - {"context_sha256"}
        if (
            not isinstance(record, dict)
            or (set(record) != allowed_fields and set(record) != legacy_fields)
        ):
            raise SedimentError(f"invalid decisions record at line {number}")
        line_index = record["candidate_line_index"]
        lesson = record["lesson"]
        if not isinstance(line_index, int) or line_index < 0 or not isinstance(lesson, str):
            raise SedimentError(f"invalid candidate identity at decisions line {number}")
        if line_index in seen:
            raise SedimentError(f"duplicate candidate_line_index in decisions: {line_index}")
        seen.add(line_index)
        decision = parse_result(json.dumps(record["decision"], ensure_ascii=False))
        context_sha256 = record.get("context_sha256", "")
        if not isinstance(context_sha256, str):
            raise SedimentError(f"invalid context_sha256 at decisions line {number}")
        decisions.append((Candidate(line_index, lesson, "", context_sha256), decision))
        valid_bytes += len(chunk)
    return decisions


def load_manual_resolutions(path: Path) -> list[ManualResolution]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise SedimentError(f"manual resolution file does not exist: {path}") from error
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SedimentError(f"cannot read manual resolution file: {error}") from error
    if not isinstance(payload, list) or not payload:
        raise SedimentError("manual resolution file must be a non-empty JSON array")
    resolutions: list[ManualResolution] = []
    seen: set[int] = set()
    for number, record in enumerate(payload, 1):
        if not isinstance(record, dict) or set(record) != MANUAL_RESOLUTION_FIELDS:
            raise SedimentError(f"invalid manual resolution record at item {number}")
        line_index = record["candidate_line_index"]
        lesson = record["lesson"]
        action = record["action"]
        target = record["target"]
        reason = record["reason"]
        if not isinstance(line_index, int) or line_index < 0:
            raise SedimentError(f"invalid candidate_line_index at item {number}")
        if line_index in seen:
            raise SedimentError(
                f"duplicate candidate_line_index in manual resolutions: {line_index}"
            )
        seen.add(line_index)
        if not isinstance(lesson, str) or not lesson.strip():
            raise SedimentError(f"manual resolution lesson must be non-empty at item {number}")
        if action not in MANUAL_ACTIONS:
            raise SedimentError(f"invalid manual resolution action at item {number}: {action}")
        if not isinstance(target, str) or not target.strip():
            raise SedimentError(f"manual resolution target must be non-empty at item {number}")
        if not isinstance(reason, str) or not reason.strip():
            raise SedimentError(f"manual resolution reason must be non-empty at item {number}")
        resolutions.append(
            ManualResolution(
                Candidate(line_index, lesson.strip()),
                action,
                target.strip(),
                reason.strip(),
            )
        )
    return resolutions


def validate_decision_candidates(
    lines: list[str], decisions: list[tuple[Candidate, dict[str, Any]]]
) -> None:
    current_by_line = {
        candidate.line_index: candidate
        for candidate in load_candidates_from_lines(lines)
    }
    for candidate, _ in decisions:
        if candidate.line_index >= len(lines):
            raise SedimentError(
                f"candidate line no longer exists: {candidate.line_index}"
            )
        content = lines[candidate.line_index].rstrip("\r\n")
        match = CANDIDATE_RE.match(content)
        if match is None or match.group("lesson").strip() != candidate.lesson:
            raise SedimentError(
                f"candidate changed since decide: line {candidate.line_index}"
            )
        current = current_by_line.get(candidate.line_index)
        if (
            candidate.context_sha256
            and (current is None or current.context_sha256 != candidate.context_sha256)
        ):
            raise SedimentError(
                f"candidate problem-card context changed since decide: line {candidate.line_index}"
            )


def atomic_write(path: Path, text: str) -> None:
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


def acquire_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+", encoding="utf-8")
    try:
        lock_exclusive_nonblocking(handle)
    except BlockingIOError as error:
        handle.close()
        raise SedimentError("another auto-sediment instance is running") from error
    handle.seek(0)
    handle.truncate()
    handle.write(f"pid={os.getpid()} started={utc_now()}\n")
    handle.flush()
    return handle


def run_in_isolated_worktree(home: Path) -> int:
    """Run Git-writing modes away from the caller's possibly dirty worktree."""
    launch_lock = acquire_lock(home / "auto-sediment-launch.lock")
    worktree: Path | None = None
    try:
        common = run_command(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"]
        )
        if common.returncode != 0:
            detail = common.stderr.strip() or common.stdout.strip()
            raise SedimentError(f"cannot locate git common directory: {detail[:500]}")
        common_dir = Path(common.stdout.strip()).resolve()
        runtime_root = common_dir.parent / ".worktrees"
        runtime_root.mkdir(parents=True, exist_ok=True)
        worktree = runtime_root / (
            f"auto-sediment-runtime-{os.getpid()}-{time.time_ns()}"
        )
        added = run_command(
            ["git", "worktree", "add", "--detach", str(worktree), "HEAD"]
        )
        if added.returncode != 0:
            detail = added.stderr.strip() or added.stdout.strip()
            raise SedimentError(f"cannot create isolated worktree: {detail[:500]}")
        relative_script = Path(__file__).resolve().relative_to(REPO_ROOT)
        environment = os.environ.copy()
        environment[ISOLATED_RUN_ENV] = "1"
        try:
            completed = subprocess.run(
                [sys.executable, str(worktree / relative_script), *sys.argv[1:]],
                cwd=worktree,
                env=environment,
                check=False,
            )
        except OSError as error:
            raise SedimentError(f"cannot start isolated auto-sediment: {error}") from error
        return completed.returncode
    finally:
        cleanup_error: str | None = None
        if worktree is not None and worktree.exists():
            removed = run_command(
                ["git", "worktree", "remove", "--force", str(worktree)]
            )
            if removed.returncode != 0:
                cleanup_error = removed.stderr.strip() or removed.stdout.strip()
        try:
            unlock(launch_lock)
            launch_lock.close()
        except OSError:
            pass
        if cleanup_error:
            raise SedimentError(
                f"cannot remove isolated worktree: {cleanup_error[:500]}"
            )


def extract_skill_truth() -> str:
    try:
        text = SKILL_PATH.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise SedimentError(f"cannot read sediment skill: {error}") from error
    start = text.find("## 1. 收集素材")
    end = text.find("## 4. 收尾", start)
    if start < 0 or end < 0:
        raise SedimentError("sediment skill is missing §1 or §4")
    templates_root = REPO_ROOT / "templates" / "knowledge"
    template_paths = [templates_root / "schema.json"] + sorted(
        path for path in templates_root.glob("*.md") if path.name != "problem-card.md"
    )
    blocks = [text[start:end].rstrip()]
    for path in template_paths:
        try:
            blocks.append(
                f"--- BEGIN {path.relative_to(REPO_ROOT)} ---\n"
                f"{path.read_text(encoding='utf-8').rstrip()}\n"
                f"--- END {path.relative_to(REPO_ROOT)} ---"
            )
        except (OSError, UnicodeError) as error:
            raise SedimentError(f"cannot read sedimentation template {path}: {error}") from error
    return "\n\n".join(blocks)


def root_cause_query(lesson: str, context: str = "") -> str:
    match = re.search(
        r"\*\*根因与证据缺口\*\*\s*[：:]\s*(.+)", context
    )
    if match and match.group(1).strip():
        return match.group(1).strip()
    for marker in ("根因：", "根因:", "因为", "原因：", "原因:"):
        if marker in lesson:
            value = lesson.split(marker, 1)[1].strip()
            if value:
                return value
    return lesson


def parse_search_output(raw: str) -> list[dict[str, Any]]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as error:
        raise SedimentError(f"invalid kb-index search JSON: {error}") from error
    if not isinstance(payload, list):
        raise SedimentError("kb-index search JSON must be an array")
    return [item for item in payload if isinstance(item, dict)]


def kb_search(kb_index: KbIndexCli, query: str) -> list[dict[str, Any]]:
    arguments = kb_index.command("search", query, "-k", "5", "--json")
    completed = run_command(arguments)
    if completed.returncode != 0:
        built = run_command(kb_index.command("build"))
        if built.returncode != 0:
            detail = built.stderr.strip() or completed.stderr.strip()
            raise SedimentError(f"kb-index search/build failed: {detail[:1000]}")
        completed = run_command(arguments)
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise SedimentError(f"kb-index search exited {completed.returncode}: {detail[:1000]}")
    return parse_search_output(completed.stdout)


def safe_source_path(raw: Any) -> Path:
    if not isinstance(raw, str) or not raw.strip():
        raise SedimentError("kb-index hit has no source_path")
    candidate = Path(raw)
    path = candidate if candidate.is_absolute() else REPO_ROOT / candidate
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to((REPO_ROOT / "knowledge").resolve())
    except (OSError, ValueError) as error:
        raise SedimentError(f"unsafe or missing search source_path: {raw}") from error
    return resolved


def render_hits(groups: list[tuple[str, list[dict[str, Any]]]]) -> str:
    blocks: list[str] = []
    seen: set[Path] = set()
    for label, hits in groups:
        blocks.append(f"### {label}检索 JSON\n{json.dumps(hits, ensure_ascii=False, indent=2)}")
        for hit in hits:
            source = safe_source_path(hit.get("source_path"))
            if source in seen:
                continue
            seen.add(source)
            try:
                full_text = source.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as error:
                raise SedimentError(f"cannot read search hit {source}: {error}") from error
            blocks.append(
                f"### 命中全文 {source.relative_to(REPO_ROOT)}\n{full_text.rstrip()}"
            )
    return "\n\n".join(blocks)


def decision_prompt(candidate: Candidate, skill_truth: str, hits: str) -> str:
    return f"""你是 /sediment 的 headless 执行器。只输出裸 JSON，契约严格为：
{{"action":"new|merge|skip|unsure","container":"...","target_doc_id":null,"doc_id":null,"slug":"kebab-english-slug(new anti-patterns 必填)","markdown":"...","reason":"..."}}
doc_id 规则：new anti-patterns 置 null（自动取号）；platform-kb 使用 platform-kb/<platform>/<slug>；tech-docs/work-model/case-studies 必须提供与容器匹配的 doc_id。
不得输出额外字段或解释。markdown 必须是完整、自包含、已脱敏的 Markdown 文档；new 时必须包含完整 frontmatter 与正文。无法可靠判断时 action=unsure。

候选原文：
{candidate.lesson}

Layer1 问题卡（为空表示旧候选；缺失信息不得编造，可 action=unsure）：
{candidate.context or '(legacy candidate: no structured problem card)'}

以下是 skills/sediment/SKILL.md 的原文真源，必须直接遵守：
--- BEGIN SKILL 原文 ---
{skill_truth}
--- END SKILL 原文 ---

两路判重命中（每个 source_path 的全文已附）：
{hits}
"""


def merge_prompt(
    candidate: Candidate,
    decision: dict[str, Any],
    target_text: str,
    skill_truth: str,
) -> str:
    return f"""你是 /sediment 的 headless 合并成文器。只输出裸 JSON，字段严格为：
{{"action":"merge","container":"...","target_doc_id":"...","doc_id":null,"markdown":"完整合并稿","reason":"..."}}
保留目标 doc_id、文件名和既有结构；markdown 必须包含完整 frontmatter 和全文，只加入候选带来的通用化增量。

候选原文：
{candidate.lesson}

Layer1 问题卡：
{candidate.context or '(legacy candidate: no structured problem card)'}

首次判定：
{json.dumps(decision, ensure_ascii=False)}

以下是 skills/sediment/SKILL.md 的原文真源，必须直接遵守：
--- BEGIN SKILL 原文 ---
{skill_truth}
--- END SKILL 原文 ---

目标全文：
--- BEGIN TARGET ---
{target_text.rstrip()}
--- END TARGET ---
"""


def unsure_decision(reason: str) -> dict[str, Any]:
    return {
        "action": "unsure",
        "container": "",
        "target_doc_id": None,
        "doc_id": None,
        "slug": None,
        "markdown": "",
        "reason": reason,
    }


def decide_candidate(
    candidate: Candidate,
    *,
    llm_cmd: str,
    kb_index: KbIndexCli,
    skill_truth: str,
    timeout: float,
    documents: dict[str, Path],
) -> dict[str, Any]:
    symptom_hits = kb_search(kb_index, candidate.lesson)
    cause_hits = kb_search(kb_index, root_cause_query(candidate.lesson, candidate.context))
    hits = render_hits([("症状", symptom_hits), ("根因", cause_hits)])
    deadline = time.monotonic() + timeout
    try:
        decision = call_llm(
            llm_cmd,
            decision_prompt(candidate, skill_truth, hits),
            deadline=deadline,
        )
        if decision["action"] == "merge":
            target_id = str(decision["target_doc_id"])
            target = documents.get(target_id)
            if target is None:
                raise SedimentError(f"merge target does not exist: {target_id}")
            original = target.read_text(encoding="utf-8")
            merged = call_llm(
                llm_cmd,
                merge_prompt(candidate, decision, original, skill_truth),
                deadline=deadline,
            )
            if merged["action"] != "merge" or merged["target_doc_id"] != target_id:
                raise SedimentError("merge drafting call changed action or target_doc_id")
            if not merged["markdown"].strip():
                raise SedimentError("merge drafting call returned empty markdown")
            decision = merged
        if (
            decision["action"] == "new"
            and decision.get("container") != "anti-patterns"
            and not str(decision.get("doc_id") or "").strip()
        ):
            return unsure_decision("new 非反模式缺 doc_id,降级存疑")
        return decision
    except CandidateTimeout as error:
        return unsure_decision(f"判定超时降级: {str(error)[:200]}")
    except (SedimentError, OSError, UnicodeError) as error:
        # 单条判定失败降级存疑,不拦整批(希波克拉底:不确定就不动)
        return unsure_decision(f"判定失败降级: {str(error)[:200]}")


def git_clean() -> None:
    completed = run_command(["git", "status", "--porcelain=v1"])
    if completed.returncode != 0:
        raise SedimentError("cannot inspect git worktree")
    if completed.stdout:
        raise SedimentError("git worktree must be clean before auto-sediment")


def create_branch(branch: str) -> str:
    exists = run_command(
        ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"]
    )
    if exists.returncode == 0:
        raise SedimentError(f"run already applied; branch exists: {branch}")
    completed = run_command(["git", "switch", "-c", branch])
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise SedimentError(f"cannot create branch {branch}: {detail[:500]}")
    return branch


def restore_checkout(original_branch: str, original_head: str) -> None:
    arguments = (
        ["git", "checkout", original_branch]
        if original_branch
        else ["git", "checkout", "--detach", original_head]
    )
    completed = run_command(arguments)
    if completed.returncode == 0:
        return
    detail = completed.stderr.strip() or completed.stdout.strip()
    fallback = run_command(["git", "checkout", "--detach", original_head])
    if fallback.returncode != 0:
        fallback_detail = fallback.stderr.strip() or fallback.stdout.strip()
        raise SedimentError(
            f"cannot restore original checkout: {detail[:500]}; "
            f"detached fallback failed: {fallback_detail[:500]}"
        )
    raise SedimentError(
        f"cannot restore original branch {original_branch}: {detail[:500]}; "
        "restored original HEAD in detached mode"
    )


def tracked_doc_map() -> dict[str, Path]:
    completed = run_command(["git", "ls-files", "-z", "--", "knowledge"])
    if completed.returncode != 0:
        raise SedimentError("cannot enumerate knowledge documents")
    result: dict[str, Path] = {}
    container_dirs = {"anti-patterns", "platform-kb", "tech-docs", "work-model"}
    for raw in completed.stdout.encode("utf-8").split(b"\0"):
        if not raw:
            continue
        relative = Path(raw.decode("utf-8"))
        if (
            relative.suffix != ".md"
            or len(relative.parts) < 3
            or relative.parts[0] != "knowledge"
            or relative.parts[1] not in container_dirs
        ):
            continue
        text = (REPO_ROOT / relative).read_text(encoding="utf-8")
        fields, _ = split_frontmatter(text)
        doc_id = fields.get("doc_id", "").strip("'\"")
        if doc_id:
            result[doc_id] = REPO_ROOT / relative
    return result


def split_frontmatter(markdown: str) -> tuple[dict[str, str], str]:
    lines = markdown.replace("\r\n", "\n").splitlines()
    if not lines or lines[0].strip() != "---":
        raise SedimentError("generated markdown has no frontmatter")
    try:
        end = next(index for index, line in enumerate(lines[1:], 1) if line.strip() == "---")
    except StopIteration as error:
        raise SedimentError("generated markdown frontmatter is not closed") from error
    fields: dict[str, str] = {}
    for line in lines[1:end]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = FRONTMATTER_KEY_RE.match(line)
        if not match:
            raise SedimentError("generated frontmatter must use flat fields")
        key, value = match.groups()
        if key in fields:
            raise SedimentError(f"generated frontmatter duplicates {key}")
        fields[key] = (value or "").strip()
    body = "\n".join(lines[end + 1 :]).strip()
    if not body:
        raise SedimentError("generated markdown body is empty")
    return fields, body


def scalar_value(raw: str) -> str:
    value = raw.strip()
    if value.startswith('"'):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError as error:
            raise SedimentError("invalid quoted frontmatter scalar") from error
        return str(decoded)
    if len(value) >= 2 and value.startswith("'") and value.endswith("'"):
        return value[1:-1].replace("''", "'")
    return value


def render_document(
    markdown: str,
    *,
    doc_id: str,
    container: str,
    expected_platform: str | None = None,
    base_markdown: str | None = None,
    strict_identity: bool = False,
    stamp_auto: bool = True,
) -> str:
    fields, body = split_frontmatter(markdown)
    base_fields: dict[str, str] = {}
    if base_markdown is not None:
        base_fields, _ = split_frontmatter(base_markdown)
    combined = {**base_fields, **fields}
    if strict_identity:
        generated_id = scalar_value(fields.get("doc_id", ""))
        generated_container = scalar_value(fields.get("container", ""))
        if generated_id and generated_id != doc_id:
            raise SedimentError("merge draft changed doc_id")
        if generated_container and generated_container != container:
            raise SedimentError("merge draft changed container")
    summary = scalar_value(combined.get("summary", ""))
    platform = expected_platform or scalar_value(combined.get("platform", ""))
    if not summary:
        raise SedimentError("generated markdown is missing summary")
    if platform not in PLATFORMS:
        raise SedimentError(f"generated markdown has invalid platform: {platform}")
    lines = [
        "---",
        f"doc_id: {json.dumps(doc_id, ensure_ascii=False)}",
        f"container: {container}",
        f"platform: {platform}",
        f"summary: {json.dumps(summary, ensure_ascii=False)}",
    ]
    for key, raw_value in combined.items():
        if key in {"doc_id", "container", "platform", "summary", "sedimented_by"}:
            continue
        if key == "related" and not (
            raw_value.startswith("[") and raw_value.endswith("]")
        ):
            raise SedimentError("generated related must be an inline list")
        lines.append(f"{key}: {raw_value}")
    if stamp_auto:
        lines.append("sedimented_by: auto")
    elif "sedimented_by" in base_fields:
        lines.append(f"sedimented_by: {base_fields['sedimented_by']}")
    lines.extend(["---", "", body, ""])
    rendered = "\n".join(lines)
    semantic_errors = validate_document(rendered, root=REPO_ROOT, require_v2=True)
    if semantic_errors:
        raise SedimentError(
            "generated markdown violates sedimentation-v2: " + "; ".join(semantic_errors)
        )
    return rendered


def next_anti_number(documents: dict[str, Path]) -> int:
    try:
        lines = (REPO_ROOT / "knowledge" / "INDEX.md").read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as error:
        raise SedimentError(f"cannot read knowledge/INDEX.md: {error}") from error
    in_section = False
    numbers: list[int] = []
    for line in lines:
        if line.startswith("## "):
            if in_section:
                break
            in_section = line.strip() == "## anti-patterns"
            continue
        if in_section:
            match = ANTI_INDEX_RE.match(line)
            if match:
                numbers.append(int(match.group(1)))
    if not numbers:
        raise SedimentError("anti-patterns section has no numbered entry")
    number = numbers[-1] + 1
    anti_root = REPO_ROOT / "knowledge" / "anti-patterns"
    while f"ap-{number:04d}" in documents or any(anti_root.glob(f"{number:04d}-*.md")):
        number += 1
    return number


def safe_doc_parts(doc_id: str) -> PurePosixPath:
    path = PurePosixPath(doc_id)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise SedimentError(f"unsafe doc_id: {doc_id}")
    if any(not re.fullmatch(r"[\w.-]+", part) for part in path.parts):
        raise SedimentError(f"doc_id has unsafe characters: {doc_id}")
    return path


def new_path_and_id(result: dict[str, Any], anti_number: int | None) -> tuple[Path, str]:
    container = result["container"]
    proposed = str(result.get("doc_id") or "").strip()
    if container == "anti-patterns":
        if anti_number is None:
            raise SedimentError("anti-pattern number was not allocated")
        import re as _re
        slug = _re.sub(r"[^a-z0-9-]", "", str(result.get("slug") or "").lower().replace("_", "-"))[:60] or "auto-sediment"
        return (
            REPO_ROOT / "knowledge" / "anti-patterns" / f"{anti_number:04d}-{slug}.md",
            f"ap-{anti_number:04d}",
        )
    if not proposed:
        raise SedimentError(f"new {container} result requires doc_id")
    parts = safe_doc_parts(proposed)
    if container == "platform-kb":
        if len(parts.parts) < 3 or parts.parts[0] != "platform-kb":
            raise SedimentError("platform-kb doc_id must be platform-kb/<platform>/<slug>")
        return REPO_ROOT / "knowledge" / Path(*parts.parts).with_suffix(".md"), proposed
    if container == "tech-docs":
        if parts.parts[0] != "tech-docs":
            raise SedimentError("tech-docs doc_id must start with tech-docs/")
        return REPO_ROOT / "knowledge" / Path(*parts.parts).with_suffix(".md"), proposed
    if container == "work-model":
        if parts.parts[0] != "work-model":
            raise SedimentError("work-model doc_id must start with work-model/")
        return REPO_ROOT / "knowledge" / Path(*parts.parts).with_suffix(".md"), proposed
    if container == "case-studies":
        if len(parts.parts) < 3 or parts.parts[:2] != ("tech-docs", "案例研究"):
            raise SedimentError("case-studies doc_id must be tech-docs/案例研究/<domain>/<slug>")
        return REPO_ROOT / "knowledge" / Path(*parts.parts).with_suffix(".md"), proposed
    raise SedimentError(f"unsupported new container: {container}")


def write_new(result: dict[str, Any], anti_number: int | None) -> tuple[Path, str]:
    path, doc_id = new_path_and_id(result, anti_number)
    if path.exists():
        raise SedimentError(f"new document path already exists: {path.relative_to(REPO_ROOT)}")
    expected_platform = None
    if result["container"] == "platform-kb":
        platform_dir = path.relative_to(REPO_ROOT / "knowledge" / "platform-kb").parts[0]
        expected_platform = "harmonyos" if platform_dir == "harmony" else platform_dir
    rendered = render_document(
        result["markdown"],
        doc_id=doc_id,
        container=result["container"],
        expected_platform=expected_platform,
    )
    if anti_number is not None:
        # 同 run 一次取号逐条递增,LLM 正文里的编号可能是陈旧号——机械强制对齐
        import re as _re
        rendered = _re.sub(r"^# \d{4} ", f"# {anti_number:04d} ", rendered, count=1, flags=_re.M)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rendered, encoding="utf-8")
    return path, doc_id


def related_ids(markdown: str) -> list[str]:
    fields, _ = split_frontmatter(markdown)
    raw = fields.get("related")
    if raw is None:
        return []
    if not (raw.startswith("[") and raw.endswith("]")):
        raise SedimentError("related must be an inline list")
    return [item.strip().strip("'\"") for item in raw[1:-1].split(",") if item.strip()]


def add_reverse_link(path: Path, new_doc_id: str) -> bool:
    original = path.read_text(encoding="utf-8")
    fields, _ = split_frontmatter(original)
    existing = related_ids(original)
    if new_doc_id in existing:
        return False
    existing.append(new_doc_id)
    rendered_related = "[" + ", ".join(existing) + "]"
    lines = original.replace("\r\n", "\n").splitlines()
    end = next(index for index, line in enumerate(lines[1:], 1) if line.strip() == "---")
    if "related" in fields:
        for index in range(1, end):
            if FRONTMATTER_KEY_RE.match(lines[index]) and lines[index].split(":", 1)[0] == "related":
                lines[index] = f"related: {rendered_related}"
                break
    else:
        lines.insert(end, f"related: {rendered_related}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return True


def apply_merge(
    candidate: Candidate,
    decision: dict[str, Any],
    documents: dict[str, Path],
) -> tuple[Path, str, str]:
    target_id = str(decision["target_doc_id"])
    target = documents.get(target_id)
    if target is None:
        raise SedimentError(f"merge target does not exist: {target_id}")
    original = target.read_text(encoding="utf-8")
    existing_fields, _ = split_frontmatter(original)
    container = scalar_value(existing_fields.get("container", ""))
    platform = scalar_value(existing_fields.get("platform", ""))
    rendered = render_document(
        decision["markdown"],
        doc_id=target_id,
        container=container,
        expected_platform=platform,
        stamp_auto=False,
        base_markdown=original,
        strict_identity=True,
    )
    target.write_text(rendered, encoding="utf-8")
    return target, target_id, str(decision["reason"])


def git_changed_knowledge() -> list[Path]:
    completed = run_command(
        ["git", "-c", "core.quotePath=false", "diff", "--cached", "--name-only", "--diff-filter=AM", "--", "knowledge"]
    )
    if completed.returncode != 0:
        raise SedimentError("cannot enumerate changed knowledge files")
    return [REPO_ROOT / line for line in completed.stdout.splitlines() if line]


def validate_and_commit(dispositions: list[Disposition], kb_index: KbIndexCli) -> str:
    document_paths = sorted(
        {path for item in dispositions for path in item.changed_paths},
        key=lambda path: str(path),
    )
    if document_paths:
        require_success(
            ["git", "add", "--", *[str(path.relative_to(REPO_ROOT)) for path in document_paths]],
            "git add generated documents",
        )
    require_success([sys.executable, str(REPO_ROOT / "scripts/kb/lint-frontmatter.py")], "lint-frontmatter")
    require_success(
        [sys.executable, str(REPO_ROOT / "scripts/kb/lint-sedimentation.py")],
        "lint-sedimentation",
    )
    require_success([sys.executable, str(REPO_ROOT / "scripts/kb/build-index-md.py")], "build-index-md")
    require_success(
        [sys.executable, str(REPO_ROOT / "scripts/kb/build-corpus-manifest.py")],
        "build-corpus-manifest",
    )
    index_path = REPO_ROOT / "knowledge" / "INDEX.md"
    manifest_path = REPO_ROOT / "knowledge" / "MANIFEST.json"
    require_success(
        [
            "git",
            "add",
            "--",
            str(index_path.relative_to(REPO_ROOT)),
            str(manifest_path.relative_to(REPO_ROOT)),
        ],
        "git add generated catalogs",
    )
    changed = git_changed_knowledge()
    deny = run_command(
        [sys.executable, str(REPO_ROOT / "scripts/kb/kb-deny-lint.py"), *[str(path) for path in changed]]
    )
    if deny.stdout.strip():
        print(deny.stdout.strip())
    if deny.returncode == 1:
        raise DenyInterception("deny lint rejected generated knowledge")
    if deny.returncode != 0:
        detail = deny.stderr.strip() or deny.stdout.strip()
        raise SedimentError(f"deny lint exited {deny.returncode}: {detail[:1000]}")
    require_success(kb_index.command("build"), "kb-index build")

    lines = ["chore(kb): auto-sediment candidates", ""]
    for item in dispositions:
        label = "MERGE" if item.action == "merge" else item.action.upper()
        target = item.doc_id or "manual"
        lines.append(f"{label}: {item.candidate.lesson} -> {target}")
    message = "\n".join(lines)
    require_success(["git", "commit", "-m", message], "git commit")
    return message


def marker(item: Disposition) -> str:
    if item.action in {"new", "merge"}:
        return f"（✅ 已沉淀 {item.doc_id}）"
    if item.action == "skip":
        return f"（✅ 判重放弃:已有 {item.doc_id}）"
    return "（❓ 证据不足待裁决）"


def no_change_dispositions(
    decisions: list[tuple[Candidate, dict[str, Any]]]
) -> list[Disposition]:
    documents = tracked_doc_map()
    dispositions: list[Disposition] = []
    for candidate, decision in decisions:
        action = decision["action"]
        if action in {"new", "merge"}:
            raise SedimentError("content-changing decision requires a review branch")
        if action == "skip":
            target_id = str(decision["target_doc_id"])
            if target_id not in documents:
                raise SedimentError(f"skip target does not exist: {target_id}")
            dispositions.append(
                Disposition(candidate, action, target_id, str(decision["reason"]))
            )
        else:
            dispositions.append(
                Disposition(candidate, action, None, str(decision["reason"]))
            )
    return dispositions


def update_candidates(path: Path, lines: list[str], dispositions: list[Disposition]) -> None:
    try:
        current = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise SedimentError(f"cannot re-read candidates before atomic update: {error}") from error
    if current != "".join(lines):
        raise SedimentError("candidate file changed during run; refusing to advance markers")
    for item in dispositions:
        original = lines[item.candidate.line_index]
        ending = "\r\n" if original.endswith("\r\n") else "\n" if original.endswith("\n") else ""
        content = original[: -len(ending)] if ending else original
        match = CANDIDATE_RE.match(content)
        if match is None:
            raise SedimentError("candidate file changed during run; refusing to advance markers")
        lines[item.candidate.line_index] = (
            f"{match.group('prefix')}{item.candidate.lesson}{marker(item)}{match.group('trailing')}{ending}"
        )
    try:
        atomic_write(path, "".join(lines))
    except OSError as error:
        raise SedimentError(f"cannot atomically update candidates: {error}") from error


def update_manual_candidates(
    path: Path, resolutions: list[ManualResolution]
) -> None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    except (OSError, UnicodeError) as error:
        raise SedimentError(f"cannot read manual candidates: {error}") from error
    changed = False
    for resolution in resolutions:
        candidate = resolution.candidate
        if candidate.line_index >= len(lines):
            raise SedimentError(
                f"manual candidate line no longer exists: {candidate.line_index}"
            )
        original = lines[candidate.line_index]
        ending = "\r\n" if original.endswith("\r\n") else "\n" if original.endswith("\n") else ""
        content = original[: -len(ending)] if ending else original
        expected_marker = marker(
            Disposition(candidate, resolution.action, resolution.target, resolution.reason)
        )
        pending = MANUAL_CANDIDATE_RE.match(content)
        if pending is not None and pending.group("lesson").strip() == candidate.lesson:
            lines[candidate.line_index] = (
                f"{pending.group('prefix')}{candidate.lesson}{expected_marker}"
                f"{pending.group('trailing')}{ending}"
            )
            changed = True
            continue
        resolved = RESOLVED_CANDIDATE_RE.match(content)
        if (
            resolved is not None
            and resolved.group("lesson").strip() == candidate.lesson
            and resolved.group("marker") == expected_marker
        ):
            continue
        raise SedimentError(
            f"manual candidate changed since review: line {candidate.line_index}"
        )
    if changed:
        try:
            atomic_write(path, "".join(lines))
        except OSError as error:
            raise SedimentError(f"cannot atomically update manual candidates: {error}") from error


def append_log(
    home: Path, run_id: str, branch: str, dispositions: list[Disposition]
) -> None:
    counts = {action: 0 for action in ("new", "merge", "skip", "unsure")}
    for item in dispositions:
        counts[item.action] += 1
    detail = {
        "timestamp": utc_now(),
        "run_id": run_id,
        "phase": "apply",
        "branch": branch,
        "summary": counts,
        "details": [
            {
                "candidate": item.candidate.lesson,
                "action": item.action,
                "doc_id": item.doc_id,
                "reason": item.reason,
            }
            for item in dispositions
        ],
    }
    path = home / "auto-sediment.log"
    try:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(detail, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as error:
        raise SedimentError(f"cannot append auto-sediment log: {error}") from error


def manual_resolution_payload(
    run_id: str,
    approved_by: str,
    resolutions: list[ManualResolution],
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "approved_by": approved_by,
        "resolutions": [
            {
                "candidate_line_index": item.candidate.line_index,
                "lesson": item.candidate.lesson,
                "action": item.action,
                "target": item.target,
                "reason": item.reason,
            }
            for item in resolutions
        ],
    }


def persist_manual_resolutions(
    home: Path,
    run_id: str,
    approved_by: str,
    resolutions: list[ManualResolution],
) -> Path:
    path = manual_resolutions_path(home, run_id)
    payload = manual_resolution_payload(run_id, approved_by, resolutions)
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    try:
        if path.exists():
            existing = json.loads(path.read_text(encoding="utf-8"))
            if existing != payload:
                raise SedimentError(
                    f"manual resolutions already exist with different content: {path}"
                )
            return path
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(path, rendered)
    except SedimentError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SedimentError(f"cannot persist manual resolutions: {error}") from error
    return path


def manual_resolution_logged(home: Path, run_id: str) -> bool:
    path = home / "auto-sediment.log"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return False
    except (OSError, UnicodeError) as error:
        raise SedimentError(f"cannot read auto-sediment log: {error}") from error
    for line in lines:
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if (
            isinstance(record, dict)
            and record.get("run_id") == run_id
            and record.get("phase") == "manual_resolve"
        ):
            return True
    return False


def append_manual_resolution_log(
    home: Path,
    run_id: str,
    approved_by: str,
    resolutions: list[ManualResolution],
) -> None:
    counts = {action: 0 for action in ("new", "merge", "skip")}
    for item in resolutions:
        counts[item.action] += 1
    detail = {
        "timestamp": utc_now(),
        "run_id": run_id,
        "phase": "manual_resolve",
        "branch": "none",
        "approved_by": approved_by,
        "summary": counts,
        "details": [
            {
                "candidate_line_index": item.candidate.line_index,
                "candidate": item.candidate.lesson,
                "action": item.action,
                "target": item.target,
                "reason": item.reason,
            }
            for item in resolutions
        ],
    }
    path = home / "auto-sediment.log"
    try:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(detail, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as error:
        raise SedimentError(f"cannot append manual resolution log: {error}") from error


def print_apply_summary(
    run_id: str, branch: str, dispositions: list[Disposition]
) -> None:
    counts = {action: 0 for action in ("new", "merge", "skip", "unsure")}
    for item in dispositions:
        counts[item.action] += 1
    print(
        "auto-sediment: "
        + f"run_id={run_id} phase=apply applied={len(dispositions)} "
        + " ".join(f"{action}={counts[action]}" for action in counts)
        + f" branch={branch}"
    )


def print_decide_summary(
    run_id: str,
    *,
    decided: int,
    skipped: int,
    total: int,
    decision_file: Path,
) -> None:
    print(
        "auto-sediment: "
        f"run_id={run_id} phase=decide decided={decided} "
        f"resume_skipped={skipped} total={total} branch=none "
        f"decisions={decision_file}"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--decide-only", action="store_true")
    mode.add_argument("--apply", metavar="RUN_ID")
    mode.add_argument("--resume", metavar="RUN_ID")
    mode.add_argument("--resolve-manual", metavar="RUN_ID")
    parser.add_argument(
        "--resolution-file",
        type=Path,
        help="human-approved JSON array used with --resolve-manual",
    )
    parser.add_argument(
        "--approved-by",
        help="auditable approver identity used with --resolve-manual",
    )
    parser.add_argument("--max-candidates", type=int, default=5)
    parser.add_argument("--per-candidate-timeout", type=float, default=180.0)
    parser.add_argument(
        "--llm-cmd",
        default=DEFAULT_LLM_CMD,
        help="command template; a standalone {prompt} is delivered through stdin",
    )
    parser.add_argument(
        "--kb-index-root",
        type=Path,
        default=KB_INDEX_ROOT,
        help="directory containing kb-index Python entry points",
    )
    parser.add_argument(
        "--kb-index-python",
        type=Path,
        help="Python interpreter for kb-index (defaults to SULDE_KB_HOME/venv)",
    )
    args = parser.parse_args()
    if args.max_candidates <= 0:
        parser.error("--max-candidates must be > 0")
    if args.per_candidate_timeout <= 0:
        parser.error("--per-candidate-timeout must be > 0")
    if args.resolve_manual:
        if args.resolution_file is None:
            parser.error("--resolve-manual requires --resolution-file")
        if not str(args.approved_by or "").strip():
            parser.error("--resolve-manual requires --approved-by")
    elif args.resolution_file is not None or args.approved_by is not None:
        parser.error("--resolution-file/--approved-by require --resolve-manual")
    return args


def run_decide_phase(
    args: argparse.Namespace,
    home: Path,
    candidate_path: Path,
    run_id: str,
    *,
    resume: bool,
) -> tuple[list[tuple[Candidate, dict[str, Any]]], int]:
    path = decisions_path(home, run_id)
    existing = load_decisions(path, recover_truncated_tail=True) if resume else []
    lines, candidates = load_candidates(candidate_path, args.max_candidates)
    if not resume and candidates:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch(exist_ok=False)
        except FileExistsError as error:
            raise SedimentError(f"decisions file already exists: {path}") from error
        except OSError as error:
            raise SedimentError(f"cannot create decisions file: {error}") from error
    validate_decision_candidates(lines, existing)
    decided_indices = {candidate.line_index for candidate, _ in existing}
    pending = [candidate for candidate in candidates if candidate.line_index not in decided_indices]
    decided_now = 0
    if pending:
        skill_truth = extract_skill_truth()
        documents = tracked_doc_map()
        for candidate in pending:
            decision = decide_candidate(
                candidate,
                llm_cmd=args.llm_cmd,
                kb_index=args.kb_index,
                skill_truth=skill_truth,
                timeout=args.per_candidate_timeout,
                documents=documents,
            )
            append_decision(path, candidate, decision)
            existing.append((candidate, decision))
            decided_now += 1
    print_decide_summary(
        run_id,
        decided=decided_now,
        skipped=len(candidates) - len(pending),
        total=len(existing),
        decision_file=path,
    )
    return existing, len(candidates)


def run_apply_phase(
    args: argparse.Namespace,
    home: Path,
    candidate_path: Path,
    run_id: str,
    decisions: list[tuple[Candidate, dict[str, Any]]] | None = None,
) -> int:
    if decisions is None:
        decisions = load_decisions(decisions_path(home, run_id))
    if not decisions:
        print_apply_summary(run_id, "none", [])
        print("auto-sediment: 无待处理")
        return 0
    lines, _ = load_candidates(candidate_path, sys.maxsize)
    validate_decision_candidates(lines, decisions)
    if not any(decision["action"] in {"new", "merge"} for _, decision in decisions):
        dispositions = no_change_dispositions(decisions)
        append_log(home, run_id, "none", dispositions)
        update_candidates(candidate_path, lines, dispositions)
        print_apply_summary(run_id, "none", dispositions)
        return 0
    git_clean()
    branch = f"auto-sediment/{run_id}"
    branch_result = run_command(["git", "branch", "--show-current"])
    head_result = run_command(["git", "rev-parse", "HEAD"])
    if branch_result.returncode != 0 or head_result.returncode != 0:
        raise SedimentError("cannot capture original git checkout")
    original_branch = branch_result.stdout.strip()
    original_head = head_result.stdout.strip()
    branch = create_branch(branch)
    try:
        return _apply_and_finish(
            args,
            home,
            run_id,
            branch,
            decisions,
            candidate_path,
            lines,
            original_branch,
            original_head,
        )
    except BaseException:
        # 半成品绝不带出手术室:清本分支工作区并切回原分支
        run_command(["git", "reset", "--hard", "HEAD"])
        run_command(["git", "clean", "-fd", "--", "knowledge"])
        restore_checkout(original_branch, original_head)
        raise


def run_manual_resolution(
    args: argparse.Namespace,
    home: Path,
    candidate_path: Path,
    run_id: str,
) -> int:
    decisions = load_decisions(decisions_path(home, run_id))
    unsure = {
        candidate.line_index: candidate
        for candidate, decision in decisions
        if decision["action"] == "unsure"
    }
    if not unsure:
        raise SedimentError(f"run has no unsure candidates to resolve: {run_id}")
    resolutions = load_manual_resolutions(args.resolution_file)
    supplied = {item.candidate.line_index: item for item in resolutions}
    if set(supplied) != set(unsure):
        missing = sorted(set(unsure) - set(supplied))
        extra = sorted(set(supplied) - set(unsure))
        raise SedimentError(
            "manual resolutions must cover every unsure candidate exactly once: "
            f"missing={missing} extra={extra}"
        )
    documents = tracked_doc_map()
    for line_index, resolution in supplied.items():
        candidate = unsure[line_index]
        if resolution.candidate.lesson != candidate.lesson:
            raise SedimentError(
                f"manual resolution lesson mismatch at line {line_index}"
            )
        if resolution.action in {"new", "merge"} and resolution.target not in documents:
            raise SedimentError(
                f"manual {resolution.action} target does not exist: {resolution.target}"
            )

    approved_by = str(args.approved_by).strip()
    audit_path = persist_manual_resolutions(
        home, run_id, approved_by, resolutions
    )
    update_manual_candidates(candidate_path, resolutions)
    if not manual_resolution_logged(home, run_id):
        append_manual_resolution_log(
            home, run_id, approved_by, resolutions
        )
    counts = {action: 0 for action in ("new", "merge", "skip")}
    for item in resolutions:
        counts[item.action] += 1
    print(
        "auto-sediment: "
        f"run_id={run_id} phase=manual-resolve resolved={len(resolutions)} "
        + " ".join(f"{action}={counts[action]}" for action in counts)
        + f" branch=none audit={audit_path}"
    )
    return 0


def main() -> int:
    args = parse_args()
    home = kb_home()
    home.mkdir(parents=True, exist_ok=True)
    if (
        not args.decide_only
        and not args.resolve_manual
        and os.environ.get(ISOLATED_RUN_ENV) != "1"
    ):
        try:
            return run_in_isolated_worktree(home)
        except (SedimentError, OSError, UnicodeError) as error:
            print(f"auto-sediment: {error}", file=sys.stderr)
            return 2
    args.kb_index = KbIndexCli(home, args.kb_index_root, args.kb_index_python)
    candidate_path = home / "distill-candidates.md"
    if not args.apply and not args.resume and not args.resolve_manual:
        _, pending = load_candidates(candidate_path, args.max_candidates)
        if not pending:
            run_id = new_run_id()
            print_decide_summary(
                run_id,
                decided=0,
                skipped=0,
                total=0,
                decision_file=decisions_path(home, run_id),
            )
            print("auto-sediment: 无待处理")
            return 0
    lock_handle = None
    try:
        lock_handle = acquire_lock(home / "auto-sediment.lock")
        if args.resolve_manual:
            return run_manual_resolution(
                args,
                home,
                candidate_path,
                validate_run_id(args.resolve_manual),
            )
        if args.apply:
            return run_apply_phase(
                args, home, candidate_path, validate_run_id(args.apply)
            )

        run_id = validate_run_id(args.resume) if args.resume else new_run_id()
        decisions, candidate_count = run_decide_phase(
            args,
            home,
            candidate_path,
            run_id,
            resume=bool(args.resume),
        )
        if args.decide_only:
            if candidate_count == 0:
                print("auto-sediment: 无待处理")
            return 0
        if candidate_count == 0 and not decisions:
            print("auto-sediment: 无待处理")
            return 0
        return run_apply_phase(args, home, candidate_path, run_id, decisions)
    except DenyInterception as error:
        print(f"auto-sediment: {error}", file=sys.stderr)
        return 1
    except (SedimentError, OSError, UnicodeError) as error:
        print(f"auto-sediment: {error}", file=sys.stderr)
        return 2
    finally:
        if lock_handle is not None:
            try:
                unlock(lock_handle)
                lock_handle.close()
            except OSError:
                pass


def _apply_and_finish(
    args, home, run_id, branch, decisions, candidate_path, lines,
    original_branch, original_head,
) -> int:
    documents = tracked_doc_map()
    anti_number = next_anti_number(documents)
    dispositions: list[Disposition] = []
    for candidate, decision in decisions:
        action = decision["action"]
        if action == "new":
            number = anti_number if decision["container"] == "anti-patterns" else None
            if number is not None:
                anti_root = REPO_ROOT / "knowledge" / "anti-patterns"
                while f"ap-{number:04d}" in documents or any(
                    anti_root.glob(f"{number:04d}-*.md")
                ):
                    number += 1
            path, doc_id = write_new(decision, number)
            if number is not None:
                anti_number = number + 1
            documents[doc_id] = path
            changed_paths = [path]
            relations = related_ids(path.read_text(encoding="utf-8"))
            if relations:
                related_target = documents.get(relations[0])
                if related_target is None:
                    raise SedimentError(f"related target does not exist: {relations[0]}")
                if add_reverse_link(related_target, doc_id):
                    changed_paths.append(related_target)
            dispositions.append(
                Disposition(
                    candidate,
                    action,
                    doc_id,
                    str(decision["reason"]),
                    tuple(changed_paths),
                )
            )
        elif action == "merge":
            path, doc_id, reason = apply_merge(candidate, decision, documents)
            dispositions.append(Disposition(candidate, action, doc_id, reason, (path,)))
        elif action == "skip":
            target_id = str(decision["target_doc_id"])
            if target_id not in documents:
                raise SedimentError(f"skip target does not exist: {target_id}")
            dispositions.append(
                Disposition(candidate, action, target_id, str(decision["reason"]))
            )
        else:
            dispositions.append(
                Disposition(candidate, action, None, str(decision["reason"]))
            )

    validate_and_commit(dispositions, args.kb_index)
    append_log(home, run_id, branch, dispositions)
    update_candidates(candidate_path, lines, dispositions)
    restore_checkout(original_branch, original_head)
    print_apply_summary(run_id, branch, dispositions)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
