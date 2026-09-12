"""Independent fault aggregation and evidence-driven closure, never authority."""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
from sulde_paths import sync_repository_path, SuldePathError

SCHEMA = "sulde-life-problems-v1"


def now():
    return datetime.now(timezone.utc).isoformat()


def sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def observer():
    root = Path(__file__).resolve().parents[2]
    path = (root.parent / "scripts/_hook_observer.py") if root.name == "runtime" else root / "integrations/codex/plugins/sulde/scripts/_hook_observer.py"
    spec = importlib.util.spec_from_file_location("sulde_independent_hook_observer", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def connect(home):
    directory = home / "life/problems"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = directory / "ledger.sqlite3"
    if directory.is_symlink() or path.is_symlink():
        raise OSError("unsafe problem ledger")
    conn = sqlite3.connect(path, timeout=.2)
    conn.execute("CREATE TABLE IF NOT EXISTS problems (id TEXT PRIMARY KEY, row TEXT NOT NULL)")
    conn.execute("CREATE TABLE IF NOT EXISTS processed (id TEXT PRIMARY KEY, row TEXT NOT NULL)")
    conn.execute("CREATE TABLE IF NOT EXISTS history (seq INTEGER PRIMARY KEY, problem TEXT, at TEXT, transition TEXT, evidence TEXT)")
    conn.commit()
    return conn


def aggregate(home):
    """Background consumer; discovery has zero dependency on Guardian health."""
    recorder = observer()
    beat = read_fact(home / "heartbeat-state.json")
    if beat.get("last_mode") == "degraded" and beat.get("last_ts"):
        event = recorder.facts(hook="heartbeat", stage="runtime",
                               payload={"session_id": "scheduler", "cwd": str(home), "call_id": str(beat.get("sequence"))},
                               code=None, kind="heartbeat_generation_degraded", source="state_readback")
        event["at"] = beat["last_ts"]
        recorder.record(event, home)
    observed = recorder.read_rows(home)
    with closing(connect(home)) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        for event in observed["rows"]:
            if conn.execute("SELECT 1 FROM processed WHERE id=?", (event["id"],)).fetchone():
                continue
            conn.execute("INSERT INTO processed VALUES (?,?)", (event["id"], json.dumps(event, sort_keys=True)))
            if event["error_category"] in {"normal", "policy_rejection"}:
                continue
            key = event["fingerprint"]
            previous = conn.execute("SELECT row FROM problems WHERE id=?", (key,)).fetchone()
            row = json.loads(previous[0]) if previous else {"id": key, "first_seen": event["at"], "occurrences": 0, "repair_commit": None, "verification": None}
            transition = "reopened" if row.get("status") == "closed" else "occurred" if previous else "discovered"
            row.update(status="open", last_seen=event["at"], last_event=event["id"],
                       occurrences=row["occurrences"] + 1, evidence_status="observed",
                       error_category=event["error_category"], lane_id=event["lane_id"])
            conn.execute("INSERT OR REPLACE INTO problems VALUES (?,?)", (key, json.dumps(row, sort_keys=True)))
            conn.execute("INSERT INTO history(problem,at,transition,evidence) VALUES (?,?,?,?)", (key, event["at"], transition, event["id"]))
    # Delivery acknowledgment removes only the duplicate transport copy, after
    # durable archival of all structured facts. The authoritative history stays.
    if observed["rows"]:
        with closing(connect(home)) as archive:
            acknowledged = [(e["id"],) for e in observed["rows"] if archive.execute("SELECT 1 FROM processed WHERE id=?", (e["id"],)).fetchone()]
        with closing(sqlite3.connect(recorder.database(home), timeout=.05)) as queue, queue:
            queue.executemany("DELETE FROM observations WHERE id=?", acknowledged)
    return {"schema": SCHEMA, "observer_status": observed["status"], **problem_status(home)}


def problem_status(home):
    path = home / "life/problems/ledger.sqlite3"
    if not path.exists():
        return {"status": "unobserved", "problems": [], "reason": "no_problem_ledger"}
    try:
        with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=.2)) as conn:
            rows = [json.loads(x[0]) for x in conn.execute("SELECT row FROM problems ORDER BY id")]
        return {"status": "open" if any(r["status"] == "open" for r in rows) else "observed", "problems": rows}
    except (sqlite3.Error, ValueError):
        return {"status": "unavailable", "problems": [], "reason": "problem_ledger_unreadable"}


