"""Native, non-effect retirement of one frozen historical contract epoch.

History is not erased or reclassified as success. The target remains paused;
only a separately verified receipt can remove its historical records from a
relocation blocker projection. Effect ledgers remain independently authoritative.
"""
from __future__ import annotations

import os
from .session_workspace import load_session_workspace, registered_worktree_identity
from approval_invariant import ApprovalInvariantError, decide_typed_approval, request_for_binding
from native_decision_journal import NativeDecisionJournalError
from .native_binding import _native_binding_snapshot

import native_decision_journal as journal

import copy
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import re
import stat

from .state import (
    ARTIFACT_GENERATION, IntentGuardianError, atomic_write, contract_lock,
    load_contract, policy_digest, _pause_global_locked, _write_contract_unlocked,
)

KIND = "historical-retirement"
SCHEMA = "sulde-historical-retirement-v1"
MARKER = "historical_retirement"
# These are observations, not the material world of the target epoch.
TELEMETRY = frozenset({
    "sequence", "material_sequence", "memory_material_sequence",
    "host_observations", "supervision_metrics", "pre_execution_probe",
    "pre_execution_proofs", "completed_calls", "pre_execution_proofs_required",
})


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode()).hexdigest()


def _view(contract):
    value = copy.deepcopy(contract)
    value.pop("updated_at", None)
    for field in TELEMETRY:
        value["runtime"].pop(field, None)
    return value


def _file(home, plan_id, suffix=".json"):
    if not re.fullmatch(r"[a-f0-9]{64}", plan_id):
        raise IntentGuardianError("invalid historical retirement plan identity")
    parent = home / "intent" / "historical-retirements"
    if parent.resolve() != parent:
        raise IntentGuardianError("historical retirement store cannot use a symlink")
    return parent / (plan_id + suffix)


def _read(path):
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o600 or info.st_size > 16 * 1024**2):
        raise IntentGuardianError("historical retirement record must be bounded and owner-only")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeError, ValueError) as error:
        raise IntentGuardianError("invalid historical retirement record") from error
    if not isinstance(value, dict):
        raise IntentGuardianError("historical retirement record must be an object")
    return value


