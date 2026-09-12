"""Immutable task epoch context for one frozen execution boundary."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import PurePosixPath
import re
from typing import Any, Iterable

from sulde_config import ConfigSnapshot
from sulde_effects import EffectRouter
from sulde_protocol import Provider


TASK_EPOCH_CONTEXT_SCHEMA = "sulde-task-epoch-context-v1"
_HEX_24 = re.compile(r"^[0-9a-f]{24}$")
_HEX_64 = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/+\-]{0,255}$")
_MAX_OWNED_PATHS = 4096


class TaskContextError(ValueError):
    """A task epoch context is ambiguous, mutable, or unbounded."""


def _canonical(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _digest(value: str, label: str, *, optional: bool = False) -> str:
    if type(value) is not str or (
        (not value and not optional) or (value and _HEX_64.fullmatch(value) is None)
    ):
        raise TaskContextError(f"{label} must be a lowercase sha256")
    return value


def _safe_id(value: str, label: str) -> str:
    if type(value) is not str or _SAFE_ID.fullmatch(value) is None:
        raise TaskContextError(f"{label} is not a bounded identifier")
    return value


def _owned_paths(values: Iterable[str]) -> tuple[str, ...]:
    if type(values) is str:
        raise TaskContextError("owned_paths must be a collection, not text")
    paths = tuple(values)
    if len(paths) > _MAX_OWNED_PATHS:
        raise TaskContextError("owned_paths exceeds the bounded manifest")
    canonical: list[str] = []
    for raw in paths:
        if type(raw) is not str or not raw or "\\" in raw:
            raise TaskContextError("owned path must be a non-empty POSIX path")
        path = PurePosixPath(raw)
        if path.is_absolute() or ".." in path.parts or str(path) != raw:
            raise TaskContextError("owned path must be canonical and workspace-relative")
        canonical.append(raw)
    if len(set(canonical)) != len(canonical):
        raise TaskContextError("owned paths are duplicated")
    return tuple(sorted(canonical))


@dataclass(frozen=True)
class TaskBudgets:
    max_events: int
    max_context_tokens: int
    max_effects: int
    max_runtime_seconds: int

    def __post_init__(self) -> None:
        for name in (
            "max_events",
            "max_context_tokens",
            "max_effects",
            "max_runtime_seconds",
        ):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise TaskContextError(f"budget {name} must be a non-negative integer")

    def to_dict(self) -> dict[str, int]:
        return {
            "max_events": self.max_events,
            "max_context_tokens": self.max_context_tokens,
            "max_effects": self.max_effects,
            "max_runtime_seconds": self.max_runtime_seconds,
        }

    @classmethod
    def from_dict(cls, value: Any) -> "TaskBudgets":
        fields = {
            "max_events",
            "max_context_tokens",
            "max_effects",
            "max_runtime_seconds",
        }
        if type(value) is not dict or set(value) != fields:
            raise TaskContextError("task budget fields are invalid")
        return cls(**value)


@dataclass(frozen=True)
class TaskEpochContext:
    context_id: str
    workspace_id: str
    intent_id: str
    intent_revision: int
    task_epoch: str
    provider: Provider
    native_session_id: str
    task_definition_sha256: str
    owned_paths: tuple[str, ...]
    policy_sha256: str
    config_snapshot_sha256: str
    capability_manifest_sha256: str
    tool_registry_sha256: str
    verifier_registry_sha256: str
    runtime_generation: str
    legacy_cut_id: str
    budgets: TaskBudgets

    def __post_init__(self) -> None:
        _digest(self.context_id, "context_id")
        _digest(self.workspace_id, "workspace_id")
        _safe_id(self.intent_id, "intent_id")
        if (
            type(self.intent_revision) is not int
            or type(self.intent_revision) is bool
            or self.intent_revision <= 0
        ):
            raise TaskContextError("intent_revision must be a positive integer")
        if type(self.task_epoch) is not str or _HEX_24.fullmatch(self.task_epoch) is None:
            raise TaskContextError("task_epoch must be 24 lowercase hex")
        if type(self.provider) is not Provider or self.provider not in {
            Provider.CLAUDE,
            Provider.CODEX,
        }:
            raise TaskContextError("task epoch provider must be a native host")
        _safe_id(self.native_session_id, "native_session_id")
        for name in (
            "task_definition_sha256",
            "policy_sha256",
            "config_snapshot_sha256",
            "capability_manifest_sha256",
            "tool_registry_sha256",
            "verifier_registry_sha256",
            "runtime_generation",
        ):
            _digest(getattr(self, name), name)
        _digest(self.legacy_cut_id, "legacy_cut_id", optional=True)
        if _owned_paths(self.owned_paths) != self.owned_paths:
            raise TaskContextError("owned_paths must be sorted and canonical")
        if type(self.budgets) is not TaskBudgets:
            raise TaskContextError("budgets must be typed")
        expected = hashlib.sha256(_canonical(self._core_dict()).encode("utf-8")).hexdigest()
        if expected != self.context_id:
            raise TaskContextError("context_id does not match the frozen context")

    def _core_dict(self) -> dict[str, Any]:
        return {
            "schema": TASK_EPOCH_CONTEXT_SCHEMA,
            "workspace_id": self.workspace_id,
            "intent_id": self.intent_id,
            "intent_revision": self.intent_revision,
            "task_epoch": self.task_epoch,
            "provider": self.provider.value,
            "native_session_id": self.native_session_id,
            "task_definition_sha256": self.task_definition_sha256,
            "owned_paths": list(self.owned_paths),
            "policy_sha256": self.policy_sha256,
            "config_snapshot_sha256": self.config_snapshot_sha256,
            "capability_manifest_sha256": self.capability_manifest_sha256,
            "tool_registry_sha256": self.tool_registry_sha256,
            "verifier_registry_sha256": self.verifier_registry_sha256,
            "runtime_generation": self.runtime_generation,
            "legacy_cut_id": self.legacy_cut_id,
            "budgets": self.budgets.to_dict(),
        }

    def to_dict(self) -> dict[str, Any]:
        return {"context_id": self.context_id, **self._core_dict()}

    @classmethod
    def build(
        cls,
        *,
        workspace_id: str,
        intent_id: str,
        intent_revision: int,
        task_epoch: str,
        provider: Provider,
        native_session_id: str,
        task_definition_sha256: str,
        owned_paths: Iterable[str],
        policy_sha256: str,
        config_snapshot: ConfigSnapshot,
        effect_router: EffectRouter,
        tool_registry_sha256: str,
        runtime_generation: str,
        budgets: TaskBudgets,
        legacy_cut_id: str = "",
    ) -> "TaskEpochContext":
        if type(config_snapshot) is not ConfigSnapshot:
            raise TaskContextError("config_snapshot must be typed")
        if type(effect_router) is not EffectRouter:
            raise TaskContextError("effect_router must be typed")
        values = {
            "workspace_id": workspace_id,
            "intent_id": intent_id,
            "intent_revision": intent_revision,
            "task_epoch": task_epoch,
            "provider": provider,
            "native_session_id": native_session_id,
            "task_definition_sha256": task_definition_sha256,
            "owned_paths": _owned_paths(owned_paths),
            "policy_sha256": policy_sha256,
            "config_snapshot_sha256": config_snapshot.snapshot_sha256,
            "capability_manifest_sha256": effect_router.manifest_sha256,
            "tool_registry_sha256": tool_registry_sha256,
            "verifier_registry_sha256": effect_router.verifier_manifest_sha256,
            "runtime_generation": runtime_generation,
            "legacy_cut_id": legacy_cut_id,
            "budgets": budgets,
        }
        provisional = cls.__new__(cls)
        for name, value in values.items():
            object.__setattr__(provisional, name, value)
        context_id = hashlib.sha256(
            _canonical(provisional._core_dict()).encode("utf-8")
        ).hexdigest()
        return cls(context_id=context_id, **values)

    @classmethod
    def from_dict(cls, value: Any) -> "TaskEpochContext":
        fields = {
            "context_id",
            "schema",
            "workspace_id",
            "intent_id",
            "intent_revision",
            "task_epoch",
            "provider",
            "native_session_id",
            "task_definition_sha256",
            "owned_paths",
            "policy_sha256",
            "config_snapshot_sha256",
            "capability_manifest_sha256",
            "tool_registry_sha256",
            "verifier_registry_sha256",
            "runtime_generation",
            "legacy_cut_id",
            "budgets",
        }
        if type(value) is not dict or set(value) != fields:
            raise TaskContextError("task epoch context fields are invalid")
        if value.get("schema") != TASK_EPOCH_CONTEXT_SCHEMA:
            raise TaskContextError("task epoch context schema is invalid")
        try:
            provider = Provider(value["provider"])
        except (TypeError, ValueError) as error:
            raise TaskContextError("task epoch provider is invalid") from error
        owned = value["owned_paths"]
        if type(owned) is not list:
            raise TaskContextError("owned_paths must be a list")
        return cls(
            context_id=value["context_id"],
            workspace_id=value["workspace_id"],
            intent_id=value["intent_id"],
            intent_revision=value["intent_revision"],
            task_epoch=value["task_epoch"],
            provider=provider,
            native_session_id=value["native_session_id"],
            task_definition_sha256=value["task_definition_sha256"],
            owned_paths=tuple(owned),
            policy_sha256=value["policy_sha256"],
            config_snapshot_sha256=value["config_snapshot_sha256"],
            capability_manifest_sha256=value["capability_manifest_sha256"],
            tool_registry_sha256=value["tool_registry_sha256"],
            verifier_registry_sha256=value["verifier_registry_sha256"],
            runtime_generation=value["runtime_generation"],
            legacy_cut_id=value["legacy_cut_id"],
            budgets=TaskBudgets.from_dict(value["budgets"]),
        )
