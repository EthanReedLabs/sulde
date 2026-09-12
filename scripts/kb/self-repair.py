#!/usr/bin/env python3
"""Draft repair briefs and execute only explicitly human-approved entries."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import runpy
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from file_lock import lock_exclusive_nonblocking, unlock
from intent_guardian import IntentGuardianError, load_contract, resume_contract
from intervention import (
    InterventionError,
    archive_store as archive_intervention_store,
    readiness_blocking_attempts as readiness_blocking_effect_attempts,
    load_projection as load_intervention_projection,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
BRIEF_TEMPLATE = REPO_ROOT / "templates" / "self-repair-brief.md"
TERMINAL_STATUSES = {"success", "failed", "timeout", "paused", "awaiting_human"}
TASK_TYPES = {"implementation", "diagnostic"}
DIAGNOSTIC_OUTCOMES = {"conclusive", "conclusive_with_gaps", "inconclusive"}
SEVERITY_ORDER = {"red": 0, "golden_red": 1, "red_team": 2, "reviewer": 3}
REQUIRED_BRIEF_HEADINGS = ("目标", "范围", "已知上下文", "完成标准", "体量与熔断")
REPORT_CLAUSE = "汇报硬性要求"
QUEUE_SCHEMA = "sulde-self-repair-queue-v2"
QUEUE_STATES = frozenset(
    {"inconclusive", "verified", "unresolved", "superseded", "expired"}
)
QUEUE_TERMINAL_STATES = frozenset({"verified", "superseded", "expired"})
MAX_RETRY_ATTEMPTS = 3
DEFAULT_QUEUE_TTL_DAYS = 30

_command_template = runpy.run_path(str(Path(__file__).with_name("command_template.py")))
split_command_template = _command_template["split_command_template"]
DEFAULT_LLM_CMD = _command_template["default_llm_command"]()


class SelfRepairError(RuntimeError):
    """A controlled self-repair failure."""


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
    )


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except (TypeError, ValueError, OverflowError):
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def queue_scope(row: dict[str, Any]) -> dict[str, str]:
    """Return the exact project/session/task-instance aggregation boundary.

    Missing legacy identities stay in an explicit legacy lane. They are never
    borrowed from the observer environment, which could join unrelated runs.
    """
    project = str(
        row.get("project_id")
        or row.get("workspace_id")
        or row.get("project_sha256")
        or "legacy-project"
    ).strip()
    session = str(row.get("session_id") or "legacy-session").strip()
    instance = str(
        row.get("task_instance_id")
        or row.get("lane_id")
        or row.get("task_epoch")
        or row.get("slug")
        or "legacy-task"
    ).strip()
    return {
        "project_id": project[:256],
        "session_id": session[:256],
        "task_instance_id": instance[:256],
    }


def queue_fingerprint(row: dict[str, Any]) -> str:
    """Stable problem fingerprint; scope is deliberately kept separate."""
    explicit = str(row.get("fingerprint") or "").strip().lower()
    if re.fullmatch(r"[0-9a-f]{64}", explicit):
        return explicit
    signature = {
        "problem_type": str(row.get("problem_type") or row.get("severity") or "unknown")[:128],
        "source": str(row.get("source") or "unknown")[:1_000],
        "symptom": str(row.get("symptom") or row.get("title") or "")[:1_000],
        "experiment_id": str(row.get("experiment_id") or "")[:256],
    }
    return hashlib.sha256(_canonical_json(signature).encode("utf-8")).hexdigest()


def _queue_times(row: dict[str, Any]) -> list[datetime]:
    keys = (
        "first_seen_at", "last_seen_at", "drafted_at", "draft_error_at",
        "decided_at", "execution_started_at", "executed_at", "diagnosed_at",
        "resolved_at", "awaiting_human_at", "aborted_at", "failed_at", "at",
    )
    return [parsed for key in keys if (parsed := _parse_time(row.get(key))) is not None]


def has_authority_debt(row: dict[str, Any]) -> bool:
    """Unknown/high-risk facts and unfinished authority records block closure."""
    effect = str(row.get("effect") or row.get("effect_class") or "").lower()
    if effect in {"external", "external_write", "destructive", "unknown"}:
        return True
    if row.get("unknown_effect") is True or row.get("awaiting_human") is True:
        return True
    for key in (
        "open_events", "open_event_ids", "pending_attempts", "attempt_ids",
        "grants", "grant_ids", "pending_verifications", "verification_ids",
        "intervention_ids",
    ):
        value = row.get(key)
        if isinstance(value, (list, dict)) and bool(value):
            return True
        if isinstance(value, str) and value.strip():
            return True
    return str(row.get("status") or "") in {"awaiting_human", "paused", "executing"}


def _legacy_closure_state(row: dict[str, Any]) -> str:
    explicit = str(row.get("closure_status") or "")
    if explicit in QUEUE_STATES:
        if has_authority_debt(row):
            return "unresolved"
        if explicit == "verified":
            evidence = any(
                str(row.get(key) or "").strip()
                for key in (
                    "resolution_evidence", "evidence_sha256",
                    "verification_sha256", "terminal_evidence_sha256",
                )
            )
            return "verified" if evidence else "inconclusive"
        return explicit
    status = str(row.get("status") or "unknown")
    if has_authority_debt(row):
        return "unresolved"
    if status in {"rejected", "superseded"}:
        return "superseded"
    if status in {"failed", "timeout", "aborted"}:
        return "unresolved"
    if status == "diagnosed":
        return (
            "inconclusive"
            if row.get("diagnostic_outcome") in {None, "", "inconclusive", "conclusive_with_gaps"}
            else "unresolved"
        )
    if status in {"resolved", "executed", "success", "verified"}:
        checks = row.get("checks")
        checks_verified = isinstance(checks, list) and bool(checks) and all(
            isinstance(check, dict) and check.get("passed") is True for check in checks
        )
        evidence = any(
            str(row.get(key) or "").strip()
            for key in ("resolution_evidence", "evidence_sha256", "verification_sha256")
        )
        if status in {"executed", "success"}:
            evidence = evidence or checks_verified
        return "verified" if evidence else "inconclusive"
    return "inconclusive"


def project_queue(
    rows: list[dict[str, Any]],
    *,
    current: datetime | None = None,
    ttl_days: int = DEFAULT_QUEUE_TTL_DAYS,
    max_retries: int = MAX_RETRY_ATTEMPTS,
) -> dict[str, Any]:
    """Aggregate queue truth without rewriting any legacy row."""
    now = (current or datetime.now(timezone.utc)).astimezone(timezone.utc)
    groups: dict[str, list[dict[str, Any]]] = {}
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        scope = queue_scope(raw)
        fingerprint = queue_fingerprint(raw)
        aggregation_key = hashlib.sha256(
            _canonical_json({"fingerprint": fingerprint, "scope": scope}).encode("utf-8")
        ).hexdigest()
        groups.setdefault(aggregation_key, []).append(raw)

    items: list[dict[str, Any]] = []
    for aggregation_key, occurrences in sorted(groups.items()):
        ordered = sorted(
            occurrences,
            key=lambda row: max(
                _queue_times(row),
                default=datetime.min.replace(tzinfo=timezone.utc),
            ),
        )
        times = [stamp for row in ordered for stamp in _queue_times(row)]
        first = min(times) if times else None
        last = max(times) if times else None
        newest = ordered[-1]
        debt = any(has_authority_debt(row) for row in occurrences)
        states = [_legacy_closure_state(row) for row in ordered]
        state = states[-1]
        if debt:
            state = "unresolved"
        attempts = max(
            [int(row.get("attempts", 0)) for row in occurrences if isinstance(row.get("attempts", 0), int)]
            or [0]
        )
        expired = bool(
            state not in QUEUE_TERMINAL_STATES
            and not debt
            and last is not None
            and now - last >= timedelta(days=max(1, ttl_days))
        )
        if expired:
            state = "expired"
        items.append(
            {
                "aggregation_key": aggregation_key,
                "fingerprint": queue_fingerprint(newest),
                "scope": queue_scope(newest),
                "status": state,
                "first_seen_at": first.isoformat().replace("+00:00", "Z") if first else None,
                "last_seen_at": last.isoformat().replace("+00:00", "Z") if last else None,
                "recurrence_count": len(occurrences),
                "attempts": attempts,
                "max_retries": max(1, int(max_retries)),
                "retry_remaining": max(0, max(1, int(max_retries)) - attempts),
                "retry_allowed": bool(
                    state not in QUEUE_TERMINAL_STATES
                    and not debt
                    and attempts < max(1, int(max_retries))
                ),
                "authority_debt": debt,
                "source_statuses": sorted({str(row.get("status") or "unknown") for row in occurrences}),
                "slugs_sha256": hashlib.sha256(
                    _canonical_json(sorted(str(row.get("slug") or "") for row in occurrences)).encode("utf-8")
                ).hexdigest(),
            }
        )
    counts = {state: 0 for state in sorted(QUEUE_STATES)}
    for item in items:
        counts[item["status"]] += 1
    return {
        "schema": QUEUE_SCHEMA,
        "generated_at": now.isoformat().replace("+00:00", "Z"),
        "counts": counts,
        "items": items,
        "total": len(items),
        "raw_rows": len(rows),
    }


def continuation_queue_entry(
    source: dict[str, Any],
    *,
    project_id: str,
    session_id: str,
    task_instance_id: str,
    continuation: dict[str, Any],
    observed_at: str | None = None,
) -> dict[str, Any]:
    """Create a fresh scoped observation only from a formal continuation.

    Authority, effects, attempts, open events, and terminal state are
    intentionally not copied from the source task.
    """
    if (
        continuation.get("schema") != "sulde-continuation-event-v1"
        or continuation.get("action") not in {"loaded", "acknowledged"}
        or continuation.get("authority_transferred") is not False
        or str(continuation.get("session_id") or "") != session_id
    ):
        raise SelfRepairError("new task binding requires a formal non-authority continuation")
    timestamp = observed_at or now_iso()
    result = {
        "slug": str(source.get("slug") or "continued-task"),
        "source": str(source.get("source") or "continuation"),
        "severity": str(source.get("severity") or "reviewer"),
        "problem_type": str(source.get("problem_type") or source.get("severity") or "unknown"),
        "title": str(source.get("title") or ""),
        "fingerprint": queue_fingerprint(source),
        "project_id": project_id,
        "session_id": session_id,
        "task_instance_id": task_instance_id,
        "continuation_id": hashlib.sha256(
            _canonical_json(
                {
                    "capsule_id": continuation.get("capsule_id"),
                    "project_id": project_id,
                    "session_id": session_id,
                    "task_instance_id": task_instance_id,
                }
            ).encode("utf-8")
        ).hexdigest(),
        "first_seen_at": timestamp,
        "last_seen_at": timestamp,
        "status": "pending",
        "closure_status": "inconclusive",
        "attempts": 0,
    }
    forbidden = {
        "grant", "grants", "grant_ids", "attempt_id", "attempt_ids",
        "pending_attempts", "pending_verifications", "verification_ids",
        "open_event", "open_events", "intervention_ids", "effect_debt",
    }
    if forbidden & result.keys():
        raise SelfRepairError("continuation binding copied authority or effect debt")
    return result


def transition_queue_item(
    item: dict[str, Any], status: str, *, evidence_sha256: str = ""
) -> dict[str, Any]:
    """Apply an idempotent projected terminal transition, failing closed."""
    if status not in QUEUE_STATES:
        raise SelfRepairError(f"invalid queue closure status: {status}")
    current = str(item.get("status") or "inconclusive")
    if current in QUEUE_TERMINAL_STATES:
        if current == status:
            return dict(item)
        raise SelfRepairError(f"terminal queue item is immutable: {current}")
    if status == "verified":
        if item.get("authority_debt"):
            raise SelfRepairError("authority debt blocks verified settlement")
        if not re.fullmatch(r"[0-9a-f]{64}", evidence_sha256):
            raise SelfRepairError("verified settlement requires evidence sha256")
    updated = dict(item)
    updated["status"] = status
    if evidence_sha256:
        updated["terminal_evidence_sha256"] = evidence_sha256
    return updated


def kb_home() -> Path:
    configured = os.environ.get("SULDE_KB_HOME")
    return Path(configured).expanduser() if configured else Path.home() / ".sulde" / "data" / "kb"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def acquire_lock(home: Path):
    digest = hashlib.sha256(str(home.resolve()).encode("utf-8")).hexdigest()[:16]
    path = Path(tempfile.gettempdir()) / f"sulde-self-repair-{digest}.lock"
    handle = path.open("a+", encoding="utf-8")
    try:
        lock_exclusive_nonblocking(handle)
    except BlockingIOError as error:
        handle.close()
        raise SelfRepairError("another self-repair instance is running") from error
    return handle


def atomic_write(path: Path, content: str) -> None:
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


def read_pending(home: Path) -> list[dict[str, Any]]:
    path = home / "self-repair" / "pending.json"
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SelfRepairError(f"invalid pending.json: {error}") from error
    if not isinstance(payload, list) or not all(isinstance(row, dict) for row in payload):
        raise SelfRepairError("invalid pending.json: root must be an array of objects")
    return payload


def write_pending(home: Path, rows: list[dict[str, Any]]) -> None:
    atomic_write(
        home / "self-repair" / "pending.json",
        json.dumps(rows, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())



def record_agent_experience(
    home: Path,
    row: dict[str, Any],
    *,
    outcome: str,
    problem_type: str,
    symptom: str,
    handling: str,
    result: str,
    evidence_material: Any,
) -> None:
    """Persist the mandatory redacted retrospective and verify it by read-back."""
    module = runpy.run_path(str(Path(__file__).with_name("agent-experience.py")))
    scope = queue_scope(row)
    evidence = [
        module["evidence_item"](
            "managed_task", "managed task terminal evidence", evidence_material
        )
    ]
    value = module["build_record"](
        task_id=str(row.get("slug") or "unknown-task"),
        run_id=f"{row.get('slug') or 'unknown'}:{int(row.get('attempts', 0))}",
        project_id=scope["project_id"],
        session_id=scope["session_id"],
        task_instance_id=scope["task_instance_id"],
        problem_type=problem_type,
        symptom=symptom,
        handling=handling,
        outcome=outcome,
        result=result,
        evidence=evidence,
        source_summary="managed self-repair lifecycle",
        occurred_at=str(
            row.get("executed_at")
            or row.get("failed_at")
            or row.get("paused_at")
            or row.get("awaiting_human_at")
            or now_iso()
        ),
        recommended_tests=(
            "tests.test_self_repair",
            "tests.test_supervision_lifecycle_e2e",
        ),
        affected_components=("self-repair", "managed-agent"),
    )
    module["record"](home, value)

def human_approvals(home: Path) -> set[str]:
    path = home / "self-repair" / "approvals.jsonl"
    if not path.is_file():
        return set()
    decisions: dict[str, str] = {}
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            if not raw.strip():
                continue
            row = json.loads(raw)
            if isinstance(row, dict) and row.get("by") == "human" and isinstance(row.get("slug"), str):
                decisions[row["slug"]] = str(row.get("decision"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SelfRepairError(f"invalid approvals.jsonl: {error}") from error
    return {slug for slug, decision in decisions.items() if decision in {"approve", "resume"}}


def latest(directory: Path, pattern: str) -> Path | None:
    paths = sorted(directory.glob(pattern), reverse=True)
    return paths[0] if paths else None


def section(markdown: str, heading_prefix: str) -> str:
    match = re.search(
        rf"^##\s+{re.escape(heading_prefix)}[^\n]*\n(.*?)(?=^##\s+|\Z)",
        markdown,
        re.MULTILINE | re.DOTALL,
    )
    return match.group(1).strip() if match else ""


def candidate(source: str, severity: str, title: str, evidence: str) -> dict[str, str]:
    return {
        "source": source,
        "severity": severity,
        "title": re.sub(r"\s+", " ", title).strip()[:180],
        "evidence": evidence.strip()[:4_000],
    }


def collect_governance_candidates(home: Path) -> list[dict[str, str]]:
    report = latest(home / "governance", "report-*.md")
    if report is None:
        return []
    text = report.read_text(encoding="utf-8", errors="replace")
    rows: list[dict[str, str]] = []
    for line in text.splitlines():
        if not line.lstrip().startswith("|") or "🔴" not in line:
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        metric = cells[0] if cells else "governance red light"
        severity = "golden_red" if "golden" in metric.lower() else "red"
        rows.append(candidate(f"{report}#red-light:{metric}", severity, f"治理红灯：{metric}", line))
    red_team = section(text, "红队质疑")
    if red_team:
        proposal = re.search(r"(?:待审提案[^\n]*|质疑[^\n]*)", red_team)
        title = proposal.group(0) if proposal else red_team.splitlines()[0]
        rows.append(candidate(f"{report}#red-team", "red_team", title, red_team))
    return rows


def collect_graph_candidates(home: Path) -> list[dict[str, str]]:
    report = latest(home / "governance", "graph-audit-*.md")
    if report is None:
        return []
    text = report.read_text(encoding="utf-8", errors="replace")
    unsupported = section(text, "Unsupported")
    rows = []
    for line in unsupported.splitlines():
        match = re.match(r"\|\s*(\d+)\s*\|", line)
        if match:
            edge_id = match.group(1)
            rows.append(candidate(f"{report}#unsupported:{edge_id}", "reviewer", f"graph-audit unsupported 边 {edge_id}", line))
    return rows


def collect_dedup_candidates(home: Path) -> list[dict[str, str]]:
    report = latest(home / "governance", "dedup-*.md")
    if report is None:
        return []
    text = report.read_text(encoding="utf-8", errors="replace")
    rows = []
    for match in re.finditer(r"^##\s+簇\s+(\d+)\s*$\n(.*?)(?=^##\s+|\Z)", text, re.MULTILINE | re.DOTALL):
        cluster_id, body = match.groups()
        if "建议合并" in body or "存疑" in body:
            rows.append(candidate(f"{report}#cluster:{cluster_id}", "reviewer", f"kb-dedup 待审簇 {cluster_id}", body))
    return rows


def collect_heartbeat_candidates(home: Path) -> list[dict[str, str]]:
    report = latest(home / "heartbeat", "observations-*.md")
    if report is None:
        return []
    text = report.read_text(encoding="utf-8", errors="replace")
    rows = []
    for index, block in enumerate(re.split(r"(?=^## Beat )", text, flags=re.MULTILINE)):
        if "三点成面" in block:
            title_line = next((line for line in block.splitlines() if "三点成面" in line), "假说已三点成面")
            rows.append(candidate(f"{report}#three-points:{index}", "reviewer", "心跳假说已三点成面", title_line))
    return rows


def collect_candidates(home: Path) -> list[dict[str, str]]:
    rows = (
        collect_governance_candidates(home)
        + collect_graph_candidates(home)
        + collect_dedup_candidates(home)
        + collect_heartbeat_candidates(home)
    )
    return sorted(rows, key=lambda row: (SEVERITY_ORDER[row["severity"]], row["source"]))


def slug_for(item: dict[str, str]) -> str:
    digest = hashlib.sha256(item["source"].encode("utf-8")).hexdigest()[:10]
    category = {
        "red": "red",
        "golden_red": "golden",
        "red_team": "redteam",
        "reviewer": "review",
    }[item["severity"]]
    return f"self-repair-{category}-{digest}"


def build_draft_prompt(item: dict[str, str], template: str) -> str:
    return f"""你是 Sulde 的 L2 修复任务书起草器。只起草，不执行任何修复。
