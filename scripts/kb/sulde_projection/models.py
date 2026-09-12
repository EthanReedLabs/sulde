"""Immutable legacy-cut and semantic projection values."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import re
from typing import Any


LEGACY_CUT_SCHEMA = "sulde-legacy-control-cut-v2"
LEGACY_PROJECTION_SCHEMA = "sulde-legacy-semantic-projection-v2"
_HEX_24 = re.compile(r"^[0-9a-f]{24}$")
_HEX_64 = re.compile(r"^[0-9a-f]{64}$")


class LegacyProjectionError(ValueError):
    """Legacy control state cannot be frozen or projected safely."""


class LegacyCutChanged(LegacyProjectionError):
    """At least one legacy source changed while the read-only cut was built."""


class LegacyContractState(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    CLOSED = "closed"


class LegacyTaskState(str, Enum):
    NONE = "none"
    RUNNING = "running"
    AWAITING_HUMAN = "awaiting_human"
    VERIFYING = "verifying"


class LegacyApprovalState(str, Enum):
    NONE = "none"
    ASKED = "asked"


class LegacyEffectState(str, Enum):
    NONE = "none"
    UNKNOWN = "unknown"


class LegacyInterventionState(str, Enum):
    NONE = "none"
    OPEN = "open"


@dataclass(frozen=True)
class SourceFingerprint:
    label: str
    path: str
    material: bool
    exists: bool
    byte_count: int
    sha256: str
    device: int
    inode: int
    modified_ns: int

    def __post_init__(self) -> None:
        if (
            type(self.label) is not str
            or not self.label
            or len(self.label) > 100
            or type(self.path) is not str
            or not self.path
            or len(self.path) > 4096
        ):
            raise LegacyProjectionError("legacy source identity is invalid")
        if type(self.material) is not bool or type(self.exists) is not bool:
            raise LegacyProjectionError("legacy source flags are invalid")
        for name in ("byte_count", "device", "inode", "modified_ns"):
            value = getattr(self, name)
            if type(value) is not int or type(value) is bool or value < 0:
                raise LegacyProjectionError(f"legacy source {name} is invalid")
        if type(self.sha256) is not str or _HEX_64.fullmatch(self.sha256) is None:
            raise LegacyProjectionError("legacy source digest is invalid")
        if not self.exists and any(
            (self.byte_count, self.device, self.inode, self.modified_ns)
        ):
            raise LegacyProjectionError("missing legacy source carries file identity")

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "path": self.path,
            "material": self.material,
            "exists": self.exists,
            "byte_count": self.byte_count,
            "sha256": self.sha256,
            "device": self.device,
            "inode": self.inode,
            "modified_ns": self.modified_ns,
        }


@dataclass(frozen=True)
class LegacySemanticProjection:
    workspace_id: str
    intent_id: str
    intent_revision: int
    task_epoch: str
    runtime_generation: str
    contract_material_digest: str
    contract_state: LegacyContractState
    task_state: LegacyTaskState
    approval_state: LegacyApprovalState
    effect_state: LegacyEffectState
    intervention_state: LegacyInterventionState
    contract_sequence: int
    material_sequence: int
    open_events: int
    pending_verifications: int
    active_skills: int
    paused_lanes: int
    open_approval_requests: int
    expired_approval_requests: int
    pending_native_transactions: int
    historical_unsealed_native_transactions: int
    blocking_effect_attempts: int
    open_interventions: int
    integrity_breaches: int
    pending_proposal: bool
    confirmation_required: bool
    blockers: tuple[str, ...]

    def __post_init__(self) -> None:
        if _HEX_64.fullmatch(self.workspace_id) is None:
            raise LegacyProjectionError("legacy workspace ID is invalid")
        if _HEX_24.fullmatch(self.task_epoch) is None:
            raise LegacyProjectionError("legacy task epoch is invalid")
        if _HEX_64.fullmatch(self.runtime_generation) is None:
            raise LegacyProjectionError("legacy runtime generation is invalid")
        if _HEX_64.fullmatch(self.contract_material_digest) is None:
            raise LegacyProjectionError("legacy contract material digest is invalid")
        if type(self.intent_id) is not str or not self.intent_id:
            raise LegacyProjectionError("legacy intent ID is invalid")
        if (
            type(self.intent_revision) is not int
            or type(self.intent_revision) is bool
            or self.intent_revision < 1
        ):
            raise LegacyProjectionError("legacy intent revision is invalid")
        for name in (
            "contract_sequence",
            "material_sequence",
            "open_events",
            "pending_verifications",
            "active_skills",
            "paused_lanes",
            "open_approval_requests",
            "expired_approval_requests",
            "pending_native_transactions",
            "historical_unsealed_native_transactions",
            "blocking_effect_attempts",
            "open_interventions",
            "integrity_breaches",
        ):
            value = getattr(self, name)
            if type(value) is not int or type(value) is bool or value < 0:
                raise LegacyProjectionError(f"legacy {name} is invalid")
        if type(self.pending_proposal) is not bool or type(
            self.confirmation_required
        ) is not bool:
            raise LegacyProjectionError("legacy projection flags are invalid")
        if (
            type(self.blockers) is not tuple
            or len(set(self.blockers)) != len(self.blockers)
            or any(type(item) is not str or not item for item in self.blockers)
        ):
            raise LegacyProjectionError("legacy cutover blockers are invalid")

    @property
    def quiescent(self) -> bool:
        return not self.blockers

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": LEGACY_PROJECTION_SCHEMA,
            "workspace_id": self.workspace_id,
            "intent_id": self.intent_id,
            "intent_revision": self.intent_revision,
            "task_epoch": self.task_epoch,
            "runtime_generation": self.runtime_generation,
            "contract_material_digest": self.contract_material_digest,
            "contract_state": self.contract_state.value,
            "task_state": self.task_state.value,
            "approval_state": self.approval_state.value,
            "effect_state": self.effect_state.value,
            "intervention_state": self.intervention_state.value,
            "contract_sequence": self.contract_sequence,
            "material_sequence": self.material_sequence,
            "open_events": self.open_events,
            "pending_verifications": self.pending_verifications,
            "active_skills": self.active_skills,
            "paused_lanes": self.paused_lanes,
            "open_approval_requests": self.open_approval_requests,
            "expired_approval_requests": self.expired_approval_requests,
            "pending_native_transactions": self.pending_native_transactions,
            "historical_unsealed_native_transactions": (
                self.historical_unsealed_native_transactions
            ),
            "blocking_effect_attempts": self.blocking_effect_attempts,
            "open_interventions": self.open_interventions,
            "integrity_breaches": self.integrity_breaches,
            "pending_proposal": self.pending_proposal,
            "confirmation_required": self.confirmation_required,
            "blockers": list(self.blockers),
        }

    def binding_dict(self) -> dict[str, Any]:
        """Exclude observation counters that may advance because cut audit is observed."""
        value = self.to_dict()
        value.pop("contract_sequence")
        value.pop("expired_approval_requests")
        return value


def _canonical(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


@dataclass(frozen=True)
class LegacyControlCut:
    cut_id: str
    sources: tuple[SourceFingerprint, ...]
    projection: LegacySemanticProjection

    def __post_init__(self) -> None:
        if type(self.cut_id) is not str or _HEX_64.fullmatch(self.cut_id) is None:
            raise LegacyProjectionError("legacy cut ID is invalid")
        if (
            type(self.sources) is not tuple
            or not self.sources
            or len({source.label for source in self.sources}) != len(self.sources)
            or tuple(sorted(self.sources, key=lambda source: source.label))
            != self.sources
        ):
            raise LegacyProjectionError("legacy cut sources are invalid")
        expected = hashlib.sha256(
            _canonical(self._binding_core_dict()).encode("utf-8")
        ).hexdigest()
        if expected != self.cut_id:
            raise LegacyProjectionError("legacy cut ID does not match its content")

    def _core_dict(self) -> dict[str, Any]:
        return {
            "schema": LEGACY_CUT_SCHEMA,
            "sources": [source.to_dict() for source in self.sources],
            "projection": self.projection.to_dict(),
        }

    def _binding_core_dict(self) -> dict[str, Any]:
        return {
            "schema": LEGACY_CUT_SCHEMA,
            "material_sources": [
                source.to_dict() for source in self.sources if source.material
            ],
            "projection": self.projection.binding_dict(),
        }

    def to_dict(self) -> dict[str, Any]:
        return {"cut_id": self.cut_id, **self._core_dict()}

    @classmethod
    def build(
        cls,
        *,
        sources: tuple[SourceFingerprint, ...],
        projection: LegacySemanticProjection,
    ) -> "LegacyControlCut":
        ordered = tuple(sorted(sources, key=lambda source: source.label))
        provisional = cls.__new__(cls)
        object.__setattr__(provisional, "sources", ordered)
        object.__setattr__(provisional, "projection", projection)
        cut_id = hashlib.sha256(
            _canonical(provisional._binding_core_dict()).encode("utf-8")
        ).hexdigest()
        return cls(cut_id=cut_id, sources=ordered, projection=projection)
