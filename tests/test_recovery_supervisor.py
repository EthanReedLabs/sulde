from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
import os
from pathlib import Path
import select
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
KB = ROOT / "scripts" / "kb"
sys.path.insert(0, str(KB))

import recovery_supervisor as recovery  # noqa: E402
import supervisor_state as durable  # noqa: E402


def digest(label: str) -> str:
    return recovery.canonical_digest("test-fixture", {"label": label})


class Crash(RuntimeError):
    pass


class Magic(dict):
    pass


class FakeClock:
    def __init__(self, wall: float = 100.0, mono: float = 0.0) -> None:
        self.wall = wall
        self.mono = mono

    def wall_time(self) -> float:
        return self.wall

    def monotonic(self) -> float:
        return self.mono

    def advance(self, seconds: float) -> None:
        self.wall += seconds
        self.mono += seconds


class OneShotFailpoint:
    def __init__(self, target: str) -> None:
        self.target = target
        self.triggered = False

    def __call__(self, boundary: str) -> None:
        if boundary == self.target and not self.triggered:
            self.triggered = True
            raise Crash(boundary)


class FakeLocalAdapter:
    """Observable non-idempotent apply with read-only same-effect reprobe."""

    def __init__(self) -> None:
        self.callbacks = 0
        self.reprobes = 0
        self.effects: dict[str, dict] = {}
        self.identity = digest("trusted-local-adapter")

    def apply(self, prepare: dict) -> dict:
        self.callbacks += 1
        effect_id = prepare["effect_id"]
        if effect_id in self.effects:
            raise AssertionError("non-idempotent apply invoked twice")
        self.effects[effect_id] = {
            "schema": recovery.ADAPTER_RESULT_SCHEMA,
            "intervention_id": prepare["intervention_id"],
            "effect_id": effect_id,
            "adapter_identity": self.identity,
            "status": "completed",
            "result": {
                "mechanical": prepare["capability"],
                "identity": effect_id,
            },
        }
        return deepcopy(self.effects[effect_id])

    def reprobe(self, prepare: dict) -> dict:
        self.reprobes += 1
        if prepare["effect_id"] in self.effects:
            return deepcopy(self.effects[prepare["effect_id"]])
        return {
            "schema": recovery.ADAPTER_RESULT_SCHEMA,
            "intervention_id": prepare["intervention_id"],
            "effect_id": prepare["effect_id"],
            "adapter_identity": self.identity,
            "status": "unknown",
            "result": {"reprobe": "unknown"},
        }


class FakeInterventionVerifier:
    def __init__(self, *, status: str = "passed") -> None:
        self.identity = digest("trusted-intervention-verifier")
        self.status = status
        self.calls = 0

    def verify(self, request: dict) -> dict:
        self.calls += 1
        material = {
            "verifier_identity": self.identity,
            **{key: request[key] for key in (
                "intervention_id", "adapter_identity", "effect_id",
                "subject_identity", "world_state_digest", "result_identity",
            )},
        }
        return {
            "schema": recovery.INTERVENTION_VERIFY_SCHEMA,
            "receipt_id": recovery.canonical_digest(
                "test-intervention-verifier", material
            ),
            **material,
            "status": self.status,
            "evidence": {"independent": True},
        }


class RecoveryFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.clock = FakeClock()
        self.path = self.root / "supervisor.jsonl"
        self.adapter = FakeLocalAdapter()
        self.intervention_verifier = FakeInterventionVerifier()
        self.supervisor = self.make_supervisor()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def make_supervisor(
        self,
        *,
        path: Path | None = None,
        failpoint=None,
        state_failpoint=None,
        clock: FakeClock | None = None,
        adapter: FakeLocalAdapter | None = None,
        verifier: FakeInterventionVerifier | None = None,
    ) -> recovery.RecoverySupervisor:
        selected_clock = clock or self.clock
        selected_adapter = adapter or self.adapter
        selected_verifier = verifier or self.intervention_verifier
        return recovery.RecoverySupervisor(
            str(path or self.path),
            wall_clock=selected_clock.wall_time,
            monotonic_clock=selected_clock.monotonic,
            failpoint=failpoint,
            state_failpoint=state_failpoint,
            trusted_adapter=selected_adapter,
            adapter_identity=selected_adapter.identity,
            trusted_intervention_verifier=selected_verifier,
            intervention_verifier_identity=selected_verifier.identity,
        )

    def process(self, suffix: str = "a", pid: int = 101) -> dict:
        return {
            "schema": recovery.PROCESS_SCHEMA,
            "pid": pid,
            "start_token": digest(f"process-{suffix}"),
        }

    def actor(
        self,
        suffix: str = "a",
        *,
        pid: int = 101,
        max_attempts: int = 2,
        backoff: list[float] | None = None,
    ) -> dict:
        selected_backoff = backoff or [2.0, 4.0][:max_attempts]
        return {
            "schema": recovery.ACTOR_SCHEMA,
            "actor_id": f"actor-{suffix}",
            "task_id": f"task-{suffix}",
            "worker_id": f"worker-{suffix}",
            "provider": "codex",
            "task_epoch": (suffix[0].lower() if suffix[0].lower() in "abcdef" else "e") * 24,
            "generation": 7,
            "lane": f"task:{suffix}",
            "allowed_paths": [f"work/{suffix}.txt"],
            "command_identity": digest(f"command-{suffix}"),
            "process_identity": self.process(suffix, pid),
            "retry_budget": {
                "max_attempts": max_attempts,
                "backoff_seconds": selected_backoff,
            },
            "verifier_identity": digest(f"verifier-{suffix}"),
            "probe_authority": digest(f"probe-authority-{suffix}"),
            "registered_wall": self.clock.wall,
            "registered_mono": self.clock.mono,
        }

    def resource(self, name: str, token: str = "owner") -> dict:
        return {
            "schema": recovery.RESOURCE_SCHEMA,
            "kind": "local_lock",
            "canonical_id": name,
            "ownership_token": digest(f"resource-{token}"),
        }

    def heartbeat(
        self,
        actor: dict,
        *,
        callback: str = "hb-1",
        heartbeat_kind: str = "worker",
        sequence: int = 1,
        state: str | None = None,
        resources: list[dict] | None = None,
        scheduler_status: str = "healthy",
        scheduler_reason: str | None = None,
        wall: float | None = None,
        mono: float | None = None,
    ) -> dict:
        return {
            "schema": recovery.HEARTBEAT_SCHEMA,
            "callback_id": callback,
            "heartbeat_kind": heartbeat_kind,
            "actor_id": actor["actor_id"],
            "worker_id": actor["worker_id"],
            "binding": recovery.binding_from_actor(actor),
            "process_identity": deepcopy(actor["process_identity"]),
            "progress_cursor": {
                "schema": recovery.PROGRESS_SCHEMA,
                "sequence": sequence,
                "state_identity": digest(state or f"progress-{sequence}"),
            },
            "resources": deepcopy(resources or []),
            "scheduler_state": {
                "schema": recovery.SCHEDULER_SCHEMA,
                "status": scheduler_status,
                "reason": scheduler_reason,
            },
            "observed_wall": self.clock.wall if wall is None else wall,
            "observed_mono": self.clock.mono if mono is None else mono,
        }

    def probe(
        self,
        actor: dict,
        status: str,
        *,
        probe_id: str = "probe-1",
        subject: dict | None = None,
        observed: dict | None = None,
        wall: float | None = None,
        mono: float | None = None,
    ) -> dict:
        selected_subject = deepcopy(subject or actor["process_identity"])
        if status == "alive" and observed is None:
            observed = deepcopy(selected_subject)
        return {
            "schema": recovery.PROCESS_PROBE_SCHEMA,
            "probe_id": probe_id,
            "actor_id": actor["actor_id"],
            "probe_authority": actor["probe_authority"],
            "source_event_identity": digest(f"source-{probe_id}"),
            "subject_process_identity": selected_subject,
            "status": status,
            "observed_process_identity": deepcopy(observed),
            "observed_wall": self.clock.wall if wall is None else wall,
            "observed_mono": self.clock.mono if mono is None else mono,
        }

    def lease(
        self,
        actor: dict,
        *,
        expires_wall: float,
        lease_id: str = "lease-1",
        lock: dict | None = None,
    ) -> dict:
        return {
            "schema": recovery.LEASE_SCHEMA,
            "lease_id": lease_id,
            "lock": deepcopy(lock or self.resource("lock-A")),
            "owner_actor_id": actor["actor_id"],
            "owner_process_identity": deepcopy(actor["process_identity"]),
            "lease_epoch": 3,
            "expires_wall": expires_wall,
            "observed_wall": self.clock.wall,
            "observed_mono": self.clock.mono,
        }

    def exit_event(
        self,
        actor: dict,
        callback: str,
        *,
        status: str = "early_exit",
        wall: float | None = None,
        mono: float | None = None,
    ) -> dict:
        return {
            "schema": recovery.EXIT_SCHEMA,
            "callback_id": callback,
            "actor_id": actor["actor_id"],
            "binding": recovery.binding_from_actor(actor),
            "process_identity": deepcopy(actor["process_identity"]),
            "status": status,
            "exit_code": 17,
            "observed_wall": self.clock.wall if wall is None else wall,
            "observed_mono": self.clock.mono if mono is None else mono,
        }

    def cancellation(self, actor: dict, callback: str = "cancel-1") -> dict:
        return {
            "schema": recovery.CANCELLATION_SCHEMA,
            "callback_id": callback,
            "actor_id": actor["actor_id"],
            "binding": recovery.binding_from_actor(actor),
            "reason": "human_cancelled",
            "observed_wall": self.clock.wall,
            "observed_mono": self.clock.mono,
        }

    def verifier(
        self,
        actor: dict,
        callback: str = "business-1",
        *,
        status: str = "passed",
    ) -> dict:
        return {
            "schema": recovery.VERIFIER_SCHEMA,
            "receipt_id": f"verify-{callback}",
            "business_callback_id": callback,
            "actor_id": actor["actor_id"],
            "provider": actor["provider"],
            "task_epoch": actor["task_epoch"],
            "generation": actor["generation"],
            "verifier_identity": actor["verifier_identity"],
            "status": status,
            "evidence": {"fixture": "exact"},
        }

    def business(
        self,
        actor: dict,
        *,
        status: str = "succeeded",
        callback: str = "business-1",
        verifier: dict | None = None,
    ) -> dict:
        return {
            "schema": recovery.BUSINESS_SCHEMA,
            "callback_id": callback,
            "actor_id": actor["actor_id"],
            "binding": recovery.binding_from_actor(actor),
            "status": status,
            "verifier_receipt": deepcopy(verifier),
            "result": {"business": status},
            "observed_wall": self.clock.wall,
            "observed_mono": self.clock.mono,
        }

    def prepare_reclaim(self) -> tuple[dict, dict]:
        actor = self.actor()
        self.supervisor.register_actor(actor)
        lease = self.lease(actor, expires_wall=110.0)
        self.supervisor.record_lock_lease(lease)
        self.clock.advance(1.0)
        self.supervisor.record_process_probe(self.probe(actor, "dead"))
        self.clock.advance(9.0)
        projection = self.supervisor.scan()
        recommendation = next(
            item for item in projection["recommendations"]
            if item["kind"] == "reclaim_lock"
        )
        return actor, recommendation


class HeartbeatAndProgressTests(RecoveryFixture):
    def test_fresh_five_second_card_and_thirty_second_typed_reason(self) -> None:
        actor = self.actor()
        self.supervisor.register_actor(actor)
        self.supervisor.record_heartbeat(self.heartbeat(actor, mono=0.0, wall=100.0))
        self.supervisor.record_heartbeat(
            self.heartbeat(actor, callback="task-hb", heartbeat_kind="task",
                           mono=0.0, wall=100.0)
        )

        self.clock.advance(4.999)
        self.assertEqual(self.supervisor.scan()["status_cards"], [])
        self.clock.advance(0.001)
        projection = self.supervisor.scan()
        self.assertEqual([card["kind"] for card in projection["status_cards"]],
                         ["visible_no_progress"])
        self.supervisor.record_heartbeat(
            self.heartbeat(actor, callback="hb-poll", sequence=1, mono=20.0, wall=120.0)
        )
        self.clock.advance(25.0)
        projection = self.supervisor.scan()
        self.assertIn("typed_reason", [card["kind"] for card in projection["status_cards"]])
        self.assertEqual(projection["actors"][actor["actor_id"]]["last_progress_mono"], 0.0)

    def test_progress_before_boundary_resets_window_and_after_boundary_is_new_state(self) -> None:
        actor = self.actor()
        self.supervisor.register_actor(actor)
        self.supervisor.record_heartbeat(self.heartbeat(actor, mono=0.0, wall=100.0))
        self.clock.advance(29.0)
        self.supervisor.record_heartbeat(
            self.heartbeat(actor, callback="hb-2", sequence=2, mono=29.0, wall=129.0)
        )
        self.clock.advance(1.0)
        projection = self.supervisor.scan()
        reasons = [card for card in projection["status_cards"] if card["kind"] == "typed_reason"]
        self.assertEqual(reasons, [])

        second_path = self.root / "after.jsonl"
        second = self.make_supervisor(path=second_path)
        late = self.actor("b")
        second.register_actor(late)
        second.record_heartbeat(self.heartbeat(late, mono=0.0, wall=100.0))
        self.clock.advance(30.0)
        self.assertIn("typed_reason", [card["kind"] for card in second.scan()["status_cards"]])
        second.record_heartbeat(
            self.heartbeat(late, callback="late-progress", sequence=2,
                           mono=self.clock.mono, wall=self.clock.wall)
        )
        state = second.projection()
        self.assertEqual(state["actors"][late["actor_id"]]["last_progress_mono"], self.clock.mono)

    def test_future_and_regressive_source_clocks_cannot_suppress_sla(self) -> None:
        future = self.actor("a")
        self.supervisor.register_actor(future)
        self.supervisor.record_heartbeat(
            self.heartbeat(future, mono=10000.0, wall=10100.0)
        )
        self.clock.advance(5.0)
        projection = self.supervisor.scan()
        self.assertIn(
            "visible_no_progress",
            [card["kind"] for card in projection["status_cards"]],
        )
        self.assertIn(
            "future_source_clock",
            [item["reason"] for item in projection["rejected_observations"]],
        )

        path = self.root / "regressive-clock.jsonl"
        clock = FakeClock()
        supervisor = self.make_supervisor(path=path, clock=clock)
        actor = self.actor("b")
        supervisor.register_actor(actor)
        clock.advance(5.0)
        supervisor.record_heartbeat(
            self.heartbeat(actor, callback="valid", sequence=1, mono=5.0, wall=105.0)
        )
        clock.advance(5.0)
        supervisor.record_heartbeat(
            self.heartbeat(
                actor, callback="regressive", sequence=2, mono=4.0, wall=104.0
            )
        )
        clock.advance(25.0)
        projection = supervisor.scan()
        self.assertIn(
            "typed_reason", [card["kind"] for card in projection["status_cards"]]
        )
        self.assertEqual(
            projection["actors"][actor["actor_id"]]["last_progress_mono"], 5.0
        )
        self.assertIn(
            "regressive_source_clock",
            [item["reason"] for item in projection["rejected_observations"]],
        )


