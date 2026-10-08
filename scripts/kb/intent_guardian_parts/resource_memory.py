"""Bounded memory annotation candidates and independent read-only receipts."""
from __future__ import annotations

import re
import sqlite3
from typing import Any

from memory_annotation import normalize as normalize_memory_annotation, digest as memory_annotation_digest, verify_receipt as verify_memory_receipt
from .state import SYSTEM_MEMORY_PROFILE, kb_home
from .resource_postconditions import _memory_annotation_postcondition, _verification_digest


def _system_memory_annotation_candidate(
    tool_input: dict[str, Any],
    *,
    provider: str,
    expected_digest: str,
) -> dict[str, Any] | None:
    """Return a fixed local policy lane for a small, attributable graph write."""
    normalized_provider = provider.strip().lower()
    if normalized_provider not in {"claude", "codex"}:
        return None
    try:
        normalized = normalize_memory_annotation(tool_input, extracted_by=normalized_provider, bounded=True)
    except (ValueError, TypeError):
        return None
    if set(tool_input) != {"entities", "edges", "extracted_by"}:
        return None
    if tool_input.get("extracted_by") != normalized_provider:
        return None
    entities = tool_input.get("entities")
    edges = tool_input.get("edges")
    if (
        not isinstance(entities, list)
        or not isinstance(edges, list)
        or not 1 <= len(entities) <= 6
        or not 1 <= len(edges) <= 3
    ):
        return None
    entity_names: set[str] = set()
    for entity in entities:
        if not isinstance(entity, dict) or set(entity) != {"name", "type"}:
            return None
        name = entity.get("name")
        if not isinstance(name, str) or not name.strip() or name.strip() in entity_names:
            return None
        entity_names.add(name.strip())
    for edge in edges:
        if not isinstance(edge, dict) or not set(edge).issubset(
            {"src", "rel", "dst", "entry_id", "confidence"}
        ):
            return None
        if not {"src", "rel", "dst"}.issubset(edge):
            return None
        if str(edge.get("src") or "").strip() not in entity_names:
            return None
        if str(edge.get("dst") or "").strip() not in entity_names:
            return None
        entry_id = edge.get("entry_id")
        if entry_id is not None and (isinstance(entry_id, bool) or not isinstance(entry_id, int)):
            return None
        confidence = edge.get("confidence", 1.0)
        if (
            isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not 0.0 <= float(confidence) <= 1.0
        ):
            return None
    postcondition = _memory_annotation_postcondition(tool_input)
    if (
        postcondition is None
        or not expected_digest
        or expected_digest not in {_verification_digest(postcondition), memory_annotation_digest(normalized)}
    ):
        return None
    return {
        "profile_id": SYSTEM_MEMORY_PROFILE,
        "effect": "local_write",
        "capability": "mcp:sulde_kb:memory_annotate",
        "target": f"[memory-annotation:{expected_digest}]",
        "verification_kind": "relation",
        "verification_sha256": expected_digest,
        "entity_count": len(entities),
        "edge_count": len(edges),
        "extracted_by": normalized_provider,
    }


def _memory_receipt_verification(expected_digest: str) -> dict[str, Any] | None:
    """Resolve a digest-only recipe through an independent read-only connection."""
    if not re.fullmatch(r"[0-9a-f]{64}", expected_digest):
        return None
    database = kb_home() / "memory.db"
    try:
        connection = sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True, timeout=0.25)
        try:
            connection.execute("PRAGMA query_only=ON")
            connection.execute("BEGIN")
            result = verify_memory_receipt(connection, expected_digest)
        finally:
            connection.close()
    except (OSError, sqlite3.Error, ValueError, TypeError):
        return None
    if result is None:
        return None
    return {"capability": "mcp:sulde_kb:memory_graph", "evidence": {"relation": [expected_digest]},
            "source": "local_memory_db_read", "recipe_schema": "sulde-memory-annotation-v2"}

def _local_memory_annotation_verification(
    tool_input: dict[str, Any],
    *,
    expected_digest: str,
) -> dict[str, Any] | None:
    """Prove every declared memory row through an independent read-only DB handle."""
    try:
        request = normalize_memory_annotation(tool_input)
    except (ValueError, TypeError):
        request = None
    if request is not None and memory_annotation_digest(request) == expected_digest:
        return _memory_receipt_verification(expected_digest)
    # v1 evidence remains v1: never silently rehash or relabel historical rows.
    postcondition = _memory_annotation_postcondition(tool_input)
    if (
        postcondition is None
        or not expected_digest
        or _verification_digest(postcondition) != expected_digest
    ):
        return None
    database_path = kb_home() / "memory.db"
    try:
        database_uri = f"{database_path.resolve().as_uri()}?mode=ro"
        connection = sqlite3.connect(
            database_uri,
            uri=True,
            timeout=0.25,
        )
        try:
            connection.execute("PRAGMA query_only = ON")
            connection.execute("PRAGMA busy_timeout = 250")
            connection.execute("BEGIN")
            for entity in postcondition["entities"]:
                row = connection.execute(
                    "SELECT 1 FROM mem_entities WHERE name = ? AND type = ? LIMIT 1",
                    (entity["name"], entity["type"]),
                ).fetchone()
                if row is None:
                    return None
            for relation in postcondition["relations"]:
                matching_edge = next(
                    edge
                    for edge in tool_input["edges"]
                    if str(edge.get("src") or "").strip() == relation["subject"]
                    and str(edge.get("rel") or "").strip() == relation["predicate"]
                    and str(edge.get("dst") or "").strip() == relation["object"]
                )
                row = connection.execute(
                    """
                    SELECT 1 FROM mem_edges
                    WHERE src = ? AND rel = ? AND dst = ?
                      AND entry_id IS ? AND extracted_by = ? AND confidence = ?
                    LIMIT 1
                    """,
                    (
                        relation["subject"],
                        relation["predicate"],
                        relation["object"],
                        matching_edge.get("entry_id"),
                        tool_input.get("extracted_by"),
                        float(matching_edge.get("confidence", 1.0)),
                    ),
                ).fetchone()
                if row is None:
                    return None
        finally:
            connection.close()
    except (OSError, sqlite3.Error, UnicodeError, ValueError):
        return None
    return {
        "capability": "mcp:sulde_kb:memory_graph",
        "evidence": {"relation": [expected_digest]},
        "source": "local_memory_db_read",
    }
