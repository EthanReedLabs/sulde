from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "kb"))

import recovery_lane as recovery  # noqa: E402
from intent_guardian_parts.recovery import (  # noqa: E402
    route_recovery_before_ordinary_policy,
)


SHA_A = "sha256:" + "a" * 64
SHA_B = "sha256:" + "b" * 64


class Clock:
    def __init__(self) -> None:
        self.wall = 100.0
        self.mono = 100.0

    def advance(self, seconds: float) -> None:
        self.wall += seconds
        self.mono += seconds


class Adapter:
    def __init__(self, status: str = "completed") -> None:
        self.status = status
        self.applied = 0
        self.reprobed = 0

    def _result(self, request: dict) -> dict:
        return {
            "schema": recovery.ADAPTER_RESULT_SCHEMA,
            "run_id": request["run_id"],
            "effect_id": request["effect_id"],
            "adapter_identity": SHA_A,
            "action": request["action"],
            "target_identity": request["target_identity"],
            "status": self.status,
            "observed_post_state": {"settled": self.status == "completed"},
            "detail": {"fixture": True},
        }

    def __getattr__(self, name: str):
        if name in {
            "settle_transaction", "abort_transaction", "repair_launcher",
            "repair_generated_bytecode", "uninstall", "rollback",
        }:
            def apply(request: dict) -> dict:
                self.applied += 1
                return self._result(request)
            return apply
        raise AttributeError(name)

    def reprobe(self, request: dict) -> dict:
        self.reprobed += 1
        return self._result(request)


class Verifier:
    def __init__(self, status: str = "passed") -> None:
        self.status = status
        self.calls = 0

    def verify(self, request: dict) -> dict:
        self.calls += 1
        return {
            "schema": recovery.VERIFIER_RECEIPT_SCHEMA,
            "receipt_id": recovery._plain_digest(
                "fixture-receipt", {"call": self.calls, "request": request}
            ),
            "verifier_identity": SHA_B,
            "run_id": request["run_id"],
            "effect_id": request["effect_id"],
            "action": request["action"],
            "target_identity": request["target_identity"],
            "result_identity": request["result_identity"],
            "status": self.status,
            "evidence": {"independent": True},
        }


class SupervisorBridge:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def record_recovery_event(self, event: dict) -> None:
        self.events.append(deepcopy(event))


class Host:
    def __init__(self, outcome: str, clock: Clock, *, extra: dict | None = None) -> None:
        self.outcome = outcome
        self.clock = clock
        self.extra = extra or {}

    def permission_request(self, card: dict) -> dict:
        return {
            "schema": recovery.DECISION_SCHEMA,
            "card_id": card["card_id"],
            "capability_id": card["capability_id"],
            "provider": card["provider"],
            "session_id": card["session_id"],
            "outcome": self.outcome,
            "decided_at": self.clock.wall,
            "authority": "human",
            "channel": "native_typed_receipt",
            "receipt_id": f"receipt-{card['capability_id'][-12:]}",
            **self.extra,
        }


class RecoveryLaneTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.clock = Clock()
        self.adapter = Adapter()
        self.verifier = Verifier()
        self.supervisor = SupervisorBridge()
        self.workspace = str(Path(self.temporary.name).resolve())
        self.state_path = str(Path(self.temporary.name) / "recovery.jsonl")
        self.lane = recovery.RecoveryLane(
            self.state_path,
            seal_key=b"k" * 32,
            wall_clock=lambda: self.clock.wall,
            monotonic_clock=lambda: self.clock.mono,
            trusted_adapter=self.adapter,
            trusted_verifier=self.verifier,
            adapter_identity=SHA_A,
            verifier_identity=SHA_B,
            supervisor=self.supervisor,
        )

    def tearDown(self) -> None:
        self.lane.state.close()
        self.temporary.cleanup()

    def capability(
        self, action: str = "status", *, nonce: str | None = None,
        pre_state: dict | None = None,
    ) -> recovery.RecoveryCapability:
        return self.lane.issue_capability(
            provider="codex",
            session_id="session-one",
            workspace=self.workspace,
            installed_generation="generation-one",
            action=action,
            target_identity=f"target-{action}",
            expected_pre_state=pre_state or {"state": "fixture"},
            expires_at=self.clock.wall + 100,
            verifier_identity=SHA_B,
            nonce=nonce or f"nonce-{action}-{self.clock.wall}",
        )

    def allow(self, capability: recovery.RecoveryCapability) -> None:
        result = self.lane.request_permission(
            capability, Host("allow", self.clock)
        )
        self.assertEqual(result["status"], "authorized")

    def test_read_routes_bypass_every_broken_ordinary_state(self) -> None:
        states = [
            "paused", "review_required", "unavailable", "schema_invalid",
            "effect_debt_blocked", "scheduler_degraded", "launcher_digest_drift",
        ]
        for index, state in enumerate(states):
            with self.subTest(state=state):
                pre_state = {"state": state}
                capability = self.capability(
                    "status", nonce=f"state-{index}", pre_state=pre_state
                )
                request = self.lane.request(capability)
                decision = route_recovery_before_ordinary_policy(
                    request,
                    lane=self.lane,
                    current_pre_state=pre_state,
                    ordinary_policy=lambda _event: self.fail("ordinary guard called"),
                )
                self.assertEqual(decision["decision"], "allow_recovery")
                self.assertFalse(decision["ordinary_pretool_policy_required"])

    def test_sealed_binding_future_expiry_forgery_and_drift_fail_closed(self) -> None:
        capability = self.capability()
        arguments = {
            "provider": "codex", "session_id": "session-one",
            "workspace": self.workspace,
            "installed_generation": "generation-one",
            "action": "status", "target_identity": "target-status",
            "current_pre_state": {"state": "fixture"},
        }
        with self.assertRaisesRegex(recovery.RecoveryLaneError, "future"):
            self.lane.validate_capability(capability, now=99.0, **arguments)
        with self.assertRaisesRegex(recovery.RecoveryLaneError, "expired"):
            self.lane.validate_capability(capability, now=200.0, **arguments)
        forged = capability.to_dict()
        forged["target_identity"] = "forged"
        with self.assertRaisesRegex(recovery.RecoveryLaneError, "forged"):
            self.lane.validate_capability(
                forged, target_identity="forged",
                **{key: value for key, value in arguments.items()
                   if key != "target_identity"},
            )
        substitutions = {
            "provider": "claude", "session_id": "session-two",
            "workspace": str(Path(self.workspace) / "other"),
            "installed_generation": "generation-two",
            "action": "doctor", "target_identity": "target-other",
        }
        for field, value in substitutions.items():
            changed = dict(arguments)
            changed[field] = value
            with self.subTest(field=field), self.assertRaisesRegex(
                recovery.RecoveryLaneError, "drift"
            ):
                self.lane.validate_capability(capability, **changed)
        changed = dict(arguments)
        changed["current_pre_state"] = {"state": "drifted"}
        with self.assertRaisesRegex(recovery.RecoveryLaneError, "pre-state"):
            self.lane.validate_capability(capability, **changed)

    def test_card_is_hmac_sealed_and_all_ui_outcomes_are_typed(self) -> None:
        outcomes = {
            "allow": "authorized", "deny": "observed",
            "inspect_diff": "observed", "later": "observed",
        }
        for index, (outcome, expected) in enumerate(outcomes.items()):
            capability = self.capability("settle", nonce=f"ui-{index}")
            card = self.lane.recovery_card(capability)
            self.assertTrue(card["card_id"].startswith("sha256:"))
            self.assertEqual(
                [choice["outcome"] for choice in card["choices"]],
                ["allow", "deny", "inspect_diff", "later"],
            )
            result = self.lane.request_permission(
                capability, Host(outcome, self.clock)
            )
            self.assertEqual(result["status"], expected)
            self.assertFalse(result["text_fallback_used"])

    def test_text_command_and_foreign_card_cannot_authorize(self) -> None:
        capability = self.capability("rollback")
        denied = self.lane.request_permission(
            capability,
            Host("allow", self.clock, extra={"command": "repair now"}),
        )
        self.assertEqual(denied["status"], "denied")
        route = self.lane.pretool_decision(
            {"command": "trusted-recovery ; rm x",
             "trusted_recovery_control": True},
            current_pre_state={"state": "fixture"},
            ordinary_guard=lambda _event: self.fail("ordinary guard called"),
        )
        self.assertEqual(route["classification"], "invalid_composition")
        self.assertFalse(route["pause"])
        self.assertFalse(route["effect_debt"])
        ordinary = self.lane.pretool_decision(
            {"command": "rm -rf x", "trusted_recovery_control": False},
            current_pre_state={"state": "fixture"},
            ordinary_guard=lambda _event: {"decision": "deny", "pause": True},
        )
        self.assertTrue(ordinary["pause"])

    def test_each_exact_write_action_executes_and_verifies_once(self) -> None:
        actions = [
            "settle", "abort", "repair_launcher",
            "repair_generated_bytecode", "uninstall", "rollback",
        ]
        for index, action in enumerate(actions):
            with self.subTest(action=action):
                capability = self.capability(action, nonce=f"write-{index}")
                self.allow(capability)
                result = self.lane.execute(
                    capability, current_pre_state={"state": "fixture"}
                )
                self.assertEqual(result["status"], "succeeded")
                duplicate = self.lane.execute(
                    capability, current_pre_state={"state": "post"}
                )
                self.assertEqual(duplicate, result)
        self.assertEqual(self.adapter.applied, len(actions))
        self.assertEqual(self.verifier.calls, len(actions))

    def test_replay_is_rejected_outside_idempotent_execute(self) -> None:
        capability = self.capability("settle")
        self.allow(capability)
        result = self.lane.execute(
            capability, current_pre_state={"state": "fixture"}
        )
        self.assertEqual(result["status"], "succeeded")
        arguments = {
            "provider": "codex", "session_id": "session-one",
            "workspace": self.workspace,
            "installed_generation": "generation-one",
            "action": "settle", "target_identity": "target-settle",
            "current_pre_state": {"state": "fixture"},
        }
        with self.assertRaisesRegex(recovery.RecoveryLaneError, "replay"):
            self.lane.validate_capability(capability, **arguments)

    def test_ui_unavailable_exposes_typed_independent_path(self) -> None:
        class BrokenHost:
            def permission_request(self, _card: dict) -> dict:
                raise RuntimeError("unavailable")

        capability = self.capability("uninstall")
        result = self.lane.request_permission(capability, BrokenHost())
        self.assertEqual(result["status"], "unavailable")
        self.assertFalse(result["ordinary_lane_required"])
        self.assertEqual(
            result["independent_path"]["authority"],
            "native_typed_callback_only",
        )

    def test_five_thirty_sla_waiting_suppression_and_bounded_reprobe(self) -> None:
        self.adapter.status = "unknown"
        self.verifier.status = "unknown"
        capability = self.capability("repair_launcher")
        self.allow(capability)
        pending = self.lane.execute(
            capability, current_pre_state={"state": "fixture"}
        )
        self.assertEqual(pending["status"], "awaiting_verification")
        run_id = pending["run_id"]
        first = self.lane.record_progress(
            run_id, stage="waiting", message="Waiting for agents"
        )
        second = self.lane.record_progress(
            run_id, stage="waiting", message="Waiting for agents"
        )
        self.assertEqual(first["status"], "recorded")
        self.assertEqual(second["status"], "suppressed_duplicate")
        self.clock.advance(5)
        visible = self.lane.tick(run_id)
        self.assertEqual(
            [row["reason"] for row in visible["changed"]],
            ["no_visible_progress_5s"],
        )
        self.clock.advance(25)
        stalled = self.lane.tick(run_id)
        self.assertEqual(
            [row["reason"] for row in stalled["changed"]],
            ["stalled_no_progress"],
        )
        self.assertEqual(self.lane.tick(run_id)["changed"], [])
        blocked = self.lane.execute(
            capability, current_pre_state={"state": "changed"}
        )
        self.assertEqual(blocked["status"], "blocked")
        self.assertEqual(self.adapter.reprobed, 1)
        self.assertTrue(any(row["kind"] == "terminal" for row in self.supervisor.events))

    def test_crash_after_adapter_reprobes_without_reapplying(self) -> None:
        fired = {"done": False}

        def failpoint(boundary: str) -> None:
            if boundary == "after_adapter" and not fired["done"]:
                fired["done"] = True
                raise RuntimeError("injected crash")

        self.lane._failpoint = failpoint
        capability = self.capability("rollback")
        self.allow(capability)
        pending = self.lane.execute(
            capability, current_pre_state={"state": "fixture"}
        )
        self.assertEqual(pending["status"], "awaiting_verification")
        self.lane._failpoint = lambda _boundary: None
        result = self.lane.execute(
            capability, current_pre_state={"state": "post"}
        )
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(self.adapter.applied, 1)
        self.assertEqual(self.adapter.reprobed, 1)
        self.assertEqual(
            len([
                row for row in self.lane._payloads("recovery_terminal_recorded")
                if row["run_id"] == result["run_id"]
            ]),
            1,
        )

    def test_doctor_separates_hook_snapshot_and_skill_restart(self) -> None:
        doctor = self.lane.doctor(
            task_lane_state="paused",
            launcher_status="drifted",
            snapshot_status="stale",
            hook_generation_status="current",
            skill_catalog_status="old",
        )
        self.assertEqual(doctor["status"], "diagnosis_available")
        self.assertFalse(doctor["ordinary_task_lane_required"])
        self.assertFalse(doctor["hook_hot_rebind_supported"])
        self.assertEqual(doctor["human_confirmation"], "unobserved")
        self.assertFalse(doctor["recovery_verified"])
        self.assertTrue(doctor["skill_catalog_restart_required"])


if __name__ == "__main__":
    unittest.main()
