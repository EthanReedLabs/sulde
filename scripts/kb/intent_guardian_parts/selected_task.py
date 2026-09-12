"""Explicit new-session selection, native CAS and recoverable route publication.

Prepare is not authority. The existing native decision journal owns approval and
recovery; these contract projections only implement its internal postcondition.
"""
from __future__ import annotations

from contextlib import ExitStack, contextmanager
import copy
import json
from pathlib import Path
import stat

from intervention import load_projection, readiness_blocking_attempts
from native_decision_journal import supersede as supersede_native_transaction, load_projection_read_only as native_projection
from task_continuation_routing import SCHEMA, digest, lane_key, route_record, verify_route
from task_ownership import TASK_CONTINUATION_SCHEMA, upsert_task_lane
from .session_workspace import (
    SESSION_WORKSPACE_SCHEMA, _mapping_material, _write_mapping_unlocked,
    load_session_workspace, resolve_session_contract, session_workspace_path,
)
from .state import (
    IntentGuardianError, _exclusive_path_lock, _write_contract_unlocked, _append_jsonl, audit_path,
    contract_lock, load_contract, now_iso, policy_digest,
)

SELECTION = "sulde-task-continuation-selection-v1"


def _home(path):
    path = Path(path).expanduser().resolve()
    if path.parent.name not in {"sessions", "workspaces"} or path.parent.parent.name != "intent":
        raise IntentGuardianError("task selection requires a canonical intent contract")
    return path.parents[2]


def _source_path(path, selection):
    if (type(selection) is not dict or selection.get("schema") != SELECTION
            or selection.get("sha256") != digest({k: v for k, v in selection.items() if k != "sha256"})):
        raise IntentGuardianError("task selection digest or schema is invalid")
    source = Path(selection["source_contract"])
    if (not source.is_absolute() or source.is_symlink() or source.resolve() != source
            or _home(source) != _home(path) or source == Path(path).resolve()
            or not stat.S_ISREG(source.stat().st_mode)):
        raise IntentGuardianError("task selection source is not a canonical peer contract")
    return source


@contextmanager
def decision_lock(path):
    """All cross-contract writers acquire lexical contract locks, then route lock."""
    path = Path(path).resolve()
    selected = load_contract(path).get("task_continuation_selection")
    source = _source_path(path, selected) if selected is not None else None
    with ExitStack() as stack:
        for item in sorted({path, source} - {None}, key=str):
            stack.enter_context(contract_lock(item))
        if load_contract(path).get("task_continuation_selection") != selected:
            raise IntentGuardianError("task selection changed while acquiring locks")
        if selected is not None:
            mapping = session_workspace_path(_home(path), selected["provider"], selected["session_id"])
            stack.enter_context(_exclusive_path_lock(mapping.with_name("." + mapping.name + ".lock")))
        yield


def _idle_current(current, provider, session_id):
    runtime = current["runtime"]
    if current["status"] == "paused":
        raise IntentGuardianError("paused current task cannot be replaced through task selection")
    provisional = (current["mode"] == "shadow" and current.get("confirmed_by") == "unconfirmed"
                   and not current.get("applied_proposal_digest"))
    if current["status"] != "active" or not (current["confirmation"]["required"] or provisional):
        raise IntentGuardianError("explicit task selection requires an unconfirmed new-session task")
    if not any(row["provider"] == provider and row["session_id"] == session_id
               and row["task_epoch"] == current["task_epoch"] for row in runtime["task_lanes"]):
        raise IntentGuardianError("new-session task has no exact current lane")
    if runtime.get("pause_reason") or any(row["provider"] == provider and row["session_id"] == session_id
            and row["task_epoch"] == current["task_epoch"] and row["state"] == "paused" for row in runtime["task_lanes"]):
        raise IntentGuardianError("paused current task cannot be replaced through task selection")
    if (current.get("continuation", {}).get("grants") or current.get("approved_event_fingerprints")
            or any(runtime.get(key) for key in ("authorized_events", "open_events", "pending_verifications",
                "continuation_uses", "pending_proposal_digest", "integrity_breaches", "pre_execution_gaps"))):
        raise IntentGuardianError("current task has authority or unsettled material state; cannot select another task")


