"""SQLite inbox and authoritative single-writer drain for one workspace."""

from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
from typing import Iterator

from sulde_protocol import (
    EventEnvelope,
    EventProtocolError,
    EventSubmission,
    EventType,
    SupervisorState,
)
from sulde_state_machine import GuardianState, TransitionError, replay, transition

from .codec import state_from_json, state_to_json
from .models import (
    DrainResult,
    InboxFull,
    StaleGeneration,
    StoreAudit,
    StoreCorruption,
    SubmissionReceipt,
    SubmissionStatus,
    SupervisorBusy,
    SupervisorError,
)


STORE_SCHEMA = "sulde-workspace-supervisor-v1"
DEFAULT_MAX_PENDING = 256
DEFAULT_MAX_PENDING_BYTES = 8 * 1024 * 1024
MAX_DRAIN_BATCH = 256
_SAFE_WRITER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/+\-]{0,255}$")


_SCHEMA_SQL = """
CREATE TABLE supervisor_meta (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    schema TEXT NOT NULL,
    initial_state_json TEXT NOT NULL,
    active_generation TEXT NOT NULL,
    pending_generation TEXT NOT NULL,
    max_pending INTEGER NOT NULL CHECK (max_pending > 0),
    max_pending_bytes INTEGER NOT NULL CHECK (max_pending_bytes > 0),
    writer_epoch INTEGER NOT NULL CHECK (writer_epoch >= 0)
);
CREATE TABLE supervisor_projection (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    state_json TEXT NOT NULL
);
CREATE TABLE supervisor_inbox (
    ordinal INTEGER PRIMARY KEY AUTOINCREMENT,
    submission_id TEXT NOT NULL UNIQUE,
    submission_json TEXT NOT NULL,
    byte_count INTEGER NOT NULL CHECK (byte_count > 0),
    status TEXT NOT NULL CHECK (status IN ('queued', 'applied', 'rejected')),
    reason TEXT NOT NULL,
    event_id TEXT NOT NULL,
    writer_epoch INTEGER NOT NULL CHECK (writer_epoch >= 0)
);
CREATE TABLE supervisor_ledger (
    sequence INTEGER PRIMARY KEY CHECK (sequence > 0),
    event_id TEXT NOT NULL UNIQUE,
    submission_id TEXT NOT NULL UNIQUE,
    envelope_json TEXT NOT NULL,
    writer_id TEXT NOT NULL,
    writer_epoch INTEGER NOT NULL CHECK (writer_epoch > 0),
    FOREIGN KEY (submission_id)
        REFERENCES supervisor_inbox(submission_id)
);
CREATE INDEX supervisor_inbox_status_ordinal
    ON supervisor_inbox(status, ordinal);
"""


def _canonical_json(value: dict[str, object]) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _bounded_reason(prefix: str, error: Exception) -> str:
    rendered = " ".join(str(error).split())
    return f"{prefix}:{rendered}"[:500]


