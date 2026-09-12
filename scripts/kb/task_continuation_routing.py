"""Read-only verification of an explicitly approved cross-contract route.

No Guardian imports: native journal producers and session routing use this same
small wire format without a dependency cycle or a second authority service.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

SCHEMA = "sulde-selected-task-route-v1"


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, allow_nan=False,
        sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def lane_key(provider, session_id):
    return hashlib.sha256(f"{provider}\0{session_id}".encode("utf-8")).hexdigest()


def route_record(document, provider, session_id):
    routes = document.get("task_continuation_routes", {})
    if type(routes) is not dict:
        raise ValueError("selected task routes must be an object")
    row = routes.get(lane_key(provider, session_id))
    if row is None:
        return None
    if (type(row) is not dict or row.get("schema") != SCHEMA
            or row.get("provider") != provider or row.get("session_id") != session_id
            or row.get("authority_transferred") is not False
            or row.get("status") not in {"prepared", "committed", "aborted"}
            or row.get("sha256") != digest({k: v for k, v in row.items() if k != "sha256"})):
        raise ValueError("selected task route record is invalid")
    return row


def pending_origin(mapping, document):
    """A staged physical mapping cannot expose an uncommitted task lane."""
    row = route_record(document, mapping["provider"], mapping["session_id"])
    if row is None or row["status"] in {"committed", "aborted"}:
        return None
    if (row["source_contract"] != mapping["contract_path"]
            or row["current_contract"] != mapping["source_contract_path"]
            or row["mapping_sha256"] != mapping["mapping_sha256"]):
        raise ValueError("pending selected task route and mapping differ")
    return Path(row["current_contract"])


def verify_route(document, binding, receipt, *, require_live=False):
    """Read the immutable commit receipt; optionally verify the live route too.

    Later prompt metadata is not allowed to invalidate a historical internal
    commit or cause its lane binding to be executed a second time.
    """
    tx = document.get("task_continuation_transaction")
    if type(tx) is not dict or tx.get("schema") != SCHEMA:
        raise ValueError("selected task route transaction missing")
    if (tx.get("target") != binding["target"] or tx.get("receipt_id") != receipt["receipt_id"]
            or tx.get("request_id") != binding["request_id"]
            or tx.get("provider") != binding["provider"] or tx.get("session_id") != binding["session_id"]
            or tx.get("authority_transferred") is not False
            or digest(tx["context"]["subject"]) != binding["target"]):
        raise ValueError("selected task route does not match native binding")
    mapping = tx["mapping_after"]
    if require_live and json.loads(Path(tx["mapping_path"]).read_text(encoding="utf-8")) != mapping:
        raise ValueError("selected task route was not published")
    if digest({k: v for k, v in mapping.items() if k != "mapping_sha256"}) != mapping["mapping_sha256"]:
        raise ValueError("selected task mapping digest differs")
    source = json.loads(Path(tx["source_contract"]).read_text(encoding="utf-8"))
    row = route_record(source, binding["provider"], binding["session_id"])
    if (row is None or row["status"] != "committed" or row["target"] != binding["target"]
            or row["receipt_id"] != receipt["receipt_id"] or row["request_id"] != binding["request_id"]
            or row["mapping_sha256"] != mapping["mapping_sha256"]
            or row["current_contract"] != tx["current_contract"]
            or source["workspace_root"] != document["workspace_root"]
            or row.get("bound_lane", {}).get("task_epoch") != tx["context"]["subject"]["source"]["task_epoch"]):
        raise ValueError("selected task commit does not match native binding")
    lane = row["bound_lane"]
    if (lane.get("provider") != binding["provider"] or lane.get("session_id") != binding["session_id"]
            or lane["state"] != "bound" or lane["source"] != "native_session_continuation"
            or lane.get("continuation_token")):
        raise ValueError("selected task target lane is not independently bound")
    if require_live and lane not in source["runtime"]["task_lanes"]:
        raise ValueError("selected task live lane differs from its commit receipt")
    continuations = [item for item in source["runtime"]["task_continuations"]
        if item.get("target") == binding["target"] and item.get("receipt_id") == receipt["receipt_id"]
        and item.get("session_id") == binding["session_id"] and item.get("authority_transferred") is False
        and item.get("task_epoch") == lane["task_epoch"]
        and item.get("policy_sha256") == tx["context"]["subject"]["source"]["policy_sha256"]]
    if len(continuations) != 1:
        raise ValueError("selected task continuation receipt is not unique")
    return {"kind": "task-continuation", "provider": binding["provider"],
        "session_id": binding["session_id"], "task_epoch": lane["task_epoch"],
        "continuation_id": continuations[0]["continuation_id"], "receipt_id": receipt["receipt_id"],
        "mapping_sha256": mapping["mapping_sha256"], "route_sha256": row["sha256"],
        "authority_transferred": False, "revision": document["revision"]}
