"""Layered configuration with source attribution."""

from .layers import (
    CONFIG_SNAPSHOT_SCHEMA,
    ConfigError,
    ConfigLayer,
    ConfigLayerKind,
    ConfigSnapshot,
    ResolvedField,
    resolve_config,
)

__all__ = [
    "CONFIG_SNAPSHOT_SCHEMA",
    "ConfigError",
    "ConfigLayer",
    "ConfigLayerKind",
    "ConfigSnapshot",
    "ResolvedField",
    "resolve_config",
]
