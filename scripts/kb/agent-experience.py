#!/usr/bin/env python3
"""Record redacted Agent retrospectives without writing the factual KB."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import tempfile
import threading
import time
from typing import Any, Iterable

_file_lock = runpy.run_path(str(Path(__file__).resolve().with_name("file_lock.py")))
lock_exclusive_nonblocking = _file_lock["lock_exclusive_nonblocking"]
unlock = _file_lock["unlock"]


SCHEMA = "sulde-agent-experience-v1"
RECALL_SCHEMA = "sulde-agent-experience-recall-v1"
CANDIDATE_SCHEMA = "sulde-experience-sedimentation-candidates-v1"
OUTCOMES = frozenset({"verified", "inconclusive", "unresolved"})
_REQUIRED = {
    "schema", "experience_id", "task_id_sha256", "run_id_sha256",
    "project_id_sha256", "session_id_sha256", "task_instance_id_sha256",
    "problem_type", "symptom", "handling", "outcome", "result",
    "evidence", "source_summary", "occurred_at",
}
_ABSOLUTE_PATH = re.compile(
    r"(?<![A-Za-z0-9_.-])(?:(?:/[A-Za-z0-9_.@+~ -]+)+|[A-Za-z]:[\\/][^\s]+)"
)
_SECRET = re.compile(
    r"(?i)\b(?:api[_-]?key|access[_-]?token|authorization|password|secret)\b\s*[:=]\s*[^\s,;]+"
)
_TOKEN = re.compile(r"[A-Za-z0-9_\-]{2,}")
_PROCESS_LOCK = threading.Lock()


class ExperienceError(ValueError):
    """An experience record violates the redacted contract."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _canonical(value: Any) -> str:
    try:
        return json.dumps(
            value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
        )
    except (TypeError, ValueError, OverflowError) as error:
        raise ExperienceError(f"experience is not lossless JSON: {error}") from error


def _digest(value: Any) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8", errors="replace")).hexdigest()


def sanitize_summary(value: Any, *, maximum: int = 1_000) -> str:
    """Keep a bounded summary while removing paths and credential-shaped text."""
    rendered = re.sub(r"[\x00-\x1f\x7f]+", " ", str(value or ""))
    rendered = _ABSOLUTE_PATH.sub("<redacted-path>", rendered)
    rendered = _SECRET.sub("<redacted-secret>", rendered)
    rendered = re.sub(r"\s+", " ", rendered).strip()
    return rendered[:maximum]