def verify_problem(home, key, *, command, repair_commit, source_root, timeout=30):
    """Explicit local verifier; never redispatch the original business action.

    Caller supplies an independently selected regression/verifier, not a claimed
    proof JSON. A clean exact Git revision and unchanged occurrence are required.
    This receipt is local test evidence and never production permission.
    """
    if not re.fullmatch(r"[a-f0-9]{40,64}", repair_commit) or not command or not 0 < timeout <= 30:
        raise ValueError("exact repair revision, verifier command and bounded timeout required")
    def git(*args):
        return subprocess.run(["git", "-C", str(source_root), *args], capture_output=True,
                              text=True, encoding="utf-8", errors="replace", timeout=3)
    head = git("rev-parse", "HEAD")
    if head.returncode or head.stdout.strip() != repair_commit or git("status", "--porcelain").stdout.strip():
        raise ValueError("verifier source does not match clean repair commit")
    def observation():
        try:
            result = aggregate(home)
            return result.get("observer_status", "unavailable") if isinstance(result, dict) else "unavailable"
        except (OSError, ValueError, RuntimeError, sqlite3.Error):
            return "unavailable"
    observation_before = observation()
    with closing(connect(home)) as conn:
        selected = conn.execute("SELECT row FROM problems WHERE id=?", (key,)).fetchone()
    if not selected:
        raise ValueError("problem not discovered")
    before = json.loads(selected[0])
    receipt = {"sourceVersion": repair_commit, "generatorVersion": SCHEMA,
               "verifier_argv_sha256": sha(command), "observed_at": now(), "status": "failed"}
    try:
        completed = subprocess.run(command, cwd=source_root, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   timeout=timeout, check=False)
        receipt.update(exit_code=completed.returncode, status="passed" if completed.returncode == 0 else "failed")
    except (OSError, subprocess.TimeoutExpired) as error:
        receipt.update(exit_code=None, reason=type(error).__name__)
    if git("rev-parse", "HEAD").stdout.strip() != repair_commit or git("status", "--porcelain").stdout.strip():
        receipt.update(status="inconclusive", reason="source_changed_during_verification")
    observation_after = observation()
    receipt["observation"] = {"before": observation_before, "after": observation_after}
    if observation_before != "observed" or observation_after != "observed":
        receipt.update(status="inconclusive", reason="observation_incomplete")
    with closing(connect(home)) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        row = json.loads(conn.execute("SELECT row FROM problems WHERE id=?", (key,)).fetchone()[0])
        if row["last_event"] != before["last_event"]:
            receipt.update(status="inconclusive", reason="recurrence_during_verification")
        row.update(repair_commit=repair_commit, verification=receipt)
        if receipt["status"] == "passed":
            row.update(status="closed", evidence_status="verified")
        conn.execute("UPDATE problems SET row=? WHERE id=?", (json.dumps(row, sort_keys=True), key))
        conn.execute("INSERT INTO history(problem,at,transition,evidence) VALUES (?,?,?,?)",
                     (key, now(), "closed" if row["status"] == "closed" else "verification_failed", json.dumps(receipt, sort_keys=True)))
    return row