def prepare(path, source_path, *, provider, session_id):
    """Persist only an explicitly selected read-only reference; leave source untouched."""
    path, source_path = Path(path).resolve(), Path(source_path).expanduser()
    if provider != "codex" or not session_id:
        raise IntentGuardianError("explicit task selection requires a current Codex session")
    if source_path.is_symlink() or source_path.resolve() != source_path or _home(source_path) != _home(path) or source_path == path:
        raise IntentGuardianError("task selection requires another canonical contract in the same data root")
    with ExitStack() as stack:
        for item in sorted({path, source_path}, key=str):
            stack.enter_context(contract_lock(item))
        current, source = load_contract(path), load_contract(source_path)
        _idle_current(current, provider, session_id)
        if Path(current["workspace_root"]).resolve() != Path(source["workspace_root"]).resolve():
            raise IntentGuardianError("task selection cannot cross physical workspaces")
        if source["status"] != "active" or source["confirmation"]["required"]:
            raise IntentGuardianError("selected source task is not confirmed and active")
        old_route = route_record(source, provider, session_id)
        if any(row["provider"] == provider and row["session_id"] == session_id
               and not (old_route and old_route["status"] == "aborted" and row["state"] == "review_required")
               for row in source["runtime"]["task_lanes"]):
            raise IntentGuardianError("selected source already contains this session; ownership needs review")
        if current.get("task_continuation_transaction"):
            raise IntentGuardianError("recover the existing native continuation transaction first")
        if readiness_blocking_attempts(load_projection(path)):
            raise IntentGuardianError("current task has unresolved effect debt")
        mapping_path = session_workspace_path(_home(path), provider, session_id)
        stack.enter_context(_exclusive_path_lock(mapping_path.with_name("." + mapping_path.name + ".lock")))
        if resolve_session_contract(_home(path), provider, session_id) != path:
            raise IntentGuardianError("task selection contract is not the active session contract")
        mapping = load_session_workspace(_home(path), provider, session_id)
        if mapping is None:
            raise IntentGuardianError("task selection requires a durable current session route")
        value = {"schema": SELECTION, "provider": provider, "session_id": session_id,
            "current_contract": str(path), "source_contract": str(source_path),
            "current_revision": current["revision"], "current_epoch": current["task_epoch"],
            "source_revision": source["revision"], "source_epoch": source["task_epoch"],
            "mapping_before": mapping}
        value["sha256"] = digest(value)
        previous = current.get("task_continuation_selection")
        if previous != value:
            current["task_continuation_selection"] = value
            _write_contract_unlocked(path, current)
        return {"schema": SELECTION, "status": "review_required", "authority_transferred": False,
            "source_contract": str(source_path), "current_contract": str(path),
            "selection_sha256": value["sha256"], "objective": source["objective"],
            "next_action": "native-decision-preview task-continuation on the current contract"}


def _source_view(source, provider, session_id):
    view = copy.deepcopy(source)
    # A virtual review lane builds a card, never persists authority during prepare.
    view["runtime"]["task_lanes"] = [row for row in view["runtime"]["task_lanes"]
        if not (row["provider"] == provider and row["session_id"] == session_id)]
    upsert_task_lane(view, provider=provider, session_id=session_id, state="review_required",
        source="explicit_task_selection", continuation_token="", continuation_eligible=False)
    return view


def context(path, current, *, provider, session_id, legacy_context):
    """Caller holds decision_lock for a coherent two-contract card/CAS snapshot."""
    selection = current.get("task_continuation_selection")
    source_path = _source_path(path, selection)
    if selection["provider"] != provider or selection["session_id"] != session_id:
        raise IntentGuardianError("task selection belongs to another native session")
    _idle_current(current, provider, session_id)
    source = load_contract(source_path)
    if (selection["current_contract"] != str(Path(path).resolve())
            or selection["current_revision"] != current["revision"] or selection["current_epoch"] != current["task_epoch"]
            or selection["source_revision"] != source["revision"] or selection["source_epoch"] != source["task_epoch"]
            or Path(source["workspace_root"]).resolve() != Path(current["workspace_root"]).resolve()):
        raise IntentGuardianError("selected source or current task world changed")
    tx = current.get("task_continuation_transaction")
    mapping = load_session_workspace(_home(path), provider, session_id)
    if mapping != selection["mapping_before"] and not (type(tx) is dict and mapping == tx.get("mapping_after")):
        raise IntentGuardianError("task continuation route predecessor changed")
    source_context = legacy_context(_source_view(source, provider, session_id), contract_path=source_path,
        provider=provider, session_id=session_id)
    current_lane = next(row for row in current["runtime"]["task_lanes"] if row["provider"] == provider
        and row["session_id"] == session_id and row["task_epoch"] == current["task_epoch"])
    subject = {"schema": "sulde-task-continuation-subject-v2", "source": source_context["subject"],
        "source_contract": str(source_path), "current_contract": str(Path(path).resolve()),
        "selection_sha256": selection["sha256"], "mapping_sha256": selection["mapping_before"]["mapping_sha256"],
        "current": {"intent_id": current["intent_id"], "revision": current["revision"],
            "task_epoch": current["task_epoch"], "policy_sha256": policy_digest(current),
            "lane": {key: current_lane.get(key) for key in ("state", "prompt_sha256", "task_instance_id", "pending_task_instance_id")},
            "material_sequence": current["runtime"]["material_sequence"]}}
    target = digest(subject)
    card = copy.deepcopy(source_context["card"])
    card["要决定的结果"] = "让当前独立新会话续接显式选择的旧任务"
    card["将离开的当前任务"] = current["objective"]
    card["绑定范围"].update({"当前合同": str(Path(path).resolve()), "源任务合同": str(source_path),
        "当前合同修订": current["revision"], "当前任务epoch": current["task_epoch"], "续接目标摘要": target})
    card["执行边界"] = "Allow 原子切换当前会话路由到选定任务；Deny 保持当前独立任务。旧授权与未决效果不转移。"
    return {"subject": subject, "target": target, "card": card,
        "source_lane": source_context["source_lane"], "target_lane": source_context["target_lane"]}


