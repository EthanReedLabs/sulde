#!/usr/bin/env python3
"""Project Sulde's L2-L4 lifecycle into one auditable, heartbeat-driven truth."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from operational_readiness import project as operational_readiness_projection  # noqa: E402
from sulde_paths import kb_home as canonical_kb_home
from life_health import aggregate as aggregate_problems, domains as health_domains
from production_recovery_readiness import (  # noqa: E402
    observe_recovery_truth,
    provision_recovery_key,
)


L2_SCRIPT = Path(__file__).with_name("l2-draft.py")
EVOLUTION_SCRIPT = Path(__file__).with_name("organ-evolution.py")
TEST_EVIDENCE_SCRIPT = Path(__file__).with_name("test-evidence.py")
SELF_REPAIR_SCRIPT = Path(__file__).with_name("self-repair.py")
TERMINAL_L3 = {"executed", "diagnosed", "rejected", "resolved", "aborted"}
L3_EXECUTION_STALE_SECONDS = 1_500
LIFE_CYCLE_SCHEDULER_LABEL = "com.sulde.life-cycle"
SCHEDULER_EXECUTION_GATES = {
    "artifact_generation_ready",
    "environment_generation_matches",
    "generation_matches",
    "managed_actor_inventory_matches",
    "provider_matches",
    "runtime_executable_available",
    "runtime_owner_active",
    "runtime_owner_present",
    "runtime_root_matches",
    "runtime_tree_digest_matches",
}


def kb_home() -> Path:
    return canonical_kb_home()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return default


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def l3_projection(home: Path) -> dict[str, Any]:
    rows = read_json(home / "self-repair/pending.json", [])
    if not isinstance(rows, list):
        rows = []
    counts: dict[str, int] = {}
    items = []
    closure = load_module("sulde_self_repair_projection", SELF_REPAIR_SCRIPT).project_queue(rows)
    now = datetime.now(timezone.utc)
    stale_executing = 0
    for row in rows:
        if not isinstance(row, dict) or not row.get("slug"):
            continue
        status = str(row.get("status", "unknown"))
        counts[status] = counts.get(status, 0) + 1
        if status == "executing":
            try:
                started = datetime.fromisoformat(
                    str(row.get("execution_started_at") or "").replace("Z", "+00:00")
                )
                if started.tzinfo is None or started.utcoffset() is None:
                    raise ValueError("naive timestamp")
                stale_executing += (now - started.astimezone(timezone.utc)).total_seconds() > L3_EXECUTION_STALE_SECONDS
            except (TypeError, ValueError, OverflowError):
                stale_executing += 1
        items.append({key: row.get(key) for key in (
            "slug", "status", "task_type", "brief_path", "branch", "worktree",
            "verify_scope", "executed_at", "diagnosed_at", "failure_reason",
            "pause_reason", "intervention_reason", "intervention_ids",
            "execution_started_at", "awaiting_human_at", "aborted_at",
        ) if row.get(key) is not None})
    actionable = counts.get("approved", 0)
    failures = counts.get("failed", 0)
    awaiting_human = counts.get("awaiting_human", 0)
    semantic_pauses = counts.get("paused", 0)
    timeouts = counts.get("timeout", 0)
    running = counts.get("executing", 0)
    if failures or semantic_pauses or timeouts or stale_executing:
        status = "blocked"
    elif awaiting_human:
        status = "awaiting_human"
    elif running:
        status = "running"
    else:
        status = "ready"
    return {
        "schema": "sulde-l3-registry-v1",
        "generated_at": now_iso(),
        "status": status,
        "counts": counts,
        "actionable": actionable,
        "awaiting_human": awaiting_human,
        "stale_executing": stale_executing,
        "terminal": sum(counts.get(status, 0) for status in TERMINAL_L3),
        "closure": closure,
        "closure_counts": closure["counts"],
        "items": items,
        "loop": {
            "discover": "heartbeat/self-repair --draft",
            "authorize": "human approval record",
            "execute": "isolated git worktree via selected Sulde agent provider",
            "verify": "agent-runtime.py verify + project tests + mem-golden",
            "adjudicate_unknown": "durable intervention inbox + human CLI decision + identity-guarded resume",
            "integrate": "reviewed branch candidate; protected operation remains human-owned",
        },
    }


def goal_id(kind: str, target: str) -> str:
    return "goal-" + hashlib.sha256(f"{kind}:{target}".encode()).hexdigest()[:12]


def proposed_goals(l2: dict[str, Any], l3: dict[str, Any]) -> list[dict[str, Any]]:
    goals: list[dict[str, Any]] = []
    if l2.get("status") != "ready":
        goals.append({"kind": "restore_l2", "target": "missing channels", "priority": 100})
    for name, channel in l2.get("channels", {}).items():
        pending = int(channel.get("pending", 0))
        if pending:
            goals.append({"kind": "reduce_backlog", "target": name, "priority": min(90, 40 + pending)})
    if l3.get("counts", {}).get("failed", 0):
        goals.append({"kind": "repair_l3_failure", "target": "failed self-repair", "priority": 95})
    if l3.get("awaiting_human", 0):
        goals.append({"kind": "human_intervention_required", "target": "unknown external effect", "priority": 100})
    if l3.get("counts", {}).get("paused", 0):
        goals.append({"kind": "review_l3_intent", "target": "semantic guardian pause", "priority": 98})
    if l3.get("stale_executing", 0):
        goals.append({"kind": "repair_stale_l3_execution", "target": "stale executing task", "priority": 97})
    if l3.get("actionable", 0):
        goals.append({"kind": "execute_approved", "target": "approved self-repair", "priority": 80})
    return goals


def reconcile_goals(home: Path, proposals: list[dict[str, Any]]) -> dict[str, Any]:
    path = home / "goals/registry.json"
    previous = read_json(path, {})
    old_items = {row.get("id"): row for row in previous.get("items", []) if isinstance(row, dict)} if isinstance(previous, dict) else {}
    timestamp = now_iso()
    items = []
    live_ids = set()
    for proposal in proposals:
        identifier = goal_id(proposal["kind"], proposal["target"])
        live_ids.add(identifier)
        old = old_items.get(identifier, {})
        status = old.get("status", "active")
        if status == "completed":
            status = "active"
        items.append({
            "id": identifier,
            **proposal,
            "status": status,
            "created_at": old.get("created_at", timestamp),
            "last_observed_at": timestamp,
            "evidence": f"derived from lifecycle truth at {timestamp}",
            "action_boundary": "draft/evaluate autonomously; protected writes require human approval",
        })
    for identifier, old in old_items.items():
        if identifier not in live_ids and old.get("status") not in {"completed", "rejected"}:
            completed = dict(old)
            completed["status"] = "completed"
            completed["completed_at"] = timestamp
            completed["completion_evidence"] = "trigger condition absent in current lifecycle truth"
            items.append(completed)
    items.sort(key=lambda row: (-int(row.get("priority", 0)), str(row.get("id"))))
    registry = {
        "schema": "sulde-l4-goals-v1",
        "generated_at": timestamp,
        "status": "ready",
        "policy": "evidence-derived goals may grow autonomously; constitution and protected actions cannot",
        "items": items,
        "active": sum(row.get("status") == "active" for row in items),
        "completed": sum(row.get("status") == "completed" for row in items),
    }
    return registry


def _canonical_digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _readback_matches(path: Path, expected: dict[str, Any]) -> bool:
    actual = read_json(path, None)
    return isinstance(actual, dict) and _canonical_digest(actual) == _canonical_digest(expected)


def closed_loop_projection(
    l2: dict[str, Any],
    l3: dict[str, Any],
    l4: dict[str, Any],
    evolution: dict[str, Any],
    operational: dict[str, Any],
    *,
    readback: dict[str, bool] | None = None,
) -> dict[str, Any]:
    """Report independently evidenced loop dimensions and authority gates."""
    evidence = readback or {}
    interactive = (
        operational.get("interactive_readiness")
        if isinstance(operational.get("interactive_readiness"), dict)
        else {}
    )
    scheduler = (
        operational.get("scheduler_readiness")
        if isinstance(operational.get("scheduler_readiness"), dict)
        else {}
    )
    gates = interactive.get("gates") if isinstance(interactive.get("gates"), dict) else {}
    items = l3.get("items") if isinstance(l3.get("items"), list) else []
    awaiting = [
        row for row in items
        if isinstance(row, dict) and row.get("status") == "awaiting_human"
    ]
    interventions_bound = all(
        isinstance(row.get("intervention_ids"), list) and bool(row["intervention_ids"])
        for row in awaiting
    )
    effect = (
        operational.get("effect_truth")
        if isinstance(operational.get("effect_truth"), dict)
        else {}
    )
    closure_counts = (
        l3.get("closure_counts")
        if isinstance(l3.get("closure_counts"), dict)
        else {}
    )
    no_l3_failure = not any(
        int(l3.get("counts", {}).get(name, 0))
        for name in ("failed", "paused", "timeout")
    ) and not int(l3.get("stale_executing", 0))
    no_unresolved = not int(closure_counts.get("unresolved", 0))
    all_persisted = all(
        evidence.get(name) is True for name in ("l2", "l3", "l4", "evolution")
    )
    scheduler_scope = operational.get("readiness_scope") == "scheduler"
    if scheduler_scope:
        delivery_ready = scheduler.get("status") == "ready"
        dimensions = {
            "sense": bool(delivery_ready and evidence.get("l2")),
            "persist": bool(delivery_ready and all_persisted),
            "decide": bool(delivery_ready and evidence.get("l4")),
            "act": bool(
                delivery_ready
                and evidence.get("l3")
                and l3.get("status") in {"ready", "running"}
            ),
            "verify": bool(
                delivery_ready
                and evidence.get("l3")
                and no_l3_failure
                and no_unresolved
            ),
        }
        human_gates = {
            "preserved": False,
            "current_permission_pairing": False,
            "unknown_effects_fail_closed": bool(interventions_bound),
            "reason": "scheduler delivery does not prove a current human decision lane",
        }
        identity_resume = {
            "guarded": False,
            "current_session_bound": False,
            "workspace_bound": False,
            "formal_continuation_only": True,
            "authority_transferred": False,
            "reason": "no current interactive session identity",
        }
    else:
        dimensions = {
            "sense": bool(evidence.get("l2") and gates.get("host_interactive_fresh")),
            "persist": bool(all_persisted and gates.get("contract_active")),
            "decide": bool(evidence.get("l4") and gates.get("contract_active")),
            "act": bool(
                evidence.get("l3")
                and l3.get("status") in {"ready", "running"}
                and gates.get("contract_enforced")
            ),
            "verify": bool(
                evidence.get("l3")
                and no_l3_failure
                and no_unresolved
                and effect.get("status") == "clear"
            ),
        }
        human_gates = {
            "preserved": bool(
                gates.get("contract_active")
                and gates.get("permission_request_fresh")
                and gates.get("native_decision_pairing_settled")
                and interventions_bound
            ),
            "current_permission_pairing": bool(
                gates.get("native_decision_pairing_settled")
            ),
            "unknown_effects_fail_closed": bool(
                gates.get("contract_active")
                and interventions_bound
                and (
                    (not awaiting and effect.get("status") == "clear")
                    or l3.get("status") == "awaiting_human"
                )
            ),
            "reason": "",
        }
        identity_resume = {
            "guarded": bool(
                gates.get("contract_active")
                and interventions_bound
                and gates.get("current_session_bound")
                and gates.get("workspace_bound")
                and gates.get("task_lane_bound")
                and gates.get("native_decision_pairing_settled")
            ),
            "current_session_bound": bool(gates.get("current_session_bound")),
            "workspace_bound": bool(gates.get("workspace_bound")),
            "formal_continuation_only": True,
            "authority_transferred": False,
            "reason": "",
        }
    overall = bool(
        all(dimensions.values())
        and human_gates["preserved"]
        and human_gates["unknown_effects_fail_closed"]
        and identity_resume["guarded"]
        and evolution.get("status") == "ready"
    )
    return {
        "schema": "sulde-closed-loop-projection-v2",
        "dimensions": dimensions,
        "human_gates": human_gates,
        "identity_resume": identity_resume,
        "evolution_ready": evolution.get("status") == "ready",
        "readback": dict(sorted(evidence.items())),
        "overall_ready": overall,
        "sense": dimensions["sense"],
        "persist": dimensions["persist"],
        "decide": dimensions["decide"],
        "act_within_boundary": dimensions["act"],
        "verify": dimensions["verify"],
        "human_gates_preserved": human_gates["preserved"],
        "unknown_effects_fail_closed": human_gates["unknown_effects_fail_closed"],
        "identity_guarded_resume": identity_resume["guarded"],
        "evolve_organs": evolution.get("status") == "ready",
    }


def build(
    home: Path,
    apply: bool = False,
    *,
    scheduler_probe: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if apply:
        provision_recovery_key(home)
        try:
            aggregate_problems(home)
        except (OSError, RuntimeError, ValueError, sqlite3.Error) as error:
            print(f"WARN independent problem aggregation unavailable: {type(error).__name__}", file=sys.stderr)
    l2 = load_module("sulde_l2_lifecycle", L2_SCRIPT).build_registry(home)
    l3 = l3_projection(home)
    evolution = load_module("sulde_organ_evolution", EVOLUTION_SCRIPT).reconcile(home, l2, l3, apply)
    if apply:
        l3 = l3_projection(home)
    l4 = reconcile_goals(home, proposed_goals(l2, l3))
    if apply:
        atomic_json(home / "l2/registry.json", l2)
        atomic_json(home / "l3/registry.json", l3)
        atomic_json(home / "goals/registry.json", l4)
    operational = operational_readiness_projection(
        home,
        scheduler_probe=scheduler_probe,
        recovery_truth=observe_recovery_truth(home),
    )
    test_evidence = {"status": "dry_run", "removed": 0}
    if apply:
        try:
            test_evidence = load_module(
                "sulde_test_evidence_gc", TEST_EVIDENCE_SCRIPT
            ).gc_records(home.parent / "test-evidence", scheduled=True)
        except (OSError, RuntimeError, ValueError) as error:
            # Retention is housekeeping, not an operational authority gate.
            test_evidence = {
                "status": "degraded",
                "removed": 0,
                "reason": type(error).__name__,
            }
    readback = {
        "l2": _readback_matches(home / "l2/registry.json", l2),
        "l3": _readback_matches(home / "l3/registry.json", l3),
        "l4": _readback_matches(home / "goals/registry.json", l4),
        "evolution": _readback_matches(home / "evolution/registry.json", evolution),
    }
    closed_loop = closed_loop_projection(
        l2, l3, l4, evolution, operational, readback=readback
    )
    ready = bool(
        all(row.get("status") == "ready" for row in (l2, l3, l4, evolution))
        and operational.get("status") == "ready"
        and closed_loop["overall_ready"]
    )
    return {
        "schema": "sulde-life-cycle-v2",
        "generated_at": now_iso(),
        "status": "ready" if ready else "degraded",
        "levels": {
            "L2": {"status": l2.get("status"), "truth": str(home / "l2/registry.json")},
            "L3": {"status": l3.get("status"), "truth": str(home / "l3/registry.json")},
            "L4": {"status": l4.get("status"), "truth": str(home / "goals/registry.json")},
        },
        "closed_loop": closed_loop,
        "operational_readiness": operational,
        "evolution": {
            "status": evolution.get("status"),
            "active": evolution.get("active", 0),
            "recommendations": evolution.get("recommendations", 0),
            "truth": str(home / "evolution/registry.json"),
        },
        "test_evidence_retention": test_evidence,
        "health_domains": health_domains(home, operational),
        "payloads": {"l2": l2, "l3": l3, "l4": l4, "evolution": evolution},
    }


def scheduler_execution_succeeded(state: dict[str, Any]) -> bool:
    """Separate a completed background projection from global LIFE readiness.

    A scheduler has no current human/session identity, so the global closed-loop
    projection intentionally remains degraded there.  That expected semantic
    result must not become the actor's own non-zero launchd status and feed back
    into scheduler health.  Only the LIFE actor's previous exit is tolerated;
    every other delivery, persistence, level, or effect-boundary failure remains
    a real process failure.
    """
    operational = state.get("operational_readiness")
    closed_loop = state.get("closed_loop")
    levels = state.get("levels")
    evolution = state.get("evolution")
    if not all(
        isinstance(value, dict)
        for value in (operational, closed_loop, levels, evolution)
    ):
        return False
    if operational.get("readiness_scope") != "scheduler":
        return state.get("status") == "ready"
    if not all(
        isinstance(levels.get(name), dict)
        and levels[name].get("status") == "ready"
        for name in ("L2", "L3", "L4")
    ) or evolution.get("status") != "ready":
        return False
    readback = closed_loop.get("readback")
    human_gates = closed_loop.get("human_gates")
    if not isinstance(readback, dict) or not all(
        readback.get(name) is True for name in ("l2", "l3", "l4", "evolution")
    ):
        return False
    if not isinstance(human_gates, dict) or not human_gates.get(
        "unknown_effects_fail_closed"
    ):
        return False
    scheduler = operational.get("scheduler_readiness")
    if not isinstance(scheduler, dict):
        return False
    gates = scheduler.get("gates")
    probe = scheduler.get("process_probe")
    if not isinstance(gates, dict) or not isinstance(probe, dict):
        return False
    if not SCHEDULER_EXECUTION_GATES.issubset(gates) or not all(
        gates.get(name) is True for name in SCHEDULER_EXECUTION_GATES
    ):
        return False
    failed = probe.get("failed_labels")
    reasons = probe.get("reasons")
    return bool(
        probe.get("probe_status") == "observed"
        and probe.get("managed") == probe.get("loaded")
        and probe.get("missing_labels") == []
        and probe.get("retired_loaded_labels") == []
        and isinstance(failed, dict)
        and set(failed).issubset({LIFE_CYCLE_SCHEDULER_LABEL})
        and isinstance(reasons, list)
        and set(reasons).issubset({"managed_actor_last_exit_nonzero"})
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--run", action="store_true")
    mode.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    home = kb_home()
    state = build(home, args.run)
    if args.run:
        atomic_json(home / "l2/registry.json", state["payloads"]["l2"])
        atomic_json(home / "l3/registry.json", state["payloads"]["l3"])
        atomic_json(home / "goals/registry.json", state["payloads"]["l4"])
        summary = {key: value for key, value in state.items() if key != "payloads"}
        atomic_json(home / "life/state.json", summary)
    counts = state["payloads"]["l4"]
    execution_succeeded = scheduler_execution_succeeded(state)
    print(f"LIFE CYCLE: {state['status'].upper()} L2={state['levels']['L2']['status']} L3={state['levels']['L3']['status']} L4={state['levels']['L4']['status']} evolution={state['evolution']['status']} goals_active={counts['active']} writes={1 if args.run else 0} execution={'ready' if execution_succeeded else 'failed'}")
    return 0 if execution_succeeded else 1


if __name__ == "__main__":
    raise SystemExit(main())
