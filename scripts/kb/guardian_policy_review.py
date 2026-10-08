#!/usr/bin/env python3
"""Audit-only Guardian feedback in the existing experience store.

Explicit retrospective ingestion and maintenance projection, never a pretool
authorization path. Assessments are evidence claims for independent review;
even a reproducible false-denial candidate cannot verify an external effect or
relax a production denial. No new store, scheduler, model call, or policy writer.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import stat
import sys
import time
from typing import Any


SCHEMA = "sulde-guardian-policy-dispute-v1"
PROBLEM = "guardian_policy_dispute"
BOUNDARY = "audit_only_independent_human_review_required"
SUMMARY_FIELDS = {
    "symptom": "Guardian denial requires policy review",
    "handling": "Retain current denial and request independent review",
    "source_summary": "Audit observation only; no execution or external effect verified",
}
FIELDS = {"schema", "rule_id", "rule_version", "reason_code", "scope_digest", "fingerprint",
          "event_digest", "assessment", "disposition", "boundary"}
ASSESSMENT_FIELDS = {"kind", "outcome", "expected_decision", "observed_decision", "source_sha256", "fingerprint"}


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def require_digest(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value):
        raise ValueError("policy evidence and scope identities must be sha256")
    return value


def require_label(value: Any) -> str:
    # Labels are code identifiers/versions, not key:value metadata. Excluding
    # ':' and '=' prevents credential assignments in every manual/read path.
    if not isinstance(value, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,79}", value):
        raise ValueError("policy labels must be bounded codes, never commands or target text")
    return value


def timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("policy timestamps require a timezone")
    return parsed.astimezone(timezone.utc)


def fingerprint(metadata: dict[str, Any]) -> str:
    return sha({key: metadata[key] for key in ("rule_id", "rule_version", "reason_code", "scope_digest")})


def classify(metadata: dict[str, Any]) -> str:
    evidence = metadata["assessment"]
    if not evidence or evidence["fingerprint"] != metadata["fingerprint"]:
        return "unconfirmed"
    if evidence["outcome"] != "passed" or evidence["observed_decision"] != "deny":
        return "unconfirmed"
    return {"allow": "false_denial", "deny": "valid_protection"}.get(evidence["expected_decision"], "unconfirmed")


def validate_metadata(value: Any) -> None:
    if not isinstance(value, dict) or set(value) != FIELDS:
        raise ValueError("policy dispute fields do not match the audit contract")
    if value["schema"] != SCHEMA or value["boundary"] != BOUNDARY:
        raise ValueError("policy dispute is not an audit-only record")
    for key in ("rule_id", "rule_version", "reason_code"):
        require_label(value[key])
    for key in ("scope_digest", "event_digest", "fingerprint"):
        require_digest(value[key])
    if value["fingerprint"] != fingerprint(value):
        raise ValueError("policy fingerprint does not match rule/version/scope/reason")
    assessment = value["assessment"]
    if assessment is not None:
        if not isinstance(assessment, dict) or set(assessment) != ASSESSMENT_FIELDS:
            raise ValueError("assessment fields must be bounded evidence, without raw text")
        if assessment["kind"] not in {"regression_test", "bounded_replay"}:
            raise ValueError("assessment kind is not supported")
        if assessment["outcome"] not in {"passed", "failed", "unknown"}:
            raise ValueError("assessment outcome is invalid")
        if any(assessment[key] not in {"allow", "deny", "unknown"} for key in ("expected_decision", "observed_decision")):
            raise ValueError("assessment decisions are invalid")
        require_digest(assessment["source_sha256"])
        require_digest(assessment["fingerprint"])
    if value["disposition"] != classify(value):
        raise ValueError("policy disposition does not follow the bound evidence")


def validate_experience(row: dict[str, Any]) -> None:
    """Called by the canonical experience validator, including file read-back."""
    validate_metadata(row["policy_dispute"])
    if row["outcome"] != "inconclusive" or row["problem_type"] != PROBLEM:
        raise ValueError("policy observations cannot become verified experience or authority")
    # Generic experience prose is deliberately unavailable for policy telemetry:
    # credential-shaped redaction alone cannot recognize arbitrary raw commands.
    if any(row.get(key) != value for key, value in SUMMARY_FIELDS.items()):
        raise ValueError("policy feedback accepts fixed summaries only")
    metadata = row["policy_dispute"]
    if (row.get("result") != metadata["disposition"] or row.get("recommended_tests", []) != []
            or row.get("affected_components", []) != ["guardian"]
            or row.get("knowledge_boundary") != "candidate_only_single_writer_required"):
        raise ValueError("policy feedback contains non-audit material")
    if row.get("evidence") != feedback_evidence(metadata):
        raise ValueError("policy evidence must match the hash-only metadata")


def feedback_evidence(metadata: dict[str, Any]) -> list[dict[str, str]]:
    evidence = [{"kind": "denial_event", "summary": "Original denial event digest", "sha256": metadata["event_digest"]}]
    if metadata["assessment"]:
        evidence.append({"kind": "policy_assessment", "summary": "Independent review evidence claim", "sha256": metadata["assessment"]["source_sha256"]})
    return evidence


@lru_cache(maxsize=1)
def experience() -> dict[str, Any]:
    return runpy.run_path(str(Path(__file__).with_name("agent-experience.py")))


def build_feedback(*, rule_id: str, rule_version: str, reason_code: str,
                   scope_digest: str, event_digest: str, occurred_at: str,
                   assessment: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build a hash-only retrospective. The caller retains original evidence.

    source_sha256 identifies immutable regression/replay evidence for a reviewer;
    it is not a verifier signature. Classification is explicitly a candidate.
    """
    metadata = dict(schema=SCHEMA, rule_id=rule_id, rule_version=rule_version,
                    reason_code=reason_code, scope_digest=scope_digest,
                    event_digest=event_digest, assessment=assessment, boundary=BOUNDARY)
    metadata["fingerprint"] = fingerprint(metadata)
    # Validate structure before using the assessment to derive disposition.
    metadata["disposition"] = "unconfirmed"
    if assessment is not None and (not isinstance(assessment, dict) or set(assessment) != ASSESSMENT_FIELDS):
        raise ValueError("assessment fields must be bounded evidence, without raw text")
    metadata["disposition"] = classify(metadata)
    validate_metadata(metadata)
    source = experience()
    row = source["build_record"](
        task_id=metadata["fingerprint"], run_id=sha(metadata), project_id=scope_digest,
        session_id=event_digest, task_instance_id=event_digest,
        problem_type=PROBLEM, **SUMMARY_FIELDS,
        outcome="inconclusive", result=metadata["disposition"], evidence=feedback_evidence(metadata),
        occurred_at=occurred_at, affected_components=["guardian"], policy_dispute=metadata,
    )
    return row


