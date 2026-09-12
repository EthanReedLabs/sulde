#!/usr/bin/env python3
"""Build the deterministic weekly Sulde governance report, with optional LLM analysis."""

from __future__ import annotations
from contextlib import closing

import argparse
import hashlib
import json
import math
import os
import re
import runpy
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable


_command_template = runpy.run_path(str(Path(__file__).with_name("command_template.py")))
split_command_template = _command_template["split_command_template"]


REPO_ROOT = Path(__file__).resolve().parents[2]
_recall_log = runpy.run_path(
    str(REPO_ROOT / "hooks" / "lib" / "recall_log.py")
)
classify_recall_source = _recall_log["classify_recall_source"]
mem_recall_opportunity_key = _recall_log["mem_recall_opportunity_key"]
RECALL_LOG_FILENAME = _recall_log["LOG_FILENAME"]
THRESHOLDS_PATH = Path(__file__).with_name("thresholds.json")
DEFAULT_LLM_CMD = _command_template["default_llm_command"]()
REQUIRED_HEADINGS = ("总评", "红绿灯表", "行动建议", "红队质疑", "下期关注")
UNAVAILABLE = "unavailable"
DISTILL_TIME = (9, 30)
L3_WINDOW_MINUTES = 15
DEFAULT_LLM_TIMEOUT = 900.0
MAX_PROMPT_CHARS = 8_000
PREVIOUS_SECTION_CHARS = 1_200
NEAR_EDGE_RATIO = 0.05
DEFAULT_HISTORY_PERIODS = 6
CONFIG_THRESHOLD_KEYS = {
    "governance_missing_source_streak_max",
    "governance_missing_source_escalation_enabled",
    "governance_near_edge_counter_start_backfilled",
    "governance_missing_counter_start_backfilled",
    "governance_breach_counter_start_backfilled",
    "degradation_drop_ratio",
}
DECISION_TRACE = "本分发不包含历史提案处置记录；结论与批准状态须以本地可核验记录为准"



class GovernanceError(RuntimeError):
    """A controlled report-generation error."""


class LLMTimeoutError(GovernanceError):
    """The LLM command exceeded its configured deadline."""


class LLMCommandError(GovernanceError):
    """The LLM command could not run successfully."""


class LLMFormatError(GovernanceError):
    """The LLM response did not satisfy the report contract."""


def kb_home() -> Path:
    configured = os.environ.get("SULDE_KB_HOME")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".sulde" / "data" / "kb"


def parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone()
    except (TypeError, ValueError, OverflowError):
        return None


def source(call: Callable[[], Any], *, name: str = "unknown", scope: str = "governance",
           collected_at: str | None = None) -> dict[str, Any]:
    metadata = {"source": name, "scope": scope,
                "collected_at": collected_at or datetime.now(timezone.utc).isoformat()}
    try:
        value = call()
        return {**metadata, "status": "available", "data": value, "error": None}
    except Exception as error:
        return {**metadata, "status": UNAVAILABLE, "error": type(error).__name__}


def run_json(command: list[str], allowed_codes: tuple[int, ...] = (0,)) -> dict[str, Any]:
    completed = subprocess.run(
        command,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=False,
    )
    if completed.returncode not in allowed_codes:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise GovernanceError(f"command exited {completed.returncode}: {detail[:300]}")
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise GovernanceError(f"invalid JSON output: {error}") from error
    if not isinstance(payload, dict):
        raise GovernanceError("JSON output must be an object")
    return payload


def collect_status(home: Path | None = None) -> dict[str, Any]:
    command = [sys.executable, str(Path(__file__).with_name("sulde-status.py")), "--json", "--read-only"]
    if home is not None:
        command.extend(["--home", str(home)])
    payload = run_json(command, allowed_codes=(0, 1))
    missing = payload.get("missing_sources")
    if not isinstance(missing, list):
        raise GovernanceError("status output is missing missing_sources")
    return payload


def collect_mem_golden() -> dict[str, Any]:
    payload = run_json(
        [sys.executable, str(Path(__file__).with_name("mem-golden.py")), "--json"],
        allowed_codes=(0, 1),
    )
    if not all(key in payload for key in ("hit", "total", "rate", "results")):
        raise GovernanceError("mem-golden output is incomplete")
    return payload


