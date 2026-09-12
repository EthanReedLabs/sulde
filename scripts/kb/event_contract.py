"""Provider-neutral, read-only observation event contract for Sulde.

The contract deliberately sits at the observation boundary.  Existing domain
logs remain authoritative and are never rewritten or dual-written by this
module.  Adapters project one legacy row into a small, redacted envelope that
can be correlated across hosts without copying prompts, commands, paths, or
free-form evidence into a new sink.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence


EVENT_SCHEMA = "sulde-observation-event-v1"
CONTRACT_VERSION = 1
SNAPSHOT_SCHEMA = "sulde-observation-snapshot-v1"

DOMAINS = frozenset(
    {
        "approval",
        "context",
        "execution",
        "governance",
        "intent",
        "knowledge",
        "lifecycle",
        "memory",
        "notification",
        "sedimentation",
    }
)
PHASES = frozenset(
    {"started", "completed", "decision", "snapshot", "observed", "finalized"}
)
PROVIDERS = frozenset({"claude", "codex", "import", "system", "unknown"})
CORRELATION_KEYS = frozenset(
    {
        "continuation_id",
        "experiment_id",
        "intent_id",
        "intent_revision",
        "lane_id",
        "opportunity_id",
        "project_id",
        "review_id",
        "run_id",
        "session_id",
        "task_id",
        "task_instance_id",
        "workspace_id",
    }
)

_TYPE_RE = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_EVENT_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_OPAQUE_ID_RE = re.compile(r"^sha256:[0-9a-f]{24}$")
_WINDOWS_ABSOLUTE_RE = re.compile(r"^[A-Za-z]:[\\/]")
_SENSITIVE_ATTRIBUTE_KEYS = frozenset(
    {
        "arguments",
        "command",
        "content",
        "cwd",
        "detail",
        "evidence",
        "lesson",
        "markdown",
        "message",
        "output",
        "path",
        "payload",
        "prompt",
        "query",
        "reason",
        "result",
        "target",
        "token",
        "url",
    }
)


class EventContractError(ValueError):
    """A source row cannot be represented by the public observation contract."""


def canonical_json(value: Any) -> str:
    """Render stable lossless JSON or raise a contract error."""
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError, OverflowError) as error:
        raise EventContractError(f"value is not lossless JSON: {error}") from error


def value_digest(value: Any) -> str:
    """Return a one-way digest for a value that must not enter the projection."""
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def text_digest(value: Any) -> str | None:
    """Digest one non-empty textual identifier or free-form field."""
    if value is None:
        return None
    rendered = str(value).strip()
    if not rendered:
        return None
    return hashlib.sha256(rendered.encode("utf-8", errors="replace")).hexdigest()


def workspace_identifier(value: Any) -> str | None:
    """Create a stable opaque workspace key without publishing an absolute path."""
    if value is None or not str(value).strip():
        return None
    rendered = str(value).strip()
    digest = hashlib.sha256(
        f"workspace_id\0{rendered}".encode("utf-8", errors="replace")
    ).hexdigest()[:24]
    return f"sha256:{digest}"


def normalize_timestamp(value: Any) -> str:
    """Normalize one timezone-aware timestamp to UTC."""
    if not isinstance(value, str) or not value.strip():
        raise EventContractError("occurred_at must be a non-empty timestamp")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except (TypeError, ValueError, OverflowError) as error:
        raise EventContractError("occurred_at is not ISO-8601") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise EventContractError("occurred_at must include a timezone")
    return (
        parsed.astimezone(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def normalize_provider(value: Any) -> str:
    provider = str(value or "unknown").strip().lower()
    return provider if provider in PROVIDERS else "unknown"


def _safe_identifier(value: Any, field: str) -> str:
    rendered = str(value or "").strip()
    if not rendered:
        raise EventContractError(f"{field} must be non-empty")
    if len(rendered) > 256 or any(ord(character) < 32 for character in rendered):
        raise EventContractError(f"{field} is not a safe identifier")
    return rendered


def _safe_scalar(value: Any, field: str) -> str | int | float | bool | None:
    if value is None or isinstance(value, (str, int, bool)):
        if isinstance(value, str) and len(value) > 512:
            raise EventContractError(f"{field} exceeds 512 characters")
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    raise EventContractError(f"{field} must be a finite JSON scalar")


def safe_attributes(values: Mapping[str, Any] | None) -> dict[str, Any]:
    """Validate the deliberately small, non-nested public attribute bag."""
    if values is None:
        return {}
    result: dict[str, Any] = {}
    for raw_key, value in sorted(values.items()):
        key = _safe_identifier(raw_key, "attribute key")
        if _TYPE_RE.fullmatch(key) is None:
            raise EventContractError(f"attribute key {key!r} is not a controlled label")
        if key in _SENSITIVE_ATTRIBUTE_KEYS or key == "id" or key.endswith("_id"):
            raise EventContractError(
                f"attribute {key!r} must be represented by a digest/count instead"
            )
        if isinstance(value, (list, tuple)):
            if len(value) > 64:
                raise EventContractError(f"attribute {key!r} has too many items")
            result[key] = [
                _safe_scalar(item, f"attribute {key!r}") for item in value
            ]
        else:
            result[key] = _safe_scalar(value, f"attribute {key!r}")
    return result


def safe_correlation(values: Mapping[str, Any] | None) -> dict[str, str]:
    """Keep named stable IDs as deterministic opaque values.

    The transformation is idempotent so a materialized event can be validated
    through the same function.  Callers may filter with a raw identifier, but
    the public projection never returns it.
    """
    if values is None:
        return {}
    unknown = set(values) - CORRELATION_KEYS
    if unknown:
        raise EventContractError(
            "unknown correlation key(s): " + ", ".join(sorted(unknown))
        )
    result: dict[str, str] = {}
    for key, value in sorted(values.items()):
        if value is None or str(value).strip() == "":
            continue
        rendered = _safe_identifier(value, f"correlation.{key}")
        if _OPAQUE_ID_RE.fullmatch(rendered) is None:
            digest = hashlib.sha256(
                f"{key}\0{rendered}".encode("utf-8", errors="replace")
            ).hexdigest()[:24]
            rendered = f"sha256:{digest}"
        result[key] = rendered
    return result


def _validate_logical_source(name: Any) -> str:
    rendered = _safe_identifier(name, "source.name")
    if rendered.startswith(("/", "\\")) or _WINDOWS_ABSOLUTE_RE.match(rendered):
        raise EventContractError("source.name must not expose an absolute path")
    if ".." in rendered.replace("\\", "/").split("/"):
        raise EventContractError("source.name must not contain parent traversal")
    return rendered


def make_event(
    *,
    domain: str,
    event_type: str,
    occurred_at: Any,
    phase: str,
    outcome: Any,
    provider: Any,
    actor: Any,
    correlation: Mapping[str, Any] | None,
    source_kind: str,
    source_name: str,
    source_line: int,
    raw_row: Mapping[str, Any],
    attributes: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Project one authoritative source row into a deterministic safe event."""
    if domain not in DOMAINS:
        raise EventContractError(f"unknown event domain: {domain}")
    if not isinstance(event_type, str) or _TYPE_RE.fullmatch(event_type) is None:
        raise EventContractError(f"invalid event type: {event_type!r}")
    if phase not in PHASES:
        raise EventContractError(f"invalid event phase: {phase!r}")
    if not isinstance(source_line, int) or isinstance(source_line, bool) or source_line < 1:
        raise EventContractError("source.line must be a positive integer")
    row_digest = value_digest(dict(raw_row))
    logical_name = _validate_logical_source(source_name)
    event_id = hashlib.sha256(
        f"{source_kind}\0{logical_name}\0{source_line}\0{row_digest}".encode("utf-8")
    ).hexdigest()[:32]
    payload = {
        "schema": EVENT_SCHEMA,
        "event_id": event_id,
        "occurred_at": normalize_timestamp(occurred_at),
        "domain": domain,
        "type": event_type,
        "phase": phase,
        "outcome": _safe_identifier(outcome or "unknown", "outcome"),
        "provider": normalize_provider(provider),
        "actor": _safe_identifier(actor or "unknown", "actor"),
        "correlation": safe_correlation(correlation),
        "source": {
            "kind": _safe_identifier(source_kind, "source.kind"),
            "name": logical_name,
            "line": source_line,
            "row_sha256": row_digest,
        },
        "attributes": safe_attributes(attributes),
    }
    validate_event(payload)
    return payload


