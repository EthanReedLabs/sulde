"""Bounded postcondition normalization and read-response evidence extraction."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from .state import _VERIFICATION_CONTENT_KEYS


def _words(name: str) -> set[str]:
    return {part for part in re.split(r"[^a-z0-9]+", name.lower()) if part}


def _verification_digest(value: Any) -> str:
    """Hash one exact, JSON-stable postcondition without retaining its value."""
    try:
        rendered = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError, OverflowError):
        return ""
    return hashlib.sha256(rendered.encode("utf-8", errors="replace")).hexdigest()


def _memory_annotation_postcondition(
    tool_input: dict[str, Any],
) -> dict[str, list[dict[str, str]]] | None:
    """Normalize the real memory_annotate schema into one bounded postcondition."""
    if "entities" not in tool_input and "edges" not in tool_input:
        return None
    raw_entities = tool_input.get("entities", [])
    raw_edges = tool_input.get("edges", [])
    if (
        not isinstance(raw_entities, list)
        or not isinstance(raw_edges, list)
        or len(raw_entities) > 100
        or len(raw_edges) > 100
    ):
        return None

    entities: dict[str, str] = {}
    for entity in raw_entities:
        if not isinstance(entity, dict):
            return None
        name = entity.get("name")
        entity_type = entity.get("type")
        if (
            not isinstance(name, str)
            or not name.strip()
            or not isinstance(entity_type, str)
            or not entity_type.strip()
        ):
            return None
        normalized_name = name.strip()
        normalized_type = entity_type.strip()
        existing_type = entities.get(normalized_name)
        if existing_type is not None and existing_type != normalized_type:
            return None
        entities[normalized_name] = normalized_type

    relations: set[tuple[str, str, str]] = set()
    for edge in raw_edges:
        if not isinstance(edge, dict):
            return None
        values = (edge.get("src"), edge.get("rel"), edge.get("dst"))
        if any(not isinstance(value, str) or not value.strip() for value in values):
            return None
        relations.add(tuple(str(value).strip() for value in values))

    if not entities and not relations:
        return None
    return {
        "entities": [
            {"name": name, "type": entities[name]}
            for name in sorted(entities)
        ],
        "relations": [
            {"subject": src, "predicate": rel, "object": dst}
            for src, rel, dst in sorted(relations)
        ],
    }


def _write_verification_expectation(
    action: str,
    tool_input: dict[str, Any],
) -> tuple[str, str]:
    """Return the strongest postcondition that a later read can prove exactly."""
    if action.strip().lower() == "memory_annotate":
        postcondition = _memory_annotation_postcondition(tool_input)
        if postcondition is not None:
            digest = _verification_digest(postcondition)
            return ("relation", digest) if digest else ("unsupported", "")
    if all(key in tool_input for key in ("subject", "predicate", "object")):
        relation = {
            key: tool_input[key]
            for key in ("subject", "predicate", "object")
        }
        digest = _verification_digest(relation)
        return ("relation", digest) if digest else ("unsupported", "")
    for key in ("content", "body", "text", "markdown", "value"):
        if key in tool_input:
            digest = _verification_digest(tool_input[key])
            return ("content", digest) if digest else ("unsupported", "")
    words = _words(action)
    if "create" in words or action.lower().startswith("create_"):
        return "existence", ""
    return "unsupported", ""


def _read_verification_evidence(value: Any) -> dict[str, list[str]]:
    """Extract bounded, digest-only evidence from an observable read response."""
    found: dict[str, set[str]] = {"content": set(), "relation": set()}
    visited = 0

    def visit(candidate: Any, *, depth: int = 0, field: str = "") -> None:
        nonlocal visited
        if depth > 6 or visited >= 500:
            return
        visited += 1
        if field.lower() in _VERIFICATION_CONTENT_KEYS:
            digest = _verification_digest(candidate)
            if digest:
                found["content"].add(digest)
        if isinstance(candidate, dict):
            if all(key in candidate for key in ("subject", "predicate", "object")):
                relation = {
                    key: candidate[key]
                    for key in ("subject", "predicate", "object")
                }
                digest = _verification_digest(relation)
                if digest:
                    found["relation"].add(digest)
            if all(key in candidate for key in ("src", "rel", "dst")):
                relation = {
                    "subject": candidate["src"],
                    "predicate": candidate["rel"],
                    "object": candidate["dst"],
                }
                digest = _verification_digest(relation)
                if digest:
                    found["relation"].add(digest)
            for key, nested in list(candidate.items())[:100]:
                visit(nested, depth=depth + 1, field=str(key))
        elif isinstance(candidate, list):
            for nested in candidate[:100]:
                visit(nested, depth=depth + 1)
        elif isinstance(candidate, str):
            stripped = candidate.strip()
            if stripped[:1] in {"{", "["} and stripped[-1:] in {"}", "]"}:
                try:
                    decoded = json.loads(stripped)
                except (json.JSONDecodeError, TypeError):
                    return
                visit(decoded, depth=depth + 1)

    visit(value)
    return {key: sorted(values) for key, values in found.items() if values}


def _response_proves_existence(value: Any, *, depth: int = 0) -> bool:
    """Conservatively recognize a non-empty read result, including MCP wrappers."""
    if depth > 6 or value is None or value is False:
        return False
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return False
        lowered = stripped.lower()
        if any(
            marker in lowered
            for marker in (
                "not found",
                "no matches",
                "does not exist",
                "不存在",
                "未找到",
            )
        ):
            return False
        if stripped[:1] in {"{", "["} and stripped[-1:] in {"}", "]"}:
            try:
                return _response_proves_existence(json.loads(stripped), depth=depth + 1)
            except (json.JSONDecodeError, TypeError):
                return False
        return lowered not in {"false", "null", "none"}
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value != 0
    if isinstance(value, list):
        return any(_response_proves_existence(item, depth=depth + 1) for item in value[:100])
    if isinstance(value, dict):
        for key in ("exists", "found"):
            if key in value and value[key] is False:
                return False
        if value.get("error") or value.get("is_error") is True:
            return False
        payload_keys = (
            "structuredContent",
            "structured_content",
            "result",
            "data",
            "content",
            "items",
            "documents",
            "records",
        )
        present_payloads = [value[key] for key in payload_keys if key in value]
        if present_payloads:
            return any(
                _response_proves_existence(item, depth=depth + 1)
                for item in present_payloads
            )
        if any(
            isinstance(value.get(key), (str, int)) and str(value[key]).strip()
            for key in (
                "id",
                "uri",
                "url",
                "document_id",
                "documentId",
                "node_id",
                "nodeId",
            )
        ):
            return True
        return any(
            _response_proves_existence(nested, depth=depth + 1)
            for key, nested in list(value.items())[:100]
            if key not in {"type", "role", "status", "success"}
        )
    return False