def read_fact(path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def domains(home, operational):
    beat = read_fact(home / "heartbeat-state.json")
    hook = observer().read_rows(home)
    return {
        "scheduling": {"status": operational.get("scheduler_readiness", {}).get("status", "unobserved"), "source": "runtime-owner/scheduler probe"},
        "collection": {"status": beat.get("collection_status", "unobserved"), "collected_at": beat.get("last_ts"), "source": "heartbeat-state.json"},
        "heartbeat_generation": {"status": beat.get("last_mode", "unobserved"), "collected_at": beat.get("last_ts"), "reason": beat.get("last_degraded_reason"), "source": "heartbeat-state.json"},
        "hooks": {"status": hook["status"], "count": len(hook["rows"]), "source": "independent hook recorder", "blind_spots": hook.get("blind_spots", [])},
        "recovery_verification": {"status": "verified" if operational.get("recovery_readiness", {}).get("last_recovery_verified") else "unverified", "scope": "last_terminal_not_current_permission", "source": "sealed recovery terminal and verifier receipt"},
        "knowledge_processing": {name: {"status": read_fact(home / path).get("status", "unobserved"), "source": path} for name, path in {"L2": "l2/registry.json", "L3": "l3/registry.json", "L4": "goals/registry.json"}.items()},
        "problems": problem_status(home),
        "synchronization": sync_preflight(home),
    }


def sync_preflight(home):
    """Inspect existing local state/receipts; network effects remain unknown."""
    config = read_fact(home / "mem-sync.json")
    result = {"scope": "local_readback_only", "collected_at": now(), "source": "mem-sync.json/state/transaction",
              "external_effect": "unknown", "retry_performed": False}
    if not config.get("repo_path"):
        return {**result, "status": "unavailable", "reason": "configuration_missing"}
    try:
        repo = sync_repository_path(config["repo_path"], home=home)
    except SuldePathError:
        return {**result, "status": "migration_required", "reason": "repository_outside_current_data_root_or_unsafe"}
    state = read_fact(home / "mem-sync-state.json")
    journal = home / "mem-sync-export-transaction.json"
    return {**result, "status": "unsettled" if journal.exists() else "local_ready" if repo.is_dir() else "unavailable",
            "repository_exists": repo.is_dir(), "state_projects": len(state["projects"]) if isinstance(state.get("projects"), dict) else None,
            "transaction_present": journal.exists(), "repository_id": sha(str(repo)),
            "migration_receipt_present": (home / "mem-sync-legacy-migration.json").is_file(),
            "reason": "external_receipt_not_verified"}


def queue_plan(home):
    """Read-only exact duplicate plan. No semantic merge, deletion or KB write."""
    queues = {}
    for name in ("self-repair/pending.json", "golden-candidates.jsonl"):
        path = home / name
        try:
            raw = path.read_bytes()
            rows = json.loads(raw) if name.endswith(".json") else [json.loads(line) for line in raw.splitlines() if line.strip()]
            groups = {}
            related = {}
            statuses = {}
            for row in rows:
                # Identical content excluding volatile bookkeeping is reviewable;
                # similarity of prose alone is not a duplicate verdict.
                material = {k: v for k, v in row.items() if k not in {"id", "slug", "created_at", "drafted_at", "updated_at", "status", "attempts"}}
                groups.setdefault(sha(material), []).append({"id": sha(row.get("id") or row.get("slug")), "status": row.get("status", "unknown")})
                status = row.get("status", "unknown")
                statuses[status] = statuses.get(status, 0) + 1
                source = str(row.get("source") or "")
                if source:
                    topic = re.sub(r"\d{4}-?\d{2}-?\d{2}", "DATE", source.rsplit("/", 1)[-1])
                    related.setdefault(sha([row.get("severity"), row.get("task_type"), topic]), []).append({"id": sha(row.get("id") or row.get("slug")), "status": status})
            queues[name] = {"status": "observed", "sourceVersion": hashlib.sha256(raw).hexdigest(),
                            "collected_at": now(), "scope": "exact content duplicates only", "count": len(rows),
                            "duplicate_groups": [v for v in groups.values() if len(v) > 1],
                            "related_issue_groups": [v for v in related.values() if len(v) > 1], "status_counts": statuses,
                            "related_evidence_status": "review_required_not_duplicate_verdict",
                            "plan": "review each duplicate; preserve unresolved, terminal evidence and candidates; no automatic deletion"}
        except (OSError, ValueError, TypeError, AttributeError) as error:
            queues[name] = {"status": "unavailable", "count": None, "reason": type(error).__name__, "collected_at": now()}
    return {"generatorVersion": SCHEMA, "writes": 0, "queues": queues}
