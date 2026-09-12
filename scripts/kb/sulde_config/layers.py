"""Layered configuration with provenance and monotonic constraints."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import math
import re
from typing import Any, Iterable


CONFIG_SNAPSHOT_SCHEMA = "sulde-config-snapshot-v1"
_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*$")
_LAYER_RE = re.compile(r"^[a-z][a-z0-9._-]{0,99}$")
_MAX_LAYER_BYTES = 64 * 1024


class ConfigError(ValueError):
    """A config layer would produce ambiguous or broader policy."""


class ConfigLayerKind(str, Enum):
    PACKAGED = "packaged"
    SHARED = "shared"
    HOST = "host"
    WORKSPACE = "workspace"
    TASK = "task"
    MANAGED = "managed"


_PRECEDENCE = {
    ConfigLayerKind.PACKAGED: 0,
    ConfigLayerKind.SHARED: 1,
    ConfigLayerKind.HOST: 2,
    ConfigLayerKind.WORKSPACE: 3,
    ConfigLayerKind.TASK: 4,
    ConfigLayerKind.MANAGED: 5,
}


def _plain_json(value: Any, *, depth: int = 0) -> bool:
    if depth > 10:
        return False
    if value is None or type(value) in {str, int, bool}:
        return True
    if type(value) is float:
        return math.isfinite(value)
    if type(value) is list:
        return all(_plain_json(item, depth=depth + 1) for item in value)
    if type(value) is dict:
        return all(
            type(key) is str and _plain_json(item, depth=depth + 1)
            for key, item in value.items()
        )
    return False


def _canonical(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError, OverflowError) as error:
        raise ConfigError("config value is not lossless JSON") from error


@dataclass(frozen=True)
class ConfigLayer:
    name: str
    kind: ConfigLayerKind
    values_json: str

    def __post_init__(self) -> None:
        if type(self.name) is not str or _LAYER_RE.fullmatch(self.name) is None:
            raise ConfigError("config layer name is invalid")
        if type(self.kind) is not ConfigLayerKind:
            raise ConfigError("config layer kind is invalid")
        try:
            values = json.loads(self.values_json)
        except (TypeError, json.JSONDecodeError) as error:
            raise ConfigError("config layer JSON is invalid") from error
        if type(values) is not dict or not _plain_json(values):
            raise ConfigError("config layer must be a plain JSON object")
        if any(_KEY_RE.fullmatch(key) is None for key in values):
            raise ConfigError("config layer contains an invalid dotted key")
        if _canonical(values) != self.values_json:
            raise ConfigError("config layer JSON is not canonical")
        if len(self.values_json.encode("utf-8")) > _MAX_LAYER_BYTES:
            raise ConfigError("config layer exceeds 64 KiB")
        if self.kind is ConfigLayerKind.MANAGED and any(
            not (key.startswith("permissions.") or key.startswith("limits."))
            for key in values
        ):
            raise ConfigError(
                "managed constraints may contain only permissions.* or limits.*"
            )

    @property
    def values(self) -> dict[str, Any]:
        return json.loads(self.values_json)

    @classmethod
    def build(
        cls,
        *,
        name: str,
        kind: ConfigLayerKind,
        values: dict[str, Any],
    ) -> "ConfigLayer":
        if type(values) is not dict:
            raise ConfigError("config layer values must be a dict")
        return cls(name=name, kind=kind, values_json=_canonical(values))


@dataclass(frozen=True)
class ResolvedField:
    key: str
    value_json: str
    source_layer: str
    constrained_by: tuple[str, ...]

    @property
    def value(self) -> Any:
        return json.loads(self.value_json)

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "value": self.value,
            "source_layer": self.source_layer,
            "constrained_by": list(self.constrained_by),
        }


@dataclass(frozen=True)
class ConfigSnapshot:
    snapshot_sha256: str
    layers: tuple[tuple[str, str], ...]
    fields: tuple[ResolvedField, ...]

    def __post_init__(self) -> None:
        if (
            type(self.snapshot_sha256) is not str
            or re.fullmatch(r"[0-9a-f]{64}", self.snapshot_sha256) is None
        ):
            raise ConfigError("config snapshot digest is invalid")
        if tuple(sorted(self.fields, key=lambda field: field.key)) != self.fields:
            raise ConfigError("config snapshot fields are not sorted")
        if len({field.key for field in self.fields}) != len(self.fields):
            raise ConfigError("config snapshot fields are duplicated")
        expected = hashlib.sha256(
            _canonical(self._core_dict()).encode("utf-8")
        ).hexdigest()
        if expected != self.snapshot_sha256:
            raise ConfigError("config snapshot digest does not match")

    def _core_dict(self) -> dict[str, Any]:
        return {
            "schema": CONFIG_SNAPSHOT_SCHEMA,
            "layers": [
                {"name": name, "kind": kind} for name, kind in self.layers
            ],
            "fields": [field.to_dict() for field in self.fields],
        }

    def to_dict(self) -> dict[str, Any]:
        return {"snapshot_sha256": self.snapshot_sha256, **self._core_dict()}

    @property
    def effective(self) -> dict[str, Any]:
        return {field.key: field.value for field in self.fields}


def _permission_set(value: Any, key: str) -> set[str]:
    if (
        type(value) is not list
        or len(value) > 1024
        or any(type(item) is not str or not item or len(item) > 1024 for item in value)
        or len(set(value)) != len(value)
    ):
        raise ConfigError(f"{key} must be a unique bounded string list")
    return set(value)


def resolve_config(layers: Iterable[ConfigLayer]) -> ConfigSnapshot:
    selected = tuple(layers)
    if not selected or any(type(layer) is not ConfigLayer for layer in selected):
        raise ConfigError("config stack requires typed layers")
    if len({layer.kind for layer in selected}) != len(selected):
        raise ConfigError("config stack contains duplicate layer kinds")
    ordered = tuple(sorted(selected, key=lambda layer: _PRECEDENCE[layer.kind]))
    values: dict[str, Any] = {}
    sources: dict[str, str] = {}
    constraints: dict[str, list[str]] = {}
    for layer in ordered:
        for key, incoming in layer.values.items():
            if key.startswith("permissions."):
                incoming_set = _permission_set(incoming, key)
                if key in values:
                    current_set = _permission_set(values[key], key)
                    narrowed = sorted(current_set & incoming_set)
                    if set(narrowed) != current_set:
                        constraints.setdefault(key, []).append(layer.name)
                    values[key] = narrowed
                else:
                    values[key] = sorted(incoming_set)
                    sources[key] = layer.name
                continue
            if key.startswith("limits."):
                if type(incoming) is not int or type(incoming) is bool or incoming < 0:
                    raise ConfigError(f"{key} must be a non-negative integer")
                if layer.kind is ConfigLayerKind.MANAGED and key in values:
                    current = values[key]
                    if type(current) is not int or type(current) is bool:
                        raise ConfigError(f"{key} cannot mix integer and non-integer values")
                    values[key] = min(current, incoming)
                    if values[key] != current:
                        constraints.setdefault(key, []).append(layer.name)
                else:
                    values[key] = incoming
                    sources[key] = layer.name
                continue
            values[key] = incoming
            sources[key] = layer.name
    fields = tuple(
        ResolvedField(
            key=key,
            value_json=_canonical(values[key]),
            source_layer=sources[key],
            constrained_by=tuple(constraints.get(key, ())),
        )
        for key in sorted(values)
    )
    layer_identity = tuple((layer.name, layer.kind.value) for layer in ordered)
    provisional = ConfigSnapshot.__new__(ConfigSnapshot)
    object.__setattr__(provisional, "layers", layer_identity)
    object.__setattr__(provisional, "fields", fields)
    digest = hashlib.sha256(
        _canonical(provisional._core_dict()).encode("utf-8")
    ).hexdigest()
    return ConfigSnapshot(
        snapshot_sha256=digest,
        layers=layer_identity,
        fields=fields,
    )