class WorkspaceSupervisor:
    """One workspace store whose reducer changes occur in one SQLite writer."""

    def __init__(self, path: Path | str, *, busy_timeout_ms: int = 250) -> None:
        self.path = Path(os.path.abspath(Path(path).expanduser()))
        if (
            type(busy_timeout_ms) is not int
            or type(busy_timeout_ms) is bool
            or not 0 <= busy_timeout_ms <= 5_000
        ):
            raise SupervisorError("busy_timeout_ms must be between 0 and 5000")
        self.busy_timeout_ms = busy_timeout_ms

    @classmethod
    def initialize(
        cls,
        path: Path | str,
        state: GuardianState,
        *,
        max_pending: int = DEFAULT_MAX_PENDING,
        max_pending_bytes: int = DEFAULT_MAX_PENDING_BYTES,
        busy_timeout_ms: int = 250,
    ) -> "WorkspaceSupervisor":
        if type(state) is not GuardianState or state.sequence != 0:
            raise SupervisorError("supervisor initialization requires an initial state")
        if (
            type(max_pending) is not int
            or type(max_pending) is bool
            or not 1 <= max_pending <= 4096
        ):
            raise SupervisorError("max_pending must be between 1 and 4096")
        if (
            type(max_pending_bytes) is not int
            or type(max_pending_bytes) is bool
            or not 1024 <= max_pending_bytes <= 64 * 1024 * 1024
        ):
            raise SupervisorError(
                "max_pending_bytes must be between 1 KiB and 64 MiB"
            )
        store = cls(path, busy_timeout_ms=busy_timeout_ms)
        if not store.path.parent.is_dir():
            raise SupervisorError("supervisor database parent does not exist")
        flags = os.O_CREAT | os.O_EXCL | os.O_RDWR
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(store.path, flags, 0o600)
        except FileExistsError as error:
            raise SupervisorError("supervisor database already exists") from error
        except OSError as error:
            raise SupervisorError(
                f"supervisor database cannot be created: {type(error).__name__}"
            ) from error
        else:
            os.close(descriptor)
        state_json = state_to_json(state)
        try:
            connection = store._connect()
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=FULL")
            connection.executescript(_SCHEMA_SQL)
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO supervisor_meta(
                    singleton, schema, initial_state_json, active_generation,
                    pending_generation, max_pending, max_pending_bytes,
                    writer_epoch
                ) VALUES (1, ?, ?, ?, '', ?, ?, 0)
                """,
                (
                    STORE_SCHEMA,
                    state_json,
                    state.runtime_generation,
                    max_pending,
                    max_pending_bytes,
                ),
            )
            connection.execute(
                "INSERT INTO supervisor_projection(singleton, state_json) VALUES (1, ?)",
                (state_json,),
            )
            connection.commit()
        except (OSError, sqlite3.Error) as error:
            raise SupervisorError(
                f"supervisor database initialization failed: {type(error).__name__}"
            ) from error
        finally:
            if "connection" in locals():
                connection.close()
        store.audit()
        return store

    def _connect(self) -> sqlite3.Connection:
        try:
            metadata = os.stat(self.path, follow_symlinks=False)
        except OSError as error:
            raise StoreCorruption("supervisor database is missing") from error
        if (
            self.path.is_symlink()
            or not stat.S_ISREG(metadata.st_mode)
            or (
                os.name == "posix"
                and (
                    metadata.st_uid != os.getuid()
                    or metadata.st_mode & 0o077
                )
            )
        ):
            raise StoreCorruption("supervisor database is missing or not a regular file")
        connection = sqlite3.connect(
            self.path,
            timeout=self.busy_timeout_ms / 1000,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(f"PRAGMA busy_timeout={self.busy_timeout_ms}")
        return connection

    @contextmanager
    def _write_transaction(self) -> Iterator[sqlite3.Connection]:
        connection: sqlite3.Connection | None = None
        try:
            connection = self._connect()
            connection.execute("BEGIN IMMEDIATE")
            self._meta(connection)
            yield connection
            connection.commit()
        except sqlite3.OperationalError as error:
            if connection is not None and connection.in_transaction:
                connection.rollback()
            message = str(error).lower()
            if "locked" in message or "busy" in message:
                raise SupervisorBusy(
                    "workspace writer is busy; the request was not accepted"
                ) from error
            raise StoreCorruption("supervisor SQLite operation failed") from error
        except Exception:
            if connection is not None and connection.in_transaction:
                connection.rollback()
            raise
        finally:
            if connection is not None:
                connection.close()

    @staticmethod
    def _meta(connection: sqlite3.Connection) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM supervisor_meta WHERE singleton = 1"
        ).fetchone()
        if row is None or row["schema"] != STORE_SCHEMA:
            raise StoreCorruption("supervisor metadata is missing or unsupported")
        return row

    @staticmethod
    def _projection(connection: sqlite3.Connection) -> GuardianState:
        row = connection.execute(
            "SELECT state_json FROM supervisor_projection WHERE singleton = 1"
        ).fetchone()
        if row is None:
            raise StoreCorruption("supervisor projection is missing")
        return state_from_json(row["state_json"])

    @staticmethod
    def _persist_projection(
        connection: sqlite3.Connection, state: GuardianState
    ) -> None:
        changed = connection.execute(
            "UPDATE supervisor_projection SET state_json = ? WHERE singleton = 1",
            (state_to_json(state),),
        ).rowcount
        if changed != 1:
            raise StoreCorruption("supervisor projection update was not singular")

    @staticmethod
    def _receipt(row: sqlite3.Row) -> SubmissionReceipt:
        try:
            status = SubmissionStatus(row["status"])
        except (KeyError, ValueError) as error:
            raise StoreCorruption("supervisor receipt status is invalid") from error
        return SubmissionReceipt(
            submission_id=row["submission_id"],
            status=status,
            event_id=row["event_id"],
            reason=row["reason"],
            writer_epoch=row["writer_epoch"],
        )

    @staticmethod
    def _insert_rejected(
        connection: sqlite3.Connection,
        *,
        submission: EventSubmission,
        submission_json: str,
        byte_count: int,
        reason: str,
    ) -> SubmissionReceipt:
        connection.execute(
            """
            INSERT INTO supervisor_inbox(
                submission_id, submission_json, byte_count, status, reason,
                event_id, writer_epoch
            ) VALUES (?, ?, ?, 'rejected', ?, '', 0)
            """,
            (submission.submission_id, submission_json, byte_count, reason),
        )
        return SubmissionReceipt(
            submission_id=submission.submission_id,
            status=SubmissionStatus.REJECTED,
            reason=reason,
        )

    def submit(self, submission: EventSubmission) -> SubmissionReceipt:
        if type(submission) is not EventSubmission:
            raise SupervisorError("supervisor accepts only EventSubmission values")
        submission_json = _canonical_json(submission.to_dict())
        byte_count = len(submission_json.encode("utf-8"))
        with self._write_transaction() as connection:
            existing = connection.execute(
                "SELECT * FROM supervisor_inbox WHERE submission_id = ?",
                (submission.submission_id,),
            ).fetchone()
            if existing is not None:
                return self._receipt(existing)
            meta = self._meta(connection)
            state = self._projection(connection)
            rejection = ""
            if submission.workspace_id != state.workspace_id:
                rejection = "workspace_mismatch"
            elif submission.correlation.task_epoch != state.task_epoch:
                rejection = "task_epoch_mismatch"
            elif (
                submission.correlation.task_epoch_context_id
                != state.task_epoch_context_id
            ):
                rejection = "task_context_mismatch"
            elif meta["pending_generation"]:
                rejection = "generation_switch_pending"
            elif submission.event_type is EventType.SUPERVISOR_GENERATION_ACTIVATED:
                queued = connection.execute(
                    "SELECT COUNT(*) FROM supervisor_inbox WHERE status = 'queued'"
                ).fetchone()[0]
                if submission.runtime_generation == meta["active_generation"]:
                    rejection = "generation_already_active"
                elif state.supervisor is not SupervisorState.STOPPED:
                    rejection = "generation_activation_requires_stopped_supervisor"
                elif queued:
                    rejection = "generation_activation_requires_empty_inbox"
            elif submission.runtime_generation != meta["active_generation"]:
                rejection = "stale_generation"
            if rejection:
                return self._insert_rejected(
                    connection,
                    submission=submission,
                    submission_json=submission_json,
                    byte_count=byte_count,
                    reason=rejection,
                )
            queued_count, queued_bytes = connection.execute(
                """
                SELECT COUNT(*), COALESCE(SUM(byte_count), 0)
                FROM supervisor_inbox WHERE status = 'queued'
                """
            ).fetchone()
            if (
                queued_count >= meta["max_pending"]
                or queued_bytes + byte_count > meta["max_pending_bytes"]
            ):
                raise InboxFull(
                    "bounded workspace inbox is full; the request was not accepted"
                )
            connection.execute(
                """
                INSERT INTO supervisor_inbox(
                    submission_id, submission_json, byte_count, status, reason,
                    event_id, writer_epoch
                ) VALUES (?, ?, ?, 'queued', '', '', 0)
                """,
                (submission.submission_id, submission_json, byte_count),
            )
            if submission.event_type is EventType.SUPERVISOR_GENERATION_ACTIVATED:
                connection.execute(
                    "UPDATE supervisor_meta SET pending_generation = ? WHERE singleton = 1",
                    (submission.runtime_generation,),
                )
            return SubmissionReceipt(
                submission_id=submission.submission_id,
                status=SubmissionStatus.QUEUED,
            )

    def drain(
        self,
        *,
        expected_generation: str,
        writer_id: str,
        limit: int = 64,
    ) -> DrainResult:
        if type(writer_id) is not str or _SAFE_WRITER.fullmatch(writer_id) is None:
            raise SupervisorError("writer_id is not a bounded identifier")
        if type(limit) is not int or type(limit) is bool or not 1 <= limit <= MAX_DRAIN_BATCH:
            raise SupervisorError(f"drain limit must be between 1 and {MAX_DRAIN_BATCH}")
        receipts: list[SubmissionReceipt] = []
        with self._write_transaction() as connection:
            meta = self._meta(connection)
            if expected_generation != meta["active_generation"]:
                raise StaleGeneration("writer generation is no longer active")
            rows = connection.execute(
                """
                SELECT * FROM supervisor_inbox
                WHERE status = 'queued' ORDER BY ordinal LIMIT ?
                """,
                (limit,),
            ).fetchall()
            if not rows:
                return DrainResult(
                    writer_id=writer_id,
                    writer_epoch=meta["writer_epoch"],
                    active_generation=meta["active_generation"],
                    receipts=(),
                )
            writer_epoch = meta["writer_epoch"] + 1
            connection.execute(
                "UPDATE supervisor_meta SET writer_epoch = ? WHERE singleton = 1",
                (writer_epoch,),
            )
            state = self._projection(connection)
            for row in rows:
                try:
                    raw_submission = json.loads(row["submission_json"])
                    submission = EventSubmission.from_dict(raw_submission)
                except (json.JSONDecodeError, EventProtocolError) as error:
                    raise StoreCorruption(
                        "accepted supervisor submission cannot be decoded"
                    ) from error
                if _canonical_json(submission.to_dict()) != row["submission_json"]:
                    raise StoreCorruption(
                        "accepted supervisor submission is not canonical"
                    )
                envelope = submission.to_envelope(
                    sequence=state.sequence + 1,
                    previous_event_id=state.last_event_id,
                )
                try:
                    result = transition(state, envelope)
                except TransitionError as error:
                    reason = _bounded_reason("transition_rejected", error)
                    connection.execute(
                        """
                        UPDATE supervisor_inbox
                        SET status = 'rejected', reason = ?, writer_epoch = ?
                        WHERE submission_id = ? AND status = 'queued'
                        """,
                        (reason, writer_epoch, submission.submission_id),
                    )
                    if (
                        submission.event_type
                        is EventType.SUPERVISOR_GENERATION_ACTIVATED
                    ):
                        connection.execute(
                            """
                            UPDATE supervisor_meta SET pending_generation = ''
                            WHERE singleton = 1
                            """
                        )
                    receipts.append(
                        SubmissionReceipt(
                            submission_id=submission.submission_id,
                            status=SubmissionStatus.REJECTED,
                            reason=reason,
                            writer_epoch=writer_epoch,
                        )
                    )
                    continue
                envelope_json = _canonical_json(envelope.to_dict())
                connection.execute(
                    """
                    INSERT INTO supervisor_ledger(
                        sequence, event_id, submission_id, envelope_json,
                        writer_id, writer_epoch
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        envelope.sequence,
                        envelope.event_id,
                        submission.submission_id,
                        envelope_json,
                        writer_id,
                        writer_epoch,
                    ),
                )
                self._persist_projection(connection, result.state)
                changed = connection.execute(
                    """
                    UPDATE supervisor_inbox
                    SET status = 'applied', event_id = ?, writer_epoch = ?
                    WHERE submission_id = ? AND status = 'queued'
                    """,
                    (envelope.event_id, writer_epoch, submission.submission_id),
                ).rowcount
                if changed != 1:
                    raise StoreCorruption("submission terminal update was not singular")
                if submission.event_type is EventType.SUPERVISOR_GENERATION_ACTIVATED:
                    connection.execute(
                        """
                        UPDATE supervisor_meta
                        SET active_generation = ?, pending_generation = ''
                        WHERE singleton = 1
                        """,
                        (result.state.runtime_generation,),
                    )
                state = result.state
                receipts.append(
                    SubmissionReceipt(
                        submission_id=submission.submission_id,
                        status=SubmissionStatus.APPLIED,
                        event_id=envelope.event_id,
                        writer_epoch=writer_epoch,
                    )
                )
            active_generation = self._meta(connection)["active_generation"]
        return DrainResult(
            writer_id=writer_id,
            writer_epoch=writer_epoch,
            active_generation=active_generation,
            receipts=tuple(receipts),
        )

    def projection(self) -> GuardianState:
        try:
            connection = self._connect()
            self._meta(connection)
            return self._projection(connection)
        except sqlite3.Error as error:
            raise StoreCorruption("supervisor projection read failed") from error
        finally:
            if "connection" in locals():
                connection.close()

    def receipt(self, submission_id: str) -> SubmissionReceipt | None:
        try:
            connection = self._connect()
            self._meta(connection)
            row = connection.execute(
                "SELECT * FROM supervisor_inbox WHERE submission_id = ?",
                (submission_id,),
            ).fetchone()
            return None if row is None else self._receipt(row)
        except sqlite3.Error as error:
            raise StoreCorruption("supervisor receipt read failed") from error
        finally:
            if "connection" in locals():
                connection.close()

    def events(self) -> tuple[EventEnvelope, ...]:
        try:
            connection = self._connect()
            self._meta(connection)
            rows = connection.execute(
                "SELECT * FROM supervisor_ledger ORDER BY sequence"
            ).fetchall()
            events: list[EventEnvelope] = []
            for row in rows:
                try:
                    raw_event = json.loads(row["envelope_json"])
                    event = EventEnvelope.from_dict(raw_event)
                except (json.JSONDecodeError, EventProtocolError) as error:
                    raise StoreCorruption("supervisor ledger event is invalid") from error
                if (
                    event.sequence != row["sequence"]
                    or event.event_id != row["event_id"]
                    or _canonical_json(event.to_dict()) != row["envelope_json"]
                ):
                    raise StoreCorruption("supervisor ledger binding is invalid")
                events.append(event)
            return tuple(events)
        except sqlite3.Error as error:
            raise StoreCorruption("supervisor ledger read failed") from error
        finally:
            if "connection" in locals():
                connection.close()

    def audit(self) -> StoreAudit:
        try:
            connection = self._connect()
            meta = self._meta(connection)
            projection = self._projection(connection)
            initial = state_from_json(meta["initial_state_json"])
            ledger_rows = connection.execute(
                "SELECT * FROM supervisor_ledger ORDER BY sequence"
            ).fetchall()
            events: list[EventEnvelope] = []
            for expected_sequence, row in enumerate(ledger_rows, start=1):
                try:
                    event = EventEnvelope.from_dict(
                        json.loads(row["envelope_json"])
                    )
                except (json.JSONDecodeError, EventProtocolError) as error:
                    raise StoreCorruption("supervisor audit cannot decode ledger") from error
                if (
                    row["sequence"] != expected_sequence
                    or event.sequence != expected_sequence
                    or row["event_id"] != event.event_id
                    or _canonical_json(event.to_dict()) != row["envelope_json"]
                ):
                    raise StoreCorruption("supervisor audit found an invalid ledger row")
                events.append(event)
            try:
                replayed = replay(initial, events)
            except TransitionError as error:
                raise StoreCorruption("supervisor ledger cannot be replayed") from error
            if replayed != projection:
                raise StoreCorruption("replayed ledger differs from persisted projection")
            if projection.runtime_generation != meta["active_generation"]:
                raise StoreCorruption("projection generation differs from supervisor meta")
            applied = connection.execute(
                "SELECT COUNT(*) FROM supervisor_inbox WHERE status = 'applied'"
            ).fetchone()[0]
            if applied != len(events):
                raise StoreCorruption("applied receipts differ from the ledger")
            queued_count, queued_bytes = connection.execute(
                """
                SELECT COUNT(*), COALESCE(SUM(byte_count), 0)
                FROM supervisor_inbox WHERE status = 'queued'
                """
            ).fetchone()
            if (
                queued_count > meta["max_pending"]
                or queued_bytes > meta["max_pending_bytes"]
            ):
                raise StoreCorruption("supervisor inbox exceeds its frozen bounds")
            pending_generation = meta["pending_generation"]
            if pending_generation:
                pending = connection.execute(
                    """
                    SELECT submission_json FROM supervisor_inbox
                    WHERE status = 'queued'
                    """
                ).fetchall()
                if len(pending) != 1:
                    raise StoreCorruption("generation switch is not singular")
                try:
                    submission = EventSubmission.from_dict(
                        json.loads(pending[0]["submission_json"])
                    )
                except (json.JSONDecodeError, EventProtocolError) as error:
                    raise StoreCorruption("pending generation request is invalid") from error
                if (
                    submission.event_type
                    is not EventType.SUPERVISOR_GENERATION_ACTIVATED
                    or submission.runtime_generation != pending_generation
                ):
                    raise StoreCorruption("pending generation binding is invalid")
            return StoreAudit(
                event_count=len(events),
                sequence=projection.sequence,
                last_event_id=projection.last_event_id,
                runtime_generation=projection.runtime_generation,
            )
        except sqlite3.Error as error:
            raise StoreCorruption("supervisor audit query failed") from error
        finally:
            if "connection" in locals():
                connection.close()
