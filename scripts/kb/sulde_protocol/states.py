"""Domain-specific state vocabularies shared by reducers and adapters.

The domains intentionally remain separate.  A task awaiting a person, an
approval awaiting a decision, and an effect awaiting verification are not the
same state and must never be collapsed into one stringly typed ``status``.
"""

from __future__ import annotations

from enum import Enum


class ContractState(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    CLOSED = "closed"


class TaskLifecycleState(str, Enum):
    NONE = "none"
    CREATED = "created"
    BOUND = "bound"
    RUNNING = "running"
    AWAITING_HUMAN = "awaiting_human"
    VERIFYING = "verifying"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    INCONCLUSIVE = "inconclusive"


class ApprovalState(str, Enum):
    NONE = "none"
    ASKED = "asked"
    REASSESSMENT_DUE = "reassessment_due"
    DECIDED = "decided"
    EXPIRED = "expired"


class EffectState(str, Enum):
    NONE = "none"
    PREPARED = "prepared"
    DISPATCHED = "dispatched"
    VERIFYING = "verifying"
    VERIFIED = "verified"
    UNKNOWN = "unknown"
    ABORTED = "aborted"


class InterventionState(str, Enum):
    NONE = "none"
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


class SupervisorState(str, Enum):
    STARTING = "starting"
    READY = "ready"
    DEGRADED = "degraded"
    BLOCKED = "blocked"
    STOPPED = "stopped"