class OrphanLockTests(RecoveryFixture):
    def test_both_predicates_reclaim_within_ten_second_window(self) -> None:
        _actor, recommendation = self.prepare_reclaim()
        self.assertEqual(recommendation["created_mono"], 10.0)
        self.assertEqual(recommendation["execute_by_mono"], 20.0)
        self.clock.advance(9.9)
        authorization = self.supervisor.authorize(recommendation["recommendation_id"])
        receipt = self.supervisor.execute(
            authorization["intervention_id"], self.adapter
        )
        self.assertEqual(receipt["status"], "completed")
        self.assertEqual(receipt["kind"], "reclaim_lock")
        self.assertFalse(receipt["external_effect"])

    def test_every_one_predicate_only_combination_is_rejected(self) -> None:
        cases = [
            ("dead_not_expired", "dead", 200.0),
            ("expired_alive", "alive", 90.0),
            ("expired_unknown", "unknown", 90.0),
            ("expired_access_denied", "access_denied", 90.0),
        ]
        for suffix, probe_status, expiry in cases:
            with self.subTest(suffix=suffix):
                path = self.root / f"{suffix}.jsonl"
                supervisor = self.make_supervisor(path=path)
                actor = self.actor(suffix)
                supervisor.register_actor(actor)
                supervisor.record_lock_lease(self.lease(actor, expires_wall=expiry,
                                                       lease_id=f"lease-{suffix}"))
                supervisor.record_process_probe(self.probe(actor, probe_status,
                                                           probe_id=f"probe-{suffix}"))
                kinds = [item["kind"] for item in supervisor.scan()["recommendations"]]
                self.assertNotIn("reclaim_lock", kinds)

    def test_pid_reuse_stale_token_wall_jump_and_generation_drift_fail_closed(self) -> None:
        actor = self.actor()
        self.supervisor.register_actor(actor)
        self.supervisor.record_lock_lease(self.lease(actor, expires_wall=200.0))
        reused = self.process("reused", pid=actor["process_identity"]["pid"])
        self.supervisor.record_process_probe(
            self.probe(actor, "stale_identity", observed=reused)
        )
        self.clock.wall = 500.0
        self.clock.mono = 1.0
        projection = self.supervisor.scan()
        self.assertFalse(projection["locks"]["local_lock:lock-A"]["owner_dead"])
        self.assertFalse(any(item["kind"] == "reclaim_lock"
                             for item in projection["recommendations"]))

        self.supervisor.record_process_probe(
            self.probe(actor, "dead", probe_id="exact-dead-after-wall-jump")
        )
        projection = self.supervisor.scan()
        self.assertTrue(projection["locks"]["local_lock:lock-A"]["owner_dead"])
        self.assertFalse(any(item["kind"] == "reclaim_lock"
                             for item in projection["recommendations"]))

        drift = self.heartbeat(actor, callback="generation-drift")
        drift["binding"]["generation"] += 1
        self.supervisor.record_heartbeat(drift)
        projection = self.supervisor.projection()
        self.assertIn("immutable_binding_mismatch",
                      [item["reason"] for item in projection["rejected_observations"]])

        self.clock.wall = 499.0
        with self.assertRaisesRegex(recovery.RecoverySupervisorError, "clock regression"):
            self.supervisor.scan()

    def test_only_trusted_exact_unambiguous_dead_receipt_can_reclaim(self) -> None:
        actor = self.actor()
        self.supervisor.register_actor(actor)
        self.supervisor.record_lock_lease(self.lease(actor, expires_wall=90.0))

        fabricated = self.probe(actor, "dead", probe_id="fabricated")
        fabricated["probe_authority"] = digest("untrusted-probe")
        self.supervisor.record_process_probe(fabricated)

        foreign = self.probe(actor, "dead", probe_id="foreign")
        foreign["subject_process_identity"] = self.process("foreign", pid=999)
        self.supervisor.record_process_probe(foreign)

        pid_only = self.probe(actor, "dead", probe_id="pid-only")
        pid_only["subject_process_identity"] = {"schema": recovery.PROCESS_SCHEMA, "pid": 101}
        self.supervisor.record_process_probe(pid_only)

        self.supervisor.record_process_probe(
            self.probe(actor, "access_denied", probe_id="denied")
        )
        self.supervisor.record_process_probe(
            self.probe(actor, "dead", probe_id="equal-dead")
        )
        self.supervisor.record_process_probe(
            self.probe(actor, "alive", probe_id="equal-alive")
        )
        projection = self.supervisor.scan()
        lock = projection["locks"]["local_lock:lock-A"]
        self.assertFalse(lock["owner_dead"])
        self.assertIn(
            "contradictory_equal_time_process_observations",
            lock["process_observation_ambiguities"],
        )
        reasons = {item["reason"] for item in projection["rejected_observations"]}
        self.assertTrue({
            "untrusted_probe_authority", "foreign_process_subject",
            "invalid_or_pid_only_process_fact",
        }.issubset(reasons))
        self.assertFalse(any(
            item["kind"] == "reclaim_lock"
            for item in projection["recommendations"]
        ))

        self.clock.advance(31.0)
        stale = self.probe(actor, "dead", probe_id="stale-dead")
        stale["observed_wall"] = 100.0
        stale["observed_mono"] = 0.0
        self.supervisor.record_process_probe(stale)
        projection = self.supervisor.scan()
        self.assertFalse(projection["locks"]["local_lock:lock-A"]["owner_dead"])
        self.assertIn(
            "stale_process_observation",
            {item["reason"] for item in projection["rejected_observations"]},
        )

        self.clock.advance(1.0)
        trusted = self.probe(actor, "dead", probe_id="trusted-exact")
        result = self.supervisor.record_process_probe(trusted)
        receipt = result["row"]["payload"]
        self.assertEqual(receipt["receipt_schema"], recovery.PROCESS_RECEIPT_SCHEMA)
        self.assertEqual(
            receipt["supervisor_received_mono"], self.clock.mono
        )
        projection = self.supervisor.scan()
        self.assertTrue(projection["locks"]["local_lock:lock-A"]["owner_dead"])
        self.assertTrue(any(
            item["kind"] == "reclaim_lock"
            for item in projection["recommendations"]
        ))


