from __future__ import annotations

import ast
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
KB = ROOT / "scripts" / "kb"
sys.path.insert(0, str(KB))

from sulde_protocol import (  # noqa: E402
    ApprovalState,
    EffectState,
    EventCorrelation,
    EventEnvelope,
    EventType,
    Provider,
    SupervisorState,
    TaskLifecycleState,
)
from sulde_state_machine import (  # noqa: E402
    TransitionError,
    initial_state,
    replay,
    transition,
)


WORKSPACE_ID = "b" * 64
TASK_EPOCH = "e" * 24
GENERATION = "a" * 64


class SuldeStateMachineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.state = initial_state(
            workspace_id=WORKSPACE_ID,
            task_epoch=TASK_EPOCH,
            runtime_generation=GENERATION,
        )

    def event(
        self,
        state,
        event_type: EventType,
        *,
        attempt_id: str = "",
        approval_request_id: str = "",
        intervention_id: str = "",
        task_epoch: str = TASK_EPOCH,
        generation: str = GENERATION,
        task_epoch_context_id: str = "",
    ) -> EventEnvelope:
        return EventEnvelope.build(
            sequence=state.sequence + 1,
            previous_event_id=state.last_event_id,
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
                attempt_id=attempt_id,
                approval_request_id=approval_request_id,
                intervention_id=intervention_id,
                task_epoch_context_id=task_epoch_context_id,
            ),
        )

    def apply(self, state, event_type: EventType, **correlation):
        event = self.event(state, event_type, **correlation)
        return transition(state, event).state, event

    def running_task(self):
        state, _ = self.apply(self.state, EventType.TASK_CREATED)
        state, _ = self.apply(state, EventType.TASK_BOUND)
        state, _ = self.apply(state, EventType.TASK_STARTED)
        return state

    def test_replay_is_deterministic_and_exact_duplicate_is_idempotent(self) -> None:
        state = self.state
        events = []
        for event_type in (
            EventType.TASK_CREATED,
            EventType.TASK_BOUND,
            EventType.TASK_STARTED,
            EventType.TASK_VERIFYING,
            EventType.TASK_SUCCEEDED,
        ):
            event = self.event(state, event_type)
            events.append(event)
            state = transition(state, event).state

        self.assertEqual(replay(self.state, events), state)
        duplicate = transition(state, events[-1])
        self.assertFalse(duplicate.changed)
        self.assertIs(duplicate.state, state)
        self.assertEqual(state.task, TaskLifecycleState.SUCCEEDED)
        with self.assertRaisesRegex(TransitionError, "terminal|cannot transition"):
            transition(state, self.event(state, EventType.TASK_FAILED))

    def test_approval_reassessment_is_not_expiration_or_authority(self) -> None:
        request_id = "apr-" + "1" * 24
        asked, _ = self.apply(
            self.state,
            EventType.APPROVAL_ASKED,
            approval_request_id=request_id,
        )
        reassessed, _ = self.apply(
            asked,
            EventType.APPROVAL_REASSESSMENT_DUE,
            approval_request_id=request_id,
        )
        self.assertEqual(reassessed.approval, ApprovalState.REASSESSMENT_DUE)
        decided, _ = self.apply(
            reassessed,
            EventType.APPROVAL_DECIDED,
            approval_request_id=request_id,
        )
        self.assertEqual(decided.approval, ApprovalState.DECIDED)

        asked_again, _ = self.apply(
            decided,
            EventType.APPROVAL_ASKED,
            approval_request_id="apr-" + "2" * 24,
        )
        expired, _ = self.apply(
            asked_again,
            EventType.APPROVAL_EXPIRED,
            approval_request_id="apr-" + "2" * 24,
        )
        with self.assertRaisesRegex(TransitionError, "cannot transition"):
            self.apply(
                expired,
                EventType.APPROVAL_DECIDED,
                approval_request_id="apr-" + "2" * 24,
            )

    def test_unknown_effect_cannot_be_hidden_by_task_success(self) -> None:
        state = self.running_task()
        attempt_id = "att-" + "3" * 24
        state, _ = self.apply(
            state,
            EventType.EFFECT_PREPARED,
            attempt_id=attempt_id,
        )
        state, _ = self.apply(
            state,
            EventType.EFFECT_DISPATCHED,
            attempt_id=attempt_id,
        )
        state, _ = self.apply(
            state,
            EventType.EFFECT_UNKNOWN,
            attempt_id=attempt_id,
        )
        with self.assertRaisesRegex(TransitionError, "unverified"):
            self.apply(state, EventType.TASK_SUCCEEDED)

        intervention_id = "int-" + "4" * 24
        state, _ = self.apply(
            state,
            EventType.INTERVENTION_OPENED,
            attempt_id=attempt_id,
            intervention_id=intervention_id,
        )
        state, _ = self.apply(
            state,
            EventType.INTERVENTION_RESOLVED,
            attempt_id=attempt_id,
            intervention_id=intervention_id,
        )
        state, _ = self.apply(
            state,
            EventType.EFFECT_ABORTED,
            attempt_id=attempt_id,
        )
        with self.assertRaisesRegex(TransitionError, "unverified"):
            self.apply(state, EventType.TASK_SUCCEEDED)
        inconclusive, _ = self.apply(state, EventType.TASK_INCONCLUSIVE)
        self.assertEqual(inconclusive.effect, EffectState.ABORTED)
        self.assertEqual(inconclusive.task, TaskLifecycleState.INCONCLUSIVE)

    def test_epoch_chain_and_generation_are_fenced(self) -> None:
        stale = self.event(
            self.state,
            EventType.TASK_CREATED,
            task_epoch="f" * 24,
        )
        with self.assertRaisesRegex(TransitionError, "task epoch"):
            transition(self.state, stale)

        wrong_generation = self.event(
            self.state,
            EventType.TASK_CREATED,
            generation="c" * 64,
        )
        with self.assertRaisesRegex(TransitionError, "runtime generation"):
            transition(self.state, wrong_generation)

        activated, _ = self.apply(
            self.state,
            EventType.SUPERVISOR_GENERATION_ACTIVATED,
            generation="c" * 64,
        )
        self.assertEqual(activated.runtime_generation, "c" * 64)
        self.assertEqual(activated.supervisor, SupervisorState.STARTING)

    def test_frozen_task_context_rejects_context_and_generation_drift(self) -> None:
        context_id = "9" * 64
        state = initial_state(
            workspace_id=WORKSPACE_ID,
            task_epoch=TASK_EPOCH,
            runtime_generation=GENERATION,
            task_epoch_context_id=context_id,
        )
        wrong_context = self.event(state, EventType.TASK_CREATED)
        with self.assertRaisesRegex(TransitionError, "task epoch context"):
            transition(state, wrong_context)

        generation_change = self.event(
            state,
            EventType.SUPERVISOR_GENERATION_ACTIVATED,
            generation="c" * 64,
            task_epoch_context_id=context_id,
        )
        with self.assertRaisesRegex(TransitionError, "new task epoch context"):
            transition(state, generation_change)

    def test_noncontiguous_or_wrong_head_event_is_rejected(self) -> None:
        event = self.event(self.state, EventType.TASK_CREATED)
        noncontiguous = EventEnvelope.build(
            sequence=2,
            previous_event_id="",
            workspace_id=WORKSPACE_ID,
            runtime_generation=GENERATION,
            event_type=EventType.TASK_CREATED,
            provider=Provider.CODEX,
            actor="codex-hook",
            occurred_at="2026-08-25T00:00:00Z",
            correlation=event.correlation,
        )
        with self.assertRaisesRegex(TransitionError, "sequence"):
            transition(self.state, noncontiguous)
        forged = EventEnvelope.build(
            sequence=1,
            previous_event_id="d" * 64,
            workspace_id=WORKSPACE_ID,
            runtime_generation=GENERATION,
            event_type=EventType.TASK_CREATED,
            provider=Provider.CODEX,
            actor="codex-hook",
            occurred_at="2026-08-25T00:00:00Z",
            correlation=event.correlation,
        )
        with self.assertRaisesRegex(TransitionError, "chain"):
            transition(self.state, forged)

    def test_state_machine_has_no_adapter_or_io_dependencies(self) -> None:
        source = (KB / "sulde_state_machine/reducer.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".", 1)[0])
        forbidden = {
            "asyncio",
            "intent_guardian_parts",
            "os",
            "pathlib",
            "socket",
            "sqlite3",
            "subprocess",
        }
        self.assertTrue(imported.isdisjoint(forbidden), imported & forbidden)


if __name__ == "__main__":
    unittest.main()
