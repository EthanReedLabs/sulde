#!/usr/bin/env python3
"""Production consumer: feed managed-run completion facts back into predictions.

Wired into the agent-runtime managed chain (run command, post-monitor): when a
task has an open prediction thread in the run's state directory, the durable
worktree delta is checked against that prediction and the mechanical verdict
is appended to the prediction ledger.  A non-trivial verdict writes the
formal feedback artifact (the launcher composes the next attempt's brief
from it) — correction-store queueing is deliberately not used, because a
queued correction flips the run to awaiting_human and turns a scope
observation into a human gate.

Identity discipline:
- Predictions are bound to task/run/session digests; a completion check only
  ever touches the thread whose digests match THIS run.  Stale or closed
  threads from other tasks or expired inputs are skipped or marked stale,
  never revived.
- The consumer never settles: verified/closed stay behind the supervisor gate
  (R1-02).  Failure of the feedback path degrades to a logged skip; ordinary
  work and the correction channel keep working.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import impact_prediction as ip
import incremental_facts as facts

PREDICTION_STORE_FILENAME = "predictions.jsonl"


def prediction_store_path(state_dir: Path) -> Path:
    return Path(state_dir) / PREDICTION_STORE_FILENAME


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _task_digest(task_id: str) -> str:
    return ip.digest(task_id)


def rebind_open_prediction(
    *, state_dir: Path, task_id: str, session_id: str, contract_version: str,
    reason: str, run_id: str = "",
) -> dict[str, Any]:
    """Bind the task's open prediction to a starting attempt (pre-spawn)."""
    store = prediction_store_path(state_dir)
    try:
        if not store.exists():
            return {"consumer": "prediction_feedback", "status": "skipped",
                    "reason": "no prediction store"}
        row = ip.rebind_attempt(store, task_id=task_id,
                                session_id=session_id, contract_version=contract_version,
                                reason=reason, at=_now(), run_id=run_id)
        return {"consumer": "prediction_feedback", "status": "rebound",
                "prediction_id": row["prediction_id"]}
    except (ip.PredictionError, OSError) as error:
        return {"consumer": "prediction_feedback", "status": "degraded",
                "error": str(error)[:300]}


def confirm_attempt_run(
    *, state_dir: Path, task_id: str, run_id: str
) -> dict[str, Any]:
    """Bind the spawned run id to the rebound prediction (post-spawn).

    R3-closeout D4: 无预测线程时返回 skipped 且零写入 —— 上层据此跳过
    账本登记,普通任务不受影响。
    """
    store = prediction_store_path(state_dir)
    if not store.exists():
        return {"consumer": "prediction_feedback", "status": "skipped",
                "reason": "no prediction store"}
    try:
        row = ip.confirm_attempt_run(store, task_id=task_id, run_id=run_id,
                                     at=_now())
        return {"consumer": "prediction_feedback", "status": "attempt_started",
                "run_id_sha256": row["run_id_sha256"]}
    except ip.PredictionError as error:
        return {"consumer": "prediction_feedback", "status": "skipped",
                "reason": str(error)[:200]}