class ConflictTests(RecoveryFixture):
    def test_overlap_pauses_only_minimal_task_lanes_and_preserves_snapshots(self) -> None:
        shared = self.resource("shared")
        actors = [self.actor("a"), self.actor("b", pid=102)]
        for index, actor in enumerate(actors):
            self.supervisor.register_actor(actor)
            resources = sorted(
                [shared, self.resource(f"private-{index}", f"private-{index}")],
                key=lambda item: f"{item['kind']}:{item['canonical_id']}",
            )
            self.supervisor.record_heartbeat(
                self.heartbeat(actor, callback=f"hb-{index}", resources=resources)
            )
        projection = self.supervisor.scan()
        conflict = projection["conflicts"][0]
        self.assertEqual(conflict["affected_lanes"], ["task:a", "task:b"])
        self.assertEqual(len(conflict["actor_snapshots"]), 2)
        self.assertEqual(
            {item["actor"]["actor_id"] for item in conflict["actor_snapshots"]},
            {"actor-a", "actor-b"},
        )
        self.assertNotIn("workspace", " ".join(conflict["affected_lanes"]))
        self.assertNotIn("global", " ".join(conflict["affected_lanes"]))

    def test_two_simultaneous_evaluators_converge_to_one_recommendation(self) -> None:
        shared = self.resource("shared")
        for suffix, pid in (("a", 101), ("b", 102)):
            actor = self.actor(suffix, pid=pid)
            self.supervisor.register_actor(actor)
            self.supervisor.record_heartbeat(
                self.heartbeat(actor, callback=f"hb-{suffix}", resources=[shared])
            )
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _unused: self.supervisor.scan(), range(2)))
        self.assertTrue(all(result["conflicts"] for result in results))
        projection = self.supervisor.projection()
        pauses = [item for item in projection["recommendations"]
                  if item["kind"] == "pause_conflict"]
        self.assertEqual(len(pauses), 1)

    def test_independent_simultaneous_scans_commit_unique_ordered_identities(self) -> None:
        actor = self.actor()
        self.supervisor.register_actor(actor)
        second = self.make_supervisor(path=self.path)
        barrier = threading.Barrier(2)

        def run(supervisor: recovery.RecoverySupervisor) -> dict:
            barrier.wait(timeout=2.0)
            return supervisor.scan()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(run, item) for item in (self.supervisor, second)]
            for future in futures:
                future.result(timeout=3.0)
        scans = [
            event["payload"] for event in self.supervisor.state.snapshot()["events"]
            if event["event_type"] == "scan_observed"
        ]
        self.assertEqual([item["scan_sequence"] for item in scans], [1, 2])
        self.assertLess(scans[0]["baseline_sequence"], scans[1]["baseline_sequence"])


class RestartAndTerminalTests(RecoveryFixture):
    def _complete_restart(self, recommendation: dict, adapter: FakeLocalAdapter) -> None:
        authorization = self.supervisor.authorize(recommendation["recommendation_id"])
        self.supervisor.execute(authorization["intervention_id"], adapter)

    def test_backoff_attempt_cap_and_single_exhausted_receipt(self) -> None:
        actor = self.actor(max_attempts=2, backoff=[2.0, 4.0])
        self.supervisor.register_actor(actor)
        adapter = self.adapter
        self.clock.advance(1.0)
        self.supervisor.record_exit(self.exit_event(actor, "exit-1"))
        self.clock.advance(1.9)
        self.assertFalse(any(item["kind"] == "restart"
                             for item in self.supervisor.scan()["recommendations"]))
        self.clock.advance(0.1)
        first = next(item for item in self.supervisor.scan()["recommendations"]
                     if item["kind"] == "restart")
        self.assertEqual(first["binding"]["attempt"], 1)
        self._complete_restart(first, adapter)

        self.clock.advance(1.0)
        self.supervisor.record_exit(self.exit_event(actor, "exit-2"))
        self.clock.advance(4.0)
        second = next(item for item in self.supervisor.scan()["recommendations"]
                      if item["kind"] == "restart" and item["binding"]["attempt"] == 2)
        self._complete_restart(second, adapter)
        self.clock.advance(1.0)
        self.supervisor.record_exit(self.exit_event(actor, "exit-3"))
        projection = self.supervisor.scan()
        self.assertEqual(len(projection["exhausted_receipts"]), 1)
        self.supervisor.scan()
        self.assertEqual(len(self.supervisor.projection()["exhausted_receipts"]), 1)

    def test_no_restart_after_business_terminal_or_cancellation(self) -> None:
        for suffix, terminal_kind in (("a", "business"), ("b", "cancel")):
            path = self.root / f"terminal-{suffix}.jsonl"
            supervisor = self.make_supervisor(path=path)
            actor = self.actor(suffix, pid=110 + len(suffix))
            supervisor.register_actor(actor)
            if terminal_kind == "business":
                supervisor.record_business_terminal(self.business(actor, verifier=None))
            else:
                supervisor.record_cancellation(self.cancellation(actor))
            self.clock.advance(1.0)
            supervisor.record_exit(self.exit_event(actor, f"exit-{suffix}"))
            self.clock.advance(10.0)
            projection = supervisor.scan()
            self.assertFalse(any(item["kind"] == "restart"
                                 for item in projection["recommendations"]))
            if terminal_kind == "business":
                self.assertEqual(
                    projection["actors"][actor["actor_id"]]["business_status"],
                    "await_verification",
                )

    def test_exact_verifier_can_promote_awaiting_but_substitution_cannot(self) -> None:
        actor = self.actor()
        self.supervisor.register_actor(actor)
        self.supervisor.record_business_terminal(self.business(actor, verifier=None))
        wrong = self.verifier(actor)
        wrong["receipt_id"] = "verify-wrong-provider"
        wrong["provider"] = "other-provider"
        self.supervisor.record_verifier_receipt(wrong)
        self.assertEqual(
            self.supervisor.projection()["actors"][actor["actor_id"]]["business_status"],
            "await_verification",
        )
        self.supervisor.record_verifier_receipt(self.verifier(actor))
        self.assertEqual(
            self.supervisor.projection()["actors"][actor["actor_id"]]["business_status"],
            "succeeded",
        )

    def test_malformed_verifier_keeps_business_terminal_awaiting(self) -> None:
        actor = self.actor()
        self.supervisor.register_actor(actor)
        malformed = {"schema": "unknown", "status": "passed"}
        self.supervisor.record_business_terminal(self.business(actor, verifier=malformed))
        state = self.supervisor.projection()["actors"][actor["actor_id"]]
        self.assertTrue(state["terminal"])
        self.assertEqual(state["business_status"], "await_verification")
        self.clock.advance(1.0)
        self.supervisor.record_exit(self.exit_event(actor, "late-noise"))
        self.clock.advance(10.0)
        self.assertFalse(any(item["kind"] == "restart"
                             for item in self.supervisor.scan()["recommendations"]))

    def test_terminal_and_cancellation_absorb_all_liveness_and_conflict_noise(self) -> None:
        for suffix, terminal_kind in (("a", "business"), ("b", "cancel")):
            with self.subTest(terminal_kind=terminal_kind):
                path = self.root / f"absorbing-{suffix}.jsonl"
                supervisor = self.make_supervisor(path=path)
                actor = self.actor(suffix, pid=120 if suffix == "a" else 121)
                peer = self.actor(f"{suffix}peer", pid=220 if suffix == "a" else 221)
                shared = self.resource(f"shared-{suffix}")
                supervisor.register_actor(actor)
                supervisor.register_actor(peer)
                supervisor.record_heartbeat(
                    self.heartbeat(actor, callback=f"hb-{suffix}", resources=[shared])
                )
                supervisor.record_heartbeat(
                    self.heartbeat(
                        peer, callback=f"hb-peer-{suffix}", resources=[shared]
                    )
                )
                supervisor.record_lock_lease(
                    self.lease(
                        actor, expires_wall=90.0, lease_id=f"lease-terminal-{suffix}"
                    )
                )
                supervisor.record_process_probe(
                    self.probe(actor, "dead", probe_id=f"dead-terminal-{suffix}")
                )
                if terminal_kind == "business":
                    supervisor.record_business_terminal(
                        self.business(actor, verifier=self.verifier(actor))
                    )
                else:
                    supervisor.record_cancellation(
                        self.cancellation(actor, callback=f"cancel-{suffix}")
                    )
                self.clock.advance(60.0)
                supervisor.record_exit(
                    self.exit_event(actor, f"late-noise-{suffix}")
                )
                projection = supervisor.scan()
                state = projection["actors"][actor["actor_id"]]
                self.assertTrue(state["terminal"])
                self.assertIsNotNone(state["snapshot"]["heartbeat"])
                self.assertFalse(any(
                    card["actor_id"] == actor["actor_id"]
                    for card in projection["status_cards"]
                ))
                self.assertEqual(projection["conflicts"], [])
                self.assertFalse(projection["locks"][
                    f"local_lock:lock-A"
                ]["owner_dead"])
                self.assertFalse(any(
                    item["kind"] in {"restart", "reclaim_lock", "pause_conflict"}
                    and actor["actor_id"] in repr(item)
                    for item in projection["recommendations"]
                ))


