from __future__ import annotations

from dataclasses import FrozenInstanceError
import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
KB = ROOT / "scripts" / "kb"
sys.path.insert(0, str(KB))

from sulde_protocol import (  # noqa: E402
    EVENT_SCHEMA,
    EventCorrelation,
    EventEnvelope,
    EventProtocolError,
    EventSubmission,
    EventType,
    Provider,
)


class SuldeProtocolTests(unittest.TestCase):
    def test_submission_leaves_sequence_and_head_to_the_writer(self) -> None:
        submission = EventSubmission.build(
            workspace_id="b" * 64,
            runtime_generation="a" * 64,
            event_type=EventType.TASK_CREATED,
            provider=Provider.CODEX,
            actor="codex-hook",
            occurred_at="2026-08-25T00:00:00Z",
            correlation=self.correlation(),
            payload={"source": "hook"},
        )

        restored = EventSubmission.from_dict(submission.to_dict())
        self.assertEqual(restored, submission)
        first = submission.to_envelope(sequence=1, previous_event_id="")
        second = submission.to_envelope(
            sequence=7,
            previous_event_id="f" * 64,
        )
        self.assertEqual(first.sequence, 1)
        self.assertEqual(second.sequence, 7)
        self.assertNotEqual(first.event_id, second.event_id)
        tampered = submission.to_dict()
        tampered["payload"] = {"source": "other"}
        with self.assertRaisesRegex(EventProtocolError, "submission_id"):
            EventSubmission.from_dict(tampered)

    def correlation(self) -> EventCorrelation:
        return EventCorrelation(
            intent_id="intent-one",
            intent_revision=7,
            task_epoch="e" * 24,
            session_id="session-one",
            task_id="task-one",
        )

    def event(self, **changes: object) -> EventEnvelope:
        arguments = {
            "sequence": 1,
            "previous_event_id": "",
            "workspace_id": "b" * 64,
            "runtime_generation": "a" * 64,
            "event_type": EventType.TASK_CREATED,
            "provider": Provider.CODEX,
            "actor": "codex-hook",
            "occurred_at": "2026-08-25T00:00:00+08:00",
            "correlation": self.correlation(),
            "payload": {"source": "fixture", "count": 1},
        }
        arguments.update(changes)
        return EventEnvelope.build(**arguments)  # type: ignore[arg-type]

    def test_envelope_is_canonical_immutable_and_round_trips(self) -> None:
        event = self.event()
        document = event.to_dict()

        self.assertEqual(document["schema"], EVENT_SCHEMA)
        self.assertEqual(document["domain"], "task")
        self.assertEqual(document["occurred_at"], "2026-08-24T16:00:00.000000Z")
        self.assertEqual(EventEnvelope.from_dict(document), event)
        self.assertEqual(
            json.dumps(document, sort_keys=True),
            json.dumps(EventEnvelope.from_dict(document).to_dict(), sort_keys=True),
        )
        with self.assertRaises(FrozenInstanceError):
            event.sequence = 2  # type: ignore[misc]
        mutated = event.payload
        mutated["count"] = 99
        self.assertEqual(event.payload["count"], 1)

    def test_digest_and_domain_tampering_fail_closed(self) -> None:
        document = self.event().to_dict()
        cases = (
            {**document, "event_id": "0" * 64},
            {**document, "domain": "approval"},
            {**document, "schema": "sulde-guardian-event-v0"},
        )
        for candidate in cases:
            with self.subTest(candidate=candidate.get("domain")):
                with self.assertRaises(EventProtocolError):
                    EventEnvelope.from_dict(candidate)

    def test_correlation_rejects_stale_shape_and_unbounded_ids(self) -> None:
        with self.assertRaises(EventProtocolError):
            EventCorrelation.from_dict(
                {
                    **self.correlation().to_dict(),
                    "surprise": "field",
                }
            )
        with self.assertRaises(EventProtocolError):
            EventCorrelation(
                intent_id="x" * 300,
                intent_revision=1,
                task_epoch="e" * 24,
            )
        with self.assertRaisesRegex(EventProtocolError, "context"):
            EventCorrelation(
                intent_id="intent-one",
                intent_revision=1,
                task_epoch="e" * 24,
                task_epoch_context_id="not-a-digest",
            )

    def test_payload_is_plain_bounded_json(self) -> None:
        with self.assertRaisesRegex(EventProtocolError, "plain dict"):
            self.event(payload=(("key", "value"),))
        nested: dict[str, object] = {}
        cursor = nested
        for _ in range(14):
            child: dict[str, object] = {}
            cursor["child"] = child
            cursor = child
        with self.assertRaisesRegex(EventProtocolError, "bounded plain JSON"):
            self.event(payload=nested)
        with self.assertRaisesRegex(EventProtocolError, "64 KiB"):
            self.event(payload={"large": "x" * (65 * 1024)})

    def test_event_type_requires_real_enum_not_a_string_alias(self) -> None:
        with self.assertRaises(EventProtocolError):
            self.event(event_type="task.created")


if __name__ == "__main__":
    unittest.main()