def load_pending_feedback(
    *, state_dir: Path, task_id: str, contract_version: str,
    consuming_run_id: str = "",
) -> tuple[dict[str, Any] | None, str]:
    """Preview-validate the pending feedback artifact (no state change).

    Binding checks (R3-followup 一): the artifact must belong to THIS task,
    reference the CURRENT open prediction id and version (an old feedback is
    never carried into a newer revision), match the current contract version,
    and require adjustment (as_predicted feedback is not delivered).
    """
    store = prediction_store_path(state_dir)
    task_digest = ip.digest(task_id)
    artifact_path = state_dir / f"prediction-feedback-{task_digest}.json"
    registry_path = state_dir / "prediction-feedback-consumed.json"
    registry_path = state_dir / "prediction-feedback-consumed.json"
    try:
        registry = {"consumed": {}}
        if registry_path.exists():
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
        if not artifact_path.exists():
            # R3-closeout 二:工件缺失但登记在案 → 已消费,不重复投递;
            # 工件在且登记在案 → 残留,绑定精确 request 清理(不误删不同请求)。
            consumed_request = None
            for rid, meta in registry["consumed"].items():
                if meta.get("task_id_sha256") == task_digest:
                    consumed_request = rid
            if consumed_request:
                residual = state_dir / f"prediction-feedback-{task_digest}.json"
                residual.unlink(missing_ok=True)  # 仅清理与登记匹配的残留
            return None, "no pending feedback artifact"
        artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
        # R3-closeout 二:发送结果不确定的反馈,在获得明确恢复决定前
        # 不再次纳入发送输入;显式恢复(recovered)后才可投递。
        request_id = str(artifact.get("request_id") or "")
        if (request_id in registry.get("send_unconfirmed", {})
                and request_id not in registry.get("recovered", {})):
            return None, ("send result uncertain; awaiting explicit recovery "
                          "decision")
        if artifact.get("task_id_sha256") != task_digest:
            return None, "feedback belongs to another task"
        # R3-closeout D3: 生成反馈的 attempt 不得消费自己的反馈。
        # 来源与消费的关系由持久化摘要判定,不信任调用方声明。
        if artifact.get("run_id_sha256") == ip.digest(consuming_run_id):
            return None, ("the generating attempt cannot consume its own "
                          "feedback")
        if artifact.get("request_id") in registry["consumed"]:
            return None, "feedback already consumed"
        entry = ip.load_projection(store)["tasks"].get(task_digest)
        current = (entry or {}).get("current")
        if current is None:
            return None, "no open prediction thread for this task"
        if artifact.get("prediction_version") != current.get("version"):
            return None, "feedback predates the current prediction revision"
        if artifact.get("prediction_id") != current.get("prediction_id"):
            return None, "feedback references a different prediction"
        if artifact.get("verdict") == "as_predicted":
            return None, "feedback carries no required adjustment"
        if current.get("status") != "open":
            return None, f"prediction thread is {current.get('status')}"
        bound_contract = str(current.get("contract_version") or "")
        if not contract_version or bound_contract != contract_version:
            return None, "contract version does not match the prediction binding"
        return artifact, "delivered"
    except (ip.PredictionError, json.JSONDecodeError, OSError) as error:
        return None, f"degraded: {str(error)[:200]}"