class StaleWorldStateTests(RecoveryFixture):
    def test_recovery_lease_generation_and_terminal_drift_retire_old_work(self) -> None:
        for index, mutation in enumerate(
            ("owner_alive", "lease_renewal", "generation_change", "terminal")
        ):
            with self.subTest(mutation=mutation):
                clock = FakeClock()
                self.clock = clock
                adapter = FakeLocalAdapter()
                verifier = FakeInterventionVerifier()
                path = self.root / f"stale-{mutation}.jsonl"
                supervisor = self.make_supervisor(
                    path=path, clock=clock, adapter=adapter, verifier=verifier
                )
                actor = self.actor(f"s{index}", pid=300 + index)
                supervisor.register_actor(actor)
                supervisor.record_lock_lease(
                    self.lease(actor, expires_wall=90.0, lease_id=f"lease-{index}")
                )
                supervisor.record_process_probe(
                    self.probe(actor, "dead", probe_id=f"dead-{index}")
                )
                recommendation = next(
                    item for item in supervisor.scan()["recommendations"]
                    if item["kind"] == "reclaim_lock"
                )
                authorize_before_drift = mutation in {"generation_change", "terminal"}
                authorization = (
                    supervisor.authorize(recommendation["recommendation_id"])
                    if authorize_before_drift else None
                )
                clock.advance(1.0)
                if mutation == "owner_alive":
                    supervisor.record_process_probe(
                        self.probe(actor, "alive", probe_id=f"alive-{index}")
                    )
                elif mutation == "lease_renewal":
                    renewal = self.lease(
                        actor, expires_wall=1000.0, lease_id=f"renewed-{index}"
                    )
                    renewal["lease_epoch"] = 4
                    supervisor.record_lock_lease(renewal)
                elif mutation == "generation_change":
                    successor = self.actor(f"g{index}", pid=400 + index)
                    successor["generation"] = actor["generation"] + 1
                    supervisor.register_actor(successor)
                    renewal = self.lease(
                        successor, expires_wall=1000.0,
                        lease_id=f"generation-{index}",
                        lock=self.resource("lock-A"),
                    )
                    renewal["lease_epoch"] = 4
                    supervisor.record_lock_lease(renewal)
                else:
                    supervisor.record_cancellation(
                        self.cancellation(actor, callback=f"terminal-{index}")
                    )
                projection = supervisor.projection()
                self.assertIn(
                    recommendation["recommendation_id"],
                    {
                        item["recommendation_id"]
                        for item in projection["retired_recommendations"]
                    },
                )
                if authorization is None:
                    with self.assertRaisesRegex(
                        recovery.RecoverySupervisorError, "stale|eligible"
                    ):
                        supervisor.authorize(recommendation["recommendation_id"])
                    self.assertEqual(projection["authorizations"], [])
                else:
                    with self.assertRaisesRegex(
                        recovery.RecoverySupervisorError,
                        "retired|world-state",
                    ):
                        supervisor.execute(
                            authorization["intervention_id"], adapter
                        )
                    self.assertEqual(adapter.callbacks, 0)
                    self.assertFalse(any(
                        event["event_type"] == "intervention_prepared"
                        for event in supervisor.state.snapshot()["events"]
                    ))