def record_feedback(home: Path, row: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(row, dict) or "policy_dispute" not in row:
        raise ValueError("record requires a policy dispute experience")
    return experience()["record"](home, row)


@lru_cache(maxsize=1)
def audit_cursors() -> dict[str, Any]:
    return runpy.run_path(str(Path(__file__).with_name("audit_cursor.py")))


def feedback_from_audit(row: dict[str, Any]) -> dict[str, Any] | None:
    """Adapt only the existing GuardianSession.observe envelope, never authority."""
    if row.get("schema") != "sulde-guardian-event-v1":
        return None
    event, decision, contract = (row.get(key) for key in ("event", "decision", "contract"))
    if not all(isinstance(value, dict) for value in (event, decision, contract)):
        raise ValueError("invalid Guardian audit envelope")
    if decision.get("schema") != "sulde-intent-decision-v2":
        raise ValueError("unsupported Guardian decision schema")
    if decision.get("dispatch") not in {"deny", "defer"} or event.get("phase") != "started":
        return None
    occurred = event.get("at")
    if not isinstance(occurred, str):
        raise ValueError("denial lacks original event timestamp")
    timestamp(occurred)
    # These are the actual producer's identity fields. Raw values are hashed
    # immediately and never copied into an experience, cursor, or report.
    scope = {key: event.get(key) for key in ("provider", "capability", "effect", "target", "resource_base")}
    scope.update(intent_id=contract.get("intent_id"), intent_revision=contract.get("revision"))
    stage = require_label(decision.get("decision_stage") or "policy")
    reason = require_label(decision.get("reason_code") or "policy_denied")
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,49}", stage) or not re.fullmatch(r"[a-z][a-z0-9_]{0,79}", reason):
        raise ValueError("decision codes do not match the existing DecisionV2 contract")
    # Runtime generation is an actual observed version, not intent revision.
    # Older producers without it remain explicitly unversioned.
    generation = event.get("runtime_generation")
    version = require_digest(generation) if generation else "unversioned"
    return build_feedback(rule_id=f"guardian.{stage}", rule_version=version,
                          reason_code=reason, scope_digest=sha(scope),
                          event_digest=sha(row), occurred_at=occurred)