严格套用下方 BRIEF-TEMPLATE，输出一份完整 Markdown 任务书。必须填写范围、禁止项、完成标准、体量与熔断，并原样保留五段汇报硬性条款。
批准闸：任务书必须声明任何 knowledge 写入、阈值实改或委托发射均须宿主原生人工批准；隔离 worker 不直接集成，验证通过后由监督 Agent 完成 commit / push。不得把命令交给人代跑。
项目根：{REPO_ROOT}
缺陷来源：{item['source']}
严重度：{item['severity']}
标题：{item['title']}
一手证据摘录：
{item['evidence']}

--- BRIEF-TEMPLATE BEGIN ---
{template}
--- BRIEF-TEMPLATE END ---
"""


def run_command_template(command_template: str, prompt: str) -> str:
    try:
        arguments = split_command_template(command_template)
    except ValueError as error:
        raise SelfRepairError(f"invalid --llm-cmd: {error}") from error
    if not arguments:
        raise SelfRepairError("--llm-cmd cannot be empty")
    stdin_prompt: str | None = prompt
    expanded = []
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
            check=False,
        )
    except OSError as error:
        raise SelfRepairError(f"LLM command failed: {error}") from error
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise SelfRepairError(f"LLM command failed (exit {completed.returncode}): {detail[:500]}")
    return completed.stdout


def clean_brief(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```") and text.endswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1]).strip()
    top_heading = re.search(r"^#\s+.+$", text, re.MULTILINE)
    if top_heading is not None:
        text = text[top_heading.start():].strip()
    else:
        separator = re.search(r"^---\s*$", text, re.MULTILINE)
        if separator is not None:
            text = text[separator.end():].strip()

    paragraphs = re.split(r"\n\s*\n", text)
    while paragraphs and re.search(r"[?？]\s*$", paragraphs[-1].strip()):
        paragraphs.pop()
    text = "\n\n".join(paragraphs).strip()

    if not re.match(r"^#\s+\S", text):
        raise SelfRepairError("draft is incomplete; must start with a level-1 heading")
    if not re.search(r"^##\s+完成标准\s*$", text, re.MULTILINE):
        raise SelfRepairError("draft is incomplete; missing: 完成标准")
    missing = [heading for heading in REQUIRED_BRIEF_HEADINGS if not re.search(rf"^##\s+{re.escape(heading)}\s*$", text, re.MULTILINE)]
    if missing or REPORT_CLAUSE not in text:
        detail = ", ".join(missing) if missing else REPORT_CLAUSE
        raise SelfRepairError(f"draft is incomplete; missing: {detail}")
    return text.rstrip() + "\n"


def notify(message: str) -> None:
    if sys.platform != "darwin":
        return
    safe = message.replace("\\", "\\\\").replace('"', '\\"')
    try:
        subprocess.run(
            ["/usr/bin/osascript", "-e", f'display notification "{safe}" with title "Sulde 自主修复"'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError:
        pass


def draft(home: Path, args: argparse.Namespace) -> int:
    candidates = collect_candidates(home)
    pending = read_pending(home)
    registered = {str(row.get("source")) for row in pending}
    available = [item for item in candidates if item["source"] not in registered]
    if getattr(args, "dry_run", False):
        print("SELF-REPAIR DRAFT DRY-RUN: PASS")
        for index, item in enumerate(candidates, 1):
            state = "new" if item["source"] not in registered else "registered"
            print(f"{index}. severity={item['severity']} state={state} source={item['source']} title={item['title']}")
        print(f"candidates={len(candidates)} selectable={len(available)} llm_calls=0 writes=0")
        return 0
    if not available:
        print(f"SELF-REPAIR DRAFT: PASS drafted=0 candidates={len(candidates)}")
        return 0
    if not BRIEF_TEMPLATE.is_file():
        raise SelfRepairError(f"brief template missing: {BRIEF_TEMPLATE}")
    item = available[0]
    slug = slug_for(item)
    brief_path = home / "self-repair" / "drafts" / f"{slug}.brief.md"
    try:
        brief = clean_brief(
            run_command_template(
                args.llm_cmd,
                build_draft_prompt(item, BRIEF_TEMPLATE.read_text(encoding="utf-8")),
            )
        )
    except SelfRepairError as error:
        failed_at = now_iso()
        pending.append(
            {
                "slug": slug,
                "source": item["source"],
                "severity": item["severity"],
                "draft_error_at": failed_at,
                "status": "draft_error",
                "failure_reason": str(error)[:4_000],
            }
        )
        write_pending(home, pending)
        notify(f"修复提案 {slug} 起草失败,未生成任务书")
        print(f"SELF-REPAIR DRAFT: FAIL drafted=0 slug={slug} status=draft_error", file=sys.stderr)
        print(f"ERROR self-repair draft: {error}", file=sys.stderr)
        return 1
    atomic_write(brief_path, brief)
    pending.append(
        {
            "slug": slug,
            "source": item["source"],
            "severity": item["severity"],
            "brief_path": str(brief_path),
            "drafted_at": now_iso(),
            "status": "pending",
        }
    )
    write_pending(home, pending)
    notify("已起草 1 份修复提案待批")
    print(f"SELF-REPAIR DRAFT: PASS drafted=1 slug={slug} severity={item['severity']}")
    print(f"brief: {brief_path}")
    return 0


def require_human_terminal() -> None:
    if "SULDE_SELF_REPAIR_AUTO" in os.environ:
        raise SelfRepairError(
            "approval gate refused: the scheduler cannot supply human authority; "
            "a supervising Agent must present a host-native Allow/Deny decision and "
            "perform the approved action outside SULDE_SELF_REPAIR_AUTO"
        )


RETRY_FAILED = False


def decide(
    home: Path,
    slug: str,
    decision: str,
    reason: str | None,
    task_type: str = "implementation",
) -> int:
    require_human_terminal()
    pending = read_pending(home)
    matches = [row for row in pending if row.get("slug") == slug]
    if len(matches) != 1:
        raise SelfRepairError(f"expected exactly one pending entry for slug={slug}; found={len(matches)}")
    row = matches[0]
    status = row.get("status")
    if status == "failed":
        # failed 项不自动复活,但允许人在排查后显式重试:--approve --retry-failed
        # (仍走同一道人工闸,且 attempts 累加以便发现反复失败的项)
        if not RETRY_FAILED:
            raise SelfRepairError(
                f"entry failed previously: slug={slug}; inspect worktree then rerun with --retry-failed"
            )
        attempts = int(row.get("attempts", 1))
        if attempts >= MAX_RETRY_ATTEMPTS:
            raise SelfRepairError(
                f"retry budget exhausted: slug={slug} attempts={attempts} max={MAX_RETRY_ATTEMPTS}"
            )
        # Execution, not approval, consumes the next attempt.
        row["attempts"] = attempts
    elif status != "pending":
        raise SelfRepairError(f"entry is not pending: slug={slug} status={status}")
    at = now_iso()
    row["status"] = "approved" if decision == "approve" else "rejected"
    if decision == "approve":
        row["task_type"] = task_type
    row["decided_at"] = at
    if reason:
        row["reason"] = reason
    write_pending(home, pending)
    append_jsonl(
        home / "self-repair" / "approvals.jsonl",
        {"slug": slug, "decision": decision, "by": "human", "at": at, "reason": reason or "", "task_type": task_type if decision == "approve" else None},
    )
    print(f"SELF-REPAIR DECISION: PASS slug={slug} decision={decision} by=human")
    return 0


def record_diagnostic_outcome(home: Path, slug: str, outcome: str, reason: str) -> int:
    """Persist a reviewed diagnostic conclusion without calling it a repair success."""
    require_human_terminal()
    if outcome not in DIAGNOSTIC_OUTCOMES:
        raise SelfRepairError(f"invalid diagnostic outcome: {outcome}")
    pending = read_pending(home)
    matches = [row for row in pending if row.get("slug") == slug]
    if len(matches) != 1:
        raise SelfRepairError(f"expected exactly one pending entry for slug={slug}; found={len(matches)}")
    row = matches[0]
    if row.get("task_type") != "diagnostic":
        brief = Path(str(row.get("brief_path") or ""))
        brief_text = brief.read_text(encoding="utf-8", errors="replace") if brief.is_file() else ""
        if not re.search(r"本任务为\*\*诊断型\*\*|任务类型\s*[:：]\s*diagnostic", brief_text):
            raise SelfRepairError(f"entry is not diagnostic: slug={slug}")
        row["task_type"] = "diagnostic"
    if row.get("status") not in {"failed", "executing"}:
        raise SelfRepairError(f"diagnostic entry is not reviewable: slug={slug} status={row.get('status')}")
    report = Path(str(row.get("worktree") or "")) / ".codex-agent" / f"{slug}.last.md"
    if not report.is_file():
        raise SelfRepairError(f"diagnostic report missing: {report}")
    report_text = report.read_text(encoding="utf-8", errors="replace")
    headings = ("结果", "过程", "遇到的问题", "解决方式", "遗留风险与建议")
    missing = [heading for heading in headings if not re.search(rf"^##\s+{re.escape(heading)}\s*$", report_text, re.MULTILINE)]
    if missing:
        raise SelfRepairError("diagnostic report incomplete; missing: " + ", ".join(missing))
    if outcome == "conclusive_with_gaps" and not re.search(r"证据(?:不足|不可得|缺口)|无法.*(?:归因|判定)", report_text):
        raise SelfRepairError("conclusive_with_gaps requires an explicit evidence gap in the report")
    at = now_iso()
    row["status"] = "diagnosed"
    row["diagnostic_outcome"] = outcome
    row["diagnostic_reason"] = reason[:4_000]
    row["diagnosed_at"] = at
    write_pending(home, pending)
    append_jsonl(home / "self-repair" / "executed.jsonl", {
        "slug": slug, "status": "diagnosed", "diagnostic_outcome": outcome,
        "reason": reason[:4_000], "at": at, "report": str(report), "by": "human",
    })
    print(f"SELF-REPAIR DIAGNOSTIC: PASS slug={slug} outcome={outcome} by=human")
    return 0


def record_resolution(home: Path, slug: str, evidence: str) -> int:
    """Close a proposal when independently verified mainline work supersedes it."""
    require_human_terminal()
    if not evidence.strip():
        raise SelfRepairError("resolution evidence must not be empty")
    pending = read_pending(home)
    matches = [row for row in pending if row.get("slug") == slug]
    if len(matches) != 1:
        raise SelfRepairError(f"expected exactly one pending entry for slug={slug}; found={len(matches)}")
    row = matches[0]
    if row.get("status") not in {"approved", "failed", "executed", "diagnosed"}:
        raise SelfRepairError(f"entry is not resolvable: slug={slug} status={row.get('status')}")
    at = now_iso()
    row["status"] = "resolved"
    row["resolved_at"] = at
    row["resolution_evidence"] = evidence[:4_000]
    write_pending(home, pending)
    append_jsonl(home / "self-repair" / "executed.jsonl", {
        "slug": slug, "status": "resolved", "at": at,
        "evidence": evidence[:4_000], "by": "human",
    })
    print(f"SELF-REPAIR RESOLUTION: PASS slug={slug} by=human")
    return 0


def resume_guarded(home: Path, slug: str, reason: str) -> int:
    """Human-resume a semantic pause or a fully adjudicated effect intervention."""
    require_human_terminal()
    pending = read_pending(home)
    matches = [row for row in pending if row.get("slug") == slug]
    if len(matches) != 1:
        raise SelfRepairError(f"expected exactly one pending entry for slug={slug}; found={len(matches)}")
    row = matches[0]
    current_status = str(row.get("status") or "")
    if current_status not in {"paused", "awaiting_human"}:
        raise SelfRepairError(
            f"entry is not resumable: slug={slug} status={current_status}"
        )
    worktree = Path(str(row.get("worktree") or ""))
    contract_path = worktree / ".codex-agent" / f"{slug}.intent.json"
    resume_context: dict[str, Any] | None = None
    if current_status == "paused":
        try:
            contract = load_contract(contract_path)
            if contract["status"] == "paused":
                runtime = contract.get("runtime", {})
                resume_provider = ""
                resume_session = ""
                if runtime.get("pause_scope") == "lane":
                    paused_lanes = [
                        lane
                        for lane in runtime.get("task_lanes", [])
                        if isinstance(lane, dict)
                        and lane.get("task_epoch") == contract.get("task_epoch")
                        and lane.get("state") == "paused"
                    ]
                    managed_session = f"managed:{contract['intent_id']}"
                    matching = [
                        lane
                        for lane in paused_lanes
                        if lane.get("session_id") == managed_session
                    ]
                    selected = matching if len(matching) == 1 else paused_lanes
                    if len(selected) != 1:
                        raise SelfRepairError(
                            "managed repair pause does not identify exactly one task lane"
                        )
                    resume_provider = str(selected[0].get("provider") or "unknown")
                    resume_session = str(selected[0].get("session_id") or "")
                resume_contract(
                    contract_path,
                    reason,
                    actor="human",
                    provider=resume_provider,
                    session_id=resume_session,
                )
            elif contract["status"] != "active":
                raise SelfRepairError(f"intent contract is not resumable: {contract['status']}")
        except IntentGuardianError as error:
            raise SelfRepairError(str(error)) from error
    else:
        try:
            projection = load_intervention_projection(contract_path)
        except (InterventionError, OSError, UnicodeError) as error:
            raise SelfRepairError(f"cannot replay intervention truth: {error}") from error
        selected_ids = {
            str(value) for value in row.get("intervention_ids", []) if str(value)
        }
        task_interventions = [
            item
            for item in projection["interventions"].values()
            if projection["attempts"].get(item.get("attempt_id"), {}).get("task_id")
            in {"", f"l3:{slug}"}
        ]
        if selected_ids:
            selected = [
                item
                for item in task_interventions
                if item.get("intervention_id") in selected_ids
            ]
        else:
            latest_by_attempt: dict[str, dict[str, Any]] = {}
            for item in task_interventions:
                latest_by_attempt[str(item.get("attempt_id") or "")] = item
            selected = list(latest_by_attempt.values())
        if not selected:
            raise SelfRepairError(f"no intervention truth found for slug={slug}")
        effective_ids = {
            str(item["intervention_id"])
            for item in selected
        }
        unresolved = [
            str(item["intervention_id"])
            for item in selected
            if item.get("status") != "resolved"
        ]
        if unresolved:
            raise SelfRepairError(
                "resolve every intervention first with intent-guardian.py "
                f"intervention-resolve; unresolved={','.join(unresolved)}"
            )
        decisions = {str(item.get("decision") or "") for item in selected}
        at = now_iso()
        if "abort" in decisions:
            row["status"] = "aborted"
            row["aborted_at"] = at
            row["abort_reason"] = reason[:2_000]
            write_pending(home, pending)
            append_jsonl(
                home / "self-repair" / "executed.jsonl",
                {
                    "slug": slug,
                    "status": "aborted",
                    "at": at,
                    "reason": reason[:2_000],
                    "by": "human",
                    "intervention_ids": sorted(effective_ids),
                },
            )
            print(f"SELF-REPAIR INTERVENTION: ABORTED slug={slug} by=human")
            return 0
        if "confirmed_failed" in decisions:
            row["status"] = "failed"
            row["failed_at"] = at
            row["failure_reason"] = "human confirmed the external effect failed: " + reason[:2_000]
            write_pending(home, pending)
            append_jsonl(
                home / "self-repair" / "executed.jsonl",
                {
                    "slug": slug,
                    "status": "failed",
                    "at": at,
                    "reason": row["failure_reason"],
                    "by": "human",
                    "intervention_ids": sorted(effective_ids),
                },
            )
            print(f"SELF-REPAIR INTERVENTION: CONFIRMED_FAILED slug={slug} by=human")
            return 0
        resumable = {
            "human_attested_success",
            "reprobe_authorized",
            "retry_authorized",
            "system_verified",
        }
        unsupported = decisions - resumable
        if unsupported:
            raise SelfRepairError(
                "intervention decision is not resumable: " + ",".join(sorted(unsupported))
            )
        context_rows = []
        for item in selected:
            attempt = projection["attempts"][item["attempt_id"]]
            context_rows.append(
                {
                    "intervention_id": item["intervention_id"],
                    "attempt_id": item["attempt_id"],
                    "decision": item["decision"],
                    "capability": attempt["capability"],
                    "provider": attempt["provider"],
                    "target_sha256": attempt["target_sha256"],
                    "evidence_sha256": hashlib.sha256(
                        str(item.get("evidence") or "").encode("utf-8", errors="replace")
                    ).hexdigest(),
                }
            )
        resume_context = {
            "schema": "sulde-intervention-resume-context-v1",
            "slug": slug,
            "created_at": at,
            "reason": reason[:2_000],
            "interventions": context_rows,
        }
        resume_path = worktree / ".codex-agent" / f"{slug}.resume-context.json"
        resume_payload = json.dumps(
            resume_context,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n"
        atomic_write(
            resume_path,
            resume_payload,
        )
        row["resume_context"] = str(resume_path)
        row["resume_context_sha256"] = hashlib.sha256(
            resume_payload.encode("utf-8")
        ).hexdigest()
        row["intervention_resume"] = True
    row["status"] = "approved"
    row["guardian_resume"] = True
    row["guardian_resume_reason"] = reason[:2_000]
    row["guardian_resumed_at"] = now_iso()
    write_pending(home, pending)
    append_jsonl(
        home / "self-repair" / "approvals.jsonl",
        {
            "slug": slug,
            "decision": "resume",
            "by": "human",
            "at": row["guardian_resumed_at"],
            "reason": reason[:2_000],
            "intervention_resume": current_status == "awaiting_human",
            "intervention_decisions": (
                sorted(
                    str(item.get("decision") or "")
                    for item in (resume_context or {}).get("interventions", [])
                )
                if resume_context
                else []
            ),
        },
    )
    print(f"SELF-REPAIR GUARDIAN: RESUMED slug={slug} by=human contract={contract_path}")
    return 0


def project_root() -> Path:
    configured = os.environ.get("SULDE_SELF_REPAIR_PROJECT_ROOT")
    return Path(configured).expanduser().resolve() if configured else REPO_ROOT


def agent_scripts() -> Path:
    configured = os.environ.get("SULDE_AGENT_RUNTIME_DIR")
    return Path(configured).expanduser() if configured else Path(__file__).resolve().parent


def command_ok(arguments: list[str], cwd: Path) -> tuple[bool, str]:
    try:
        completed = subprocess.run(
            arguments,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError as error:
        return False, f"{type(error).__name__}: {error}"
    output = (completed.stdout + "\n" + completed.stderr).strip()
    return completed.returncode == 0, f"exit={completed.returncode} {output[-1500:]}"


def launch_detached(arguments: list[str], cwd: Path, log_path: Path) -> tuple[bool, str]:
    """Start the agent without waiting on inherited pipes; the status file is truth."""
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handle = log_path.open("ab")
        detached_options: dict[str, Any] = {}
        if os.name == "nt":
            detached_options["creationflags"] = (
                getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
                | getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
            )
        else:
            detached_options["start_new_session"] = True
        process = subprocess.Popen(
            arguments,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=handle,
            stderr=subprocess.STDOUT,
            **detached_options,
        )
        handle.close()
    except OSError as error:
        return False, f"{type(error).__name__}: {error}"
    return True, f"pid={process.pid} log={log_path}"


def git_command(arguments: list[str], root: Path) -> tuple[int, str]:
    try:
        completed = subprocess.run(
            ["git", *arguments],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError as error:
        raise SelfRepairError(f"git command failed: {error}") from error
    output = (completed.stdout + "\n" + completed.stderr).strip()
    return completed.returncode, output


def validate_slug(slug: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", slug):
        raise SelfRepairError(f"invalid slug: {slug}")


def worktree_identity(root: Path, slug: str) -> tuple[Path, str]:
    validate_slug(slug)
    return root / ".worktrees" / f"self-repair-{slug}", f"self-repair/{slug}"


def registered_worktrees(root: Path) -> set[Path]:
    returncode, output = git_command(["worktree", "list", "--porcelain"], root)
    if returncode != 0:
        raise SelfRepairError(f"cannot inspect git worktrees (exit {returncode}): {output[:500]}")
    return {
        Path(line.removeprefix("worktree ")).resolve()
        for line in output.splitlines()
        if line.startswith("worktree ")
    }


def branch_exists(root: Path, branch: str) -> bool:
    returncode, output = git_command(["show-ref", "--verify", "--quiet", f"refs/heads/{branch}"], root)
    if returncode not in (0, 1):
        raise SelfRepairError(f"cannot inspect branch {branch} (exit {returncode}): {output[:500]}")
    return returncode == 0


def ensure_worktree_available(root: Path, slug: str) -> tuple[Path, str]:
    worktree, branch = worktree_identity(root, slug)
    path_collision = worktree.exists() or worktree.resolve() in registered_worktrees(root)
    branch_collision = branch_exists(root, branch)
    if path_collision or branch_collision:
        collisions = []
        if path_collision:
            collisions.append(f"worktree={worktree}")
        if branch_collision:
            collisions.append(f"branch={branch}")
        raise SelfRepairError(
            f"self-repair target already exists ({', '.join(collisions)}); "
            f"run --cleanup {slug} after reviewing it"
        )
    return worktree, branch


def create_worktree(root: Path, worktree: Path, branch: str) -> None:
    worktree.parent.mkdir(parents=True, exist_ok=True)
    returncode, output = git_command(
        ["worktree", "add", str(worktree), "-b", branch, "main"],
        root,
    )
    if returncode != 0:
        raise SelfRepairError(f"cannot create worktree (exit {returncode}): {output[:1000]}")


def prepare_acceptance_root(worktree: Path) -> Path:
    state_dir = worktree / ".codex-agent"
    if state_dir.is_symlink():
        raise SelfRepairError(f"acceptance state directory must not be a symlink: {state_dir}")
    state_dir.mkdir(parents=True, exist_ok=True)
    expected = worktree.resolve() / ".codex-agent"
    if state_dir.resolve() != expected:
        raise SelfRepairError(f"acceptance state directory escaped worktree: {state_dir}")
    return worktree


def wait_for_status(path: Path, timeout: float, interval: float) -> tuple[str, str]:
    deadline = time.monotonic() + timeout
    while time.monotonic() <= deadline:
        if path.is_file():
            content = path.read_text(encoding="utf-8", errors="replace").strip()
            match = re.search(
                r"(?:^|\s)status=(success|failed|timeout|paused|awaiting_human)(?:\s|$)",
                content,
            )
            if match and match.group(1) in TERMINAL_STATUSES:
                return match.group(1), content
        time.sleep(interval)
    return "timeout", f"status poll timed out after {timeout:g}s"


def execute_one(home: Path, row: dict[str, Any], args: argparse.Namespace) -> str:
    slug = str(row["slug"])
    root = project_root()
    scripts = agent_scripts()
    worktree, branch = worktree_identity(root, slug)
    row["worktree"] = str(worktree)
    row["branch"] = branch
    row["verify_scope"] = "worktree"
    row["verify_root"] = str(worktree)
    source_brief = Path(str(row["brief_path"]))
    if not source_brief.is_file():
        return mark_failed(home, row, f"brief missing: {source_brief}")
    guardian_resume = bool(row.get("guardian_resume"))
    persisted_execution = row.get("status") == "executing" and not guardian_resume
    reusing_worktree = (persisted_execution or guardian_resume) and worktree.is_dir()
    try:
        if not reusing_worktree:
            create_worktree(root, worktree, branch)
        acceptance_root = prepare_acceptance_root(worktree)
    except SelfRepairError as error:
        return mark_failed(home, row, str(error))

    row["worktree"] = str(acceptance_root)
    row["verify_root"] = str(acceptance_root)

    launch_brief = acceptance_root / ".codex-agent" / f"{slug}.md"
    brief_content = source_brief.read_text(encoding="utf-8")
    if launch_brief.exists() and launch_brief.read_text(encoding="utf-8") != brief_content:
        return mark_failed(home, row, f"launch brief collision: {launch_brief}")
    atomic_write(launch_brief, brief_content)
    row["status"] = "executing"
    row.pop("guardian_resume", None)
    row["attempts"] = int(row.get("attempts", 0)) + (0 if persisted_execution else 1)
    row["execution_started_at"] = now_iso()
    write_pending(home, read_pending_with_replacement(home, row))

    status_path = acceptance_root / ".codex-agent" / f"{slug}.status"
    resume_context_path = Path(str(row.get("resume_context") or ""))
    resume_arguments: list[str] = []
    intervention_resume_for_launch = bool(
        guardian_resume and row.get("intervention_resume")
    )
    if intervention_resume_for_launch:
        expected_resume_digest = str(row.get("resume_context_sha256") or "")
        if not resume_context_path.is_file() or not re.fullmatch(
            r"[0-9a-f]{64}", expected_resume_digest
        ):
            return mark_failed(home, row, "intervention resume context is missing or unbound")
        actual_resume_digest = hashlib.sha256(resume_context_path.read_bytes()).hexdigest()
        if actual_resume_digest != expected_resume_digest:
            return mark_failed(home, row, "intervention resume context digest changed")
        resume_arguments = ["--resume-context", str(resume_context_path)]
    if guardian_resume:
        if status_path.is_file():
            round_number = 1
            while status_path.with_name(f"{slug}.resume{round_number}.status").exists():
                round_number += 1
            status_path.replace(status_path.with_name(f"{slug}.resume{round_number}.status"))
        launched, launch_output = launch_detached(
            [
                sys.executable,
                str(scripts / "agent-runtime.py"),
                "run",
                str(acceptance_root),
                slug,
                str(launch_brief),
                "--effort",
                args.effort,
                "--guardian-mode",
                getattr(args, "guardian_mode", "shadow"),
                *resume_arguments,
                *(["--semantic-critic"] if getattr(args, "guardian_critic", False) else []),
            ],
            acceptance_root,
            acceptance_root / ".codex-agent" / f"{slug}.launch.log",
        )
    elif persisted_execution:
        launched, launch_output = True, "resumed from persisted executing state"
    else:
        launched, launch_output = launch_detached(
            [
                sys.executable,
                str(scripts / "agent-runtime.py"),
                "run",
                str(acceptance_root),
                slug,
                str(launch_brief),
                "--effort",
                args.effort,
                "--guardian-mode",
                getattr(args, "guardian_mode", "shadow"),
                *(["--semantic-critic"] if getattr(args, "guardian_critic", False) else []),
            ],
            acceptance_root,
            acceptance_root / ".codex-agent" / f"{slug}.launch.log",
        )
    if launched and intervention_resume_for_launch:
        row["intervention_resume"] = False
        row["resume_context_consumed_at"] = now_iso()
        write_pending(home, read_pending_with_replacement(home, row))
    status, status_output = wait_for_status(
        status_path,
        args.status_timeout,
        args.poll_interval,
    )
    if status == "paused":
        return mark_guardian_paused(home, row, status_output)
    if status == "awaiting_human":
        return mark_awaiting_human(home, row, status_output)
    if not launched or status != "success":
        return mark_failed(home, row, f"launch={launch_output}; terminal={status} {status_output}")

    test_command = (
        [sys.executable, "-m", "pytest", "-q"]
        if importlib.util.find_spec("pytest") is not None
        else [sys.executable, "-m", "unittest", "discover", "-s", "tests"]
    )
    checks = [
        [
            sys.executable,
            str(scripts / "agent-runtime.py"),
            "verify",
            str(acceptance_root),
            slug,
            "--allowed-paths",
            ".*",
        ],
        test_command,
        [sys.executable, str(acceptance_root / "scripts" / "kb" / "mem-golden.py"), "--json"],
    ]
    evidence = []
    for command in checks:
        passed, output = command_ok(command, acceptance_root)
        evidence.append({"command": command, "passed": passed, "output": output})
        if not passed:
            return mark_failed(home, row, f"acceptance failed: {output}", evidence)

    completed_at = now_iso()
    row["status"] = "executed"
    row["executed_at"] = completed_at
    row["verification_sha256"] = hashlib.sha256(
        _canonical_json(evidence).encode("utf-8")
    ).hexdigest()
    write_pending(home, read_pending_with_replacement(home, row))
    append_jsonl(
        home / "self-repair" / "executed.jsonl",
        {
            "slug": slug,
            "status": "success",
            "at": completed_at,
            "verify_scope": "worktree",
            "verify_root": str(acceptance_root),
            "checks": evidence,
        },
    )
    message = f"修复 {slug} 完成,分支 {branch} 待人审(worktree: {acceptance_root})"
    record_agent_experience(
        home,
        row,
        outcome="verified",
        problem_type="none",
        symptom="no issue observed",
        handling="completed managed execution and scoped verification",
        result="all managed acceptance checks passed",
        evidence_material=[
            {
                "command_sha256": hashlib.sha256(
                    _canonical_json(item.get("command", [])).encode("utf-8")
                ).hexdigest(),
                "passed": item.get("passed") is True,
                "output_sha256": hashlib.sha256(
                    str(item.get("output") or "").encode("utf-8", errors="replace")
                ).hexdigest(),
            }
            for item in evidence
        ],
    )
    notify(message)
    print(f"EXECUTED slug={slug} status=success checks=3 attempts=1 branch={branch} worktree={acceptance_root} verify_scope=worktree verify_root={acceptance_root}")
    return "success"


def read_pending_with_replacement(home: Path, changed: dict[str, Any]) -> list[dict[str, Any]]:
    rows = read_pending(home)
    return [changed if row.get("slug") == changed.get("slug") else row for row in rows]


def mark_failed(home: Path, row: dict[str, Any], reason: str, checks: list[dict[str, Any]] | None = None) -> str:
    row["status"] = "failed"
    row["failed_at"] = now_iso()
    row["failure_reason"] = reason[:4_000]
    row.setdefault("attempts", 1)
    write_pending(home, read_pending_with_replacement(home, row))
    append_jsonl(
        home / "self-repair" / "executed.jsonl",
        {
            "slug": row.get("slug"),
            "status": "failed",
            "at": row["failed_at"],
            "reason": reason[:4_000],
            "verify_scope": row.get("verify_scope", "main"),
            "verify_root": row.get("verify_root", str(project_root())),
            "checks": checks or [],
        },
    )
    record_agent_experience(
        home,
        row,
        outcome="unresolved",
        problem_type="managed_execution_failure",
        symptom=reason,
        handling="preserved task state and evidence for bounded human-reviewed retry",
        result="managed task did not verify",
        evidence_material={
            "reason_sha256": hashlib.sha256(reason.encode("utf-8", errors="replace")).hexdigest(),
            "check_count": len(checks or []),
        },
    )
    worktree = row.get("worktree", "unknown")
    notify(f"修复 {row.get('slug')} 失败,worktree 已保留供排查: {worktree}")
    print(f"EXECUTED slug={row.get('slug')} status=failed attempts=1 worktree={worktree} reason={reason[:300]}")
    return "failed"


def mark_guardian_paused(home: Path, row: dict[str, Any], reason: str) -> str:
    row["status"] = "paused"
    row["paused_at"] = now_iso()
    row["pause_reason"] = reason[:4_000]
    write_pending(home, read_pending_with_replacement(home, row))
    append_jsonl(
        home / "self-repair" / "executed.jsonl",
        {
            "slug": row.get("slug"),
            "status": "paused",
            "at": row["paused_at"],
            "reason": reason[:4_000],
            "worktree": row.get("worktree"),
            "by": "intent-guardian",
        },
    )
    record_agent_experience(
        home,
        row,
        outcome="unresolved",
        problem_type="intent_pause",
        symptom=reason,
        handling="preserved the paused lane without widening authority",
        result="human review remains required",
        evidence_material={
            "pause_reason_sha256": hashlib.sha256(
                reason.encode("utf-8", errors="replace")
            ).hexdigest()
        },
    )
    notify(f"修复 {row.get('slug')} 因意图冲突暂停，worktree 已保留")
    print(f"EXECUTED slug={row.get('slug')} status=paused worktree={row.get('worktree')} reason={reason[:300]}")
    return "paused"


def mark_awaiting_human(home: Path, row: dict[str, Any], reason: str) -> str:
    row["status"] = "awaiting_human"
    row["awaiting_human_at"] = now_iso()
    row["intervention_reason"] = reason[:4_000]
    worktree = Path(str(row.get("worktree") or ""))
    contract_path = worktree / ".codex-agent" / f"{row.get('slug')}.intent.json"
    intervention_ids: list[str] = []
    try:
        projection = load_intervention_projection(contract_path)
        intervention_ids = sorted(
            str(item["intervention_id"])
            for item in projection["interventions"].values()
            if item.get("status") in {"open", "acknowledged"}
        )
    except (InterventionError, OSError, UnicodeError):
        pass
    row["intervention_ids"] = intervention_ids
    write_pending(home, read_pending_with_replacement(home, row))
    append_jsonl(
        home / "self-repair" / "executed.jsonl",
        {
            "slug": row.get("slug"),
            "status": "awaiting_human",
            "at": row["awaiting_human_at"],
            "reason": reason[:4_000],
            "worktree": row.get("worktree"),
            "intervention_ids": intervention_ids,
            "by": "effect-intervention",
        },
    )
    record_agent_experience(
        home,
        row,
        outcome="unresolved",
        problem_type="unknown_external_effect",
        symptom=reason,
        handling="kept effect debt and routed the task to the human gate",
        result="no success settlement was produced",
        evidence_material={
            "intervention_count": len(intervention_ids),
            "interventions_sha256": hashlib.sha256(
                _canonical_json(intervention_ids).encode("utf-8")
            ).hexdigest(),
        },
    )
    notify(
        f"修复 {row.get('slug')} 有无法证明的外部操作，等待监督 Agent 重探测或发起原生裁决；"
        f"worktree 已保留，intervention={','.join(intervention_ids) or 'unknown'}"
    )
    print(
        f"EXECUTED slug={row.get('slug')} status=awaiting_human "
        f"worktree={row.get('worktree')} interventions={','.join(intervention_ids) or 'unknown'}"
    )
    return "awaiting_human"


def execute(home: Path, args: argparse.Namespace) -> int:
    require_human_terminal()
    pending = read_pending(home)
    approval_records = human_approvals(home)
    approved = [
        row
        for row in pending
        if row.get("status") in {"approved", "executing"} and row.get("slug") in approval_records
    ]
    unproven = [
        str(row.get("slug"))
        for row in pending
        if row.get("status") == "approved" and row.get("slug") not in approval_records
    ]
    if unproven:
        print("WARN skipped approved entries without human approval record: " + ",".join(unproven))
    root = project_root()
    if getattr(args, "dry_run", False):
        print("SELF-REPAIR EXECUTE DRY-RUN: PASS")
        for row in approved:
            worktree, branch = worktree_identity(root, str(row["slug"]))
            print(
                f"would_create worktree={worktree} branch={branch} "
                f"launch_project_root={worktree} verify_project_root={worktree} verify_scope=worktree"
            )
        print(f"approved={len(approved)} creates=0 launches=0 writes=0")
        return 0
    for row in approved:
        if row.get("status") == "approved" and not row.get("guardian_resume"):
            ensure_worktree_available(root, str(row["slug"]))
    failures = 0
    pauses = 0
    interventions = 0
    for row in approved:
        outcome = execute_one(home, row, args)
        if outcome == "failed":
            failures += 1
        elif outcome == "paused":
            pauses += 1
        elif outcome == "awaiting_human":
            interventions += 1
    skipped = len(pending) - len(approved)
    print(
        f"SELF-REPAIR EXECUTE: {'INCOMPLETE' if failures or pauses or interventions else 'PASS'} "
        f"approved={len(approved)} skipped={skipped} failed={failures} "
        f"paused={pauses} awaiting_human={interventions}"
    )
    return 1 if failures or pauses or interventions else 0


def cleanup(slug: str, force: bool, home: Path | None = None) -> int:
    require_human_terminal()
    state_home = home or kb_home()
    matches = [row for row in read_pending(state_home) if row.get("slug") == slug]
    active_statuses = {"approved", "executing", "paused", "awaiting_human"}
    if any(str(row.get("status") or "") in active_statuses for row in matches):
        statuses = ",".join(sorted({str(row.get("status") or "unknown") for row in matches}))
        raise SelfRepairError(
            f"cleanup refused: L3 task still requires execution or adjudication; status={statuses}"
        )
    root = project_root()
    worktree, branch = worktree_identity(root, slug)
    is_registered = worktree.resolve() in registered_worktrees(root)
    has_branch = branch_exists(root, branch)
    if not is_registered and not worktree.exists() and not has_branch:
        raise SelfRepairError(f"nothing to clean for slug={slug}")

    if has_branch and not force:
        returncode, output = git_command(["merge-base", "--is-ancestor", branch, "main"], root)
        if returncode == 1:
            raise SelfRepairError(
                f"cleanup refused: branch {branch} has commits not merged into main; review them or add --force"
            )
        if returncode != 0:
            raise SelfRepairError(f"cannot compare {branch} with main (exit {returncode}): {output[:500]}")

    archived: Path | None = None
    contract_path = worktree / ".codex-agent" / f"{slug}.intent.json"
    intervention_log = contract_path.with_name(f"{slug}.intent.interventions.jsonl")
    if intervention_log.is_file():
        try:
            projection = load_intervention_projection(contract_path)
            blocked = readiness_blocking_effect_attempts(projection)
            if blocked:
                identifiers = ",".join(
                    str(row.get("attempt_id") or "unknown") for row in blocked
                )
                raise SelfRepairError(
                    "cleanup refused: external-effect truth is unresolved; "
                    f"adjudicate/resume or abort first; attempts={identifiers}"
                )
            archived = archive_intervention_store(
                contract_path,
                state_home / "interventions" / "archive",
                slug=slug,
            )
        except InterventionError as error:
            raise SelfRepairError(
                f"cleanup refused: cannot archive intervention truth: {error}"
            ) from error

    if is_registered or worktree.exists():
        arguments = ["worktree", "remove"]
        if force:
            arguments.append("--force")
        arguments.append(str(worktree))
        returncode, output = git_command(arguments, root)
        if returncode != 0:
            raise SelfRepairError(f"cannot remove worktree (exit {returncode}): {output[:1000]}")
    if has_branch:
        returncode, output = git_command(["branch", "-D" if force else "-d", branch], root)
        if returncode != 0:
            raise SelfRepairError(f"cannot delete branch (exit {returncode}): {output[:1000]}")
    print(
        f"SELF-REPAIR CLEANUP: PASS slug={slug} branch={branch} "
        f"worktree={worktree} force={str(force).lower()} "
        f"intervention_archive={archived or 'none'}"
    )
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--draft", action="store_true")
    actions.add_argument("--approve", metavar="SLUG")
    actions.add_argument("--reject", nargs=2, metavar=("SLUG", "REASON"))
    actions.add_argument("--record-diagnostic", nargs=3, metavar=("SLUG", "OUTCOME", "REASON"))
    actions.add_argument("--resolve", nargs=2, metavar=("SLUG", "EVIDENCE"))
    actions.add_argument("--resume-guarded", nargs=2, metavar=("SLUG", "REASON"))
    actions.add_argument("--execute", action="store_true")
    parser.add_argument("--task-type", choices=sorted(TASK_TYPES), default="implementation", help="with --approve: classify the approved task")
    parser.add_argument(
        "--retry-failed",
        action="store_true",
        help="allow re-approving a previously failed entry (human must inspect the worktree first)",
    )
    actions.add_argument("--cleanup", metavar="SLUG")
    parser.add_argument("--force", action="store_true", help="with --cleanup: remove a dirty worktree and unmerged branch")
    parser.add_argument("--dry-run", action="store_true", help="with --draft/--execute: inspect without calls, writes, or worktree creation")
    parser.add_argument("--llm-cmd", default=DEFAULT_LLM_CMD)
    parser.add_argument("--effort", choices=("low", "medium", "high"), default="high")
    parser.add_argument("--guardian-mode", choices=("off", "shadow", "enforce"), default="shadow")
    parser.add_argument(
        "--guardian-critic",
        action="store_true",
        help="allow extra read-only provider calls over changed artifacts for semantic drift review",
    )
    parser.add_argument("--status-timeout", type=float, default=1_200)
    parser.add_argument("--poll-interval", type=float, default=2)
    args = parser.parse_args()
    if args.dry_run and not (args.draft or args.execute):
        parser.error("--dry-run is only valid with --draft or --execute")
    if args.force and not args.cleanup:
        parser.error("--force is only valid with --cleanup")
    if args.status_timeout <= 0 or args.poll_interval <= 0:
        parser.error("timeouts must be greater than zero")
    return args


def main() -> int:
    args = parse_args()
    home = kb_home()
    lock_handle = None
    try:
        if not args.dry_run:
            lock_handle = acquire_lock(home)
        if args.draft:
            return draft(home, args)
        global RETRY_FAILED
        RETRY_FAILED = bool(getattr(args, "retry_failed", False))
        if args.approve:
            return decide(home, args.approve, "approve", None, args.task_type)
        if args.reject:
            return decide(home, args.reject[0], "reject", args.reject[1])
        if args.record_diagnostic:
            return record_diagnostic_outcome(home, *args.record_diagnostic)
        if args.resolve:
            return record_resolution(home, *args.resolve)
        if args.resume_guarded:
            return resume_guarded(home, *args.resume_guarded)
        if args.cleanup:
            return cleanup(args.cleanup, args.force, home)
        return execute(home, args)
    except (SelfRepairError, OSError, UnicodeError) as error:
        print("SELF-REPAIR RESULT: FAIL", file=sys.stderr)
        print(f"ERROR self-repair: {error}", file=sys.stderr)
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