def committed(current, binding, receipt):
    if current.get("task_continuation_transaction") is None:
        return False
    try:
        verify_route(current, binding, receipt)
    except (ValueError, KeyError, OSError, TypeError):
        return False
    return True


def _checkpoint(stage):
    """Inert production seam for interruption-boundary tests."""
    del stage


def apply(path, current, binding, receipt, *, legacy_context):
    """Only called by the existing durable native decision executor under locks."""
    if committed(current, binding, receipt):
        return
    selected = context(path, current, provider=binding["provider"], session_id=binding["session_id"],
        legacy_context=legacy_context)
    if selected["target"] != binding["target"]:
        raise IntentGuardianError("selected task changed before native route application")
    selection = current["task_continuation_selection"]
    source_path = _source_path(path, selection)
    source = load_contract(source_path)
    tx = current.get("task_continuation_transaction")
    if tx is None:
        mapping = {**selection["mapping_before"], "schema": SESSION_WORKSPACE_SCHEMA,
            "contract_path": str(source_path), "source_contract_path": str(Path(path).resolve()), "bound_at": now_iso()}
        mapping["mapping_sha256"] = digest(_mapping_material(mapping))
        tx = {"schema": SCHEMA, "target": binding["target"], "provider": binding["provider"],
            "session_id": binding["session_id"], "receipt_id": receipt["receipt_id"], "request_id": binding["request_id"],
            "current_contract": str(Path(path).resolve()), "source_contract": str(source_path),
            "context": {"subject": selected["subject"], "card": selected["card"]},
            "mapping_path": str(session_workspace_path(_home(path), binding["provider"], binding["session_id"])),
            "mapping_after": mapping, "authority_transferred": False}
        current["task_continuation_transaction"] = tx
        _write_contract_unlocked(path, current)
        _checkpoint("transaction_prepared")
    if (tx["target"] != binding["target"] or tx["receipt_id"] != receipt["receipt_id"]
            or tx["request_id"] != binding["request_id"]):
        raise IntentGuardianError("another selected-task transaction already exists")
    key = lane_key(binding["provider"], binding["session_id"])
    row = route_record(source, binding["provider"], binding["session_id"])
    if row is None or row["status"] == "aborted":
        source = _source_view(source, binding["provider"], binding["session_id"])
        row = {"schema": SCHEMA, "status": "prepared", "target": binding["target"],
            "provider": binding["provider"], "session_id": binding["session_id"], "receipt_id": receipt["receipt_id"],
            "request_id": binding["request_id"], "current_contract": str(Path(path).resolve()),
            "source_contract": str(source_path), "mapping_sha256": tx["mapping_after"]["mapping_sha256"],
            "authority_transferred": False}
        row["sha256"] = digest(row)
        source.setdefault("task_continuation_routes", {})[key] = row
        _write_contract_unlocked(source_path, source)
        _checkpoint("source_staged")
    if row["target"] != binding["target"] or row["receipt_id"] != receipt["receipt_id"]:
        raise IntentGuardianError("selected task has a different route transaction")
    mapping = load_session_workspace(_home(path), binding["provider"], binding["session_id"])
    if mapping == selection["mapping_before"]:
        _write_mapping_unlocked(_home(path), tx["mapping_after"])
        _checkpoint("mapping_staged")
    elif mapping != tx["mapping_after"]:
        raise IntentGuardianError("selected task route CAS failed")
    source_subject = selected["subject"]["source"]
    lane = upsert_task_lane(source, provider=binding["provider"], session_id=binding["session_id"],
        state="bound", source="native_session_continuation", proposal_digest=source_subject["proposal_digest"],
        continuation_token="", continuation_eligible=True)
    lane["continuation_token"] = ""
    continuation_id = digest({"target": binding["target"], "receipt_id": receipt["receipt_id"], "request_id": binding["request_id"]})
    source["runtime"]["task_continuations"].append({"schema": TASK_CONTINUATION_SCHEMA,
        "continuation_id": continuation_id, "target": binding["target"], "provider": binding["provider"],
        "session_id": binding["session_id"], "task_epoch": source["task_epoch"], "intent_revision": source["revision"],
        "proposal_digest": source_subject["proposal_digest"], "policy_sha256": source_subject["policy_sha256"],
        "source_lane_sha256": source_subject["source_lane_sha256"], "target_lane_sha256": source_subject["target_lane_sha256"],
        "task_instance_id": lane.get("task_instance_id", ""), "receipt_id": receipt["receipt_id"],
        "approval_request_id": binding["request_id"], "authority_transferred": False, "recorded_at": now_iso()})
    row = {**row, "status": "committed", "bound_lane": dict(lane)}
    row["sha256"] = digest({k: v for k, v in row.items() if k != "sha256"})
    source["task_continuation_routes"][key] = row
    # Linearization point: lane authority and effective routing become live in
    # this single atomic contract replacement. Earlier stages resolve to origin.
    _write_contract_unlocked(source_path, source)
    _checkpoint("source_committed")
    verify_route(current, binding, receipt, require_live=True)