def collect_kb_golden() -> dict[str, Any]:
    completed = subprocess.run(
        [sys.executable, str(REPO_ROOT / "tests" / "kb-golden-eval.py"), "--min-rate", "0"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise GovernanceError(f"kb-golden exited {completed.returncode}: {detail[:300]}")
    match = re.search(r"hit@5:\s*(\d+)/(\d+)\s*=\s*([\d.]+)%", completed.stdout)
    if match is None:
        raise GovernanceError("kb-golden summary is missing")
    hit, total, percent = match.groups()
    return {"hit": int(hit), "total": int(total), "rate": float(percent) / 100}


def read_calibrate(home: Path) -> dict[str, Any]:
    path = home / "calibrate-weekly.md"
    text = path.read_text(encoding="utf-8")
    return {"path": str(path), "content": text[-20_000:]}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                value = json.loads(line)
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(value, dict):
                rows.append(value)
    return rows


def score_distribution(values: list[float]) -> dict[str, int | float | None]:
    ordered = sorted(values)
    if not ordered:
        return {"count": 0, "min": None, "p50": None, "p90": None, "max": None}

    def percentile(fraction: float) -> float:
        return ordered[round((len(ordered) - 1) * fraction)]

    return {
        "count": len(ordered),
        "min": ordered[0],
        "p50": percentile(0.5),
        "p90": percentile(0.9),
        "max": ordered[-1],
    }


def collect_recall(path: Path, now: datetime) -> dict[str, Any]:
    rows = read_jsonl(path)
    cutoffs = {"today": now.replace(hour=0, minute=0, second=0, microsecond=0), "7d": now - timedelta(days=7)}
    result: dict[str, Any] = {"records_total": len(rows)}
    for label, cutoff in cutoffs.items():
        selected = [row for row in rows if (parse_timestamp(row.get("ts")) or datetime.min.replace(tzinfo=timezone.utc).astimezone()) >= cutoff]
        classified = [row for row in selected if classify_recall_source(row) is not None]
        scores = [
            float(score)
            for row in classified
            for score in (row.get("top_scores") if isinstance(row.get("top_scores"), list) else [])
            if isinstance(score, (int, float)) and not isinstance(score, bool)
        ]
        injected = sum(len(row["injected"]) for row in classified)
        result[label] = {
            "records_seen": len(selected),
            "recalls": len(classified),
            "injected": injected,
            "unclassified": len(selected) - len(classified),
            "score_distribution": score_distribution(scores),
        }
    return result


def collect_mem_adoption(path: Path, now: datetime, recall_path: Path | None = None) -> dict[str, Any]:
    cutoff = now - timedelta(days=7)
    upstream_present = path.is_file()
    try:
        rows = read_jsonl(path)
    except FileNotFoundError:
        rows = []
    recent = [
        row
        for row in rows
        if (parse_timestamp(row.get("ts")) or datetime.min.replace(tzinfo=timezone.utc).astimezone()) >= cutoff
        and row.get("verdict") in {"adopted", "ignored"}
    ]
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in recent:
        key = str(
            row.get("opportunity_id") or f"legacy:{row.get('recall_ts', '')}"
        )
        grouped.setdefault(key, []).append(row)
    adopted = sum(any(row.get("verdict") == "adopted" for row in group) for group in grouped.values())
    ignored = len(grouped) - adopted
    samples = len(grouped)
    eligible = samples
    if recall_path is not None:
        try:
            recalls = read_jsonl(recall_path)
        except FileNotFoundError:
            recalls = []
        eligible_keys: set[str] = set()
        for row in recalls:
            timestamp = parse_timestamp(row.get("ts"))
            injected = row.get("injected")
            if (
                timestamp is None
                or timestamp < cutoff
                or not isinstance(injected, list)
                or not any(
                    isinstance(value, int) and not isinstance(value, bool)
                    for value in injected
                )
            ):
                continue
            key = mem_recall_opportunity_key(row)
            if key is not None:
                eligible_keys.add(key)
        eligible = len(eligible_keys)
    coverage = samples / eligible if eligible else None
    return {
        "adopted_7d": adopted,
        "ignored_7d": ignored,
        "samples_7d": samples,
        "required_minimum": 10,
        "eligible_opportunities_7d": eligible,
        "observed_opportunities_7d": samples,
        "observation_coverage": coverage,
        "upstream_present": upstream_present,
        "rate": adopted / samples if samples >= 10 and samples == eligible else "insufficient",
    }


WINDOW_RE = re.compile(r"(?:backfill )?window .*?entries=(\d+) chars=(\d+)")
RESULT_RE = re.compile(r"(?P<backfill>backfill )?result .*?edges=(\d+)")


def collect_distill(path: Path, now: datetime) -> dict[str, Any]:
    lines = path.read_text(encoding="utf-8").splitlines()
    cutoff = now - timedelta(days=7)
    recent = [line for line in lines if (parse_timestamp(line.split(maxsplit=1)[0]) or datetime.min.replace(tzinfo=timezone.utc).astimezone()) >= cutoff]
    windows = [tuple(map(int, match.groups())) for line in recent if (match := WINDOW_RE.search(line))]
    results = [match for line in recent if (match := RESULT_RE.search(line))]
    return {
        "lines_7d": len(recent),
        "windows_7d": len(windows),
        "normal_runs_7d": sum(match.group("backfill") is None for match in results),
        "backfill_runs_7d": sum(match.group("backfill") is not None for match in results),
        "edges_7d": sum(int(match.group(2)) for match in results),
        "window_entries_min": min((item[0] for item in windows), default=None),
        "window_entries_max": max((item[0] for item in windows), default=None),
        "window_chars_max": max((item[1] for item in windows), default=None),
        "age_seconds": max(0, int(now.timestamp() - path.stat().st_mtime)),
    }


def collect_sediment(path: Path, now: datetime) -> dict[str, Any]:
    cutoff = now - timedelta(days=7)
    totals = {key: 0 for key in ("new", "merge", "skip", "unsure")}
    runs = 0
    for row in read_jsonl(path):
        timestamp = parse_timestamp(row.get("timestamp"))
        if timestamp is None or timestamp < cutoff:
            continue
        summary = row.get("summary")
        if not isinstance(summary, dict):
            continue
        runs += 1
        for key in totals:
            value = summary.get(key)
            if isinstance(value, int) and not isinstance(value, bool):
                totals[key] += value
    return {"runs_7d": runs, "dispositions_7d": totals}


def collect_candidates(path: Path) -> dict[str, int]:
    text = path.read_text(encoding="utf-8")
    return {
        "pending": text.count("（待 /sediment 处理）")
        + text.count("（待 /sediment 人工处理）"),
        "unsure": text.count("（❓ 证据不足待裁决）")
        + text.count("（❓ 存疑留人工）"),
        "sedimented": text.count("（✅ 已沉淀"),
    }


def is_l3_timestamp(timestamp: datetime) -> bool:
    local = timestamp.astimezone()
    scheduled = local.replace(hour=DISTILL_TIME[0], minute=DISTILL_TIME[1], second=0, microsecond=0)
    return scheduled <= local < scheduled + timedelta(minutes=L3_WINDOW_MINUTES)



COVERAGE_SCHEMA = "sulde-l2-coverage-v1"


def utc_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return result.astimezone(timezone.utc) if result.tzinfo is not None else None
    except ValueError:
        return None


def evidence_digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def collect_edges(path: Path, now: datetime, baseline: dict[str, Any] | None = None) -> dict[str, Any]:
    if now.tzinfo is None:
        raise GovernanceError("coverage observation requires an aware UTC clock")
    end = now.astimezone(timezone.utc)
    start = end - timedelta(days=7)
    with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=0.2)) as connection:
        connection.row_factory = sqlite3.Row
        rows = [dict(row) for row in connection.execute("SELECT * FROM mem_edges ORDER BY id")]
    members = {}
    timestamps = []
    invalid = 0
    for row in rows:
        timestamp = utc_timestamp(row.get("ts"))
        if timestamp is None:
            invalid += 1
        elif start <= timestamp < end:
            timestamps.append(timestamp)
            members[str(row["id"])] = {"ts": timestamp.isoformat(), "sha256": evidence_digest(row)}
    total = len(timestamps)
    l3 = sum(is_l3_timestamp(item) for item in timestamps)
    l2 = total - l3
    collection_source = {
        "path": str(path.resolve()), "table": "mem_edges", "timestamp_field": "ts",
        "method": "timestamp_schedule_proxy_v1",
        "classification_timezone": os.environ.get("TZ") or str(now.astimezone().tzinfo),
        "l3_local_start": "09:30:00", "l3_window_minutes": L3_WINDOW_MINUTES,
        "limitation": "L2/L3 inferred from schedule, not verified actor provenance",
    }
    result = {
        "schema": COVERAGE_SCHEMA, "numerator": None if invalid else l2,
        "denominator": None if invalid else total,
        "total_7d": None if invalid else total, "l2_7d": None if invalid else l2,
        "l3_7d": None if invalid else l3,
        "l2_coverage_rate": l2 / total if total and not invalid else None,
        "window": {"start_utc": start.isoformat(), "end_utc": end.isoformat(), "bounds": "[start,end)"},
        "observed_at_utc": end.isoformat(), "source": collection_source,
        "invalid_timestamp_rows": invalid, "members": members,
        "evidence_status": "inconclusive" if invalid or not total else "observed",
        "baseline": {"status": "unavailable", "provenance": None},
        "discontinuity": {"state": "unknown", "reason": "no compatible baseline"},
        "reusable_success_evidence": False,
    }
    if baseline is not None:
        compatible = (valid_coverage_observation(baseline) and baseline["source"] == collection_source
                      and baseline.get("discontinuity", {}).get("state") != "discontinuous")
        if compatible:
            prior_end = utc_timestamp(baseline["window"]["end_utc"])
            compatible = start < prior_end <= end and any(start <= utc_timestamp(member["ts"]) < end
                                                       for member in baseline["members"].values())
        result["baseline"] = {
            "status": "available" if compatible else "inconclusive",
            "provenance": {"observation_sha256": baseline.get("observation_sha256"),
                           "source": baseline.get("source"), "window": baseline.get("window")},
            "numerator": baseline.get("numerator"), "denominator": baseline.get("denominator"),
        }
        if compatible:
            lost = [identifier for identifier, member in baseline["members"].items()
                    if start <= utc_timestamp(member["ts"]) < end and members.get(identifier) != member]
            result["discontinuity"] = {
                "state": "discontinuous" if lost or invalid else "continuous",
                "reason": "overlapping evidence removed or changed" if lost else
                          "invalid denominator timestamps" if invalid else "overlapping evidence preserved",
                "changed_or_missing_ids": lost,
            }
    if invalid:
        result["discontinuity"] = {"state": "discontinuous", "reason": "invalid denominator timestamps"}
    result["reusable_success_evidence"] = bool(total and not invalid and
                                                  result["discontinuity"]["state"] == "continuous")
    if result["discontinuity"]["state"] == "discontinuous":
        result["evidence_status"] = "inconclusive"
    result["observation_sha256"] = evidence_digest(result)
    return result


