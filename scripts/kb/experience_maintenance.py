"""Eventually consistent run observations; maintenance never grants authority.

The producer touches one bounded inbox object, not historical experience. Only
the existing maintenance actor merges that transport into experience/agent.jsonl.
Source logs, unresolved history and review candidates are never retention targets.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import stat
import tempfile
from typing import Any

SCHEMA = "sulde-run-retrospective-inbox-v1"
GENERATOR = "sulde-experience-maintenance-v1"
SOURCE_VERSION = "sulde-agent-experience-v1"
MAX_RECORD_BYTES = 16 * 1024
MAX_STORE_BYTES = 16 * 1024 * 1024
MAX_ENTRIES = 4096
MAX_BATCH = 250
STATUSES = {"success", "failed", "timeout", "paused", "awaiting_human"}
FACT_FIELDS = {"status", "returncode", "stop_reason", "report_passed", "quiescent",
               "findings_count", "open_effects", "evidence_sha256"}


@lru_cache(maxsize=3)
def component(name: str) -> dict[str, Any]:
    return runpy.run_path(str(Path(__file__).with_name(name + ".py")))


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def aware(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("aware terminal time required")
    return parsed.astimezone(timezone.utc)


def directory(home: Path, relative: str, *, create: bool = False) -> Path:
    home = Path(home)
    if home.is_symlink():
        raise ValueError("explicit experience home must not be a symlink")
    current = home.resolve()
    if create:
        current.mkdir(parents=True, exist_ok=True, mode=0o700)
    for part in Path(relative).parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("experience directory must not be a symlink")
        if create:
            current.mkdir(exist_ok=True, mode=0o700)
    return current


def read_object(path: Path, *, maximum: int = MAX_RECORD_BYTES) -> dict[str, Any]:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        metadata = os.fstat(descriptor)
        if (not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1
                or metadata.st_size > maximum):
            raise ValueError("unsafe or oversized experience input")
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            raw = handle.read(maximum + 1)
        if len(raw) > maximum:
            raise ValueError("experience input grew beyond its bound")
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError("experience object required")
        return value
    finally:
        os.close(descriptor)


def write_object(path: Path, value: Any, *, exclusive: bool = False) -> None:
    """Owner-only atomic bytes; an exclusive inbox identity is never overwritten."""
    raw = canonical(value)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        if exclusive:
            os.link(temporary, path)
        else:
            if path.is_symlink():
                raise ValueError("unsafe experience output")
            os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    descriptor = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def validate_facts(facts: dict[str, Any]) -> None:
    if set(facts) != FACT_FIELDS or facts["status"] not in STATUSES:
        raise ValueError("unsupported terminal facts")
    if facts["returncode"] is not None and type(facts["returncode"]) is not int:
        raise ValueError("return code must be observed integer or absent")
    if not isinstance(facts["stop_reason"], str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", facts["stop_reason"]):
        raise ValueError("terminal reason must be a code")
    for key in ("report_passed", "quiescent"):
        if type(facts[key]) is not bool:
            raise ValueError("terminal checks require booleans")
    for key in ("findings_count", "open_effects"):
        if type(facts[key]) is not int or not 0 <= facts[key] <= 1_000_000:
            raise ValueError("terminal counts must be bounded")
    evidence = facts["evidence_sha256"]
    if not isinstance(evidence, dict) or not evidence or not set(evidence).issubset({"terminal", "status", "report", "binding", "output", "summary"}):
        raise ValueError("bounded terminal evidence required")
    if any(not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value) for value in evidence.values()):
        raise ValueError("only evidence hashes may be retained")


def observation_fields(facts: dict[str, Any]) -> dict[str, str]:
    successful = (facts["status"] == "success" and facts["stop_reason"] == "completed" and facts["returncode"] == 0
                  and facts["report_passed"] and facts["quiescent"] and not facts["open_effects"])
    no_issue = successful and not facts["findings_count"]
    return {
        "problem_type": "managed_run_no_issue" if no_issue else "managed_run_" + ("observations" if successful else facts["status"]),
        "symptom": "No issue observed in bounded terminal checks" if no_issue else "Managed run has terminal observations requiring review",
        "handling": "Preserve established task status and retain independent review boundary",
        "outcome": "inconclusive" if successful else "unresolved",
        "result": facts["status"],
        "source_summary": "Managed runtime terminal facts only; no independent effect verification or knowledge authority",
    }


def queue_identity(record: dict[str, Any]) -> str:
    return digest({key: record[key] for key in ("task_id_sha256", "run_id_sha256", "task_instance_id_sha256")})


def validate_envelope(value: dict[str, Any]) -> dict[str, Any]:
    if set(value) != {"schema", "record", "facts", "source_sha256"} or value["schema"] != SCHEMA:
        raise ValueError("invalid retrospective envelope")
    facts, row = value["facts"], value["record"]
    validate_facts(facts)
    component("agent-experience")["validate_record"](row)
    if any(row[key] != expected for key, expected in observation_fields(facts).items()):
        raise ValueError("terminal observation cannot become verified strategy")
    expected_evidence = [{"kind": key, "summary": "Terminal evidence digest", "sha256": evidence}
                         for key, evidence in sorted(facts["evidence_sha256"].items())]
    if (row["evidence"] != expected_evidence or row.get("recommended_tests") != []
            or row.get("affected_components") != ["managed-agent"]
            or "policy_dispute" in row or value["source_sha256"] != digest({"record": row, "facts": facts})):
        raise ValueError("retrospective binding changed")
    if row["experience_id"] != queue_identity(row):
        raise ValueError("retrospective run identity changed")
    return row


def record_run_retrospective(home: Path, *, task_id: str, run_id: str | None,
    project_id: str, session_id: str, task_instance_id: str, occurred_at: str | None,
    status: str, returncode: int | None, stop_reason: str, report_passed: bool,
    quiescent: bool, findings_count: int, open_effects: int,
    evidence_sha256: dict[str, str]) -> dict[str, Any]:
    """O(1) observed terminal inbox write; errors never change the task outcome."""
    result: dict[str, Any] = {"status": "degraded", "execution_authorized": False,
                              "consistency": "eventual_maintenance_merge", "task_status_changed": False}
    if not run_id:
        return {**result, "status": "non_run", "reason_code": "no_launched_run"}
    try:
        for identity in (task_id, run_id, project_id, session_id, task_instance_id):
            if not isinstance(identity, str) or not identity or len(identity) > 4096:
                raise ValueError("bounded real task identities required")
        if not isinstance(occurred_at, str):
            raise ValueError("missing terminal fact time")
        moment = aware(occurred_at)
        if moment > datetime.now(timezone.utc) + timedelta(seconds=5):
            raise ValueError("terminal fact time is in the future")
        facts = dict(status=status, returncode=returncode, stop_reason=stop_reason,
                     report_passed=report_passed, quiescent=quiescent,
                     findings_count=findings_count, open_effects=open_effects, evidence_sha256=evidence_sha256)
        validate_facts(facts)
        row = component("agent-experience")["build_record"](
            task_id=task_id, run_id=run_id, project_id=project_id, session_id=session_id,
            task_instance_id=task_instance_id, occurred_at=moment.isoformat(),
            **observation_fields(facts), affected_components=["managed-agent"],
            evidence=[{"kind": key, "summary": "Terminal evidence digest", "sha256": value}
                      for key, value in sorted(evidence_sha256.items())])
        # Stable even after inbox acknowledgment. A changed terminal time/body
        # conflicts in the canonical store rather than creating a second run.
        row["experience_id"] = queue_identity(row)
        value = {"schema": SCHEMA, "record": row, "facts": facts, "source_sha256": digest({"record": row, "facts": facts})}
        validate_envelope(value)
        if len(canonical(value)) > MAX_RECORD_BYTES:
            raise ValueError("retrospective exceeds inbox bound")
        target = directory(home, "experience/inbox", create=True) / (queue_identity(row) + ".json")
        try:
            write_object(target, value, exclusive=True)
            status = "queued"
        except FileExistsError:
            status = "duplicate"
        if read_object(target) != value:
            raise ValueError("run retrospective identity collision")
        return {**result, "status": status, "experience_id": row["experience_id"]}
    except Exception as error:
        # Exception type only: messages may contain raw paths, commands or secrets.
        return {**result, "reason_code": "retrospective_" + type(error).__name__}


def canonical_records(home: Path) -> list[dict[str, Any]]:
    store = directory(home, "experience") / "agent.jsonl"
    if store.is_symlink() or (store.exists() and store.stat().st_size > MAX_STORE_BYTES):
        raise ValueError("canonical experience history exceeds maintenance bound")
    return component("agent-experience")["load_records"](home)


def project_retrospectives(home: Path, *, now: str | None = None) -> dict[str, Any]:
    """Read-only daily and weekly candidate projection, not a settlement ledger."""
    current = aware(now) if now else datetime.now(timezone.utc)
    rows = canonical_records(home)
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in rows:
        occurred = aware(row["occurred_at"])
        if "policy_dispute" in row or not current - timedelta(days=7) < occurred <= current:
            continue
        key = (occurred.date().isoformat(), row["problem_type"], row["outcome"])
        groups.setdefault(key, []).append(row)
    daily = [{"day": day, "problem_type": kind, "outcome": outcome,
              "count": len({row["experience_id"] for row in values}),
              "source_sha256": digest(sorted(row["experience_id"] for row in values))}
             for (day, kind, outcome), values in sorted(groups.items())]
    weekly: dict[tuple[str, str], list[str]] = {}
    for row in daily:
        if row["problem_type"] not in {"none", "managed_run_no_issue"}:
            weekly.setdefault((row["problem_type"], row["outcome"]), []).append(row["source_sha256"])
    return {"schema": "sulde-experience-review-v1", "observed_at": current.isoformat(),
            "status": "ready" if len(daily) <= MAX_BATCH and len(weekly) <= MAX_BATCH else "degraded",
            "daily": daily[:MAX_BATCH], "projection_complete": len(daily) <= MAX_BATCH and len(weekly) <= MAX_BATCH,
            "weekly_candidates": [{"problem_type": kind, "outcome": outcome,
                "source_sha256": digest(sorted(sources)), "status": "pending_independent_review"}
                for (kind, outcome), sources in sorted(weekly.items())][:MAX_BATCH],
            "consistency": "eventual_maintenance_merge", "execution_authorized": False,
            "knowledge_write_performed": False, "managed_audit_coverage": "unavailable_no_authoritative_registration",
            "limitations": ["rolling_projection_is_not_pending_candidate_settlement", "canonical_history_is_retained"]}


def maintenance(home: Path, *, apply: bool = False, now: str | None = None,
                max_batch: int = MAX_BATCH, max_entries: int = MAX_ENTRIES) -> dict[str, Any]:
    """Existing LIFE/weekly maintenance only; dry-run does not create directories."""
    result: dict[str, Any] = {"schema": GENERATOR, "status": "ready" if apply else "dry_run",
        "merged": 0, "checked": 0, "discovery_complete": True, "diagnostics": [],
        "consistency": "eventual_maintenance_merge", "execution_authorized": False,
        "managed_audit_coverage": "unavailable_no_authoritative_registration"}
    def degraded(code: str) -> None:
        result["status"] = "degraded"
        result["diagnostics"].append(code)
    try:
        if type(max_batch) is not int or not 1 <= max_batch <= MAX_BATCH or type(max_entries) is not int or not 1 <= max_entries <= MAX_ENTRIES:
            raise ValueError("invalid maintenance bounds")
        current = aware(now) if now else datetime.now(timezone.utc)
        inbox = directory(home, "experience/inbox")
        paths = []
        if inbox.exists():
            with os.scandir(inbox) as iterator:
                for index, entry in enumerate(iterator):
                    if index >= max_entries:
                        result["discovery_complete"] = False
                        degraded("inbox_discovery_limit")
                        break
                    if re.fullmatch(r"[a-f0-9]{64}\.json", entry.name):
                        paths.append(Path(entry.path))
        paths.sort(key=lambda path: (path.lstat().st_mtime_ns, path.name))
        result["pending_discovered"] = len(paths)
        if len(paths) > max_batch:
            degraded("inbox_batch_limit")
        selected = []
        for path in paths[:max_batch]:
            result["checked"] += 1
            try:
                envelope = read_object(path)
                row = validate_envelope(envelope)
                if aware(row["occurred_at"]) > current + timedelta(seconds=5):
                    raise ValueError("future retrospective")
                if path.stem != queue_identity(row):
                    raise ValueError("inbox identity differs")
                selected.append((path, envelope, row))
            except (OSError, ValueError, TypeError, KeyError):
                degraded("invalid_inbox_record")
            finally:
                if apply and path.is_file() and not path.is_symlink():
                    # Derived fairness only: never change the terminal fact time.
                    os.utime(path, None, follow_symlinks=False)
        if apply and selected:
            canonical_records(home)  # history work is bounded, not a hot-path scan
            component("agent-experience")["record_many"](home, [row for _, _, row in selected], maximum_bytes=MAX_STORE_BYTES)
            for path, envelope, _ in selected:
                if read_object(path) != envelope:
                    raise ValueError("inbox changed during merge")
                path.unlink()  # acknowledged transport only; canonical row read back above
                result["merged"] += 1
        result["retrospectives"] = project_retrospectives(home, now=current.isoformat())
        if result["retrospectives"]["status"] == "degraded":
            degraded("retrospective_projection_limit")
        policy = component("guardian_policy_review")
        result["policy_ingestion"] = policy["ingest_audits"](home) if apply else {"status": "not_requested"}
        result["policy_review"] = policy["project"](home, now=current.isoformat())
        if result["policy_ingestion"]["status"] == "degraded":
            degraded("policy_ingestion_degraded")
        result["retention"] = {"status": "dry_run", "deletion_performed": False}
        details = directory(home, "experience/derived-details")
        if apply:
            output = directory(home, "experience", create=True)
            # Pending review and daily aggregates are kept outside disposable details.
            write_object(output / "review.json", result["retrospectives"])
            details = directory(home, "experience/derived-details", create=True)
            # Only redundant no-issue observation renderings are disposable.
            # Pending, unresolved and verified rows never enter this store.
            identities = sorted(row["experience_id"] for row in canonical_records(home)
                if row["problem_type"] == "managed_run_no_issue" and row["outcome"] == "inconclusive"
                and aware(row["occurred_at"]).date() == current.date() and aware(row["occurred_at"]) <= current)
            if identities:
                detail = {"schema": GENERATOR, "day": current.date().isoformat(),
                          "kind": "no_issue_observation_rendering", "source_experience_ids": identities[:MAX_BATCH],
                          "coverage_complete": len(identities) <= MAX_BATCH, "execution_authorized": False}
                name = current.strftime("%Y%m%d") + "-" + digest(detail)[:16]
                target = details / (name + ".detail.json")
                manifest = details / (name + ".meta.json")
                if target.exists() != manifest.exists():
                    raise ValueError("incomplete derived detail publication")
                if not target.exists() and not manifest.exists():
                    write_object(target, detail, exclusive=True)
                    write_object(manifest, {"kind": "derived_detail", "authoritative": False,
                        "issue_status": "closed", "effect_status": "settled", "candidate_pending": False,
                        "verified_aggregate": False, "sourceVersion": SOURCE_VERSION, "generatorVersion": GENERATOR,
                        "created_at": current.isoformat(), "sha256": hashlib.sha256(canonical(detail)).hexdigest()}, exclusive=True)
        if details.exists():
            collector = component("derived-details")
            plan = collector["plan"](details, source_version=SOURCE_VERSION, generator_version=GENERATOR,
                                     ttl_seconds=30 * 86400, capacity=250, at=current.isoformat())
            result["retention"] = {"status": "no_candidates" if apply else "dry_run",
                                   "plan_id": plan["plan_id"], "candidates": len(plan["candidates"]),
                                   "protected": plan["protected"], "ttl_seconds": 30 * 86400,
                                   "capacity": 250, "deletion_performed": False}
            if plan["protected"]:
                degraded("protected_or_invalid_derived_details")
            if apply and plan["candidates"]:
                collector["quarantine"](details, plan)
                result["retention"] = collector["readback"](details, plan)
        return result
    except Exception as error:
        degraded("maintenance_" + type(error).__name__)
        return result
