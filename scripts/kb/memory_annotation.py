"""Versioned memory annotation values; no host authority or database side effects."""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any

SCHEMA = "sulde-memory-annotation-v2"
RECEIPT_SCHEMA = "sulde-memory-annotation-receipt-v2"
MAX_ENTITIES = 6
MAX_EDGES = 3
MAX_TEXT = 512
TRUTH_STATES = {"current", "goal", "planned", "not_ready", "counterfactual", "uncertain", "unsupported", "unverified"}


class AnnotationConflict(ValueError):
    """A pre-commit conflict, not a backend availability failure."""
    code = "memory_annotation_conflict"


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > MAX_TEXT:
        raise ValueError(f"{field} must be a non-empty string of at most {MAX_TEXT} characters")
    return value.strip()


def normalize(payload: Any, *, extracted_by: str | None = None, bounded: bool = False) -> dict[str, Any]:
    if not isinstance(payload, dict) or not set(payload).issubset({"entities", "edges", "extracted_by"}):
        raise ValueError("annotation must contain only entities, edges and extracted_by")
    actor = payload.get("extracted_by", extracted_by)
    # No implicit Claude attribution. A caller must supply an explicit source;
    # an ordinary process environment is not a trusted current-session identity.
    if not isinstance(actor, str) or actor not in {"claude", "codex", "import"}:
        raise ValueError("extracted_by is required: claude, codex, or import")
    if extracted_by is not None and "extracted_by" in payload and actor != extracted_by:
        raise ValueError("extracted_by conflicts with the explicit caller attribution")
    entities, edges = payload.get("entities", []), payload.get("edges", [])
    if not isinstance(entities, list) or not isinstance(edges, list):
        raise ValueError("entities and edges must be arrays")
    if len(entities) > (MAX_ENTITIES if bounded else 100) or len(edges) > (MAX_EDGES if bounded else 100):
        raise ValueError("annotation batch is too large; split it into bounded batches")
    if bounded and (not entities or not edges or actor == "import"):
        raise ValueError("interactive annotation requires entities, edges and a host attribution")
    names: dict[str, str] = {}
    for entity in entities:
        if not isinstance(entity, dict) or set(entity) != {"name", "type"}:
            raise ValueError("entity requires exactly name and type")
        name, kind = text(entity["name"], "entity.name"), text(entity["type"], "entity.type")
        if name in names and names[name] != kind:
            raise AnnotationConflict("conflicting batch entity types; human review required")
        names[name] = kind
    relations: dict[tuple[str, str, str], dict[str, Any]] = {}
    for edge in edges:
        allowed = {"src", "rel", "dst", "entry_id", "confidence"}
        if not bounded:
            allowed.add("truth_status")
        if not isinstance(edge, dict) or not set(edge).issubset(allowed):
            raise ValueError("edge contains unsupported fields")
        triple = tuple(text(edge.get(key), "edge." + key) for key in ("src", "rel", "dst"))
        if bounded and (triple[0] not in names or triple[2] not in names):
            raise ValueError("edge endpoints must be declared in entities")
        entry = edge.get("entry_id")
        if entry is not None and (type(entry) is not int or entry <= 0):
            raise ValueError("entry_id must be a positive integer or null")
        confidence = edge.get("confidence", 1.0)
        if type(confidence) not in (int, float) or not math.isfinite(confidence) or not 0 <= confidence <= 1:
            raise ValueError("confidence must be finite and between 0 and 1")
        truth = edge.get("truth_status", "uncertain")
        if not isinstance(truth, str) or truth not in TRUTH_STATES:
            raise ValueError("truth_status is invalid")
        if truth == "unverified":
            truth = "uncertain"
        item = dict(zip(("src", "rel", "dst"), triple))
        item.update(entry_id=entry, confidence=float(confidence), truth_status=truth)
        if triple in relations and relations[triple] != item:
            raise AnnotationConflict("conflicting batch assertions; human review required")
        relations[triple] = item
    return {"schema": SCHEMA, "extracted_by": actor,
            "entities": [{"name": name, "type": kind} for name, kind in sorted(names.items())],
            "edges": [relations[key] for key in sorted(relations)]}