def _immutable(path, value):
    if path.exists() or path.is_symlink():
        if _read(path) != value:
            raise IntentGuardianError("historical retirement record changed")
        return
    atomic_write(path, json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n")


def _load(home, plan_id):
    plan = _read(_file(home, plan_id))
    if plan.get("schema") != SCHEMA or _digest(plan) != plan_id:
        raise IntentGuardianError("historical retirement plan digest differs")
    return plan


def _identity(contract):
    return {"intent_id": contract["intent_id"], "policy": policy_digest(contract), "revision": contract["revision"],
            "epoch": contract["task_epoch"], "workspace": contract["workspace_root"]}


def _target_path(home, source):
    path = source.expanduser().resolve(strict=True)
    if source.is_symlink() or path.parent not in {
        home / "intent" / "workspaces", home / "intent" / "sessions",
    } or not path.name.endswith(".active.json"):
        raise IntentGuardianError("retirement target must be a canonical active contract")
    return path


def _lane(home, controller, provider, session_id):
    if provider != "codex" or not session_id:
        raise IntentGuardianError("retirement requires an exact Codex session")
    mapping = load_session_workspace(home, provider, session_id)
    if not mapping or Path(mapping["contract_path"]).resolve() != controller:
        raise IntentGuardianError("retirement controller is not the current task lane")


def _same_repository(controller, source):
    first = registered_worktree_identity(Path(controller["workspace_root"]))
    second = registered_worktree_identity(Path(source["workspace_root"]))
    if first["git_common_dir"] != second["git_common_dir"]:
        raise IntentGuardianError("retirement target belongs to another repository")
    info = Path(first["git_common_dir"]).stat()
    return {"common_dir": first["git_common_dir"], "device": info.st_dev, "inode": info.st_ino}


def _paused(plan, plan_id):
    value = copy.deepcopy(plan["source_contract"])
    _pause_global_locked(value, reason="历史执行阶段已终止；结果未知，不得重试或复用旧授权",
                         pause_class="historical_retirement", requires_revision=True)
    value["runtime"][MARKER] = {"plan_id": plan_id, "epoch": value["task_epoch"]}
    return value


def prepare(home, controller, source, *, provider, session_id, native_transactions=False):
    if native_transactions:
        try:
            return _native_prepare(home, controller, source, provider=provider, session_id=session_id)
        except (ApprovalInvariantError, NativeDecisionJournalError) as error:
            raise IntentGuardianError(str(error)) from error
    home, controller = home.resolve(), controller.resolve()
    source = _target_path(home, source)
    _lane(home, controller, provider, session_id)
    if source == controller:
        raise IntentGuardianError("cannot retire the executing control contract")
    with contract_lock(source):
        current, target = load_contract(controller), load_contract(source)
        if target["runtime"].get(MARKER):
            raise IntentGuardianError("target already has a historical retirement")
        opened = target["runtime"]["open_events"]
        gaps = target["runtime"]["pre_execution_gaps"]
        if not opened and not gaps:
            raise IntentGuardianError("target has no historical records to retire")
        if any(row.get("effect") != "local_write" or row.get("attempt_id") for row in opened):
            raise IntentGuardianError("external or linked effect must use effect recovery")
        if any(row.get("session_id") == session_id for row in [*opened, *gaps]):
            raise IntentGuardianError("cannot retire current session records as historical")
        plan = {"schema": SCHEMA, "controller": str(controller), "source": str(source),
                "controller_identity": _identity(current), "source_contract": target,
                "source_raw": source.read_text(encoding="utf-8"),
                "repository": _same_repository(current, target), "provider": provider,
                "session_id": session_id, "generation": ARTIFACT_GENERATION}
        plan_id = _digest(plan)
        _immutable(_file(home, plan_id), plan)
    return {"plan_id": plan_id, "execution_authorized": False,
            "open_events": len(opened), "gap_rows": len(gaps), "source": str(source)}


def _context(plan, plan_id):
    if "native_transactions" in plan:
        return _native_context(plan, plan_id)
    target = plan["source_contract"]
    detail = {"目标工作区": target["workspace_root"], "历史任务": target["objective"],
              "终止 revision": target["revision"], "终止 epoch": target["task_epoch"],
              "未闭合本地写入": len(target["runtime"]["open_events"]),
              "历史监督缺口记录": len(target["runtime"]["pre_execution_gaps"]),
              "历史会话": sorted({str(row.get("session_id") or "") for row in
                                  [*target["runtime"]["open_events"], *target["runtime"]["pre_execution_gaps"]]}),
              "边界": "保留原文和未知结果；终止整个旧阶段并保持暂停；不重试、不继承权限，真实效果债务仍独立阻断",
              "plan_id": plan_id}
    identity = plan["controller_identity"]
    return {"kind": KIND, "decision": "terminate", "target": plan_id,
            "action": "terminate-historical-epoch", "choice": "终止卡片中的历史执行阶段且不重试",
            "card": {"operation_id": KIND, "decision_id": "terminate",
                     "action": "terminate-historical-epoch", "决策内容": detail,
                     "宿主": "codex", "会话内确认": True},
            "workspace": identity["workspace"],
            "intent_id": identity["intent_id"], "intent_revision": identity["revision"],
            "task_epoch": identity["epoch"]}


def review(home, controller, plan_id, *, provider, session_id):
    home, controller = home.resolve(), controller.resolve()
    plan = _load(home, plan_id)
    _lane(home, controller, provider, session_id)
    if (plan["controller"] != str(controller) or plan["provider"] != provider
            or plan["session_id"] != session_id or plan["generation"] != ARTIFACT_GENERATION
            or _identity(load_contract(controller)) != plan["controller_identity"]):
        raise IntentGuardianError("retirement control lane, policy or generation changed")
    source = _target_path(home, Path(plan["source"]))
    current = load_contract(source)
    if _same_repository(load_contract(controller), current) != plan["repository"]:
        raise IntentGuardianError("retirement physical repository changed")
    if "native_transactions" in plan:
        _native_review_source(home, source, current, plan)
    elif _view(current) not in (_view(plan["source_contract"]), _view(_paused(plan, plan_id))):
        raise IntentGuardianError("historical retirement source CAS changed")
    return _context(plan, plan_id)


def _allow(controller, context, session_id):
    request = request_for_binding(controller, kind="intent-confirmation", target=context["target"],
        provider="codex", session_id=session_id, source="codex_permission_request",
        card=context["card"], workspace=context["workspace"], route="human", status="decided")
    receipt = (request or {}).get("typed_receipt")
    if (not request or request.get("typed") is not True or request.get("prompt_shown") is not True
            or request.get("decision_owner") != "human" or not isinstance(receipt, dict)
            or receipt.get("outcome") != "allow"):
        raise IntentGuardianError("retirement requires an exact typed native Allow")
    return {"request_id": request["request_id"], "decision_identity": receipt["decision_identity"],
            "snapshot": request["snapshot"]}


def _boundary(stage):
    """Fault-injection seam; production has no behavior here."""


def execute(home, controller, plan_id, *, decision, provider, session_id):
    home, controller = home.resolve(), controller.resolve()
    plan = _load(home, plan_id)
    if "native_transactions" in plan:
        try:
            return _native_execute(home, controller, plan_id, plan, decision=decision,
                                  provider=provider, session_id=session_id)
        except (ApprovalInvariantError, NativeDecisionJournalError) as error:
            raise IntentGuardianError(str(error)) from error
    if decision != "terminate":
        raise IntentGuardianError("unsupported historical retirement decision")
    source = _target_path(home, Path(plan["source"]))
    # Deterministic lock order; only the target projection is changed.
    with ExitStack() as locks:
        for path in sorted({controller, source}, key=str):
            locks.enter_context(contract_lock(path))
        context = review(home, controller, plan_id, provider=provider, session_id=session_id)
        terminal = _file(home, plan_id, ".committed.json")
        if terminal.exists():
            return verify(home, source, load_contract(source))
        request = request_for_binding(controller, kind="intent-confirmation", target=plan_id,
            provider=provider, session_id=session_id, source="codex_permission_request",
            card=context["card"], workspace=context["workspace"], route="human", status="asked")
        if request:
            if request.get("typed") is not True or request.get("prompt_shown") is not True:
                raise IntentGuardianError("retirement request is not a live native question")
            decide_typed_approval(controller, request_id=request["request_id"],
                receipt_id=request["request_identity"], outcome="allow", snapshot=request["snapshot"],
                current_snapshot=_native_binding_snapshot(controller, context, session_id),
                provider=provider, session_id=session_id, decision_owner="human", actor="permission-request:codex")
        authority = _allow(controller, context, session_id)
        _boundary("decision_recorded")
        # Recheck under the target lock after approval. Never replay its operation.
        review(home, controller, plan_id, provider=provider, session_id=session_id)
        current = load_contract(source)
        if _view(current) != _view(_paused(plan, plan_id)):
            _pause_global_locked(current, reason="历史执行阶段已终止；结果未知，不得重试或复用旧授权",
                                 pause_class="historical_retirement", requires_revision=True)
            current["runtime"][MARKER] = {"plan_id": plan_id, "epoch": current["task_epoch"]}
            _write_contract_unlocked(source, current)
        _boundary("target_paused")
        _immutable(terminal, {"schema": SCHEMA, "plan_id": plan_id, "authority": authority,
                              "outcome": "inconclusive", "effect_asserted": False,
                              "authority_transferred": False})
        _boundary("committed")
        return verify(home, source, load_contract(source))


def verify(home, source, contract):
    """Historical authority readback, not fresh permission and not an effect verifier."""
    marker = contract["runtime"].get(MARKER)
    if not isinstance(marker, dict):
        raise IntentGuardianError("historical retirement proof missing")
    plan_id = marker.get("plan_id", "")
    plan = _load(home.resolve(), plan_id)
    if str(source.resolve()) != plan["source"] or _view(contract) != _view(_paused(plan, plan_id)):
        raise IntentGuardianError("historical retirement target or material state changed")
    expected = {"schema": SCHEMA, "plan_id": plan_id,
                "authority": _allow(Path(plan["controller"]), _context(plan, plan_id), plan["session_id"]),
                "outcome": "inconclusive", "effect_asserted": False, "authority_transferred": False}
    if _read(_file(home.resolve(), plan_id, ".committed.json")) != expected:
        raise IntentGuardianError("historical retirement terminal receipt differs")
    return {"status": "retired_inconclusive", **expected,
            "execution_authorized": False, "source": plan["source"]}


def _native_review_source(home, source, current, plan):
    if _view(current) != _view(plan["source_contract"]):
        raise IntentGuardianError("historical native retirement source CAS changed")
    # A previous epoch decision is proof of inactivity, NOT approval of this batch.
    verify(home, source, current)
    if current["status"] != "paused":
        raise IntentGuardianError("native retirement source must remain paused")


def _native_prepare(home, controller, source, *, provider, session_id):
    home, controller = home.resolve(), controller.resolve()
    source = _target_path(home, source)
    _lane(home, controller, provider, session_id)
    if source == controller:
        raise IntentGuardianError("cannot retire the executing control contract")
    with ExitStack() as locks:
        for path in sorted({controller, source}, key=str):
            locks.enter_context(contract_lock(path))
        current, target = load_contract(controller), load_contract(source)
        verify(home, source, target)
        if target["status"] != "paused":
            raise IntentGuardianError("native retirement source must remain paused")
        projection = journal.load_projection_read_only(source)
        selected = []
        for tx_id, row in sorted(projection["transactions"].items()):
            if (row.get("stage") in journal.TERMINAL_STAGES
                    or journal.is_legacy_unsealed_prepared_diagnostic(row)):
                continue
            binding = row["binding"]
            if (row.get("stage") != "contract_applied" or row.get("sealed") is not True
                    or row.get("status") != "active" or row.get("historical_terminal_seen") is not False
                    or row.get("operation") not in {"proposal", "resume"}
                    or binding.get("intent_id") != target["intent_id"]
                    or binding.get("workspace") != target["workspace_root"]
                    or not 0 < binding.get("intent_revision", 0) < target["revision"]
                    or binding.get("session_id") == session_id):
                raise IntentGuardianError("native retirement has a nonhistorical or noncontract transaction")
            journal.historical_contract_retirement_proof(source, projection, row)
            selected.append(tx_id)
        if not 0 < len(selected) <= 100:
            raise IntentGuardianError("native retirement requires 1..100 frozen contract transactions")
        plan = {"schema": SCHEMA, "controller": str(controller), "source": str(source),
                "controller_identity": _identity(current), "source_contract": target,
                "source_raw": source.read_text(encoding="utf-8"),
                "repository": _same_repository(current, target), "provider": provider,
                "session_id": session_id, "generation": ARTIFACT_GENERATION,
                "native_transactions": selected, "native_snapshot": journal.retirement_snapshot(projection)}
        plan_id = _digest(plan)
        # Fail BEFORE writing a plan that the bounded reader could never reopen.
        if len((json.dumps(plan, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()) > 16 * 1024**2:
            raise IntentGuardianError("historical native retirement plan exceeds bound")
        _immutable(_file(home, plan_id), plan)
    return {"plan_id": plan_id, "execution_authorized": False,
            "native_transactions": len(selected), "source": str(source)}


def _native_context(plan, plan_id):
    identity = plan["controller_identity"]
    rows = plan["native_snapshot"]["transactions"]
    detail = {"目标工作区": plan["source_contract"]["workspace_root"],
              "历史合同事务": [{"事务": key, "revision": rows[key]["binding"]["intent_revision"],
                              "操作": rows[key]["operation"]} for key in plan["native_transactions"]],
              "边界": "仅追加终止后续推进资格；保留未知结果；不重放、不认定成功、不转移权限",
              "plan_id": plan_id}
    return {"kind": KIND, "decision": "terminate", "target": plan_id,
            "action": "terminate-historical-epoch", "choice": "终止卡片中历史合同事务的后续推进资格",
            "card": {"operation_id": KIND, "decision_id": "terminate",
                     "action": "terminate-historical-epoch", "决策内容": detail,
                     "宿主": "codex", "会话内确认": True},
            "workspace": identity["workspace"], "intent_id": identity["intent_id"],
            "intent_revision": identity["revision"], "task_epoch": identity["epoch"]}


def _native_execute(home, controller, plan_id, plan, *, decision, provider, session_id):
    if decision != "terminate":
        raise IntentGuardianError("unsupported historical native retirement decision")
    source = _target_path(home, Path(plan["source"]))
    with ExitStack() as locks:
        for path in sorted({controller, source}, key=str):
            locks.enter_context(contract_lock(path))
        card = review(home, controller, plan_id, provider=provider, session_id=session_id)
        request = request_for_binding(controller, kind="intent-confirmation", target=plan_id,
            provider=provider, session_id=session_id, source="codex_permission_request",
            card=card["card"], workspace=card["workspace"], route="human", status="asked")
        if request:
            if request.get("typed") is not True or request.get("prompt_shown") is not True:
                raise IntentGuardianError("retirement request is not a live native question")
            decide_typed_approval(controller, request_id=request["request_id"],
                receipt_id=request["request_identity"], outcome="allow", snapshot=request["snapshot"],
                current_snapshot=_native_binding_snapshot(controller, card, session_id),
                provider=provider, session_id=session_id, decision_owner="human", actor="permission-request:codex")
        authority = _allow(controller, card, session_id)
        terminal = {"schema": SCHEMA, "plan_id": plan_id, "authority": authority,
                    "outcome": "inconclusive", "effect_asserted": False,
                    "authority_transferred": False, "native_transactions": plan["native_transactions"]}
        terminal_path = _file(home, plan_id, ".committed.json")
        if (terminal_path.exists() or terminal_path.is_symlink()) and _read(terminal_path) != terminal:
            raise IntentGuardianError("native retirement terminal receipt differs")
        _boundary("native_decision_recorded")
        # One journal append batch, with whole-cut CAS under its existing writer
        # lock. Its anchored pending protocol recovers an interrupted append.
        journal.supersede_frozen_contracts(source, snapshot=plan["native_snapshot"],
            transaction_ids=plan["native_transactions"], reason="historical-native-retirement:" + plan_id)
        _boundary("native_superseded")
        _immutable(terminal_path, terminal)
        _boundary("native_committed")
        # This is the administrative batch receipt, never a committed OLD txn.
        if _read(_file(home, plan_id, ".committed.json")) != terminal:
            raise IntentGuardianError("native retirement terminal receipt differs")
        return {"status": "retired_inconclusive", **terminal, "execution_authorized": False,
                "source": str(source)}