class OrderingAndAttackTests(RecoveryFixture):
    def test_reversed_heartbeat_exit_lease_probe_then_register_loses_nothing(self) -> None:
        actor = self.actor()
        self.clock.advance(1.0)
        self.supervisor.record_heartbeat(self.heartbeat(actor, mono=0.0, wall=100.0))
        self.supervisor.record_exit(self.exit_event(actor, "early", mono=1.0, wall=101.0))
        self.supervisor.record_lock_lease(self.lease(actor, expires_wall=105.0))
        self.supervisor.record_process_probe(
            self.probe(actor, "dead", wall=101.0, mono=1.0)
        )
        self.supervisor.register_actor(actor)
        self.clock.advance(5.0)
        projection = self.supervisor.scan()
        kinds = {item["kind"] for item in projection["recommendations"]}
        self.assertEqual(kinds, {"reclaim_lock", "restart"})
        self.assertEqual(projection["actors"][actor["actor_id"]]["progress_cursor"]["sequence"], 1)

    def test_allowed_path_provider_epoch_command_generation_attacks_fail_closed(self) -> None:
        actor = self.actor()
        self.supervisor.register_actor(actor)
        mutations = [
            ("paths", lambda binding: binding["allowed_paths"].append("wider/path")),
            ("provider", lambda binding: binding.__setitem__("provider", "other")),
            ("epoch", lambda binding: binding.__setitem__("task_epoch", "f" * 24)),
            ("command", lambda binding: binding.__setitem__("command_identity", digest("evil"))),
            ("generation", lambda binding: binding.__setitem__("generation", 8)),
        ]
        for index, (_name, mutate) in enumerate(mutations):
            event = self.exit_event(actor, f"attack-{index}")
            mutate(event["binding"])
            if event["binding"]["allowed_paths"] != sorted(event["binding"]["allowed_paths"]):
                event["binding"]["allowed_paths"].sort()
            self.supervisor.record_exit(event)
        projection = self.supervisor.projection()
        rejected = [item for item in projection["rejected_observations"]
                    if item["reason"] == "immutable_binding_mismatch"]
        self.assertEqual(len(rejected), len(mutations))
        self.assertFalse(any(item["kind"] == "restart"
                             for item in projection["pending_recommendations"]))

    def test_exact_plain_json_and_schema_versions_reject_magic_or_extra_fields(self) -> None:
        with self.assertRaises(durable.SupervisorStateError):
            self.supervisor.register_actor(Magic(self.actor()))
        event = self.heartbeat(self.actor())
        event["unexpected"] = True
        with self.assertRaises(durable.SupervisorStateError):
            self.supervisor.record_heartbeat(event)