def validate_event(value: Any) -> None:
    """Validate an already materialized observation event."""
    if not isinstance(value, dict):
        raise EventContractError("event must be an object")
    expected = {
        "schema",
        "event_id",
        "occurred_at",
        "domain",
        "type",
        "phase",
        "outcome",
        "provider",
        "actor",
        "correlation",
        "source",
        "attributes",
    }
    if set(value) != expected:
        raise EventContractError("event envelope fields do not match the v1 contract")
    if value.get("schema") != EVENT_SCHEMA:
        raise EventContractError("event schema mismatch")
    if not isinstance(value.get("event_id"), str) or _EVENT_ID_RE.fullmatch(
        value["event_id"]
    ) is None:
        raise EventContractError("event_id must be 32 lowercase hex characters")
    normalize_timestamp(value.get("occurred_at"))
    if value.get("domain") not in DOMAINS:
        raise EventContractError("event domain is invalid")
    if not isinstance(value.get("type"), str) or _TYPE_RE.fullmatch(value["type"]) is None:
        raise EventContractError("event type is invalid")
    if value.get("phase") not in PHASES:
        raise EventContractError("event phase is invalid")
    outcome = _safe_identifier(value.get("outcome"), "outcome")
    if _TYPE_RE.fullmatch(outcome) is None:
        raise EventContractError("event outcome must be a controlled label")
    if value.get("provider") not in PROVIDERS:
        raise EventContractError("event provider is invalid")
    actor = _safe_identifier(value.get("actor"), "actor")
    if _TYPE_RE.fullmatch(actor) is None:
        raise EventContractError("event actor must be a controlled label")
    correlation = value.get("correlation")
    if not isinstance(correlation, dict) or safe_correlation(correlation) != correlation:
        raise EventContractError("event correlation identifiers must already be opaque")
    source = value.get("source")
    if not isinstance(source, dict) or set(source) != {
        "kind",
        "name",
        "line",
        "row_sha256",
    }:
        raise EventContractError("event source is invalid")
    source_kind = _safe_identifier(source.get("kind"), "source.kind")
    if _TYPE_RE.fullmatch(source_kind) is None:
        raise EventContractError("source.kind must be a controlled label")
    _validate_logical_source(source.get("name"))
    if not isinstance(source.get("line"), int) or isinstance(source.get("line"), bool) or source["line"] < 1:
        raise EventContractError("source.line must be a positive integer")
    if not isinstance(source.get("row_sha256"), str) or _DIGEST_RE.fullmatch(
        source["row_sha256"]
    ) is None:
        raise EventContractError("source.row_sha256 must be lowercase sha256")
    if not isinstance(value.get("attributes"), dict):
        raise EventContractError("attributes must be an object")
    safe_attributes(value["attributes"])


def count_digest(values: Sequence[Any]) -> tuple[int, str]:
    """Return a safe count and digest for a list whose content stays at source."""
    return len(values), value_digest(list(values))