def valid_coverage_observation(value: Any) -> bool:
    if not isinstance(value, dict) or value.get("schema") != COVERAGE_SCHEMA:
        return False
    material = {key: item for key, item in value.items() if key != "observation_sha256"}
    if value.get("observation_sha256") != evidence_digest(material):
        return False
    numerator, denominator = value.get("numerator"), value.get("denominator")
    window, members = value.get("window"), value.get("members")
    if (type(numerator) is not int or type(denominator) is not int
            or not 0 <= numerator <= denominator or not isinstance(window, dict)
            or not isinstance(members, dict) or len(members) != denominator):
        return False
    start, end = utc_timestamp(window.get("start_utc")), utc_timestamp(window.get("end_utc"))
    if start is None or end is None or end - start != timedelta(days=7) or window.get("bounds") != "[start,end)":
        return False
    expected_rate = numerator / denominator if denominator else None
    if value.get("l2_coverage_rate") != expected_rate or value.get("invalid_timestamp_rows") != 0:
        return False
    if value.get("reusable_success_evidence") and (not denominator or
            value.get("discontinuity", {}).get("state") != "continuous"):
        return False
    return all(isinstance(member, dict) and utc_timestamp(member.get("ts")) is not None
               and start <= utc_timestamp(member["ts"]) < end
               and isinstance(member.get("sha256"), str) and len(member["sha256"]) == 64
               for member in members.values())


def coverage_baseline(home: Path) -> dict[str, Any] | None:
    # Legacy ratio-only history cannot supply a denominator baseline.
    rows = read_history(home / "governance/history.jsonl")
    return next((row["l2_observation"] for row in reversed(rows)
                 if isinstance(row.get("l2_observation"), dict)), None)


def collect_export_age(path: Path, now: datetime) -> dict[str, int]:
    modified = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).astimezone()
    return {"age_seconds": max(0, int((now - modified).total_seconds()))}


def collect_fleet() -> dict[str, Any]:
    payload = run_json([sys.executable, str(Path(__file__).with_name("fleet.py")), "--json"])
    projects = payload.get("projects")
    if not isinstance(projects, list):
        raise GovernanceError("fleet output is missing projects")
    running_ages = [
        task.get("age_seconds")
        for project in projects
        if isinstance(project, dict)
        for task in (project.get("tasks") if isinstance(project.get("tasks"), list) else [])
        if isinstance(task, dict) and task.get("status") == "running" and isinstance(task.get("age_seconds"), int)
    ]
    payload["max_running_age_seconds"] = max(running_ages, default=0)
    return payload


def collect_previous(home: Path) -> dict[str, str]:
    report_dir = home / "governance"
    candidates = sorted(report_dir.glob("report-*.md"), reverse=True)
    if not candidates:
        raise FileNotFoundError("no previous governance report")
    path = candidates[0]
    return {"path": str(path), "content": path.read_text(encoding="utf-8")[-20_000:]}


def collect_golden_candidates(path: Path) -> dict[str, Any]:
    review = runpy.run_path(str(Path(__file__).with_name("golden-review.py")))
    rows = review["load_jsonl"](path)
    audit_path = path.with_name("golden-review-decisions.jsonl")
    reviews = review["load_jsonl"](audit_path, allow_missing=True)
    return {**review["stage_accounting"](rows, reviews), "path": str(path),
            "review_path": str(audit_path), "review_journal_present": audit_path.is_file(),
            "scope": "unique IDs observed in the candidate queue and available review journal"}


def collect_latest_report(report_dir: Path, pattern: str, label: str, field: str) -> dict[str, Any]:
    candidates = sorted(report_dir.glob(pattern), reverse=True)
    if not candidates:
        raise FileNotFoundError(f"no report matching {pattern}")
    path = candidates[0]
    content = path.read_text(encoding="utf-8")
    match = re.search(rf"^-\s*{re.escape(label)}[：:]\s*(\d+)\s*$", content, re.MULTILINE)
    if match is None:
        raise GovernanceError(f"latest report is missing {label}: {path}")
    return {field: int(match.group(1)), "path": str(path)}


def collectors(home: Path, now: datetime) -> dict[str, Callable[[], Any]]:
    return {
            "status": (lambda: collect_status(home)),
            "fleet": collect_fleet,
            "kb_golden": collect_kb_golden,
            "mem_golden": collect_mem_golden,
            "calibrate": (lambda: read_calibrate(home)),
            "recall": (lambda: collect_recall(home / RECALL_LOG_FILENAME, now)),
            "mem_adoption": (lambda: collect_mem_adoption(home / "mem-adoption-log.jsonl", now, home / RECALL_LOG_FILENAME)),
            "auto_distill": (lambda: collect_distill(home / "auto-distill.log", now)),
            "auto_sediment": (lambda: collect_sediment(home / "auto-sediment.log", now)),
            "golden_candidates": (lambda: collect_golden_candidates(home / "golden-candidates.jsonl")),
            "graph_audit": (
                lambda: collect_latest_report(home / "governance", "graph-audit-*.md", "unsupported", "unsupported")
            ),
            "kb_aging": (
                lambda: collect_latest_report(home / "governance", "aging-*.md", "零采纳且超龄", "stale")
            ),
            "kb_dedup": (
                lambda: collect_latest_report(home / "governance", "dedup-*.md", "候选簇", "clusters")
            ),
            "candidates": (lambda: collect_candidates(home / "distill-candidates.md")),
            "mem_edges": (lambda: collect_edges(home / "memory.db", now, coverage_baseline(home))),
            "sync_export": (lambda: collect_export_age(home / "mem-sync-state.json", now)),
            "previous_report": (lambda: collect_previous(home)),
    }


def collect(home: Path | None = None, now: datetime | None = None) -> dict[str, Any]:
    home = home or kb_home()
    now = now or datetime.now().astimezone()
    return {"collected_at": now.isoformat(), "kb_home": str(home),
            "sources": {name: source(call, name=name, collected_at=now.isoformat()) for name, call in collectors(home, now).items()}}