def mark_feedback_recovered(
    *, state_dir: Path, task_id: str, request_id: str, decision: str, at: str,
) -> dict[str, Any]:
    """Explicit recovery decision for a send-uncertain feedback (launcher)."""
    task_digest = ip.digest(task_id)
    registry_path = state_dir / "prediction-feedback-consumed.json"
    registry = {"consumed": {}, "send_unconfirmed": {}, "recovered": {}}
    if registry_path.exists():
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registry.setdefault("recovered", {})[request_id] = {
        "task_id_sha256": task_digest, "decision": decision, "at": at,
    }
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(
        json.dumps(registry, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    return registry


def confirm_feedback_consumed(
    *, state_dir: Path, task_id: str, request_id: str,
    consuming_run_id: str, consuming_session_id: str,
) -> dict[str, Any]:
    """Register the consumption after the attempt actually started.

    The consuming attempt's real run id is only known after spawn, so the
    registry entry is written here rather than at prompt-preview time.
    """
    task_digest = ip.digest(task_id)
    registry_path = state_dir / "prediction-feedback-consumed.json"
    registry = {"consumed": {}}
    if registry_path.exists():
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registry["consumed"][request_id] = {
        "consumed_at": _now(),
        "consuming_run_id_sha256": ip.digest(consuming_run_id),
        "consuming_session_id_sha256": ip.digest(consuming_session_id),
    }
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(
        json.dumps(registry, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    artifact_path = state_dir / f"prediction-feedback-{task_digest}.json"
    # R3-closeout D2: 只清理与被确认 request 一致的工件;
    # 后来产生的新请求(不同 request)不受旧确认影响。
    if artifact_path.exists():
        try:
            residual = json.loads(artifact_path.read_text(encoding="utf-8"))
            if residual.get("request_id") == request_id:
                artifact_path.unlink()
        except (json.JSONDecodeError, OSError):
            pass  # 无法识别的残留不盲目删除;load 端按 registry 判定
    return registry_path


def record_completion_feedback(
    *,
    state_dir: Path,
    repo: Path,
    task_id: str,
    run_id: str,
    session_id: str,
    provider: str,
    intent_id: str,
    intent_revision: int,
    contract_version: str = "",
    baseline_revision: str = "",
) -> dict[str, Any]:
    """Check the task's open prediction against the durable worktree delta.

    Returns a disclosure dict; this function never raises for absent
    predictions or degraded stores (the caller logs the disclosure and the
    managed chain continues unaffected).
    """
    disclosure: dict[str, Any] = {"consumer": "prediction_feedback", "status": "skipped"}
    task_digest = ip.digest(task_id)
    store = prediction_store_path(state_dir)
    try:
        if not store.exists():
            disclosure["reason"] = "no prediction store for this run"
            return disclosure
        projection = ip.load_projection(store)
        entry = projection["tasks"].get(_task_digest(task_id))
        current = (entry or {}).get("current")
        if current is None:
            disclosure["reason"] = "no prediction thread for this task"
            return disclosure
        if current.get("run_id_sha256") != ip.digest(run_id):
            disclosure["reason"] = "prediction bound to another run; expired for this run"
            disclosure["status"] = "rejected"
            return disclosure
        # R2-02: the baseline must be a real, resolvable commit of this
        # repository.  A missing or unresolvable baseline is an explicit
        # degradation — never a checked/as_predicted verdict.
        verify = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--verify",
             f"{baseline_revision}^{{commit}}"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=30, check=False,
        )
        if verify.returncode != 0:
            disclosure["status"] = "degraded"
            disclosure["error"] = (
                f"baseline revision {baseline_revision!r} is not resolvable in "
                "this repository; no verdict recorded"
            )
            return disclosure
        status = current.get("status")
        if status == "closed":
            disclosure["reason"] = "prediction thread already closed"
            return disclosure
        if status == "stale":
            disclosure["reason"] = "prediction stale; awaiting agent re-judgment"
            disclosure["status"] = "stale_skipped"
            return disclosure
        # R2-03 identity discipline: session and contract version must match
        # the binding established at attempt start (explicit rebind updates
        # both); a mismatch means the feedback would cross sessions.
        if current.get("session_id_sha256") != ip.digest(session_id):
            disclosure["status"] = "rejected"
            disclosure["reason"] = "prediction bound to another session"
            return disclosure
        # R3-01: missing producer version must not silently skip the check.
        bound_contract = str(current.get("contract_version") or "")
        if not contract_version:
            disclosure["status"] = "degraded"
            disclosure["error"] = (
                "contract version unavailable in this run; no verdict recorded"
            )
            return disclosure
        if not bound_contract:
            disclosure["status"] = "degraded"
            disclosure["error"] = (
                "prediction has no bound contract version; no verdict recorded"
            )
            return disclosure
        # R3-closeout 一: a continuation running under a DIFFERENT contract
        # than the prediction's binding expires the pending feedback (kept,
        # not consumed).  Same-contract continuations consume normally.
        attempt_contract = str(current.get("attempt_contract_version") or "")
        if attempt_contract and attempt_contract != bound_contract:
            disclosure["status"] = "rejected"
            disclosure["reason"] = (
                "contract changed during continuation "
                f"({bound_contract!r} -> {attempt_contract!r}); feedback expired"
            )
            return disclosure
        if bound_contract != contract_version:
            disclosure["status"] = "rejected"
            disclosure["reason"] = (
                f"prediction bound to contract {bound_contract!r}, "
                f"current is {contract_version!r}"
            )
            return disclosure

        expected_flat = [
            item
            for group in (current.get("expected_touch") or {}).values()
            if isinstance(group, list)
            for item in group
        ]
        bundle = facts.collect(
            repo,
            baseline=baseline_revision,
            expected_paths=expected_flat,
            source_identities=dict(current.get("source_identities") or {}),
        )
        fact_view = {
            **bundle,
            "changed_paths": bundle["diff"]["changed_paths"],
            "expected_paths": expected_flat,
        }
        # R2-03/R3-02: drift INSIDE the expected touch is the change itself;
        # only out-of-scope bound basis changes invalidate the prediction
        # basis.  Consistent rule: a bound path is out-of-scope unless it
        # matches (exactly or by prefix) an expected entry.
        raw_drift = (bundle["source_identity_drift"] or {}).get("drifted") or {}
        relevant_drift = {
            path: row for path, row in raw_drift.items()
            if not any(facts.match_entry(path, entry) for entry in expected_flat)
        }
        if relevant_drift:
            ip.mark_stale(store, task_id=task_id,
                          input_changed=relevant_drift, at=_now())
            disclosure["status"] = "stale_marked"
            disclosure["drift"] = relevant_drift
            return disclosure

        prediction_now = ip.load_projection(store)["tasks"][_task_digest(task_id)]["current"]
        verdict = facts.classify_against_prediction(fact_view, bundle["split"], prediction_now)
        scope_facts = facts.feedback_scope_facts(bundle, verdict)
        if verdict.get("incomplete"):
            # Incomplete observation is neither a mismatch nor success. Keep
            # existing pending feedback and the prediction check ledger intact.
            return {**disclosure, "status": "degraded", "error": verdict["reason"],
                    "facts": scope_facts}
        ip.record_check(store, {
            "verdict": verdict["suggested_verdict"],
            "facts": scope_facts,
            "evidence": [f"worktree-delta-vs:{baseline_revision}"],
        }, at=_now(), task_id=task_id)
        disclosure["status"] = "checked"
        disclosure["verdict"] = verdict["suggested_verdict"]
        disclosure["baseline_revision"] = baseline_revision
        disclosure["task_id_sha256"] = _task_digest(task_id)

        if verdict["suggested_verdict"] == "as_predicted":
            return disclosure

        # R2-04/R3-03: the feedback artifact is the formal continuation
        # channel — the launcher composes the next attempt's brief from it.
        # Correction-store queueing is deliberately NOT used: a queued
        # correction flips the run to awaiting_human, which would turn a
        # scope observation into a human gate.
        request_id = ip.digest(f"{task_digest}\0{run_id}\0{current.get('prediction_id')}\0{verdict['suggested_verdict']}")
        artifact_path = state_dir / f"prediction-feedback-{task_digest}.json"
        pending = None
        if artifact_path.exists():
            pending = json.loads(artifact_path.read_text(encoding="utf-8"))
            if not isinstance(pending, dict) or pending.get("task_id_sha256") != task_digest:
                raise ValueError("pending feedback identity is invalid; artifact retained")
            registry_path = state_dir / "prediction-feedback-consumed.json"
            registry = (json.loads(registry_path.read_text(encoding="utf-8"))
                        if registry_path.exists() else {})
            if not isinstance(registry, dict) or any(
                not isinstance(registry.get(key, {}), dict)
                for key in ("consumed", "send_unconfirmed", "recovered")
            ):
                raise ValueError("feedback registry is invalid; artifact retained")
            pending_request = pending.get("request_id")
            if not isinstance(pending_request, str) or not pending_request:
                raise ValueError("pending request identity is missing; artifact retained")
            if (pending_request in registry.get("send_unconfirmed", {})
                    and pending_request not in registry.get("recovered", {})):
                # A new run gets a new request ID. Replacing the task's only
                # pending artifact would bypass the old ID's recovery gate.
                # The new observation is already durable via record_check;
                # retain the unresolved delivery, even across prediction edits.
                # load_pending_feedback still checks prediction identity/version.
                disclosure["feedback_artifact"] = str(artifact_path)
                disclosure["feedback"] = {
                    "request_id": pending_request,
                    "disposition": "preserved_send_unconfirmed",
                    "deferred_request_id": request_id,
                    "deduplicated": pending_request == request_id,
                }
                return disclosure
        deduplicated = pending is not None and pending.get("request_id") == request_id
        if not deduplicated:
            artifact = {
                "schema": "sulde-prediction-feedback-v1",
                "request_id": request_id,
                "task_id_sha256": task_digest,
                "run_id_sha256": ip.digest(run_id),
                "session_id_sha256": ip.digest(session_id),
                "prediction_id": current.get("prediction_id"),
                "prediction_version": current.get("version"),
                "verdict": verdict["suggested_verdict"],
                "facts": scope_facts,
                "evidence": [f"worktree-delta-vs:{baseline_revision}"],
                "created_at": _now(),
            }
            artifact_path.write_text(
                json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8")
            disclosure["feedback_artifact"] = str(artifact_path)
        disclosure["feedback"] = {
            "request_id": request_id,
            "deduplicated": deduplicated,
            "verdict": verdict["suggested_verdict"],
        }
        return disclosure

    except (ip.PredictionError, facts.FactError, OSError, ValueError) as error:
        # explicit degradation: ordinary work and the correction channel keep
        # working; no forged verified state is produced.
        return {**disclosure, "status": "degraded", "error": str(error)[:300]}