def _timestamp(value: Any) -> str:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError, OverflowError) as error:
        raise ExperienceError("occurred_at is not ISO-8601") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ExperienceError("occurred_at must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def evidence_item(kind: str, summary: str, material: Any) -> dict[str, str]:
    label = sanitize_summary(kind, maximum=64).lower().replace(" ", "_")
    if not re.fullmatch(r"[a-z][a-z0-9_.-]{0,63}", label):
        raise ExperienceError("evidence kind is invalid")
    return {
        "kind": label,
        "summary": sanitize_summary(summary, maximum=300),
        "sha256": hashlib.sha256(_canonical(material).encode("utf-8")).hexdigest(),
    }


def build_record(
    *,
    task_id: str,
    run_id: str,
    project_id: str,
    session_id: str,
    task_instance_id: str,
    problem_type: str,
    symptom: str,
    handling: str,
    outcome: str,
    result: str,
    evidence: Iterable[dict[str, Any]] = (),
    source_summary: str,
    occurred_at: str | None = None,
    recommended_tests: Iterable[str] = (),
    affected_components: Iterable[str] = (),
) -> dict[str, Any]:
    if outcome not in OUTCOMES:
        raise ExperienceError(f"invalid experience outcome: {outcome}")
    timestamp = _timestamp(occurred_at or _now().isoformat())
    safe_evidence: list[dict[str, str]] = []
    for item in evidence:
        if not isinstance(item, dict):
            raise ExperienceError("evidence entries must be objects")
        digest = str(item.get("sha256") or "")
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ExperienceError("evidence sha256 is invalid")
        safe_evidence.append(
            {
                "kind": sanitize_summary(item.get("kind"), maximum=64),
                "summary": sanitize_summary(item.get("summary"), maximum=300),
                "sha256": digest,
            }
        )
    material = {
        "task": _digest(task_id),
        "run": _digest(run_id),
        "project": _digest(project_id),
        "session": _digest(session_id),
        "instance": _digest(task_instance_id),
        "problem_type": sanitize_summary(problem_type, maximum=80),
        "occurred_at": timestamp,
    }
    record = {
        "schema": SCHEMA,
        "experience_id": hashlib.sha256(_canonical(material).encode("utf-8")).hexdigest(),
        "task_id_sha256": _digest(task_id),
        "run_id_sha256": _digest(run_id),
        "project_id_sha256": _digest(project_id),
        "session_id_sha256": _digest(session_id),
        "task_instance_id_sha256": _digest(task_instance_id),
        "problem_type": sanitize_summary(problem_type or "none", maximum=80),
        "symptom": sanitize_summary(symptom or "no issue observed"),
        "handling": sanitize_summary(handling or "no corrective action required"),
        "outcome": outcome,
        "result": sanitize_summary(result),
        "evidence": safe_evidence,
        "source_summary": sanitize_summary(source_summary, maximum=300),
        "occurred_at": timestamp,
        "recommended_tests": sorted(
            {
                sanitize_summary(value, maximum=160)
                for value in recommended_tests
                if sanitize_summary(value, maximum=160)
            }
        ),
        "affected_components": sorted(
            {
                sanitize_summary(value, maximum=160)
                for value in affected_components
                if sanitize_summary(value, maximum=160)
            }
        ),
        "knowledge_boundary": "candidate_only_single_writer_required",
    }
    validate_record(record)
    return record


def validate_record(value: Any) -> None:
    optional = {"recommended_tests", "affected_components", "knowledge_boundary"}
    if not isinstance(value, dict) or set(value) - optional != _REQUIRED:
        raise ExperienceError("experience fields do not match the v1 contract")
    if value.get("schema") != SCHEMA or value.get("outcome") not in OUTCOMES:
        raise ExperienceError("experience schema or outcome is invalid")
    for key in (
        "experience_id", "task_id_sha256", "run_id_sha256", "project_id_sha256",
        "session_id_sha256", "task_instance_id_sha256",
    ):
        if not re.fullmatch(r"[0-9a-f]{64}", str(value.get(key) or "")):
            raise ExperienceError(f"{key} must be sha256")
    _timestamp(value.get("occurred_at"))
    for key in ("problem_type", "symptom", "handling", "result", "source_summary"):
        text = str(value.get(key) or "")
        if not text or _ABSOLUTE_PATH.search(text) or _SECRET.search(text):
            raise ExperienceError(f"{key} is empty or contains sensitive text")
    evidence = value.get("evidence")
    if not isinstance(evidence, list):
        raise ExperienceError("evidence must be a list")
    for item in evidence:
        if (
            not isinstance(item, dict)
            or set(item) != {"kind", "summary", "sha256"}
            or not re.fullmatch(r"[a-z][a-z0-9_.-]{0,63}", str(item.get("kind") or ""))
            or not re.fullmatch(r"[0-9a-f]{64}", str(item.get("sha256") or ""))
            or _ABSOLUTE_PATH.search(str(item.get("summary") or ""))
            or _SECRET.search(str(item.get("summary") or ""))
        ):
            raise ExperienceError("evidence item is invalid")


def store_path(home: Path) -> Path:
    return home / "experience" / "agent.jsonl"


def load_records(home: Path) -> list[dict[str, Any]]:
    path = store_path(home)
    if not path.is_file():
        return []
    records: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as error:
        raise ExperienceError(f"cannot read experience store: {type(error).__name__}") from error
    for line in lines:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            validate_record(row)
        except (json.JSONDecodeError, ExperienceError) as error:
            raise ExperienceError(f"invalid experience store: {error}") from error
        records.append(row)
    return records


def _atomic_records(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(_canonical(row) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def record(home: Path, value: dict[str, Any]) -> dict[str, Any]:
    """Append idempotently under a process/file lock and verify by read-back."""
    validate_record(value)
    path = store_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(".lock")
    with _PROCESS_LOCK:
        handle = lock_path.open("a+", encoding="utf-8")
        try:
            for _attempt in range(100):
                try:
                    lock_exclusive_nonblocking(handle)
                    break
                except BlockingIOError:
                    time.sleep(0.01)
            else:
                raise ExperienceError("experience store lock is busy")
            rows = load_records(home)
            existing = next(
                (row for row in rows if row["experience_id"] == value["experience_id"]),
                None,
            )
            if existing is not None:
                if existing != value:
                    raise ExperienceError("experience idempotency collision")
                return existing
            _atomic_records(path, [*rows, value])
            persisted = load_records(home)
            if not persisted or persisted[-1] != value:
                raise ExperienceError("experience read-back verification failed")
            return value
        finally:
            try:
                unlock(handle)
            except OSError:
                pass
            handle.close()


def _tokens(value: str) -> set[str]:
    return {token.casefold() for token in _TOKEN.findall(value)}


def recall(
    home: Path,
    *,
    problem_type: str,
    symptom: str,
    affected_components: Iterable[str] = (),
) -> dict[str, Any]:
    """Verified experience may select strategy; weaker states remain advisory."""
    wanted = _tokens(" ".join([problem_type, symptom, *affected_components]))
    matches: list[tuple[int, dict[str, Any]]] = []
    for row in load_records(home):
        haystack = _tokens(
            " ".join(
                [
                    str(row.get("problem_type") or ""),
                    str(row.get("symptom") or ""),
                    *[str(value) for value in row.get("affected_components", [])],
                ]
            )
        )
        score = len(wanted & haystack)
        if score:
            matches.append((score, row))
    matches.sort(key=lambda item: (-item[0], str(item[1].get("occurred_at") or "")))
    verified = [row for _score, row in matches if row["outcome"] == "verified"]
    inconclusive = [row for _score, row in matches if row["outcome"] == "inconclusive"]
    unresolved = [row for _score, row in matches if row["outcome"] == "unresolved"]
    return {
        "schema": RECALL_SCHEMA,
        "strategy": {
            "source": "verified_experience" if verified else "default",
            "recommended_tests": sorted(
                {test for row in verified for test in row.get("recommended_tests", [])}
            ),
            "experience_ids": [row["experience_id"] for row in verified],
        },
        "diagnostic_hints": [
            {
                "experience_id": row["experience_id"],
                "problem_type": row["problem_type"],
                "symptom": row["symptom"],
            }
            for row in inconclusive
        ],
        "unresolved_retained": len(unresolved),
        "matched": len(matches),
    }


def sedimentation_candidates(home: Path) -> dict[str, Any]:
    """Return candidates only; this module has no knowledge writer."""
    rows = [
        {
            "experience_id": row["experience_id"],
            "problem_type": row["problem_type"],
            "symptom": row["symptom"],
            "handling": row["handling"],
            "result": row["result"],
            "evidence_sha256": hashlib.sha256(_canonical(row["evidence"]).encode("utf-8")).hexdigest(),
            "source_summary": row["source_summary"],
        }
        for row in load_records(home)
        if row["outcome"] == "verified"
    ]
    return {
        "schema": CANDIDATE_SCHEMA,
        "knowledge_write_performed": False,
        "single_writer_required": True,
        "candidates": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("list", "candidates"))
    parser.add_argument("--home", type=Path, default=Path.home() / ".sulde/data/kb")
    args = parser.parse_args()
    payload: Any = (
        load_records(args.home.expanduser())
        if args.action == "list"
        else sedimentation_candidates(args.home.expanduser())
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