class DurabilityAndCrashTests(RecoveryFixture):
    def test_duplicate_heartbeat_scan_callback_and_recovery_are_idempotent(self) -> None:
        actor = self.actor()
        self.supervisor.register_actor(actor)
        heartbeat = self.heartbeat(actor)
        first = self.supervisor.record_heartbeat(heartbeat)
        self.clock.advance(1.0)
        second = self.supervisor.record_heartbeat(heartbeat)
        self.assertEqual(first["status"], "appended")
        self.assertEqual(second["status"], "duplicate")
        self.assertEqual(
            second["row"]["payload"]["supervisor_received_mono"],
            first["row"]["payload"]["supervisor_received_mono"],
        )
        self.clock.advance(5.0)
        self.supervisor.scan()
        self.supervisor.scan()
        self.assertEqual(len(self.supervisor.projection()["status_cards"]), 1)

    def test_same_callback_or_receipt_identity_with_changed_payload_is_rejected(self) -> None:
        actor = self.actor()
        self.supervisor.register_actor(actor)
        heartbeat = self.heartbeat(actor)
        self.supervisor.record_heartbeat(heartbeat)
        changed = deepcopy(heartbeat)
        changed["progress_cursor"]["sequence"] = 2
        changed["progress_cursor"]["state_identity"] = digest("changed")
        with self.assertRaisesRegex(durable.SupervisorStateError, "conflicting payloads"):
            self.supervisor.record_heartbeat(changed)

    def test_state_crash_before_and_after_durable_append_boundaries(self) -> None:
        actor = self.actor()
        for boundary, expected_rows in (
            ("before_append", 0),
            ("after_append_before_fsync", 1),
            ("after_fsync", 1),
        ):
            with self.subTest(boundary=boundary):
                path = self.root / f"state-{boundary}.jsonl"
                failed = self.make_supervisor(
                    path=path, state_failpoint=OneShotFailpoint(boundary)
                )
                with self.assertRaises(Crash):
                    failed.register_actor(actor)
                recovered = self.make_supervisor(path=path)
                self.assertEqual(recovered.state.snapshot()["sequence"], expected_rows)
                recovered.register_actor(actor)
                self.assertEqual(recovered.state.snapshot()["sequence"], 1)

    def test_crash_before_after_each_intervention_boundary_converges(self) -> None:
        authorization_boundaries = ["before_authorization", "after_authorization"]
        for boundary in authorization_boundaries:
            with self.subTest(boundary=boundary):
                clock = FakeClock()
                self.clock = clock
                adapter = FakeLocalAdapter()
                verifier = FakeInterventionVerifier()
                path = self.root / f"intervention-{boundary}.jsonl"
                base = self.make_supervisor(
                    path=path, clock=clock, adapter=adapter, verifier=verifier
                )
                actor = self.actor()
                base.register_actor(actor)
                base.record_lock_lease(self.lease(actor, expires_wall=110.0))
                clock.advance(1.0)
                base.record_process_probe(self.probe(actor, "dead"))
                clock.advance(9.0)
                recommendation = next(
                    item for item in base.scan()["recommendations"]
                    if item["kind"] == "reclaim_lock"
                )
                crashing = self.make_supervisor(
                    path=path, clock=clock, adapter=adapter, verifier=verifier,
                    failpoint=OneShotFailpoint(boundary),
                )
                with self.assertRaises(Crash):
                    crashing.authorize(recommendation["recommendation_id"])
                recovered = self.make_supervisor(
                    path=path, clock=clock, adapter=adapter, verifier=verifier
                )
                authorization = recovered.authorize(
                    recommendation["recommendation_id"]
                )
                receipt = recovered.execute(
                    authorization["intervention_id"], adapter
                )
                self.assertEqual(receipt["status"], "completed")
                self.assertTrue(receipt["verified"])
                self.assertEqual(adapter.callbacks, 1)

        execution_boundaries = {
            "before_intervention_start": "completed",
            "before_prepare": "completed",
            "after_prepare": "awaiting_verification",
            "after_intervention_start": "awaiting_verification",
            "before_apply": "awaiting_verification",
            "after_apply": "completed",
            "before_dispatch_receipt": "completed",
            "after_dispatch_receipt": "completed",
            "before_verifier": "completed",
            "after_verifier": "completed",
            "before_verifier_receipt": "completed",
            "after_verifier_receipt": "completed",
            "before_intervention_receipt": "completed",
            "after_intervention_receipt": "completed",
        }
        for index, (boundary, expected) in enumerate(execution_boundaries.items()):
            with self.subTest(boundary=boundary):
                clock = FakeClock()
                self.clock = clock
                adapter = FakeLocalAdapter()
                verifier = FakeInterventionVerifier()
                path = self.root / f"dispatch-{index}-{boundary}.jsonl"
                base = self.make_supervisor(
                    path=path, clock=clock, adapter=adapter, verifier=verifier
                )
                actor = self.actor(f"c{index}", pid=500 + index)
                base.register_actor(actor)
                base.record_lock_lease(
                    self.lease(actor, expires_wall=110.0, lease_id=f"crash-{index}")
                )
                clock.advance(1.0)
                base.record_process_probe(
                    self.probe(actor, "dead", probe_id=f"crash-probe-{index}")
                )
                clock.advance(9.0)
                recommendation = next(
                    item for item in base.scan()["recommendations"]
                    if item["kind"] == "reclaim_lock"
                )
                authorization = base.authorize(
                    recommendation["recommendation_id"]
                )
                crashing = self.make_supervisor(
                    path=path, clock=clock, adapter=adapter, verifier=verifier,
                    failpoint=OneShotFailpoint(boundary),
                )
                with self.assertRaises(Crash):
                    crashing.execute(authorization["intervention_id"], adapter)
                recovered = self.make_supervisor(
                    path=path, clock=clock, adapter=adapter, verifier=verifier
                )
                receipt = recovered.execute(
                    authorization["intervention_id"], adapter
                )
                self.assertEqual(receipt["status"], expected)
                self.assertLessEqual(adapter.callbacks, 1)
                terminals = recovered.projection()["terminal_receipts"]
                if expected == "completed":
                    self.assertTrue(receipt["verified"])
                    self.assertEqual(len(terminals), 1)
                else:
                    self.assertFalse(receipt["verified"])
                    self.assertEqual(terminals, [])

        for index, boundary in enumerate(("before_reprobe", "after_reprobe")):
            with self.subTest(boundary=boundary):
                clock = FakeClock()
                self.clock = clock
                adapter = FakeLocalAdapter()
                verifier = FakeInterventionVerifier()
                path = self.root / f"reprobe-{boundary}.jsonl"
                base = self.make_supervisor(
                    path=path, clock=clock, adapter=adapter, verifier=verifier
                )
                actor = self.actor(f"r{index}", pid=700 + index)
                base.register_actor(actor)
                base.record_lock_lease(
                    self.lease(actor, expires_wall=90.0, lease_id=f"reprobe-{index}")
                )
                base.record_process_probe(
                    self.probe(actor, "dead", probe_id=f"reprobe-probe-{index}")
                )
                recommendation = next(
                    item for item in base.scan()["recommendations"]
                    if item["kind"] == "reclaim_lock"
                )
                authorization = base.authorize(
                    recommendation["recommendation_id"]
                )
                prepare_crash = self.make_supervisor(
                    path=path, clock=clock, adapter=adapter, verifier=verifier,
                    failpoint=OneShotFailpoint("after_prepare"),
                )
                with self.assertRaises(Crash):
                    prepare_crash.execute(
                        authorization["intervention_id"], adapter
                    )
                reprobe_crash = self.make_supervisor(
                    path=path, clock=clock, adapter=adapter, verifier=verifier,
                    failpoint=OneShotFailpoint(boundary),
                )
                with self.assertRaises(Crash):
                    reprobe_crash.execute(
                        authorization["intervention_id"], adapter
                    )
                recovered = self.make_supervisor(
                    path=path, clock=clock, adapter=adapter, verifier=verifier
                )
                receipt = recovered.execute(
                    authorization["intervention_id"], adapter
                )
                self.assertEqual(receipt["status"], "awaiting_verification")
                self.assertFalse(receipt["verified"])
                self.assertEqual(adapter.callbacks, 0)
                self.assertGreaterEqual(
                    adapter.reprobes, 1 if boundary == "before_reprobe" else 2
                )
                self.assertEqual(recovered.projection()["terminal_receipts"], [])

    def test_malformed_torn_tampered_and_read_only_storage_fail_closed(self) -> None:
        cases = {
            "malformed": b"not-json\n",
            "torn": b'{"schema":"partial"}',
        }
        for name, content in cases.items():
            with self.subTest(name=name):
                path = self.root / f"{name}.jsonl"
                path.write_bytes(content)
                os.chmod(path, 0o600)
                with self.assertRaises(durable.SupervisorStateError):
                    self.make_supervisor(path=path).state.snapshot()

        path = self.root / "tampered.jsonl"
        supervisor = self.make_supervisor(path=path)
        supervisor.register_actor(self.actor())
        row = json.loads(path.read_text(encoding="utf-8"))
        row["payload"]["provider"] = "tampered"
        path.write_text(json.dumps(row, separators=(",", ":")) + "\n", encoding="utf-8")
        os.chmod(path, 0o600)
        with self.assertRaisesRegex(durable.SupervisorStateError, "tampered"):
            supervisor.state.snapshot()

        readonly = self.root / "readonly.jsonl"
        writable = self.make_supervisor(path=readonly)
        writable.register_actor(self.actor("b"))
        os.chmod(readonly, stat.S_IRUSR)
        try:
            with self.assertRaises(durable.SupervisorStateError):
                writable.record_process_probe(self.probe(self.actor("b"), "unknown"))
        finally:
            os.chmod(readonly, stat.S_IRUSR | stat.S_IWUSR)

    def test_held_state_lock_fails_typed_and_bounded_without_journal_damage(self) -> None:
        actor = self.actor()
        self.supervisor.register_actor(actor)
        baseline = self.path.read_bytes()
        program = (
            "import fcntl,os,sys\n"
            "fd=os.open(sys.argv[1],os.O_RDWR|os.O_CREAT,0o600)\n"
            "fcntl.flock(fd,fcntl.LOCK_EX)\n"
            "print('ready',flush=True)\n"
            "sys.stdin.readline()\n"
        )
        process = subprocess.Popen(
            [sys.executable, "-c", program, str(self.supervisor.state.lock_path)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding="utf-8",
            errors="replace",
        )
        try:
            ready, _, _ = select.select([process.stdout], [], [], 2.0)
            self.assertTrue(ready)
            self.assertEqual(process.stdout.readline().strip(), "ready")
            started = time.monotonic()
            with self.assertRaises(durable.SupervisorStateBusyError):
                self.supervisor.state.snapshot()
            elapsed = time.monotonic() - started
            self.assertLess(elapsed, 5.0)
            self.assertEqual(self.path.read_bytes(), baseline)
        finally:
            assert process.stdin is not None
            process.stdin.write("\n")
            process.stdin.flush()
            process.communicate(timeout=2.0)
        self.assertEqual(self.supervisor.state.snapshot()["sequence"], 1)

    def test_relative_parent_and_leaf_identity_attacks_fail_closed(self) -> None:
        with self.assertRaisesRegex(
            durable.SupervisorStateError, "must be absolute"
        ):
            durable.SupervisorState("relative-state.jsonl")

        parent = self.root / "retained-parent"
        parent.mkdir(mode=0o700)
        path = parent / "state.jsonl"
        state = durable.SupervisorState(path)
        state.append("fixture", {"value": 1})
        displaced = self.root / "displaced-parent"
        os.rename(parent, displaced)
        parent.mkdir(mode=0o700)
        with self.assertRaisesRegex(
            durable.SupervisorStateError, "parent pathname identity changed"
        ):
            state.snapshot()
        state.close()

        for attack in ("replacement", "symlink", "hardlink", "broad_mode"):
            with self.subTest(attack=attack):
                attack_parent = self.root / f"leaf-{attack}"
                attack_parent.mkdir(mode=0o700)
                attack_path = attack_parent / "state.jsonl"
                selected = durable.SupervisorState(attack_path)
                selected.append("fixture", {"attack": attack})
                backup = attack_parent / "original.jsonl"
                if attack == "replacement":
                    content = attack_path.read_bytes()
                    os.rename(attack_path, backup)
                    attack_path.write_bytes(content)
                    os.chmod(attack_path, 0o600)
                elif attack == "symlink":
                    os.rename(attack_path, backup)
                    os.symlink(backup.name, attack_path)
                elif attack == "hardlink":
                    os.rename(attack_path, backup)
                    os.link(backup, attack_path)
                else:
                    os.chmod(attack_path, 0o644)
                with self.assertRaises(durable.SupervisorStateError):
                    selected.snapshot()
                selected.close()

        mode_parent = self.root / "mode-parent"
        mode_parent.mkdir(mode=0o700)
        mode_state = durable.SupervisorState(mode_parent / "state.jsonl")
        mode_state.append("fixture", {"mode": "private"})
        os.chmod(mode_parent, 0o777)
        try:
            with self.assertRaisesRegex(
                durable.SupervisorStateError, "untrusted writes"
            ):
                mode_state.snapshot()
        finally:
            os.chmod(mode_parent, 0o700)
            mode_state.close()

        readonly_parent = self.root / "readonly-parent"
        readonly_parent.mkdir(mode=0o700)
        readonly_state = durable.SupervisorState(readonly_parent / "state.jsonl")
        os.chmod(readonly_parent, 0o500)
        try:
            with self.assertRaisesRegex(
                durable.SupervisorStateError, "read-only"
            ):
                readonly_state.snapshot()
        finally:
            os.chmod(readonly_parent, 0o700)
            readonly_state.close()

        fd_parent = self.root / "fd-parent"
        fd_parent.mkdir(mode=0o700)
        fd_state = durable.SupervisorState(fd_parent / "state.jsonl")
        replacement_fd = os.open(
            self.root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        )
        original_fd = fd_state._parent_fd
        fd_state._parent_fd = replacement_fd
        try:
            with self.assertRaisesRegex(
                durable.SupervisorStateError, "descriptor was substituted"
            ):
                fd_state.snapshot()
        finally:
            fd_state._parent_fd = original_fd
            os.close(replacement_fd)
            fd_state.close()

        owner_parent = self.root / "owner-parent"
        owner_parent.mkdir(mode=0o700)
        owner_state = durable.SupervisorState(owner_parent / "state.jsonl")
        with mock.patch.object(
            durable, "_trusted_uid", return_value=os.getuid() + 1
        ):
            with self.assertRaisesRegex(
                durable.SupervisorStateError, "owner is not trusted"
            ):
                owner_state.snapshot()
        owner_state.close()

        path_parent = self.root / "path-substitution-parent"
        path_parent.mkdir(mode=0o700)
        path_state = durable.SupervisorState(path_parent / "state.jsonl")
        path_state.append("fixture", {"path": "original"})
        path_state.path = self.root / "substituted.jsonl"
        with self.assertRaisesRegex(
            durable.SupervisorStateError, "path metadata was substituted"
        ):
            path_state.snapshot()
        path_state.path = path_parent / "state.jsonl"
        path_state.close()

        if sys.platform == "darwin":
            canonical = str(self.root.resolve())
            if canonical.startswith("/private/var/"):
                alias = Path("/var") / Path(canonical).relative_to("/private/var")
                alias_state = durable.SupervisorState(alias / "canonical.jsonl")
                alias_state.append("fixture", {"canonical": True})
                self.assertEqual(alias_state.snapshot()["sequence"], 1)
                alias_state.close()


class AuthorityBoundaryTests(RecoveryFixture):
    def test_no_signal_delete_git_external_or_production_mutation(self) -> None:
        _actor, recommendation = self.prepare_reclaim()
        adapter = self.adapter
        with mock.patch("os.kill", side_effect=AssertionError("real signal")), \
             mock.patch("os.unlink", side_effect=AssertionError("delete")), \
             mock.patch("subprocess.run", side_effect=AssertionError("external command")):
            authorization = self.supervisor.authorize(recommendation["recommendation_id"])
            receipt = self.supervisor.execute(authorization["intervention_id"], adapter)
        self.assertTrue(receipt["local_only"])
        authority = self.supervisor.projection()["authority"]
        self.assertTrue(all(value is False for value in authority.values()))

    def test_adapter_cannot_expand_external_effect(self) -> None:
        _actor, recommendation = self.prepare_reclaim()
        authorization = self.supervisor.authorize(recommendation["recommendation_id"])

        class HostileAdapter:
            def apply(self, selected: dict) -> dict:
                return {
                    "schema": recovery.ADAPTER_RESULT_SCHEMA,
                    "intervention_id": selected["intervention_id"],
                    "status": "completed", "local_only": False,
                    "external_effect": True, "result": {},
                }

        with self.assertRaisesRegex(recovery.RecoverySupervisorError, "not supervisor-trusted"):
            self.supervisor.execute(authorization["intervention_id"], HostileAdapter())

    def test_adapter_completion_without_independent_verification_is_not_success(self) -> None:
        clock = FakeClock()
        self.clock = clock
        adapter = FakeLocalAdapter()
        verifier = FakeInterventionVerifier(status="unknown")
        supervisor = self.make_supervisor(
            path=self.root / "unverified.jsonl", clock=clock,
            adapter=adapter, verifier=verifier,
        )
        actor = self.actor()
        supervisor.register_actor(actor)
        supervisor.record_lock_lease(self.lease(actor, expires_wall=90.0))
        supervisor.record_process_probe(self.probe(actor, "dead"))
        recommendation = next(
            item for item in supervisor.scan()["recommendations"]
            if item["kind"] == "reclaim_lock"
        )
        authorization = supervisor.authorize(
            recommendation["recommendation_id"]
        )
        receipt = supervisor.execute(
            authorization["intervention_id"], adapter
        )
        self.assertEqual(receipt["status"], "awaiting_verification")
        self.assertFalse(receipt["verified"])
        self.assertEqual(supervisor.projection()["terminal_receipts"], [])
        dispatch = next(
            event["payload"] for event in supervisor.state.snapshot()["events"]
            if event["event_type"] == "intervention_dispatch_observed"
        )
        self.assertNotIn("local_only", dispatch)
        self.assertNotIn("external_effect", dispatch)


if __name__ == "__main__":
    unittest.main()