def load_thresholds(path: Path = THRESHOLDS_PATH) -> dict[str, dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not payload:
        raise GovernanceError("threshold registry must be a non-empty object")
    for name, rule in payload.items():
        required = {"value", "op", "unit", "rationale", "owner"}
        if not isinstance(rule, dict) or not required.issubset(rule) or not set(rule).issubset(required | {"absolute_margin", "observation"}):
            raise GovernanceError(f"invalid threshold entry: {name}")
        if rule["op"] not in {">=", "<="} or isinstance(rule["value"], bool) or not isinstance(rule["value"], (int, float)):
            raise GovernanceError(f"invalid threshold rule: {name}")
        if not math.isfinite(rule["value"]) or any(
            not isinstance(rule[field], str) or not rule[field].strip()
            for field in ("unit", "rationale", "owner")
        ):
            raise GovernanceError(f"invalid threshold ownership/value: {name}")
        absolute_margin = rule.get("absolute_margin")
        if absolute_margin is not None and (
            isinstance(absolute_margin, bool) or not isinstance(absolute_margin, (int, float)) or not math.isfinite(absolute_margin) or absolute_margin <= 0
        ):
            raise GovernanceError(f"invalid absolute margin: {name}")
    known_sources = set(collectors(Path("."), datetime.now(timezone.utc))) | {"threshold_registry"}
    for name, rule in payload.items():
        mapping = rule.get("observation")
        if (not isinstance(mapping, dict) or set(mapping) != {"source", "field", "bucket"}
                or not isinstance(mapping["source"], str) or mapping["source"] not in known_sources
                or not isinstance(mapping["field"], str) or not mapping["field"]
                or not isinstance(mapping["bucket"], str) or mapping["bucket"] not in {"knowledge_quality", "retrieval_quality", "runtime_health", "collection_health", "configuration"}):
            raise GovernanceError(f"invalid governance ownership mapping: {name}")
        if name in CONFIG_THRESHOLD_KEYS and mapping["bucket"] != "configuration":
            raise GovernanceError(f"configuration bucket mismatch: {name}")
    return payload


METRIC_SOURCES = {name: rule["observation"]["source"] for name, rule in load_thresholds().items()}


def metric_values(snapshot: dict[str, Any], thresholds: dict[str, Any] | None = None) -> dict[str, Any]:
    values = {}
    for name, rule in (thresholds if thresholds is not None else load_thresholds()).items():
        mapping = rule["observation"]
        if mapping["source"] == "threshold_registry":
            values[name] = rule["value"]
            continue
        item = snapshot["sources"].get(mapping["source"], {})
        data = item.get("data", {}) if item.get("status") == "available" else {}
        if isinstance(data, dict) and data and mapping["field"] not in data:
            raise GovernanceError(f"metric source field mismatch: {name}")
        values[name] = data.get(mapping["field"]) if isinstance(data, dict) else None
        if name == "l2_coverage_rate" and not valid_coverage_observation(data):
            values[name] = None
    return values


def prejudge(snapshot: dict[str, Any], thresholds: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    values = metric_values(snapshot, thresholds)
    rows: list[dict[str, Any]] = []
    for name, rule in thresholds.items():
        if name in CONFIG_THRESHOLD_KEYS:
            continue
        value = values.get(name)
        diagnostic = unavailable_diagnostic(snapshot, name, value, rule["observation"]["source"])
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            light = "yellow"
            margin_ratio = None
        else:
            passed = value >= rule["value"] if rule["op"] == ">=" else value <= rule["value"]
            light = "green" if passed else "red"
            margin_ratio = threshold_margin_ratio(value, rule["value"], rule["op"])
        evidence = snapshot["sources"].get(rule["observation"]["source"], {}).get("data", {}) if name in {"l2_coverage_rate", "golden_candidates_pending"} else None
        if name == "l2_coverage_rate" and light == "green" and not evidence.get("reusable_success_evidence"):
            light = "yellow"
        absolute_margin = threshold_absolute_margin(value, rule["value"], rule["op"])
        absolute_limit = rule.get("absolute_margin")
        breached = margin_ratio is not None and margin_ratio < 0
        near_edge = margin_ratio is not None and 0 <= margin_ratio <= NEAR_EDGE_RATIO
        if absolute_limit is not None:
            near_edge = near_edge and absolute_margin is not None and absolute_margin < absolute_limit
        rows.append(
            {
                "metric": name,
                "measurement": evidence,
                "source": rule["observation"]["source"],
                "bucket": rule["observation"]["bucket"],
                "current": value,
                "threshold_value": rule["value"],
                "light": light,
                "margin_ratio": margin_ratio,
                "absolute_margin_value": absolute_margin,
                "near_edge": near_edge,
                "breached": breached,
                "diagnostic": diagnostic,
                "degraded": False,
                "trend_state": "无基线",
                **rule,
            }
        )
    for name, item in snapshot["sources"].items():
        if item["status"] == UNAVAILABLE:
            rows.append(
                {
                    "metric": f"source:{name}",
                    "current": UNAVAILABLE,
                    "threshold_value": None,
                    "value": None,
                    "op": "n/a",
                    "unit": "source",
                    "rationale": item.get("error", "missing source"),
                    "owner": "governance-weekly",
                    "light": "yellow",
                    "margin_ratio": None,
                    "near_edge": False,
                    "breached": False,
                    "diagnostic": missing_diagnostic("no_source", 0, 1, False),
                    "degraded": False,
                    "trend_state": "无基线",
                }
            )
    return rows


def threshold_margin_ratio(current: float, threshold: float, op: str) -> float | None:
    if threshold == 0:
        return None
    if op == ">=":
        return (current - threshold) / abs(threshold)
    if op == "<=":
        return (threshold - current) / abs(threshold)
    return None


def threshold_absolute_margin(current: Any, threshold: float, op: str) -> float | None:
    if isinstance(current, bool) or not isinstance(current, (int, float)):
        return None
    if op == ">=":
        return current - threshold
    if op == "<=":
        return threshold - current
    return None


def missing_diagnostic(
    reason: str,
    sample_count: int | None,
    required_minimum: int | None,
    upstream_present: bool,
    collected_at: str | None = None,
    sample_denominator: int | None = None,
) -> dict[str, Any]:
    diagnostic = {
        "reason": reason,
        "sample_count": sample_count,
        "required_minimum": required_minimum,
        "upstream_present": upstream_present,
    }
    if collected_at:
        diagnostic["collected_at"] = collected_at
    if sample_denominator is not None:
        diagnostic["sample_denominator"] = sample_denominator
    return diagnostic


def diagnostic_is_missing(diagnostic: Any) -> bool:
    return isinstance(diagnostic, dict) and diagnostic.get("reason") in {"no_source", "null_value", "insufficient_sample"}


def unavailable_diagnostic(snapshot: dict[str, Any], metric: str, value: Any, source_name: str | None = None) -> dict[str, Any] | None:
    source_name = source_name or METRIC_SOURCES.get(metric)
    if source_name is None:
        return missing_diagnostic("null_value", None, None, True, str(snapshot.get("collected_at", "未知")))
    item = snapshot["sources"].get(source_name, {})
    data = item.get("data", {}) if isinstance(item.get("data"), dict) else {}
    upstream_present = item.get("status") == "available" and data.get("upstream_present", True) is not False
    sample_count = data.get("samples_7d")
    required_minimum = data.get("required_minimum")
    if not isinstance(sample_count, int) or isinstance(sample_count, bool):
        sample_count = None
    if not isinstance(required_minimum, int) or isinstance(required_minimum, bool):
        required_minimum = None
    denominator = data.get("samples_7d", data.get("total"))
    if not isinstance(denominator, int) or isinstance(denominator, bool):
        denominator = None
    collected_at = str(snapshot.get("collected_at", "未知"))
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        reason = "zero_value" if value == 0 else "observed_value"
        return missing_diagnostic(reason, sample_count, required_minimum, upstream_present, collected_at, denominator)
    reason = "null_value" if value is None else ("insufficient_sample" if upstream_present else "no_source")
    return missing_diagnostic(reason, sample_count, required_minimum, upstream_present, collected_at, denominator)


def read_streaks(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError, UnicodeError):
        return {}
    periods = payload.get("metrics") if isinstance(payload, dict) else None
    return periods if isinstance(periods, dict) else {}


def apply_missing_streaks(
    lights: list[dict[str, Any]],
    previous: dict[str, Any],
    period: str,
    maximum: int,
    escalation_enabled: bool = False,
    start_backfilled: bool = False,
) -> None:
    for row in lights:
        missing = diagnostic_is_missing(row.get("diagnostic"))
        old = previous.get(row["metric"], {})
        old_count = old.get("count", 0) if isinstance(old, dict) else 0
        old_missing = old.get("missing", False) if isinstance(old, dict) else False
        old_period = old.get("last_period") if isinstance(old, dict) else None
        if old_period == period:
            count = old_count if missing == old_missing else (1 if missing else 0)
        else:
            count = old_count + 1 if missing and old_missing else (1 if missing else 0)
        row["missing_streak"] = count
        row["streak_counting_since"] = old.get("counting_since") if isinstance(old, dict) else None
        if not row["streak_counting_since"]:
            row["streak_counting_since"] = old_period or period
        row["missing_escalation_enabled"] = escalation_enabled
        row["missing_counter_start_date"] = (
            old.get("missing_counter_start_date", old.get("counting_since")) if isinstance(old, dict) else None
        ) or old_period or period
        row["missing_counter_start_backfilled"] = bool(old.get("missing_counter_start_backfilled", start_backfilled)) if isinstance(old, dict) else start_backfilled
        row["missing_count_before_backfill"] = count
        row["missing_count_after_backfill"] = old.get("missing_count_after_backfill") if isinstance(old, dict) else None
        row["self_proof_conflict"] = bool(not missing and old_count > 0 and (old_missing or not escalation_enabled))
        if isinstance(row.get("diagnostic"), dict):
            row["diagnostic"]["counter_start_backfilled"] = row["missing_counter_start_backfilled"]
        if missing and count >= maximum and escalation_enabled:
            row["light"] = "red"


def apply_near_edge_streaks(
    lights: list[dict[str, Any]], previous: dict[str, Any], period: str, start_backfilled: bool = False
) -> None:
    for row in lights:
        near_edge = bool(row.get("near_edge"))
        old = previous.get(row["metric"], {})
        old_count = old.get("near_edge_count", 0) if isinstance(old, dict) else 0
        old_near_edge = old.get("near_edge", False) if isinstance(old, dict) else False
        old_period = old.get("last_period") if isinstance(old, dict) else None
        if old_period == period:
            count = old_count if near_edge == old_near_edge else (1 if near_edge else 0)
        else:
            count = old_count + 1 if near_edge and old_near_edge else (1 if near_edge else 0)
        row["near_edge_streak"] = count
        row["near_edge_counter_start_date"] = (
            old.get("near_edge_counter_start_date") if isinstance(old, dict) else None
        ) or (old.get("counting_since") if isinstance(old, dict) and old_near_edge else None) or old_period or period
        row["near_edge_counter_start_backfilled"] = bool(old.get("near_edge_counter_start_backfilled", start_backfilled)) if isinstance(old, dict) else start_backfilled
        row["near_edge_count_before_backfill"] = count
        row["near_edge_count_after_backfill"] = old.get("near_edge_count_after_backfill") if isinstance(old, dict) else None


def apply_breach_streaks(
    lights: list[dict[str, Any]], previous: dict[str, Any], period: str, start_backfilled: bool = False
) -> None:
    for row in lights:
        breached = bool(row.get("breached"))
        old = previous.get(row["metric"], {})
        old_count = old.get("breach_count", 0) if isinstance(old, dict) else 0
        old_breached = old.get("breached", False) if isinstance(old, dict) else False
        old_period = old.get("last_period") if isinstance(old, dict) else None
        if old_period == period:
            count = old_count if breached == old_breached else (1 if breached else 0)
        else:
            count = old_count + 1 if breached and old_breached else (1 if breached else 0)
        row["breach_streak"] = count
        row["breach_counter_start_date"] = (
            old.get("breach_counter_start_date") if isinstance(old, dict) else None
        ) or old_period or period
        row["breach_counter_start_backfilled"] = bool(old.get("breach_counter_start_backfilled", start_backfilled)) if isinstance(old, dict) else start_backfilled
        row["breach_count_before_backfill"] = count
        row["breach_count_after_backfill"] = old.get("breach_count_after_backfill") if isinstance(old, dict) else None


def read_history(path: Path) -> list[dict[str, Any]]:
    try:
        return read_jsonl(path)
    except (FileNotFoundError, OSError, UnicodeError):
        return []


def apply_degradation(lights: list[dict[str, Any]], history: list[dict[str, Any]], period: str, drop_ratio: float, periods: int = DEFAULT_HISTORY_PERIODS) -> None:
    prior = [row for row in history if row.get("period") != period and isinstance(row.get("values"), dict)]
    for light in lights:
        light["trend_state"] = "无基线"
        light["baseline_period_dates"] = []
        light["trend_magnitude"] = None
        light["trend_uncompared_reason"] = "历史基线不足"
        light["trend_permanently_blind"] = False
        current = light.get("current")
        if not isinstance(current, (int, float)) or isinstance(current, bool) or current < 0:
            diagnostic = light.get("diagnostic")
            if diagnostic_is_missing(diagnostic):
                no_source = diagnostic.get("reason") in {"no_source", "null_value"}
                light["trend_uncompared_reason"] = "缺源" if no_source else "样本不足"
                light["trend_permanently_blind"] = no_source
            else:
                light["trend_uncompared_reason"] = "当前值无效"
            continue
        if light["metric"] == "l2_coverage_rate" and not (light.get("measurement") or {}).get("reusable_success_evidence"):
            light["trend_uncompared_reason"] = "分母连续性未获证明"
            continue
        samples = [
            (row.get("period"), row["values"].get(light["metric"]))
            for row in prior
            if (light["metric"] != "l2_coverage_rate" or
                (valid_coverage_observation(row.get("l2_observation")) and
                 row["l2_observation"].get("reusable_success_evidence") and
                 row["l2_observation"]["source"] == light["measurement"]["source"] and
                 row["values"].get(light["metric"]) == row["l2_observation"]["l2_coverage_rate"]))
            and isinstance(row["values"].get(light["metric"]), (int, float))
            and not isinstance(row["values"].get(light["metric"]), bool)
        ][-periods:]
        if not samples:
            continue
        numeric = [value for _, value in samples]
        mean = sum(numeric) / len(numeric)
        if mean <= 0:
            light["trend_uncompared_reason"] = "基线均值非正"
            continue
        relative_change = (mean - current) / mean if light["op"] == ">=" else (current - mean) / mean
        light["history_mean"] = mean
        light["degradation_ratio"] = relative_change
        light["degraded"] = relative_change > drop_ratio
        light["trend_state"] = "↓退化" if light["degraded"] else "未见退化"
        light["trend_magnitude"] = {"baseline": mean, "current": current, "change_ratio": (current - mean) / mean}
        light["trend_uncompared_reason"] = None
        light["baseline_period_dates"] = [str(date) for date, _ in samples if date]


def atomic_write(path: Path, content: str) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def persist_governance_state(home: Path, snapshot: dict[str, Any], lights: list[dict[str, Any]]) -> None:
    output_dir = home / "governance"
    output_dir.mkdir(parents=True, exist_ok=True)
    period = str(snapshot["collected_at"])[:10]
    streak_payload = {
        "version": 2,
        "metrics": {
            row["metric"]: {
                "count": row.get("missing_streak", 0),
                "last_period": period,
                "missing": diagnostic_is_missing(row.get("diagnostic")),
                "counting_since": row.get("streak_counting_since", period),
                "missing_counter_start_date": row.get("missing_counter_start_date", period),
                "missing_counter_start_backfilled": bool(row.get("missing_counter_start_backfilled")),
                "missing_count_after_backfill": row.get("missing_count_after_backfill"),
                "near_edge_count": row.get("near_edge_streak", 0),
                "near_edge": bool(row.get("near_edge")),
                "near_edge_counter_start_date": row.get("near_edge_counter_start_date", period),
                "near_edge_counter_start_backfilled": bool(row.get("near_edge_counter_start_backfilled")),
                "near_edge_count_after_backfill": row.get("near_edge_count_after_backfill"),
                "breach_count": row.get("breach_streak", 0),
                "breached": bool(row.get("breached")),
                "breach_counter_start_date": row.get("breach_counter_start_date", period),
                "breach_counter_start_backfilled": bool(row.get("breach_counter_start_backfilled")),
                "breach_count_after_backfill": row.get("breach_count_after_backfill"),
            }
            for row in lights
        },
    }
    atomic_write(output_dir / "streaks.json", json.dumps(streak_payload, ensure_ascii=False, indent=2) + "\n")

    history_path = output_dir / "history.jsonl"
    history = [row for row in read_history(history_path) if row.get("period") != period]
    values = {
        row["metric"]: row["current"]
        for row in lights
        if not row["metric"].startswith("source:")
        and isinstance(row.get("current"), (int, float))
        and not isinstance(row.get("current"), bool)
    }
    observation = snapshot.get("sources", {}).get("mem_edges", {}).get("data")
    if not valid_coverage_observation(observation) or not observation.get("reusable_success_evidence"):
        values.pop("l2_coverage_rate", None)
    history.append({"period": period, "collected_at": snapshot["collected_at"], "values": values,
                    "l2_observation": observation})
    content = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in history)
    atomic_write(history_path, content)


def strip_markdown_fence(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```") and text.endswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3 and lines[0].strip().lower() in {"```", "```md", "```markdown"}:
            return "\n".join(lines[1:-1]).strip()
    return text


def run_llm(command_template: str, prompt: str, timeout: float = DEFAULT_LLM_TIMEOUT) -> str:
    try:
        arguments = split_command_template(command_template)
    except ValueError as error:
        raise GovernanceError(f"invalid --llm-cmd: {error}") from error
    if not arguments:
        raise GovernanceError("--llm-cmd cannot be empty")
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
        completed = subprocess.run(expanded, input=stdin_prompt, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, check=False)
    except subprocess.TimeoutExpired as error:
        raise LLMTimeoutError(f"LLM 超时（{timeout:g} 秒）") from error
    except OSError as error:
        raise LLMCommandError(f"LLM 命令失败：{error}") from error
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise LLMCommandError(f"LLM 命令失败（exit {completed.returncode}）：{detail[:500]}")
    return completed.stdout


def valid_report(text: str) -> bool:
    if not text.strip() or not all(re.search(rf"^##\s+{re.escape(heading)}\s*$", text, re.MULTILINE) for heading in REQUIRED_HEADINGS):
        return False
    table_section = text.partition("## 红绿灯表")[2].partition("## 行动建议")[0]
    action_section = text.partition("## 行动建议")[2].partition("## 红队质疑")[0]
    red_team_section = text.partition("## 红队质疑")[2].partition("## 下期关注")[0]
    summary_section = text.partition("## 总评")[2].partition("## 红绿灯表")[0]
    # 红队只验"有实质内容"(≥80 字符),不验列表形态——深度论述优于凑格式的条目
    return (
        "|" in table_section
        and bool(re.search(r"⚠️\s*(?:项数|计数|数量)?\s*[:：为]?\s*\d+\s*项", summary_section))
        and bool(re.search(r"真正健康绿灯\s*\d+\s*项", summary_section))
        and bool(re.search(r"^\s*(?:\d+[.)]|[-*])\s+\S", action_section, re.MULTILINE))
        and len(red_team_section.strip()) >= 40
    )


def report_section(text: str, heading: str) -> str:
    match = re.search(
        rf"^##\s+{re.escape(heading)}\s*$\n?(.*?)(?=^##\s+|\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    if match is None:
        return UNAVAILABLE
    content = match.group(1).strip()
    return content[:PREVIOUS_SECTION_CHARS] if content else UNAVAILABLE


def compact_lights(lights: list[dict[str, Any]]) -> str:
    def clean(value: Any) -> str:
        return str(value).replace("\n", " ").replace("|", "/")[:120]

    lines = []
    for row in lights:
        threshold = "n/a" if row["op"] == "n/a" else f"{row['op']} {display_value(row['threshold_value'], row['unit'])}"
        margin = display_margin(row)
        diagnostic = display_diagnostic(row.get("diagnostic"), row.get("missing_streak"))
        degradation = display_trend(row)
        lines.append(
            f"- {clean(row['metric'])} | {clean(display_value(row['current'], row['unit']))} | "
            f"{clean(threshold)} | {display_light(row)} | 余量 {margin} | 诊断 {diagnostic} | 趋势 {degradation}"
        )
    return "\n".join(lines)


def build_prompt(snapshot: dict[str, Any], lights: list[dict[str, Any]], retry: bool = False) -> str:
    previous = snapshot["sources"]["previous_report"]
    previous_text = previous.get("data", {}).get("content", UNAVAILABLE) if previous["status"] == "available" else UNAVAILABLE
    warning_total = warning_count(lights)
    breach_total = breach_count(lights)
    green_total = sum(row["light"] == "green" for row in lights)
    healthy_green_total = healthy_green_count(lights)
    capacity_clause = "总评还必须原样标注“合格但无余量”。" if warning_total > green_total / 3 else ""
    prompt = f"""你是 Sulde 周质量委员会。根据机器已算好的指标和红绿灯撰写《记忆栈周报》，不得自行重算或改变灯色。
必须只输出 Markdown，且严格包含这五个二级标题：## 总评、## 红绿灯表、## 行动建议、## 红队质疑、## 下期关注。
总评必须原样披露“当期 ⚠️ {warning_total} 项、⛔ {breach_total} 项”和“真正健康绿灯 {healthy_green_total} 项”。{capacity_clause}
红绿灯表必须是 Markdown 表格；行动建议必须按优先级排序，并给出可执行建议。缺源计数自 {streak_counting_since(lights)} 起算；升级暂缓:计数起点待人工回填。贴边、缺源、已破三类计数器的起点/回填状态/双值，未回填时的 ×N⁺ 下界，趋势“未见退化”及幅度，null/0 诊断、自证冲突、未比对清单与趋势永久失明均是机器事实，应明确解释。
红队职责条款：必须提出≥1 条对现行阈值/规则/机制本身的质疑，不许全盘认可；质疑不得擅自改阈值，只能形成待审提案。
请继续评估贴边告警、缺源诊断/连续升级、相对退化检测这三项机制本身是否有效、有无盲区。
新增治理闭环指标 golden_candidates_pending、graph_audit_unsupported、kb_aging_stale、kb_dedup_clusters、event_contract_violations、interventions_open、effect_blocking、intervention_invalid_stores 必须逐项解释状态与处置优先级；缺源只能标 unavailable，不得推断为 0。外部操作无法证明时必须保持 unknown 并转人工，不得建议盲重试。
请专门红队评估本轮 P-12 至 P-17 机制是否真正封闭判定边界、诚实声明计数起点、可读展示趋势幅度、区分 null/0 并完整自证；同时继续评估持续贴边与决策留痕的盲区。

指标紧凑摘要（每行：名称 | 值 | 阈值 | 灯色 | 余量 | 诊断 | 趋势）：
{compact_lights(lights)}
{detector_proof(lights)}

上期报告摘录：
### 红队质疑
{report_section(previous_text, "红队质疑")}

### 下期关注
{report_section(previous_text, "下期关注")}

“下期关注”必须完整写出处置结论：{DECISION_TRACE}。
"""
    if retry:
        prompt += "\n上次输出结构不合格。请严格补齐五个二级标题、Markdown 红绿灯表和至少一条红队质疑，只输出报告。"
    if len(prompt) >= MAX_PROMPT_CHARS:
        raise GovernanceError(f"LLM prompt exceeds {MAX_PROMPT_CHARS} characters: {len(prompt)}")
    return prompt


def display_value(value: Any, unit: str) -> str:
    if value is None or value == UNAVAILABLE:
        return UNAVAILABLE
    if unit == "ratio" and isinstance(value, (int, float)):
        return f"{value:.1%}"
    return str(value)


def display_diagnostic(diagnostic: Any, streak: Any = None, conflict: bool = False) -> str:
    if not isinstance(diagnostic, dict):
        return "-"
    reason = diagnostic.get("reason")
    if reason in {"no_source", "null_value"}:
        text = "null(取不到)" if reason == "null_value" else "数据源断链/null(取不到)"
    elif reason == "zero_value":
        text = "0(取到零)"
    elif reason == "observed_value":
        text = "已取值"
    else:
        sample = diagnostic.get("sample_count")
        required = diagnostic.get("required_minimum")
        left = "?" if sample is None else str(sample)
        right = "?" if required is None else str(required)
        text = f"样本不足({left}/{right})"
    collected_at = diagnostic.get("collected_at", "未知")
    denominator = diagnostic.get("sample_denominator")
    text += f" · 采集 {collected_at} · 样本分母 {'?' if denominator is None else denominator}"
    if diagnostic_is_missing(diagnostic) and isinstance(streak, int) and streak > 0:
        text += f" · 缺源×{streak}{'' if diagnostic.get('counter_start_backfilled') else '⁺'}"
    if conflict:
        text += " · 自证冲突"
    return text


def warning_count(lights: list[dict[str, Any]]) -> int:
    return sum(bool(row.get("near_edge")) for row in lights)


def breach_count(lights: list[dict[str, Any]]) -> int:
    return sum(bool(row.get("breached")) for row in lights)


def green_display_tier(row: dict[str, Any]) -> str | None:
    """返回绿灯的只读显示分级；踩线优先于高位退化，保证单行只落一级。"""
    if row.get("light") != "green":
        return None
    if row.get("near_edge") is True:
        return "踩线"
    if row.get("trend_state") == "↓退化":
        return "高位退化"
    return "余量充裕"


def display_light(row: dict[str, Any]) -> str:
    tier = green_display_tier(row)
    if tier is not None:
        return f"🟢[{tier}]"
    return {"yellow": "🟡", "red": "🔴"}.get(str(row.get("light")), "—")


def healthy_green_count(lights: list[dict[str, Any]]) -> int:
    return sum(green_display_tier(row) == "余量充裕" for row in lights)


def streak_counting_since(lights: list[dict[str, Any]]) -> str:
    dates = sorted(str(row["streak_counting_since"]) for row in lights if row.get("streak_counting_since"))
    return dates[0] if dates else "未知日期"


def detector_proof(lights: list[dict[str, Any]]) -> str:
    compared = sum(row.get("trend_state") in {"未见退化", "↓退化"} for row in lights)
    dates = sorted({date for row in lights for date in row.get("baseline_period_dates", [])})
    earliest = dates[0] if dates else "无基线"
    uncompared = []
    for row in lights:
        if row.get("trend_state") != "无基线":
            continue
        reason = str(row.get("trend_uncompared_reason") or "原因未知")
        if row.get("trend_permanently_blind"):
            reason += "，趋势永久失明"
        uncompared.append(f"{row['metric']}({reason})")
    missing_list = "、".join(uncompared) if uncompared else "无"
    return (
        f"检测器自证：本期比对了 {compared} 项指标；基线期数 {len(dates)}；基线最早日期 {earliest}；"
        f"未比对项清单及原因：{missing_list}"
    )


def counter_contract_summary(lights: list[dict[str, Any]]) -> str:
    specs = (("贴边", "near_edge"), ("缺源", "missing"), ("已破", "breach"))
    parts = []
    for label, prefix in specs:
        starts = sorted(str(row.get(f"{prefix}_counter_start_date")) for row in lights if row.get(f"{prefix}_counter_start_date"))
        backfilled = bool(lights) and all(bool(row.get(f"{prefix}_counter_start_backfilled")) for row in lights)
        pairs = sorted(
            {
                f"{row.get(f'{prefix}_count_before_backfill', 0)}/{row.get(f'{prefix}_count_after_backfill') if row.get(f'{prefix}_count_after_backfill') is not None else '待回填'}"
                for row in lights
            }
        )
        parts.append(
            f"{label}[计数起点日期:{starts[0] if starts else '未知'}；起点是否已回填:{'是' if backfilled else '否'}；"
            f"回填前/后双值:{','.join(pairs) if pairs else '0/待回填'}]"
        )
    return "；".join(parts)


def display_trend(row: dict[str, Any]) -> str:
    state = row.get("trend_state", "无基线")
    magnitude = row.get("trend_magnitude")
    if not isinstance(magnitude, dict):
        reason = row.get("trend_uncompared_reason")
        blind = "；趋势永久失明" if row.get("trend_permanently_blind") else ""
        return f"{state}（{reason}{blind}）" if reason else str(state)
    baseline = display_value(magnitude.get("baseline"), row.get("unit", ""))
    current = display_value(magnitude.get("current"), row.get("unit", ""))
    change = magnitude.get("change_ratio")
    suffix = f"，变化 {change:+.2%}" if isinstance(change, (int, float)) else ""
    return f"{state}（{baseline}→{current}{suffix}）"


def display_margin(row: dict[str, Any]) -> str:
    margin = row.get("margin_ratio")
    if not isinstance(margin, (int, float)) or isinstance(margin, bool):
        return "n/a"
    streak = row.get("near_edge_streak", 0)
    if row.get("breached"):
        breach_streak = row.get("breach_streak", 0)
        lower_bound = "" if row.get("breach_counter_start_backfilled") else "⁺"
        suffix = f" ⛔已破 {breach_streak}{lower_bound} 期" if isinstance(breach_streak, int) and breach_streak > 0 else " ⛔已破"
    else:
        lower_bound = "" if row.get("near_edge_counter_start_backfilled") else "⁺"
        suffix = f" ⚠️×{streak}{lower_bound}" if row.get("near_edge") and isinstance(streak, int) and streak > 0 else ""
    return f"{margin:.2%}{suffix}"


def display_current(row: dict[str, Any]) -> str:
    diagnostic = row.get("diagnostic")
    return display_diagnostic(diagnostic, row.get("missing_streak")) if diagnostic_is_missing(diagnostic) else display_value(row["current"], row["unit"])


def machine_table(lights: list[dict[str, Any]]) -> str:
    lines = [
        "| 指标 | 当前值 | 阈值 | 余量 | 诊断 | 趋势 | 灯色 | 执法组件 |",
        "|---|---:|---:|---:|---|:---:|:---:|---|",
    ]
    for row in lights:
        threshold = "n/a" if row["op"] == "n/a" else f"{row['op']} {display_value(row['threshold_value'], row['unit'])}"
        trend = display_trend(row)
        diagnostic = display_diagnostic(row.get("diagnostic"), row.get("missing_streak"), bool(row.get("self_proof_conflict")))
        lines.append(
            f"| {row['metric']} | {display_current(row)} | {threshold} | {display_margin(row)} | {diagnostic} | {trend} | {display_light(row)} | {row['owner']} |"
        )
    lines.append(f"| 检测器自证 | {detector_proof(lights)} | n/a | n/a | 自证 | n/a | — | governance-weekly |")
    lines.append(f"| 计数器自证 | {counter_contract_summary(lights)} | n/a | n/a | 自证 | n/a | — | governance-weekly |")
    lines.append(
        f"| 缺源连续期机制 | 自 {streak_counting_since(lights)} 起算；升级暂缓:计数起点待人工回填 | n/a | n/a | n/a | n/a | — | governance-weekly |"
    )
    for row in lights:
        if row["metric"] == "l2_coverage_rate":
            evidence = row.get("measurement") or {"evidence_status": "unavailable"}
            public = {key: value for key, value in evidence.items() if key != "members"}
            lines.extend(["", "L2 observation (UTC; schedule proxy):", "",
                          "~~~json", json.dumps(public, ensure_ascii=False, sort_keys=True), "~~~"])
        if row["metric"] == "golden_candidates_pending":
            stages = {key: value for key, value in (row.get("measurement") or {}).items() if key != "stages_by_id"}
            lines.extend(["", "Golden stage accounting:", "", "~~~json",
                          json.dumps(stages, ensure_ascii=False, sort_keys=True), "~~~"])
        if row.get("observation"):
            lines.append(f"<!-- governance-ownership {row['metric']}: {json.dumps(row['observation'], sort_keys=True)} -->")
    return "\n".join(lines)


def enforce_machine_table(report: str, lights: list[dict[str, Any]]) -> str:
    pattern = re.compile(r"(^##\s+红绿灯表\s*$).*?(^##\s+行动建议\s*$)", re.MULTILINE | re.DOTALL)
    rendered, count = pattern.subn(
        lambda match: f"{match.group(1)}\n\n{machine_table(lights)}\n\n{match.group(2)}",
        report,
        count=1,
    )
    if count != 1:
        raise GovernanceError("cannot replace LLM red/green table")
    return rendered


def fallback_report(snapshot: dict[str, Any], lights: list[dict[str, Any]], reason: str) -> str:
    red = sum(row["light"] == "red" for row in lights)
    yellow = sum(row["light"] == "yellow" for row in lights)
    warnings = warning_count(lights)
    breaches = breach_count(lights)
    green = sum(row["light"] == "green" for row in lights)
    healthy_green = healthy_green_count(lights)
    capacity = "；合格但无余量" if warnings > green / 3 else ""
    lines = [
        "# 记忆栈周报（仅机器红绿灯）",
        "",
        "> ⚠️ LLM 分析降级：仅保留确定性收集与机器预判。",
        f"> 原因：{reason[:500]}",
        "",
        "## 总评",
        "",
        f"机器预判：红灯 {red} 项，黄灯 {yellow} 项；当期 ⚠️ {warnings} 项、⛔ {breaches} 项，真正健康绿灯 {healthy_green} 项{capacity}；报告处于降级模式。",
        "",
        "## 红绿灯表",
        "",
        machine_table(lights),
    ]
    first = next((row for row in lights if row["light"] == "red"), None)
    action = f"修复红灯指标 `{first['metric']}` 并复跑确定性预判。" if first else "补齐 unavailable 数据源并复跑确定性预判。"
    lines += [
        "",
        "## 行动建议",
        "",
        f"1. P0：{action}",
        "2. P1：恢复 LLM 周报链路后复核建议排序，不改动机器灯色。",
        "",
        "## 红队质疑",
        "",
        "- 新增机制提升了治理分辨率：余量标记能揭示压线绿，结构化诊断与三期升红能区分并约束长期失联，相对退化提示能发现绝对阈值尚绿时的趋势恶化。当前盲区是历史不足六期时均值稳定性偏弱，且缺源计数依赖本地状态文件连续保存；建议持续验证，不修改既有阈值。",
        "",
        "## 下期关注",
        "",
        "- 验证缺失源恢复情况，并比较本期与下期红黄灯变化。",
        f"- 提案处置结论：{DECISION_TRACE}。",
        "",
    ]
    return "\n".join(lines)


def prepare_lights(snapshot: dict[str, Any], thresholds: dict[str, dict[str, Any]], home: Path | None = None) -> list[dict[str, Any]]:
    home = home or Path(snapshot["kb_home"])
    period = str(snapshot["collected_at"])[:10]
    lights = prejudge(snapshot, thresholds)
    missing_max = int(thresholds["governance_missing_source_streak_max"]["value"])
    drop_ratio = float(thresholds["degradation_drop_ratio"]["value"])
    escalation_enabled = bool(thresholds["governance_missing_source_escalation_enabled"]["value"])
    previous = read_streaks(home / "governance" / "streaks.json")
    apply_missing_streaks(
        lights,
        previous,
        period,
        missing_max,
        escalation_enabled,
        bool(thresholds["governance_missing_counter_start_backfilled"]["value"]),
    )
    apply_near_edge_streaks(
        lights, previous, period, bool(thresholds["governance_near_edge_counter_start_backfilled"]["value"])
    )
    apply_breach_streaks(
        lights, previous, period, bool(thresholds["governance_breach_counter_start_backfilled"]["value"])
    )
    apply_degradation(lights, read_history(home / "governance" / "history.jsonl"), period, drop_ratio)
    return lights


def first_action(report: str) -> str:
    match = re.search(r"^\s*(?:\d+[.)]|[-*])\s*(.+)$", report.partition("## 行动建议")[2].partition("## 红队质疑")[0], re.MULTILINE)
    return match.group(1).strip()[:80] if match else "查看本周治理报告"


def notify(report: str, lights: list[dict[str, Any]]) -> None:
    sys.path.insert(0, str(REPO_ROOT / "hooks" / "lib"))
    try:
        import kb_notify

        red = sum(row["light"] == "red" for row in lights)
        kb_notify.run({"message": f"记忆栈周报：红灯 {red} 项；{first_action(report)}"})
    except Exception:
        return


def print_summary(label: str, lights: list[dict[str, Any]], output: Path | None = None) -> None:
    counts = {color: sum(row["light"] == color for row in lights) for color in ("green", "yellow", "red")}
    unavailable = [row["metric"] for row in lights if row["metric"].startswith("source:")]
    print(f"GOVERNANCE {label}: {'FAIL' if counts['red'] else 'PASS'}")
    print(f"lights: green={counts['green']} yellow={counts['yellow']} red={counts['red']} total={len(lights)}")
    if unavailable:
        print("WARN unavailable: " + ",".join(unavailable))
    if output is not None:
        print(f"details: {output}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--llm-cmd", default=DEFAULT_LLM_CMD, help="command template; standalone {prompt} is sent over stdin")
    parser.add_argument("--llm-timeout", type=float, default=DEFAULT_LLM_TIMEOUT, help="timeout in seconds for each LLM attempt (default: 900)")
    parser.add_argument("--dry-run", action="store_true", help="print report without writing or notifying")
    parser.add_argument("--collect-only", action="store_true", help="print collected metrics and deterministic lights only")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.llm_timeout <= 0:
        print("ERROR governance-report: --llm-timeout must be greater than zero", file=sys.stderr)
        return 2
    home = kb_home()
    try:
        thresholds = load_thresholds()
        snapshot = collect(home)
        lights = prepare_lights(snapshot, thresholds, home)
    except (GovernanceError, OSError, UnicodeError, json.JSONDecodeError) as error:
        print(f"ERROR governance-report: {error}", file=sys.stderr)
        return 2
    if args.collect_only:
        print_summary("COLLECT", lights)
        return 0

    report: str | None = None
    errors: list[str] = []
    for attempt in range(2):
        try:
            candidate = strip_markdown_fence(run_llm(args.llm_cmd, build_prompt(snapshot, lights, retry=attempt == 1), args.llm_timeout))
            if not valid_report(candidate):
                raise LLMFormatError("LLM 格式不合格：缺少规定标题、Markdown 表格或列表项")
            report = enforce_machine_table(candidate, lights).rstrip() + "\n"
            break
        except GovernanceError as error:
            errors.append(str(error))
            category = "timeout" if isinstance(error, LLMTimeoutError) else "command" if isinstance(error, LLMCommandError) else "format" if isinstance(error, LLMFormatError) else "prompt"
            print(f"ERROR llm attempt={attempt + 1} category={category}: {error}", file=sys.stderr)
    if report is None:
        report = fallback_report(snapshot, lights, "; ".join(errors))
        mode = "DEGRADED"
    else:
        mode = "RESULT"

    if args.dry_run:
        print(report, end="")
        return 0
    output_dir = home / "governance"
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"report-{datetime.now().astimezone():%Y%m%d}.md"
    output.write_text(report, encoding="utf-8")
    persist_governance_state(home, snapshot, lights)
    notify(report, lights)
    print_summary(mode, lights, output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
