"""Signed, non-authorizing facts about committed session workspace transitions.

Only the committed control-transition writers call record_transition. A failed
telemetry publication does not undo or block their already-committed mapping.
Readers never infer a transition merely from sharing a repository or session.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import hmac
import json
import os
from pathlib import Path
from typing import Any

from file_lock import lock_exclusive_nonblocking, unlock
from host_observation_index import _atomic_signed, _encoded, _private_file

SCHEMA = "sulde-session-lifecycle-lineage-v1"
MAX_BYTES = 256 * 1024
MAX_EDGES = 128


def _digest(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _committed_mapping_matches(home: Path, provider: str, session_id: str, mapping: dict[str, Any], source_workspace: str) -> bool:
    from intent_guardian_parts.session_workspace import load_session_workspace
    from intent_guardian_parts.state import load_contract
    return (load_session_workspace(home, provider, session_id) == mapping
            and Path(load_contract(Path(mapping["source_contract_path"]))["workspace_root"]).resolve()
            == Path(source_workspace).resolve())


def lineage_path(home: Path, provider: str, session_id: str) -> Path:
    identity = hashlib.sha256(_encoded([provider, session_id])).hexdigest()
    return home / "host-session-lineage" / (identity + ".json")


def _read(home: Path, provider: str, session_id: str, key: bytes) -> list[dict[str, Any]]:
    path = lineage_path(home, provider, session_id)
    with os.fdopen(_private_file(path, os.O_RDONLY), "rb") as handle:
        raw = handle.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("lineage exceeds its bound")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("invalid lineage object")
    signature = value.pop("signature", "")
    if not isinstance(signature, str) or not hmac.compare_digest(
        signature, hmac.new(key, _encoded(value), hashlib.sha256).hexdigest()
    ):
        raise ValueError("lineage signature differs")
    if (value.get("schema") != SCHEMA or value.get("provider") != provider
            or value.get("session_id") != session_id
            or not isinstance(value.get("edges"), list) or len(value["edges"]) > MAX_EDGES):
        raise ValueError("lineage schema or session differs")
    for edge in value["edges"]:
        if (not isinstance(edge, dict) or edge.get("authority_transferred") is not False
                or not _digest(edge.get("receipt_sha256"))
                or not (_digest(edge.get("mapping_sha256")) or (
                    edge.get("evidence_kind") == "completed_release_pair"
                    and _digest(edge.get("commit_evidence_sha256"))))):
            raise ValueError("lineage edge is not a committed non-authorizing transition")
        for name in ("source_workspace_id", "target_workspace_id"):
            identity = edge.get(name)
            if (not isinstance(identity, str) or not identity.startswith("sha256:")
                    or len(identity) != 31 or any(c not in "0123456789abcdef" for c in identity[7:])):
                raise ValueError("lineage workspace identity is invalid")
        if datetime.fromisoformat(edge["at"]).tzinfo is None:
            raise ValueError("lineage timestamp has no timezone")
    return value["edges"]


def record_transition(
    home: Path, *, provider: str, session_id: str,
    source_workspace: str, mapping: dict[str, Any], receipt_id: str,
) -> bool:
    """Publish only after the authoritative mapping has committed successfully."""
    from host_capabilities import _read_provenance_key, workspace_identifier

    if (not receipt_id or mapping.get("provider") != provider
            or mapping.get("session_id") != session_id or not mapping.get("mapping_sha256")):
        return False
    try:
        if not _committed_mapping_matches(home, provider, session_id, mapping, source_workspace):
            return False
        key = _read_provenance_key(home)
        path = lineage_path(home, provider, session_id)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if path.parent.is_symlink():
            return False
        with os.fdopen(_private_file(path.with_suffix(".lock"), os.O_RDWR | os.O_CREAT), "r+") as lock:
            lock_exclusive_nonblocking(lock)
            try:
                try:
                    edges = _read(home, provider, session_id, key)
                except FileNotFoundError:
                    edges = []
                edge = {
                    "source_workspace_id": workspace_identifier(source_workspace),
                    "target_workspace_id": workspace_identifier(mapping["workspace_root"]),
                    "at": mapping["bound_at"],
                    "receipt_sha256": hashlib.sha256(receipt_id.encode()).hexdigest(),
                    "mapping_sha256": mapping["mapping_sha256"],
                    "authority_transferred": False,
                }
                identity = (edge["source_workspace_id"], edge["target_workspace_id"], edge["receipt_sha256"])
                if any((old["source_workspace_id"], old["target_workspace_id"], old["receipt_sha256"]) == identity for old in edges):
                    return True
                if len(edges) >= MAX_EDGES:
                    return False  # maintenance required, never discard the chain
                if not _committed_mapping_matches(home, provider, session_id, mapping, source_workspace):
                    return False  # CAS against the authoritative route, not caller claims
                edges.append(edge)
                _atomic_signed(path, {"schema": SCHEMA, "provider": provider,
                                      "session_id": session_id, "edges": edges}, key)
                return True
            finally:
                unlock(lock)
    except (OSError, ValueError, TypeError, KeyError, RuntimeError):
        return False


def recover_current_transition(home: Path, *, provider: str, session_id: str) -> dict[str, Any]:
    """Explicit repair after an old install or append/publication crash.

    Recover only the current committed edge with independent decision/release
    evidence. Missing older edges are reported, never guessed from repo identity.
    This maintenance path may replay approval history; Hook readers never do.
    """
    from intent_guardian_parts.session_workspace import load_session_workspace, _cleanup_record
    from intent_guardian_parts.state import load_contract, audit_path, NATIVE_PERMISSION_SOURCE
    from approval_invariant import request_binding_receipt, decided_request_receipt, request_by_id

    result = {"status": "inconclusive", "authority_transferred": False, "source_modified": False}
    try:
        mapping = load_session_workspace(home, provider, session_id)
        if not mapping or not mapping.get("source_contract_path"):
            return {**result, "reason": "no_committed_transition"}
        source_path = Path(mapping["source_contract_path"])
        source = load_contract(source_path)
        target = load_contract(Path(mapping["contract_path"]))
        source_workspace = source["workspace_root"]
        receipt_id = ""
        cleanup = _cleanup_record(target)
        if cleanup:
            released = source.get("workspace_release", {})
            if (cleanup["provider"] == provider and cleanup["session_id"] == session_id
                    and cleanup["source_contract"] == str(source_path)
                    and cleanup["target_workspace"] == mapping["workspace_root"]
                    and released.get("release_id") == cleanup["release_id"]
                    and released.get("provider") == provider and released.get("session_id") == session_id
                    and source["status"] == "closed"):
                receipt_id = cleanup["release_id"]
        else:
            for observation in reversed(target["runtime"].get("host_observations", [])):
                if (observation.get("event") != "workspace_handoff"
                        or observation.get("provider") != provider or observation.get("session_id") != session_id
                        or observation.get("at", "") > mapping["bound_at"]):
                    continue
                # Legacy normalization discarded the source/no-authority fields.
                # Exact independently paired receipt + committed mapping below
                # provide the evidence; omitted fields are never assumed true.
                receipts = [row for row in source["runtime"]["approval_receipts"]
                            if row.get("receipt_id") == observation.get("receipt_id")]
                if len(receipts) != 1:
                    continue
                receipt = receipts[0]
                if (receipt.get("provider") != provider or receipt.get("session_id") != session_id
                        or receipt.get("action") != "handoff-workspace"
                        or receipt.get("target") != mapping["workspace_root"]
                        or receipt.get("channel") != "codex-native-permission"
                        or not receipt.get("consumed_at")):
                    continue
                asked = request_binding_receipt(source_path, receipt["approval_request_id"])
                request = request_by_id(source_path, receipt["approval_request_id"])
                if not request or request.get("outcome") not in {"approved", "allow"}:
                    continue
                decided = decided_request_receipt(
                    source_path, asked, outcome=request["outcome"], provider=provider,
                    session_id=session_id, actor=request["decision_actor"],
                )
                # The approval decision receipt and subsequent execution receipt
                # are distinct identities. Bind them by exact request + immutable
                # execution audit, never demand equality or omit either link.
                with audit_path(source_path).open(encoding="utf-8") as audit:
                    executed = any(
                        row.get("action") == "native-decision"
                        and row.get("receipt_id") == receipt["receipt_id"]
                        and row.get("detail") == "workspace-handoff:approve:" + mapping["workspace_root"]
                        and row.get("at", "") <= mapping["bound_at"]
                        for row in (json.loads(line) for line in audit)
                    )
                if (asked["target_sha256"] == hashlib.sha256(mapping["workspace_root"].encode()).hexdigest()
                        and asked["source"] == NATIVE_PERMISSION_SOURCE
                        and asked["kind"] == "intent-confirmation"
                        and decided["decided_at"] <= mapping["bound_at"] and executed):
                    receipt_id = receipt["receipt_id"]
                    break
        if not receipt_id:
            return {**result, "reason": "original_transition_evidence_unavailable"}
        if not record_transition(home, provider=provider, session_id=session_id,
                                 source_workspace=source_workspace, mapping=mapping, receipt_id=receipt_id):
            return {**result, "reason": "concurrent_change_or_projection_unavailable"}
        return {**result, "status": "recovered", "mapping_sha256": mapping["mapping_sha256"],
                "coverage": "current_edge_only_older_edges_require_original_evidence"}
    except (OSError, ValueError, TypeError, KeyError, RuntimeError) as error:
        return {**result, "reason": "original_transition_evidence_invalid", "error_kind": type(error).__name__}


def predecessor_workspaces(
    home: Path, *, provider: str, session_id: str, target_workspace_id: str,
    before: datetime,
) -> tuple[dict[str, datetime], str]:
    from host_capabilities import _read_provenance_key

    try:
        edges = _read(home, provider, session_id, _read_provenance_key(home))
        predecessors = {target_workspace_id: before}
        for edge in sorted(edges, key=lambda row: datetime.fromisoformat(row["at"]), reverse=True):
            target_deadline = predecessors.get(edge["target_workspace_id"])
            at = datetime.fromisoformat(edge["at"])
            if target_deadline is not None and at <= target_deadline:
                source = edge["source_workspace_id"]
                predecessors[source] = max(predecessors.get(source, at), at)
        return predecessors, "verified" if len(predecessors) > 1 else "no_predecessor"
    except FileNotFoundError:
        return {}, "missing"
    except (OSError, ValueError, TypeError, KeyError, RuntimeError):
        return {}, "invalid"
