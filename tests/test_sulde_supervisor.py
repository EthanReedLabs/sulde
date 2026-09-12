from __future__ import annotations

import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
KB = ROOT / "scripts" / "kb"
sys.path.insert(0, str(KB))

from sulde_protocol import (  # noqa: E402
    EventCorrelation,
    EventSubmission,
    EventType,
    Provider,
    SupervisorState,
    TaskLifecycleState,
)
from sulde_state_machine import initial_state  # noqa: E402
from sulde_supervisor import (  # noqa: E402
    InboxFull,
    StaleGeneration,
    StoreCorruption,
    SubmissionStatus,
    SupervisorBusy,
    WorkspaceSupervisor,
)


WORKSPACE_ID = "b" * 64
TASK_EPOCH = "e" * 24
GENERATION = "a" * 64
NEXT_GENERATION = "c" * 64


class WorkspaceSupervisorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.database = Path(self.temporary.name) / "supervisor.sqlite3"
        self.store = WorkspaceSupervisor.initialize(
            self.database,
            initial_state(
                workspace_id=WORKSPACE_ID,
                task_epoch=TASK_EPOCH,
                runtime_generation=GENERATION,
            ),
            busy_timeout_ms=0,
        )

    def submission(
        self,
        event_type: EventType,
        *,
        generation: str = GENERATION,
        task_epoch: str = TASK_EPOCH,
        marker: str = "",
    ) -> EventSubmission:
        return EventSubmission.build(
            workspace_id=WORKSPACE_ID,
            runtime_generation=generation,
            event_type=event_type,
            provider=Provider.CODEX,
            actor="codex-hook",
            occurred_at="2026-08-25T00:00:00Z",
            correlation=EventCorrelation(
                intent_id="intent-one",
                intent_revision=7,
                task_epoch=task_epoch,
                session_id="session-one",
                task_id="task-one",
            ),
            payload={"marker": marker} if marker else {},
        )

    def test_producers_do_not_assign_sequence_and_drain_applies_once(self) -> None:
        submissions = [
            self.submission(EventType.TASK_CREATED),
            self.submission(EventType.TASK_BOUND),
            self.submission(EventType.TASK_STARTED),
        ]
        for submission in submissions:
            self.assertEqual(
                self.store.submit(submission).status,
                SubmissionStatus.QUEUED,
            )
        duplicate = self.store.submit(submissions[0])
        self.assertEqual(duplicate.status, SubmissionStatus.QUEUED)

        first = self.store.drain(
            expected_generation=GENERATION,
            writer_id="writer-one",
            limit=2,
        )
        self.assertEqual(len(first.receipts), 2)
        self.assertTrue(
            all(receipt.status is SubmissionStatus.APPLIED for receipt in first.receipts)
        )
        second = self.store.drain(
            expected_generation=GENERATION,
            writer_id="writer-two",
        )
        self.assertEqual(len(second.receipts), 1)
        events = self.store.events()
        self.assertEqual([event.sequence for event in events], [1, 2, 3])
        self.assertEqual(events[1].previous_event_id, events[0].event_id)
        self.assertEqual(events[2].previous_event_id, events[1].event_id)
        self.assertEqual(
            self.store.projection().task,
            TaskLifecycleState.RUNNING,
        )
        self.assertEqual(
            self.store.submit(submissions[0]).status,
            SubmissionStatus.APPLIED,
        )
        audit = self.store.audit()
        self.assertEqual((audit.event_count, audit.sequence), (3, 3))

    def test_inbox_backpressure_refuses_before_accepting(self) -> None:
        database = Path(self.temporary.name) / "bounded.sqlite3"
        store = WorkspaceSupervisor.initialize(
            database,
            initial_state(
                workspace_id=WORKSPACE_ID,
                task_epoch=TASK_EPOCH,
                runtime_generation=GENERATION,
            ),
            max_pending=1,
        )
        first = self.submission(EventType.TASK_CREATED)
        second = self.submission(EventType.TASK_BOUND)
        store.submit(first)

        with self.assertRaisesRegex(InboxFull, "not accepted"):
            store.submit(second)
        self.assertIsNone(store.receipt(second.submission_id))
        store.drain(expected_generation=GENERATION, writer_id="writer-one")
        self.assertEqual(store.submit(second).status, SubmissionStatus.QUEUED)

    def test_stale_generation_and_task_epoch_are_terminal_rejections(self) -> None:
        stale = self.submission(
            EventType.TASK_CREATED,
            generation=NEXT_GENERATION,
        )
        wrong_epoch = self.submission(
            EventType.TASK_CREATED,
            task_epoch="f" * 24,
        )

        stale_receipt = self.store.submit(stale)
        epoch_receipt = self.store.submit(wrong_epoch)
        self.assertEqual(stale_receipt.status, SubmissionStatus.REJECTED)
        self.assertEqual(stale_receipt.reason, "stale_generation")
        self.assertEqual(epoch_receipt.reason, "task_epoch_mismatch")
        self.assertEqual(self.store.audit().event_count, 0)

    def test_bound_context_is_checked_before_queue_admission(self) -> None:
        database = Path(self.temporary.name) / "context.sqlite3"
        context_id = "9" * 64
        store = WorkspaceSupervisor.initialize(
            database,
            initial_state(
                workspace_id=WORKSPACE_ID,
                task_epoch=TASK_EPOCH,
                runtime_generation=GENERATION,
                task_epoch_context_id=context_id,
            ),
        )
        unbound = self.submission(EventType.TASK_CREATED)
        receipt = store.submit(unbound)
        self.assertEqual(receipt.status, SubmissionStatus.REJECTED)
        self.assertEqual(receipt.reason, "task_context_mismatch")

        bound = EventSubmission.build(
            workspace_id=WORKSPACE_ID,
            runtime_generation=GENERATION,
            event_type=EventType.TASK_CREATED,
            provider=Provider.CODEX,
            actor="codex-hook",
            occurred_at="2026-08-25T00:00:00Z",
            correlation=EventCorrelation(
                intent_id="intent-one",
                intent_revision=7,
                task_epoch=TASK_EPOCH,
                task_epoch_context_id=context_id,
            ),
        )
        self.assertEqual(store.submit(bound).status, SubmissionStatus.QUEUED)

    def test_invalid_transition_gets_one_rejected_terminal_result(self) -> None:
        invalid = self.submission(EventType.TASK_STARTED)
        self.store.submit(invalid)

        result = self.store.drain(
            expected_generation=GENERATION,
            writer_id="writer-one",
        )
        self.assertEqual(len(result.receipts), 1)
        self.assertEqual(result.receipts[0].status, SubmissionStatus.REJECTED)
        self.assertIn("transition_rejected", result.receipts[0].reason)
        self.assertEqual(self.store.events(), ())
        self.assertEqual(
            self.store.receipt(invalid.submission_id),
            result.receipts[0],
        )

    def test_transaction_failure_rolls_back_ledger_projection_and_receipt(self) -> None:
        submission = self.submission(EventType.TASK_CREATED)
        self.store.submit(submission)

        with mock.patch.object(
            self.store,
            "_persist_projection",
            side_effect=RuntimeError("injected crash"),
        ):
            with self.assertRaisesRegex(RuntimeError, "injected crash"):
                self.store.drain(
                    expected_generation=GENERATION,
                    writer_id="writer-one",
                )
        self.assertEqual(self.store.events(), ())
        self.assertEqual(
            self.store.receipt(submission.submission_id).status,
            SubmissionStatus.QUEUED,
        )
        self.assertEqual(self.store.audit().event_count, 0)

        recovered = self.store.drain(
            expected_generation=GENERATION,
            writer_id="writer-two",
        )
        self.assertEqual(recovered.receipts[0].status, SubmissionStatus.APPLIED)
        self.assertEqual(self.store.audit().event_count, 1)

    def test_generation_rotation_is_singular_and_fences_old_writers(self) -> None:
        stopped = self.submission(EventType.SUPERVISOR_STOPPED)
        self.store.submit(stopped)
        self.store.drain(
            expected_generation=GENERATION,
            writer_id="writer-old",
        )
        self.assertEqual(
            self.store.projection().supervisor,
            SupervisorState.STOPPED,
        )

        activation = self.submission(
            EventType.SUPERVISOR_GENERATION_ACTIVATED,
            generation=NEXT_GENERATION,
        )
        self.assertEqual(
            self.store.submit(activation).status,
            SubmissionStatus.QUEUED,
        )
        blocked_during_switch = self.store.submit(
            self.submission(EventType.TASK_CREATED, marker="during-switch")
        )
        self.assertEqual(
            blocked_during_switch.reason,
            "generation_switch_pending",
        )
        rotated = self.store.drain(
            expected_generation=GENERATION,
            writer_id="writer-old",
        )
        self.assertEqual(rotated.active_generation, NEXT_GENERATION)
        self.assertEqual(
            self.store.projection().runtime_generation,
            NEXT_GENERATION,
        )
        with self.assertRaises(StaleGeneration):
            self.store.drain(
                expected_generation=GENERATION,
                writer_id="stale-writer",
            )

        current = self.submission(
            EventType.TASK_CREATED,
            generation=NEXT_GENERATION,
        )
        self.store.submit(current)
        self.store.drain(
            expected_generation=NEXT_GENERATION,
            writer_id="writer-new",
        )
        self.assertEqual(self.store.audit().runtime_generation, NEXT_GENERATION)

    def test_concurrent_drains_never_duplicate_a_terminal_result(self) -> None:
        for event_type in (
            EventType.TASK_CREATED,
            EventType.TASK_BOUND,
            EventType.TASK_STARTED,
        ):
            self.store.submit(self.submission(event_type))
        barrier = threading.Barrier(2)
        results: list[object] = []

        def drain(writer: str) -> None:
            barrier.wait()
            try:
                results.append(
                    self.store.drain(
                        expected_generation=GENERATION,
                        writer_id=writer,
                    )
                )
            except SupervisorBusy as error:
                results.append(error)

        threads = [
            threading.Thread(target=drain, args=("writer-a",)),
            threading.Thread(target=drain, args=("writer-b",)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)
            self.assertFalse(thread.is_alive())

        events = self.store.events()
        self.assertEqual(len(events), 3)
        self.assertEqual(len({event.event_id for event in events}), 3)
        self.assertEqual(self.store.audit().event_count, 3)
        self.assertEqual(len(results), 2)

    def test_busy_writer_refuses_submission_without_accepting_it(self) -> None:
        submission = self.submission(EventType.TASK_CREATED)
        blocker = sqlite3.connect(self.database, timeout=0, isolation_level=None)
        blocker.execute("BEGIN IMMEDIATE")
        try:
            with self.assertRaisesRegex(SupervisorBusy, "not accepted"):
                self.store.submit(submission)
        finally:
            blocker.rollback()
            blocker.close()
        self.assertIsNone(self.store.receipt(submission.submission_id))

    def test_owner_only_and_final_symlink_are_enforced(self) -> None:
        if os.name != "posix":
            self.skipTest("POSIX ownership and symlink mode test")
        os.chmod(self.database, 0o644)
        with self.assertRaises(StoreCorruption):
            self.store.audit()
        os.chmod(self.database, 0o600)
        alias = Path(self.temporary.name) / "supervisor-alias.sqlite3"
        alias.symlink_to(self.database)
        with self.assertRaises(StoreCorruption):
            WorkspaceSupervisor(alias).audit()

    def test_projection_tampering_is_detected_by_replay(self) -> None:
        self.store.submit(self.submission(EventType.TASK_CREATED))
        self.store.drain(
            expected_generation=GENERATION,
            writer_id="writer-one",
        )
        connection = sqlite3.connect(self.database)
        connection.execute(
            "UPDATE supervisor_projection SET state_json = '{}' WHERE singleton = 1"
        )
        connection.commit()
        connection.close()

        with self.assertRaises(StoreCorruption):
            self.store.audit()

    def test_database_is_owner_only(self) -> None:
        if os.name != "posix":
            self.skipTest("POSIX mode bits are not the Windows ACL model")
        self.assertEqual(os.stat(self.database).st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