def input_from_normalized(value: dict[str, Any]) -> dict[str, Any]:
    return {key: value[key] for key in ("entities", "edges", "extracted_by")}


def snapshot(connection: Any, value: dict[str, Any]) -> dict[str, Any]:
    """Read exact rows; retain original attribution instead of rewriting it."""
    entities, edges = [], []
    for item in value["entities"]:
        row = connection.execute("SELECT name,type,first_seen FROM mem_entities WHERE name=?", (item["name"],)).fetchone()
        if row is None or row[1] != item["type"]:
            raise AnnotationConflict("entity type conflicts; human review required")
        entities.append(list(row))
    for item in value["edges"]:
        row = connection.execute(
            "SELECT id,src,rel,dst,entry_id,extracted_by,confidence,ts,truth_status,truth_source_sha256 "
            "FROM mem_edges WHERE src=? AND rel=? AND dst=?", (item["src"], item["rel"], item["dst"])
        ).fetchone()
        source_digest = None
        if item["entry_id"] is not None:
            source = connection.execute("SELECT content FROM mem_entries WHERE id=?", (item["entry_id"],)).fetchone()
            if source is None:
                raise AnnotationConflict("annotation source is missing")
            source_digest = digest(source[0])
        if row is None or (row[4], row[6], row[8], row[9]) != (
            item["entry_id"], item["confidence"], item["truth_status"], source_digest
        ):
            raise AnnotationConflict("existing assertion conflicts with source/status/confidence; human review required")
        edges.append(list(row))
    return {"entities": entities, "edges": edges}


def verify_receipt(connection: Any, request_sha256: str) -> dict[str, Any] | None:
    """Read-only proof. Storage verification is not semantic fact verification."""
    row = connection.execute(
        "SELECT request_json,result_json FROM mem_annotation_receipts WHERE request_sha256=?", (request_sha256,)
    ).fetchone()
    if row is None:
        return None
    try:
        request, result = json.loads(row[0]), json.loads(row[1])
        if not isinstance(request, dict) or not isinstance(result, dict):
            return None
        normalized = normalize(input_from_normalized(request))
        if request != normalized or digest(request) != request_sha256:
            return None
        if (result.get("schema") != RECEIPT_SCHEMA or result.get("request_sha256") != request_sha256
                or result.get("status") not in {"created", "already_present"}
                or result.get("request_actor") != request["extracted_by"]):
            return None
        if digest(snapshot(connection, request)) != result.get("rows_sha256"):
            return None
    except (ValueError, TypeError, KeyError):
        return None
    return result


def input_schema() -> dict[str, Any]:
    string = {"type": "string", "minLength": 1, "maxLength": MAX_TEXT}
    return {"type": "object", "required": ["entities", "edges", "extracted_by"],
            "additionalProperties": False, "properties": {
                "extracted_by": {"type": "string", "enum": ["claude", "codex"]},
                "entities": {"type": "array", "minItems": 1, "maxItems": MAX_ENTITIES,
                    "items": {"type": "object", "required": ["name", "type"], "additionalProperties": False,
                              "properties": {"name": dict(string), "type": dict(string)}}},
                "edges": {"type": "array", "minItems": 1, "maxItems": MAX_EDGES,
                    "items": {"type": "object", "required": ["src", "rel", "dst"], "additionalProperties": False,
                              "properties": {"src": dict(string), "rel": dict(string), "dst": dict(string),
                                  "entry_id": {"type": ["integer", "null"], "minimum": 1},
                                  "confidence": {"type": "number", "minimum": 0, "maximum": 1, "default": 1.0}}}}}}
