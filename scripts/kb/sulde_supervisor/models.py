"""Typed results and errors for the workspace supervisor."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class SupervisorError(RuntimeError):
    """The supervisor cannot safely accept or apply a request."""


class SupervisorBusy(SupervisorError):
    """Another bounded writer transaction currently owns the SQLite lock."""


class InboxFull(SupervisorError):
    """The bounded inbox refused a new request before accepting it."""


class StaleGeneration(SupervisorError):
    """A writer tried to drain a generation that is no longer active."""


class StoreCorruption(SupervisorError):
    """Persisted supervisor truth cannot be validated or replayed."""


class SubmissionStatus(str, Enum):
    QUEUED = "queued"
    APPLIED = "applied"
    REJECTED = "rejected"


@dataclass(frozen=True)
class SubmissionReceipt:
    submission_id: str
    status: SubmissionStatus
    event_id: str = ""
    reason: str = ""
    writer_epoch: int = 0


@dataclass(frozen=True)
class DrainResult:
    writer_id: str
    writer_epoch: int
    active_generation: str
    receipts: tuple[SubmissionReceipt, ...]


@dataclass(frozen=True)
class StoreAudit:
    event_count: int
    sequence: int
    last_event_id: str
    runtime_generation: str
