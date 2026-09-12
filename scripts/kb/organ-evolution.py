#!/usr/bin/env python3
"""Create and evaluate evidence-driven upgrades for Sulde organs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CHANNEL_ORGANS = {
    "sediment_draft": ("auto-sediment", "scripts/kb/auto-sediment.py", 90),
    "golden_case": ("golden-review", "scripts/kb/golden-review.py", 80),
    "threshold_proposal": ("governance-review", "scripts/kb/governance-review.py", 60),
}
CLOSED_EXPERIMENTS = {"retained", "rolled_back", "inconclusive", "rejected"}
OBSERVATIONS_REQUIRED = 2


def kb_home() -> Path:
    configured = os.environ.get("SULDE_KB_HOME")
    return Path(configured).expanduser() if configured else Path.home() / ".sulde/data/kb"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return default


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def atomic_json(path: Path, payload: Any) -> None:
    atomic_write(path, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def experiment_id(organ: str, signal: str) -> str:
    return "evo-" + hashlib.sha256(f"{organ}:{signal}".encode()).hexdigest()[:12]


def opportunities(l2: dict[str, Any], l3: dict[str, Any]) -> list[dict[str, Any]]:
    # wp_brief.pending is a human-review queue, not failed execution. Mapping it
    # to self-repair would make the repair task itself create another repair task.
    rows: list[dict[str, Any]] = []
    for channel, (organ, source, priority) in CHANNEL_ORGANS.items():
        pending = int(l2.get("channels", {}).get(channel, {}).get("pending", 0))
        if pending:
            rows.append({
                "organ": organ,
                "source": source,
                "signal": f"l2_backlog:{channel}",
                "metric": f"l2.channels.{channel}.pending",
                "baseline_value": pending,
                "priority": min(100, priority + min(9, pending // 10)),
                "hypothesis": f"升级 {organ} 的可靠性或吞吐后，{channel} 待处理数应低于 {pending}",
            })
    failures = int(l3.get("counts", {}).get("failed", 0))
    if failures:
        rows.append({
            "organ": "self-repair",
            "source": "scripts/kb/self-repair.py",
            "signal": "l3_failed",
            "metric": "l3.counts.failed",
            "baseline_value": failures,
            "priority": 100,
            "hypothesis": f"升级 self-repair 的恢复或验收后，失败项应低于 {failures}",
        })
    return sorted(rows, key=lambda row: (-row["priority"], row["signal"]))


def metric_value(metric: str, l2: dict[str, Any], l3: dict[str, Any]) -> int | None:
    parts = metric.split(".")
    value: Any = {"l2": l2, "l3": l3}.get(parts[0])
    for part in parts[1:]:
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return int(value) if isinstance(value, int) and not isinstance(value, bool) else None


def build_brief(experiment: dict[str, Any]) -> str:
    return f"""# 器官升级实验：{experiment['organ']} — {experiment['signal']}

## 目标
在不修改法典、知识资产、治理阈值和外部系统的前提下，诊断并升级 `{experiment['organ']}`，验证假设：{experiment['hypothesis']}。

## 范围
- 主要器官：`{experiment['source']}`
- 允许修改：该器官、直接相关测试与非宪法文档。
- 禁止修改：`knowledge/**`、`templates/SELF.md` 法典段、`scripts/kb/thresholds.json`、任何同步/出境配置。

## 已知上下文
- 实验 ID：`{experiment['id']}`
- 触发信号：`{experiment['signal']}`
- 基线指标：`{experiment['metric']} = {experiment['baseline_value']}`
- 成功标准：完成 L3 隔离验收后，至少 {OBSERVATIONS_REQUIRED} 次独立生命周期观察均取得有效样本，且最后样本小于基线；否则只能建议回退或记为 inconclusive。
- 禁止用本实验生成的数据给自身验收；代码测试与运行效果必须分别取证。

## 完成标准
1. 给出一手根因证据，并说明为什么改动能影响登记指标。
2. 改动保持在允许范围，新增回归测试且全量测试通过。
3. 记录升级前后代码差异，但不得在执行器内 commit、push 或合并。
4. 完成完整五段报告；每项结论附命令、exit code 和输出摘要。
5. L3 仅形成候选分支；上线、保留或回退由后续人类闸门决定。

## 体量与熔断
三次修复尝试仍不通过即停止；若需触及任一永久禁区，立即停止并上报。

