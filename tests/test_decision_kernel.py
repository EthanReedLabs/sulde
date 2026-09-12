from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "kb"))

from decision_kernel import (  # noqa: E402
    claim_human_grant,
    prepare_human_grant,
)
from grant_broker import transaction  # noqa: E402
from intent_guardian import (  # noqa: E402
    GuardianSession,
    execute_native_decision,
    load_contract,
    native_decision_context,
    native_decision_description,
    normalize_hook_event,
)
from intent_guardian_parts.policy import evaluate_event  # noqa: E402
from intent_guardian_parts.state import default_contract, write_contract  # noqa: E402
import intent_guardian_parts.audit as guardian_audit  # noqa: E402
import intent_guardian_parts.state as guardian_state  # noqa: E402
from intent_guardian_parts.state import RUNTIME_GENERATION  # noqa: E402
from production_recovery import recovery_pre_state  # noqa: E402
from recovery_lane import RecoveryLane  # noqa: E402


class DecisionKernelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.contract_path = self.root / "intent.json"
        contract = default_contract(
            intent_id="guardian-v3-kernel",
            objective="modify one reviewed file",
            acceptance_criteria=["one native Allow executes once"],
            workspace=self.root,
            mode="enforce",
            allowed_paths=["allowed/**"],
            confirmed_by="human-readable-proposal-approval",
        )
        write_contract(self.contract_path, contract)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def event(self, target: str = "doc://reviewed/resource") -> dict:
        return normalize_hook_event(
            {
                "client": "codex",
                "session_id": "thread-one",
                "cwd": str(self.root),
                "call_id": "call-one",
                "tool_name": "mcp__docs__update_document",
                "tool_input": {"uri": target, "content": "v1"},
            },
            phase="started",
            provider="codex",
        )

    def authorize(self, event: dict) -> tuple[dict, dict]:
        contract = load_contract(self.contract_path)
        denied = evaluate_event(contract, event)
        self.assertEqual(denied.reason_code, "external_effect_not_authorized")
        tx = prepare_human_grant(self.contract_path, contract, event, denied)
        self.assertIsNotNone(tx)
        context = native_decision_context(
            self.contract_path,
            kind="grant",
            decision="allow",
            target="current",
            provider="codex",
            session_id="thread-one",
        )
        description = native_decision_description(context)
        self.assertIn("Allow 仅执行一次；Deny 不执行", description)
        for noisy in ("复制摘要", "另开终端", "外部终端", "copy a digest"):
            self.assertNotIn(noisy, description)
        from decision_kernel import observe_grant_prompt

        observe_grant_prompt(self.contract_path, tx)
        result = execute_native_decision(
            self.contract_path,
            kind="grant",
            decision="allow",
            target=context["target"],
            provider="codex",
            session_id="thread-one",
        )
        self.assertEqual(result["status"], "grant_recorded")
        return tx, result

    def test_native_allow_is_consumed_before_policy_exactly_once(self) -> None:
        event = self.event()
        tx, _result = self.authorize(event)
        contract = load_contract(self.contract_path)

        dispatch = claim_human_grant(self.contract_path, contract, event)
        self.assertIsNotNone(dispatch)
        authorized = dict(event)
        authorized["human_grant_dispatch"] = dispatch
        decision = GuardianSession(
            self.contract_path,
            provider="codex",
            session_id="thread-one",
            hot_path=True,
        ).observe(authorized)

        self.assertEqual(decision.action, "allow", decision.reason)
        self.assertEqual(decision.authority, "human_grant")
        self.assertEqual(decision.reason_code, "human_grant_consumed")
        self.assertIsNone(
            claim_human_grant(
                self.contract_path,
                load_contract(self.contract_path),
                event,
            )
        )
        settled = transaction(self.contract_path, tx["transaction_id"])
        self.assertIsNotNone(settled.get("dispatch_reprobe"))

    def test_undecided_transaction_is_non_authorizing_without_crashing(self) -> None:
        event = self.event()
        contract = load_contract(self.contract_path)
        denied = evaluate_event(contract, event)
        tx = prepare_human_grant(self.contract_path, contract, event, denied)

        self.assertIsNotNone(tx)
        self.assertIsNone(transaction(self.contract_path, tx["transaction_id"])["decision"])
        self.assertIsNone(
            claim_human_grant(
                self.contract_path,
                load_contract(self.contract_path),
                event,
            )
        )

    def test_world_drift_requires_a_fresh_decision(self) -> None:
        event = self.event()
        tx, _result = self.authorize(event)
        contract = load_contract(self.contract_path)
        contract["runtime"]["material_sequence"] += 1
        write_contract(self.contract_path, contract)

        self.assertIsNone(
            claim_human_grant(
                self.contract_path,
                load_contract(self.contract_path),
                event,
            )
        )
        current = transaction(self.contract_path, tx["transaction_id"])
        self.assertEqual(current["settlement"]["status"], "fresh_decision_required")

    def test_immutable_exclusions_do_not_create_questions(self) -> None:
        contract = load_contract(self.contract_path)
        contract["constraints"]["frozen_paths"] = ["reviewed/**"]
        event = normalize_hook_event(
            {
                "client": "codex",
                "session_id": "thread-one",
                "cwd": str(self.root),
                "tool_name": "Write",
                "tool_input": {
                    "file_path": str(self.root / "reviewed/outside.txt"),
                    "content": "v1",
                },
            },
            phase="started",
            provider="codex",
        )
        denied = evaluate_event(contract, event)
        self.assertIsNone(
            prepare_human_grant(self.contract_path, contract, event, denied)
        )

        destructive = normalize_hook_event(
            {
                "client": "codex",
                "session_id": "thread-one",
                "cwd": str(self.root),
                "tool_name": "Bash",
                "tool_input": {"command": "rm -rf reviewed"},
            },
            phase="started",
            provider="codex",
        )
        destructive_denied = evaluate_event(contract, destructive)
        self.assertIsNone(
            prepare_human_grant(
                self.contract_path,
                contract,
                destructive,
                destructive_denied,
            )
        )

    def test_local_source_filename_is_not_mistaken_for_secret_material(self) -> None:
        target = self.root / "scripts" / "mem-secret-scan.py"
        event = normalize_hook_event(
            {
                "client": "codex",
                "session_id": "thread-one",
                "cwd": str(self.root),
                "tool_name": "apply_patch",
                "tool_input": {
                    "patch": (
                        "*** Begin Patch\n"
                        f"*** Update File: {target}\n"
                        "@@\n-old\n+new\n*** End Patch"
                    )
                },
            },
            phase="started",
            provider="codex",
        )
        self.assertIn(str(target), event["write_targets"])
        self.assertNotIn("[redacted-sensitive-target]", event["write_targets"])
        self.assertFalse(event["sensitive_input"])

    def test_read_hot_path_never_constructs_legacy_session(self) -> None:
        payload = {
            "client": "codex",
            "session_id": "thread-read",
            "cwd": str(self.root),
            "intent_contract": str(self.contract_path),
            "tool_name": "Read",
            "tool_input": {"file_path": str(self.root / "allowed/input.txt")},
        }
        with mock.patch.object(
            guardian_audit,
            "GuardianSession",
            side_effect=AssertionError("legacy session entered read hot path"),
        ):
            decision, selected = guardian_audit.process_hook(
                payload,
                phase="started",
                provider="codex",
            )
        self.assertEqual(selected, self.contract_path)
        self.assertEqual(decision.reason_code, "read_hot_path")
        self.assertEqual(decision.action, "allow")

    def test_git_passthrough_never_resolves_session_mapping(self) -> None:
        for command in (
            "git status --short",
            "git status && git diff --stat",
            "git worktree add .worktrees/task task/one",
            "git branch -D merged-task",
        ):
            with self.subTest(command=command), mock.patch.object(
                guardian_audit,
                "resolve_contract_path",
                side_effect=guardian_state.IntentGuardianError(
                    "session workspace mapping target is unavailable"
                ),
            ) as resolver:
                decision, selected = guardian_audit.process_hook(
                    {
                        "client": "codex",
                        "session_id": "thread-stale-mapping",
                        "cwd": str(self.root),
                        "tool_name": "Bash",
                        "tool_input": {"command": command},
                    },
                    phase="started",
                    provider="codex",
                )
            resolver.assert_not_called()
            self.assertIsNone(selected)
            self.assertEqual(decision.action, "allow")
            self.assertEqual(decision.reason_code, "git_execution_passthrough")

    def test_read_diagnosis_survives_unavailable_session_mapping(self) -> None:
        with mock.patch.object(
            guardian_audit,
            "resolve_contract_path",
            side_effect=guardian_state.IntentGuardianError(
                "session workspace mapping target is unavailable"
            ),
        ):
            decision, selected = guardian_audit.process_hook(
                {
                    "client": "codex",
                    "session_id": "thread-stale-mapping",
                    "cwd": str(self.root),
                    "tool_name": "Read",
                    "tool_input": {"file_path": str(self.root / "input.txt")},
                },
                phase="started",
                provider="codex",
            )
        self.assertIsNone(selected)
        self.assertEqual(decision.action, "allow")
        self.assertEqual(decision.reason_code, "read_diagnostic_fallback")

    def test_trusted_control_does_not_enter_human_grant_composition(self) -> None:
        skill_path = ROOT / "skills" / "intent-guardian" / "SKILL.md"
        payload = {
            "client": "codex",
            "session_id": "thread-control",
            "cwd": str(self.root),
            "intent_contract": str(self.contract_path),
            "tool_name": "Bash",
            "tool_input": {
                "command": (
                    f"{sys.executable} {ROOT / 'scripts/kb/intent-guardian.py'} "
                    f"skill-start sulde:intent-guardian --skill-path {skill_path} "
                    f"--contract {self.contract_path} --provider codex "
                    "--session-id thread-control"
                )
            },
        }
        with (
            mock.patch.object(
                guardian_audit,
                "claim_human_grant",
                side_effect=AssertionError("control command claimed a human grant"),
            ),
            mock.patch.object(
                guardian_audit,
                "prepare_human_grant",
                side_effect=AssertionError("control command prepared a human grant"),
            ),
        ):
            decision, selected = guardian_audit.process_hook(
                payload,
                phase="started",
                provider="codex",
            )
        self.assertEqual(selected, self.contract_path)
        self.assertEqual(decision.action, "allow", decision.reason)

    def test_read_hot_path_internal_p95_is_below_budget(self) -> None:
        samples: list[float] = []
        for index in range(40):
            payload = {
                "client": "codex",
                "session_id": "thread-read",
                "cwd": str(self.root),
                "intent_contract": str(self.contract_path),
                "call_id": f"read-{index}",
                "tool_name": "Read",
                "tool_input": {"file_path": str(self.root / "allowed/input.txt")},
            }
            started = time.perf_counter()
            decision, _selected = guardian_audit.process_hook(
                payload,
                phase="started",
                provider="codex",
            )
            samples.append((time.perf_counter() - started) * 1000)
            self.assertEqual(decision.action, "allow")
        p95 = sorted(samples)[int(len(samples) * 0.95) - 1]
        self.assertLess(p95, 50.0, samples)

    def test_read_hot_path_telemetry_never_fsyncs_or_takes_a_ledger_lock(self) -> None:
        payload = {
            "client": "codex",
            "session_id": "thread-read",
            "cwd": str(self.root),
            "intent_contract": str(self.contract_path),
            "call_id": "read-no-fsync",
            "tool_name": "Read",
            "tool_input": {"file_path": str(self.root / "allowed/input.txt")},
        }
        with (
            mock.patch.object(
                guardian_state.os,
                "fsync",
                side_effect=AssertionError("read observation forced durable I/O"),
            ),
            mock.patch.object(
                guardian_state,
                "_exclusive_path_lock",
                side_effect=AssertionError("read observation took a durable ledger lock"),
            ),
        ):
            decision, _selected = guardian_audit.process_hook(
                payload,
                phase="started",
                provider="codex",
            )
        self.assertEqual(decision.action, "allow")
        hot_path = self.contract_path.with_name(f".{self.contract_path.stem}.hot-path.jsonl")
        self.assertIn(
            "sulde-guardian-hot-path-observation-v1",
            hot_path.read_text(encoding="utf-8"),
        )

    def test_material_audit_append_remains_fsync_durable(self) -> None:
        target = self.root / "material.jsonl"
        with mock.patch.object(guardian_state.os, "fsync") as fsync:
            guardian_state._append_jsonl(target, {"material": True})
        fsync.assert_called_once()

    def test_unbound_recovery_dictionary_cannot_authorize_shell_even_with_broken_contract(self) -> None:
        self.contract_path.write_text("{broken\n", encoding="utf-8")
        key = self.root / "recovery.key"
        key.write_bytes(b"k" * 32)
        key.chmod(0o600)
        state = self.root / "recovery.jsonl"
        lane = RecoveryLane(
            str(state),
            seal_key=b"k" * 32,
            wall_clock=time.time,
            monotonic_clock=time.monotonic,
        )
        capability = lane.issue_capability(
            provider="codex",
            session_id="thread-recovery",
            workspace=str(self.root),
            installed_generation=RUNTIME_GENERATION,
            action="status",
            target_identity="guardian-status",
            expected_pre_state=recovery_pre_state(self.contract_path),
            expires_at=time.time() + 60,
            verifier_identity="sha256:" + "a" * 64,
            nonce="status-on-broken-contract",
        )
        payload = {
            "client": "codex",
            "session_id": "thread-recovery",
            "cwd": str(self.root),
            "intent_contract": str(self.contract_path),
            "tool_name": "Bash",
            "tool_input": {
                "command": "sulde recovery status",
                "sulde_recovery_request": lane.request(capability),
            },
        }
        environment = {
            "SULDE_RECOVERY_KEY_FILE": str(key),
            "SULDE_RECOVERY_STATE_FILE": str(state),
            "SULDE_RUNTIME_GENERATION": RUNTIME_GENERATION,
        }
        with mock.patch.dict(__import__("os").environ, environment, clear=False), mock.patch.object(
            guardian_audit,
            "GuardianSession",
            side_effect=AssertionError("ordinary Guardian entered recovery lane"),
        ), mock.patch.object(
            guardian_audit,
            "resolve_contract_path",
            side_effect=guardian_state.IntentGuardianError(
                "session workspace mapping target is unavailable"
            ),
        ) as resolver:
            decision, _selected = guardian_audit.process_hook(
                payload,
                phase="started",
                provider="codex",
            )
        resolver.assert_not_called()
        self.assertEqual(decision.action, "deny", decision.reason)
        self.assertEqual(decision.reason_code, "recovery_command_unbound")

        forged = dict(payload)
        forged["session_id"] = "foreign-session"
        with mock.patch.dict(__import__("os").environ, environment, clear=False), mock.patch.object(
            guardian_audit,
            "GuardianSession",
            side_effect=AssertionError("ordinary Guardian entered forged recovery lane"),
        ):
            denied, _selected = guardian_audit.process_hook(
                forged,
                phase="started",
                provider="codex",
            )
        self.assertEqual(denied.action, "deny")
        self.assertFalse(denied.pause)
        lane.state.close()

    def test_exact_native_doctor_is_reachable_without_hidden_tool_fields(self) -> None:
        self.contract_path.write_text("{broken\n", encoding="utf-8")
        key = self.root / "recovery.key"
        key.write_bytes(b"k" * 32)
        key.chmod(0o600)
        state = self.root / "recovery.jsonl"
        launcher = self.root / "bin" / "intent-guardian"
        payload = {
            "client": "codex",
            "session_id": "thread-recovery-doctor",
            "cwd": str(self.root),
            "intent_contract": str(self.contract_path),
            "tool_name": "Bash",
            "tool_input": {
                "command": (
                    f"{launcher} doctor --workspace task-worktree "
                    "--provider codex --session-id thread-recovery-doctor"
                ),
            },
        }
        environment = {
            "SULDE_HOME": str(self.root),
            "SULDE_RECOVERY_KEY_FILE": str(key),
            "SULDE_RECOVERY_STATE_FILE": str(state),
            "SULDE_RUNTIME_GENERATION": RUNTIME_GENERATION,
        }
        with mock.patch.dict(__import__("os").environ, environment, clear=False), mock.patch.object(
            guardian_audit,
            "GuardianSession",
            side_effect=AssertionError("ordinary Guardian entered recovery lane"),
        ):
            decision, _selected = guardian_audit.process_hook(
                payload,
                phase="started",
                provider="codex",
            )
        self.assertEqual(decision.action, "allow", decision.reason)
        self.assertEqual(decision.reason_code, "recovery_lane_allowed")
        self.assertEqual(decision.decision_stage, "recovery")


if __name__ == "__main__":
    unittest.main()