def supersede_route(path, transaction_id, *, reason, contract, binding):
    """Terminalize the journal first, then undo only this uncommitted route CAS."""
    result = supersede_native_transaction(path, transaction_id, reason=reason)
    tx = contract.get("task_continuation_transaction")
    if not tx or tx.get("target") != binding["target"]:
        return result
    source_path = _source_path(path, contract["task_continuation_selection"])
    source = load_contract(source_path)
    row = route_record(source, binding["provider"], binding["session_id"])
    if row and row["status"] == "committed":
        raise IntentGuardianError("a committed selected task route cannot be undone as unexecuted")
    mapping = load_session_workspace(_home(path), binding["provider"], binding["session_id"])
    before = contract["task_continuation_selection"]["mapping_before"]
    if mapping == tx["mapping_after"]:
        _write_mapping_unlocked(_home(path), before)
    elif mapping != before:
        raise IntentGuardianError("superseded route cleanup cannot overwrite a newer mapping")
    history = {"event": "selected_task_route_superseded", "target": binding["target"],
        "transaction_id": transaction_id, "transaction_sha256": digest(tx),
        "source_record_sha256": digest(row), "reason": reason, "authority_transferred": False}
    _append_jsonl(audit_path(path), history)
    contract.setdefault("task_continuation_history", {})[binding["target"]] = {
        "transaction": tx, "terminal": history, "sha256": digest(history)}
    if row:
        row = {**row, "status": "aborted"}
        row["sha256"] = digest({k: v for k, v in row.items() if k != "sha256"})
        source["task_continuation_routes"][lane_key(binding["provider"], binding["session_id"])] = row
        _append_jsonl(audit_path(source_path), history)
        _write_contract_unlocked(source_path, source)
    contract.pop("task_continuation_transaction", None)
    _write_contract_unlocked(path, contract)
    return result


def recovery_origin(path, provider, session_id):
    """Find the one fenced origin after route commit but before journal completion."""
    if provider != "codex" or not session_id:
        return None
    source = load_contract(path)
    row = route_record(source, provider, session_id)
    if row is None or row["status"] != "committed":
        return None
    origin = Path(row["current_contract"])
    if (_home(origin) != _home(path) or origin == Path(path).resolve()
            or row["source_contract"] != str(Path(path).resolve())):
        raise IntentGuardianError("selected task recovery origin differs")
    current = load_contract(origin)
    tx = current.get("task_continuation_transaction", {})
    if (tx.get("target") != row["target"] or tx.get("receipt_id") != row["receipt_id"]
            or tx.get("source_contract") != str(Path(path).resolve())):
        raise IntentGuardianError("selected task recovery origin has no exact transaction")
    return origin


def recover_terminal(path):
    """Finish revocation if a crash followed journal supersession before cleanup."""
    if not Path(path).is_file() or not load_contract(path).get("task_continuation_transaction"):
        return
    with decision_lock(path):
        current = load_contract(path)
        tx = current.get("task_continuation_transaction")
        if not tx:
            return
        matches = [row for row in native_projection(Path(path))["transactions"].values()
            if row["binding"].get("target") == tx["target"] and row["binding"].get("request_id") == tx["request_id"]]
        if len(matches) != 1:
            raise IntentGuardianError("selected task transaction lacks its unique native journal authority")
        transaction = matches[0]
        if transaction["status"] == "superseded":
            supersede_route(path, transaction["transaction_id"], reason="recover superseded selected route",
                contract=current, binding=transaction["binding"])