## 汇报硬性要求
必须包含且各出现一次：## 结果、## 过程、## 遇到的问题、## 解决方式、## 遗留风险与建议。
"""


def _queue_authority_debt(task: dict[str, Any]) -> bool:
    effect = str(task.get("effect") or task.get("effect_class") or "").lower()
    if effect in {"external", "external_write", "destructive", "unknown"}:
        return True
    if task.get("unknown_effect") is True or task.get("awaiting_human") is True:
        return True
    for key in (
        "open_events", "open_event_ids", "pending_attempts", "attempt_ids",
        "grants", "grant_ids", "pending_verifications", "verification_ids",
        "intervention_ids",
    ):
        value = task.get(key)
        if isinstance(value, (list, dict)) and bool(value):
            return True
        if isinstance(value, str) and value.strip():
            return True
    return str(task.get("status") or "") in {"paused", "awaiting_human", "executing"}


def _queue_verified_evidence(task: dict[str, Any]) -> bool:
    checks = task.get("checks")
    direct = any(
        str(task.get(key) or "").strip()
        for key in (
            "resolution_evidence", "evidence_sha256", "verification_sha256",
            "terminal_evidence_sha256",
        )
    )
    return direct or (
        isinstance(checks, list)
        and bool(checks)
        and all(isinstance(row, dict) and row.get("passed") is True for row in checks)
    )


def queue_closure_status(task: dict[str, Any] | None) -> str:
    """Compatibility projection: evidence, never a legacy label, closes work."""
    if not isinstance(task, dict):
        return "unresolved"
    if _queue_authority_debt(task):
        return "unresolved"
    explicit = str(task.get("closure_status") or "")
    if explicit in {"verified", "inconclusive", "unresolved", "superseded", "expired"}:
        if explicit == "verified" and not _queue_verified_evidence(task):
            return "inconclusive"
        return explicit
    status = str(task.get("status") or "unknown")
    if status in {"rejected", "superseded"}:
        return "superseded"
    if status in {"failed", "timeout", "aborted"}:
        return "unresolved"
    if status in {"resolved", "executed", "success", "verified"}:
        return "verified" if _queue_verified_evidence(task) else "inconclusive"
    return "inconclusive"


def reconcile(home: Path, l2: dict[str, Any], l3: dict[str, Any], apply: bool) -> dict[str, Any]:
    path = home / "evolution/registry.json"
    previous = read_json(path, {})
    items = [dict(row) for row in previous.get("items", []) if isinstance(row, dict)] if isinstance(previous, dict) else []
    by_id = {str(row.get("id")): row for row in items if row.get("id")}
    pending = read_json(home / "self-repair/pending.json", [])
    if not isinstance(pending, list):
        pending = []
    pending_by_slug = {str(row.get("slug")): row for row in pending if isinstance(row, dict) and row.get("slug")}
    timestamp = now_iso()

    for item in items:
        if item.get("status") in CLOSED_EXPERIMENTS:
            continue
        task = pending_by_slug.get(str(item.get("task_slug")))
        task_status = str(task.get("status")) if task else "missing"
        closure_status = queue_closure_status(task)
        item["l3_status"] = task_status
        item["l3_closure_status"] = closure_status
        if closure_status == "unresolved":
            item["status"] = "blocked"
            item["blocked_reason"] = str(
                (task or {}).get("failure_reason") or "L3 truth remains unresolved"
            )[:1000]
        elif closure_status == "verified":
            if item.get("status") not in {"observing", "retain_recommended", "rollback_recommended"}:
                item["status"] = "observing"
                item["observation_started_at"] = timestamp
            value = metric_value(str(item["metric"]), l2, l3)
            samples = item.setdefault("observations", [])
            if value is not None and (not samples or samples[-1].get("observed_at") != timestamp):
                samples.append({"observed_at": timestamp, "value": value})
            if len(samples) >= int(item.get("observations_required", OBSERVATIONS_REQUIRED)):
                last = int(samples[-1]["value"])
                baseline = int(item["baseline_value"])
                item["status"] = "retain_recommended" if last < baseline else "rollback_recommended"
                item["decision_reason"] = f"last={last} baseline={baseline} samples={len(samples)}"

    active = [row for row in items if row.get("status") not in CLOSED_EXPERIMENTS]
    if not active:
        for opportunity in opportunities(l2, l3):
            identifier = experiment_id(opportunity["organ"], opportunity["signal"])
            old = by_id.get(identifier)
            if old and old.get("status") in CLOSED_EXPERIMENTS:
                continue
            slug = f"organ-upgrade-{identifier}"
            brief = home / "evolution/briefs" / f"{identifier}.brief.md"
            experiment = {
                "id": identifier,
                **opportunity,
                "status": "drafted",
                "created_at": timestamp,
                "task_slug": slug,
                "brief_path": str(brief),
                "observations_required": OBSERVATIONS_REQUIRED,
                "observations": [],
                "action_boundary": "L3 isolated candidate; retain/rollback requires human approval",
            }
            items.append(experiment)
            if apply:
                atomic_write(brief, build_brief(experiment))
                pending.append({
                    "slug": slug,
                    "source": f"organ-evolution:{identifier}",
                    "severity": "evolution",
                    "brief_path": str(brief),
                    "drafted_at": timestamp,
                    "status": "pending",
                    "task_type": "implementation",
                    "experiment_id": identifier,
                })
            break

    registry = {
        "schema": "sulde-organ-evolution-v1",
        "generated_at": timestamp,
        "status": "ready",
        "policy": "measure before change; L3 isolates implementation; observe independently; human retains or rolls back",
        "items": items,
        "active": sum(row.get("status") not in CLOSED_EXPERIMENTS for row in items),
        "recommendations": sum(str(row.get("status", "")).endswith("_recommended") for row in items),
    }
    if apply:
        atomic_json(path, registry)
        atomic_json(home / "self-repair/pending.json", pending)
    return registry


def decide(home: Path, identifier: str, decision: str, evidence: str) -> dict[str, Any]:
    """Record the human gate after an experiment has produced a recommendation."""
    path = home / "evolution/registry.json"
    registry = read_json(path, {})
    items = registry.get("items", []) if isinstance(registry, dict) else []
    if not isinstance(items, list):
        raise ValueError("invalid evolution registry")
    target = next((row for row in items if isinstance(row, dict) and row.get("id") == identifier), None)
    if target is None:
        raise ValueError(f"unknown experiment: {identifier}")
    allowed = {
        "retain": ("retain_recommended", "retained"),
        "rollback": ("rollback_recommended", "rolled_back"),
        "inconclusive": (None, "inconclusive"),
        "reject": (None, "rejected"),
    }
    required, status = allowed[decision]
    if required and target.get("status") != required:
        raise ValueError(f"{decision} requires status {required}, got {target.get('status')}")
    if target.get("status") in CLOSED_EXPERIMENTS:
        raise ValueError(f"experiment already closed: {target.get('status')}")
    timestamp = now_iso()
    target["status"] = status
    target["human_decision"] = decision
    target["decision_evidence"] = evidence
    target["decided_at"] = timestamp
    registry["generated_at"] = timestamp
    registry["active"] = sum(row.get("status") not in CLOSED_EXPERIMENTS for row in items if isinstance(row, dict))
    registry["recommendations"] = sum(str(row.get("status", "")).endswith("_recommended") for row in items if isinstance(row, dict))
    atomic_json(path, registry)
    decision_log = home / "evolution/decisions.jsonl"
    decision_log.parent.mkdir(parents=True, exist_ok=True)
    with decision_log.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"experiment_id": identifier, "decision": decision, "evidence": evidence, "decided_at": timestamp}, ensure_ascii=False) + "\n")
    return registry


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--run", action="store_true")
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--decide", nargs=2, metavar=("EXPERIMENT_ID", "DECISION"))
    parser.add_argument("--evidence", help="human review evidence for --decide")
    args = parser.parse_args()
    home = kb_home()
    if args.decide:
        identifier, decision = args.decide
        if decision not in {"retain", "rollback", "inconclusive", "reject"}:
            parser.error("DECISION must be retain, rollback, inconclusive, or reject")
        if not args.evidence:
            parser.error("--evidence is required with --decide")
        registry = decide(home, identifier, decision, args.evidence)
        print(f"ORGAN EVOLUTION: DECIDED id={identifier} decision={decision} active={registry['active']}")
        return 0
    l2 = read_json(home / "l2/registry.json", {})
    l3 = read_json(home / "l3/registry.json", {})
    registry = reconcile(home, l2, l3, args.run)
    print(f"ORGAN EVOLUTION: {registry['status'].upper()} active={registry['active']} recommendations={registry['recommendations']} writes={1 if args.run else 0}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