def mark_source_checked(directory: Path, source_id: str, checked_ns: int) -> None:
    """Derived fairness metadata, independent of authoritative audit offsets.

    A zero-content marker records attempts even when the audit is corrupt or
    oversized. It contains no event data and cannot advance an audit checkpoint.
    """
    if directory.is_symlink() or directory.parent.is_symlink():
        raise ValueError("maintenance cursor directory must not be a symlink")
    directory.parent.mkdir(mode=0o700, exist_ok=True)
    directory.mkdir(mode=0o700, exist_ok=True)
    descriptor = os.open(directory / f"{source_id}.checked",
                         os.O_CREAT | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1 or metadata.st_size != 0:
            raise ValueError("maintenance check marker is not an empty regular file")
        os.utime(descriptor, ns=(checked_ns, checked_ns))
    finally:
        os.close(descriptor)


def ingest_audits(home: Path, *, max_files: int = 16, max_entries: int = 256,
                  max_source_bytes: int = 512 * 1024, max_total_bytes: int = 4 * 1024 * 1024,
                  max_rows: int = 256) -> dict[str, Any]:
    """Bounded maintenance-only ingestion with canonical cursor CAS checkpoints.

    The source size bound also bounds audit_cursor's prefix-integrity read.
    Oversized/corrupt sources are reported, not skipped by advancing a cursor.
    Experience is written before checkpoint CAS; a crash replays idempotently.
    """
    limits = (max_files, max_entries, max_source_bytes, max_total_bytes, max_rows)
    if any(type(limit) is not int or limit <= 0 for limit in limits):
        raise ValueError("maintenance limits must be positive integers")
    home = home.resolve()
    result: dict[str, Any] = {"status": "ready", "recorded": 0, "sources_checked": 0,
                              "rows_checked": 0, "source_bytes": 0, "diagnostics": [],
                              "source_scope": "intent_workspaces_and_sessions_only",
                              "discovery_complete": True, "automatic_coverage": "discovered_sources",
                              "execution_authorized": False}
    def degraded(reason: str, path: Path | None = None) -> None:
        result["status"] = "degraded"
        result["diagnostics"].append({"reason": reason, "source_digest": sha(str(path.relative_to(home))) if path else None})

    sources: list[Path] = []
    entries = 0
    for directory in (home / "intent/workspaces", home / "intent/sessions"):
        if directory.is_symlink() or directory.parent.is_symlink():
            result["discovery_complete"] = False
            degraded("source_directory_symlink", directory)
            continue
        if not directory.exists():
            continue
        try:
            with os.scandir(directory) as iterator:
                for entry in iterator:
                    entries += 1
                    if entries > max_entries:
                        result["discovery_complete"] = False
                        degraded("source_discovery_limit")
                        break
                    if entry.name.endswith(".events.jsonl"):
                        sources.append(Path(entry.path))
        except OSError:
            result["discovery_complete"] = False
            degraded("source_directory_unavailable", directory)
        if entries > max_entries:
            break
    if len(sources) > max_files:
        degraded("source_file_limit")
    if not result["discovery_complete"]:
        result["automatic_coverage"] = "partial"
    cursor_directory = home / "governance/policy-review-cursors"
    checks: dict[Path, int] = {}
    for path in sources:
        marker = cursor_directory / f"{sha(str(path.relative_to(home)))}.checked"
        try:
            metadata = marker.lstat()
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_size != 0 or metadata.st_nlink != 1:
                raise ValueError("invalid maintenance marker")
            checks[path] = metadata.st_mtime_ns
        except FileNotFoundError:
            checks[path] = 0
        except (OSError, ValueError):
            degraded("check_marker_invalid", path)
    checked_ns = max(time.time_ns(), max(checks.values(), default=0) + 1)
    cursor_api = audit_cursors()
    for path in sorted(checks, key=lambda item: (checks[item], str(item)))[:max_files]:
        source_id = sha(str(path.relative_to(home)))
        checkpoint_path = cursor_directory / f"{source_id}.json"
        try:
            result["sources_checked"] += 1
            # Advance attempt time before source validation, including failure.
            # A crash may postpone this source by one cycle, never settle it.
            mark_source_checked(cursor_directory, source_id, checked_ns)
            checked_ns += 1
            size = path.lstat().st_size
            if size > max_source_bytes:
                degraded("source_byte_limit", path)
                continue
            if result["source_bytes"] + size > max_total_bytes:
                degraded("total_byte_limit", path)
                continue
            result["source_bytes"] += size
            checkpoint = cursor_api["load_cursor"](checkpoint_path) if checkpoint_path.exists() else None
            scanned = cursor_api["scan_increment"](
                path, runtime_generation="guardian-policy-review-adapter-v1", cursor=checkpoint,
                max_bytes=max_source_bytes, enforce_event_generation=False)
            if result["rows_checked"] + len(scanned.rows) > max_rows:
                degraded("row_limit", path)
                continue
            result["rows_checked"] += len(scanned.rows)
            # Validate the entire bounded batch before persisting any of it.
            records = [record for row in scanned.rows if (record := feedback_from_audit(row)) is not None]
            governance_home = home / "governance"
            if governance_home.is_symlink():
                raise ValueError("governance directory must not be a symlink")
            governance_home.mkdir(mode=0o700, exist_ok=True)
            for record in records:
                record_feedback(home, record)
                result["recorded"] += 1
            cursor_api["save_cursor"](checkpoint_path, scanned.cursor,
                                      expected_digest=cursor_api["cursor_digest"](checkpoint) if checkpoint else None)
        except (OSError, ValueError, RuntimeError, TypeError, KeyError):
            # Do not leak source text/paths through exception messages. A failed
            # checkpoint can leave idempotent experience rows, never authority.
            degraded("source_or_checkpoint_invalid", path)
    return result


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    metadata = rows[0]["policy_dispute"]
    dispositions = {row["policy_dispute"]["disposition"] for row in rows} - {"unconfirmed"}
    disposition = next(iter(dispositions)) if len(dispositions) == 1 else "unconfirmed"
    return {
        **{key: metadata[key] for key in ("fingerprint", "rule_id", "rule_version", "reason_code", "scope_digest")},
        "recurrence": len({row["policy_dispute"]["event_digest"] for row in rows}),
        "disposition": disposition,
        "conflicting_evidence": len(dispositions) > 1,
        "source_event_sha256": sorted({row["policy_dispute"]["event_digest"] for row in rows}),
        "source_evidence_sha256": sorted({row["policy_dispute"]["assessment"]["source_sha256"] for row in rows if row["policy_dispute"]["assessment"]}),
        "experience_ids": sorted({row["experience_id"] for row in rows}),
        "suggested_disposition": {"valid_protection": "retain", "false_denial": "review_fix", "unconfirmed": "collect_evidence"}[disposition],
        "status": "pending_independent_review",
        "execution_authorized": False,
        "target_identity_quality": "scope_digest_only",
    }


def project(home: Path, *, now: str | None = None, window_days: int = 7) -> dict[str, Any]:
    """Rebuild daily dedup and rolling weekly candidates from canonical history."""
    if type(window_days) is not int or not 1 <= window_days <= 366:
        raise ValueError("window_days must be between 1 and 366")
    current = timestamp(now) if now else datetime.now(timezone.utc)
    cutoff = current - timedelta(days=window_days)
    daily: dict[tuple[str, str], list[dict[str, Any]]] = {}
    weekly: dict[str, list[dict[str, Any]]] = {}
    records = [row for row in experience()["load_records"](home) if "policy_dispute" in row]
    # The same denial event may gain assessment evidence later. Recurrence and
    # daily bucketing follow its earliest recorded occurrence, not replay times.
    event_times: dict[tuple[str, str], datetime] = {}
    for row in records:
        metadata = row["policy_dispute"]
        identity = (metadata["fingerprint"], metadata["event_digest"])
        occurred = timestamp(row["occurred_at"])
        event_times[identity] = min(occurred, event_times.get(identity, occurred))
    for row in records:
        key = row["policy_dispute"]["fingerprint"]
        occurred = event_times[(key, row["policy_dispute"]["event_digest"])]
        if not cutoff < occurred <= current or timestamp(row["occurred_at"]) > current:
            continue
        daily.setdefault((occurred.date().isoformat(), key), []).append(row)
        weekly.setdefault(key, []).append(row)
    return {
        "schema": "sulde-guardian-policy-review-v1", "observed_at": current.isoformat(),
        "window_start": cutoff.isoformat(), "window_days": window_days,
        "daily": [{"day": day, **summarize(rows)} for (day, _key), rows in sorted(daily.items())],
        "weekly_candidates": [summarize(rows) for _key, rows in sorted(weekly.items())],
        "execution_authorized": False, "production_policy_changed": False,
        "boundary": BOUNDARY,
        "limitations": ["assessment_is_not_authority", "scope_digest_does_not_prove_unique_endpoint",
                        "unknown_effects_remain_unknown", "no_automatic_rule_activation",
                        "rolling_window_is_not_pending_review_settlement"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("record", "project"))
    parser.add_argument("--home", type=Path, required=True, help="existing experience/KB state home")
    parser.add_argument("--input", type=Path, help="redacted policy dispute experience JSON")
    parser.add_argument("--now")
    parser.add_argument("--window-days", type=int, default=7)
    args = parser.parse_args()
    try:
        if args.action == "record":
            if args.input is None:
                parser.error("record requires --input")
            row = record_feedback(args.home, json.loads(args.input.read_text(encoding="utf-8")))
            result = {"experience_id": row["experience_id"], "execution_authorized": False, "production_policy_changed": False}
        else:
            result = project(args.home, now=args.now, window_days=args.window_days)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (ValueError, OSError, UnicodeError) as error:
        print(f"POLICY REVIEW: FAIL {type(error).__name__}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
