from __future__ import annotations

import os
from pathlib import Path
import runpy
import stat
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "kb"))

from production_recovery_readiness import (  # noqa: E402
    ProductionRecoveryReadinessError,
    observe_recovery_truth,
    provision_recovery_key,
    recovery_paths,
)
from codex_recovery_defer import (  # noqa: E402
    native_recovery_read_action,
    payload_requires_fail_closed,
)


class ProductionRecoveryReadinessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.home = Path(self.temporary.name) / "kb"
        self.home.mkdir()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_provision_is_private_persistent_and_observable_without_journal_write(self) -> None:
        key_path = provision_recovery_key(self.home)
        original = key_path.read_bytes()
        self.assertEqual(len(original), 32)
        self.assertEqual(stat.S_IMODE(key_path.stat().st_mode), 0o600)
        self.assertEqual(provision_recovery_key(self.home).read_bytes(), original)

        key_path, state_path = recovery_paths(self.home)
        truth = observe_recovery_truth(self.home)
        self.assertTrue(truth["lane_available"])
        self.assertTrue(truth["typed_route_available"])
        self.assertEqual(truth["snapshot_status"], "empty")
        self.assertFalse(state_path.exists())
        self.assertFalse(state_path.with_name(f".{state_path.name}.lock").exists())

    def test_observation_fails_closed_without_manufacturing_authority(self) -> None:
        key_path, state_path = recovery_paths(self.home)
        truth = observe_recovery_truth(self.home)
        self.assertFalse(truth["lane_available"])
        self.assertTrue(truth["typed_route_available"])
        self.assertFalse(key_path.exists())
        self.assertFalse(state_path.exists())

    def test_exact_diagnosis_survives_missing_recovery_key(self) -> None:
        from production_recovery import route_production_recovery
        with mock.patch.dict(os.environ, {
            "SULDE_HOME": str(self.home),
            "SULDE_RECOVERY_KEY_FILE": str(self.home / "missing.key"),
        }):
            decision = route_production_recovery({
                "client": "codex", "session_id": "diagnostic-session", "cwd": str(self.home),
                "tool_name": "exec_command", "tool_input": {
                    "cmd": f"{self.home}/bin/intent-guardian doctor --provider codex",
                },
            }, contract_path=self.home / "missing-contract.json")
        self.assertEqual(decision.dispatch, "allow")
        self.assertEqual(decision.authority, "none")
        self.assertEqual(decision.reason_code, "recovery_diagnosis_only")

    def test_structural_readiness_never_claims_live_confirmation_or_repair(self) -> None:
        provision_recovery_key(self.home)
        truth = observe_recovery_truth(self.home)
        self.assertTrue(truth["diagnosis_available"])
        self.assertEqual(truth["human_confirmation"], "unobserved")
        self.assertEqual(truth["repair_execution"], "unverified")
        self.assertFalse(truth["recovery_verified"])

    def test_recovery_terminal_is_read_from_validated_journal(self) -> None:
        # Exercise the real lane/state machine with isolated test adapters;
        # this is not evidence of a live human decision or production repair.
        from recovery_lane import RecoveryLane
        from tests.test_recovery_lane import Adapter, Verifier, Clock, Host, SHA_A, SHA_B
        key_path = provision_recovery_key(self.home)
        _, state_path = recovery_paths(self.home)
        clock = Clock()
        lane = RecoveryLane(str(state_path), seal_key=key_path.read_bytes(),
                            wall_clock=lambda: clock.wall, monotonic_clock=lambda: clock.mono,
                            trusted_adapter=Adapter(), trusted_verifier=Verifier(),
                            adapter_identity=SHA_A, verifier_identity=SHA_B)
        try:
            cap = lane.issue_capability(provider="codex", session_id="isolated", workspace=str(self.home),
                                        installed_generation="fixture", action="repair_launcher", target_identity="fixture-launcher",
                                        expected_pre_state={"fixture": True}, expires_at=clock.wall + 100,
                                        verifier_identity=SHA_B, nonce="isolated-repair")
            lane.request_permission(cap, Host("allow", clock))
            terminal = lane.execute(cap, current_pre_state={"fixture": True})
            self.assertEqual(terminal["status"], "succeeded")
        finally:
            lane.state.close()
        before = state_path.read_bytes()
        truth = observe_recovery_truth(self.home)
        self.assertTrue(truth["recovery_verified"])
        self.assertEqual(truth["last_terminal"]["run_id"], terminal["run_id"])
        self.assertEqual(truth["human_confirmation"], "unobserved")
        self.assertEqual(state_path.read_bytes(), before)

    def test_malformed_existing_key_is_never_replaced(self) -> None:
        key_path, _state_path = recovery_paths(self.home)
        key_path.parent.mkdir(parents=True)
        key_path.write_bytes(b"too-short")
        key_path.chmod(0o600)
        with self.assertRaises(ProductionRecoveryReadinessError):
            provision_recovery_key(self.home)
        self.assertEqual(key_path.read_bytes(), b"too-short")

    @unittest.skipIf(os.name == "nt", "POSIX permission identity test")
    def test_broad_key_permissions_are_rejected(self) -> None:
        key_path, _state_path = recovery_paths(self.home)
        key_path.parent.mkdir(parents=True)
        key_path.write_bytes(b"x" * 32)
        key_path.chmod(0o644)
        truth = observe_recovery_truth(self.home)
        self.assertFalse(truth["lane_available"])
        with self.assertRaises(ProductionRecoveryReadinessError):
            provision_recovery_key(self.home)

    @unittest.skipIf(os.name == "nt", "POSIX directory identity test")
    def test_broad_control_directory_permissions_are_rejected(self) -> None:
        key_path, _state_path = recovery_paths(self.home)
        key_path.parent.mkdir(parents=True)
        key_path.parent.chmod(0o777)
        with self.assertRaises(ProductionRecoveryReadinessError):
            provision_recovery_key(self.home)
        self.assertFalse(key_path.exists())

    def test_only_exact_native_doctor_maps_to_a_read_recovery_action(self) -> None:
        launcher_root = self.home / "launcher"
        runtime_root = self.home / "runtime"
        command = (
            f"{launcher_root}/bin/intent-guardian doctor "
            "--workspace task-worktree --provider codex --session-id thread-one"
        )
        self.assertEqual(
            native_recovery_read_action(
                command,
                runtime_root=runtime_root,
                launcher_home=launcher_root,
            ),
            "doctor",
        )
        for rejected in (
            command.replace("--provider codex", "--provider claude"),
            command + " --unknown value",
            command + "; touch /tmp/forbidden",
            command.replace("intent-guardian doctor", "other-tool doctor"),
        ):
            with self.subTest(command=rejected):
                self.assertIsNone(
                    native_recovery_read_action(
                        rejected,
                        runtime_root=runtime_root,
                        launcher_home=launcher_root,
                    )
                )

    def test_busy_fallback_keeps_read_only_mcp_and_figma_outside_control(self) -> None:
        static = runpy.run_path(
            str(
                ROOT
                / "integrations/codex/plugins/sulde/scripts/_recovery_defer.py"
            )
        )["payload_requires_fail_closed"]
        classifiers = (payload_requires_fail_closed, static)
        read_only = (
            "mcp__sulde_kb__kb_status",
            "mcp__sulde-kb__memory_search",
            "mcp__figma__use_figma",
            "mcp__codex_apps__figma_create_new_file",
        )
        for classify in classifiers:
            for tool_name in read_only:
                with self.subTest(classifier=classify.__module__, tool_name=tool_name):
                    self.assertFalse(
                        classify(
                            {"tool_name": tool_name, "tool_input": {}},
                            runtime_root=self.home / "runtime",
                            launcher_home=self.home / "launcher",
                        )
                    )
            for tool_name in (
                "mcp__sulde_kb__memory_annotate",
                "mcp__untrusted__kb_status",
            ):
                with self.subTest(classifier=classify.__module__, tool_name=tool_name):
                    self.assertTrue(
                        classify(
                            {"tool_name": tool_name, "tool_input": {}},
                            runtime_root=self.home / "runtime",
                            launcher_home=self.home / "launcher",
                        )
                    )


if __name__ == "__main__":
    unittest.main()
