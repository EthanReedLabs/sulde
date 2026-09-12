from __future__ import annotations

from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "kb"))

from host_capabilities import (  # noqa: E402
    HostCapabilityError,
    capability_specs,
    hook_failure_path,
    hook_failure_projection,
    issue_host_provenance,
    observation_path,
    provision_provenance_key,
    readiness_projection,
    record_hook_observation,
    record_hook_failure,
    record_observation,
    validate_artifact,
    workspace_identifier,
)


class HostCapabilityContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def artifact(self, provider: str) -> Path:
        artifact = self.root / provider
        if provider == "claude":
            descriptor = artifact / ".claude-plugin" / "plugin.json"
            hooks = artifact / "hooks" / "hooks.json"
            descriptor.parent.mkdir(parents=True)
            hooks.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / ".claude-plugin" / "plugin.json", descriptor)
            shutil.copy2(ROOT / "hooks" / "hooks.json", hooks)
            contract_runtime = artifact / "scripts" / "kb" / "host_capabilities.py"
        else:
            descriptor = artifact / ".codex-plugin" / "plugin.json"
            hooks = artifact / "hooks" / "hooks.json"
            descriptor.parent.mkdir(parents=True)
            hooks.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(
                ROOT
                / "integrations"
                / "codex"
                / "plugins"
                / "sulde"
                / ".codex-plugin"
                / "plugin.json",
                descriptor,
            )
            shutil.copy2(
                ROOT
                / "integrations"
                / "codex"
                / "plugins"
                / "sulde"
                / "hooks.posix.json",
                hooks,
            )
            contract_runtime = (
                artifact / "runtime" / "scripts" / "kb" / "host_capabilities.py"
            )
        contract_runtime.parent.mkdir(parents=True, exist_ok=True)
        contract_runtime.write_text("# fixture\n", encoding="utf-8")
        for spec in capability_specs(provider):
            for relative in spec.entrypoints:
                path = artifact / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
        return artifact

    def record_live(
        self,
        home: Path,
        *,
        hook_event: str,
        session_id: str,
        workspace: Path,
        now: datetime | None = None,
        call_id: str = "",
        runtime_sha256: str | None = None,
        loaded_module_generation: str = "",
        artifact_generation: str = "",
    ) -> dict:
        def record() -> dict:
            provision_provenance_key(home)
            proof = issue_host_provenance(
                provider="codex",
                hook_event=hook_event,
                session_id=session_id,
                workspace=workspace,
                call_id=call_id,
                loaded_module_generation=loaded_module_generation,
                artifact_generation=artifact_generation,
                home=home,
                now=now,
            )
            return record_observation(
                provider="codex",
                hook_event=hook_event,
                session_id=session_id,
                workspace=workspace,
                call_id=call_id,
                source="live_host_hook",
                provenance=proof,
                home=home,
                now=now,
            )

        if runtime_sha256 is None:
            return record()
        with mock.patch(
            "host_capabilities.runtime_identity", return_value=runtime_sha256
        ):
            return record()

    def test_both_artifacts_share_one_complete_contract(self) -> None:
        for provider in ("claude", "codex"):
            with self.subTest(provider=provider):
                evidence = validate_artifact(self.artifact(provider), provider=provider)
                self.assertEqual(evidence["status"], "artifact_ready")
                expected = {
                    "session_context",
                    "prompt_control",
                    "tool_guard",
                    "tool_result",
                    "turn_reconcile",
                    "mcp_initialize",
                }
                if provider == "codex":
                    expected.add("host_approval")
                self.assertEqual(set(evidence["capabilities"]), expected)
                self.assertTrue(all(
                    row["packaged"] and row["declared"]
                    for row in evidence["capabilities"].values()
                ))

    def test_rejects_double_registration_and_missing_lifecycle_hook(self) -> None:
        artifact = self.artifact("codex")
        descriptor_path = artifact / ".codex-plugin" / "plugin.json"
        descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
        descriptor["hooks"] = "./hooks/hooks.json"
        descriptor_path.write_text(json.dumps(descriptor), encoding="utf-8")
        with self.assertRaisesRegex(HostCapabilityError, "must not explicitly register"):
            validate_artifact(artifact, provider="codex")

        descriptor.pop("hooks")
        descriptor_path.write_text(json.dumps(descriptor), encoding="utf-8")
        hooks_path = artifact / "hooks" / "hooks.json"
        hooks = json.loads(hooks_path.read_text(encoding="utf-8"))
        hooks["hooks"].pop("UserPromptSubmit")
        hooks_path.write_text(json.dumps(hooks), encoding="utf-8")
        with self.assertRaisesRegex(HostCapabilityError, "UserPromptSubmit"):
            validate_artifact(artifact, provider="codex")

    def test_live_and_synthetic_readiness_are_session_scoped_and_redacted(self) -> None:
        home = self.root / "kb"
        workspace = self.root / "private-project-name"
        workspace.mkdir()
        for hook_event in ("SessionStart", "UserPromptSubmit"):
            record_observation(
                provider="codex",
                hook_event=hook_event,
                session_id="synthetic-session",
                workspace=workspace,
                source="synthetic_smoke",
                home=home,
            )
        record_observation(
            provider="codex",
            hook_event="MCPInitialize",
            source="synthetic_smoke",
            home=home,
        )

        synthetic = readiness_projection(
            home,
            provider="codex",
            session_id="synthetic-session",
            workspace=workspace,
        )
        self.assertEqual(synthetic["status"], "synthetic_only")
        self.assertEqual(synthetic["interactive_status"], "synthetic_only")
        self.assertEqual(
            synthetic["capabilities"]["mcp_initialize"]["status"],
            "synthetic_only",
        )

        for hook_event in ("SessionStart", "UserPromptSubmit"):
            self.record_live(
                home,
                hook_event=hook_event,
                session_id="live-session",
                workspace=workspace,
            )
        live = readiness_projection(
            home,
            provider="codex",
            session_id="live-session",
            workspace=workspace,
        )
        wrong_session = readiness_projection(
            home,
            provider="codex",
            session_id="other-session",
            workspace=workspace,
        )
        self.assertEqual(live["status"], "interactive_ready")
        self.assertEqual(live["interactive_status"], "live_verified")
        self.assertEqual(
            live["telemetry_authority"],
            "integrity_only_not_permission_authority",
        )
        self.assertEqual(wrong_session["interactive_status"], "unobserved")
        self.assertNotIn(
            str(workspace),
            observation_path(home).read_text(encoding="utf-8"),
        )

    def test_observation_from_previous_runtime_cannot_prove_current_readiness(self) -> None:
        home = self.root / "kb-stale"
        workspace = self.root / "stale-project"
        workspace.mkdir()
        for hook_event in ("SessionStart", "UserPromptSubmit"):
            self.record_live(
                home,
                hook_event=hook_event,
                session_id="same-native-session",
                workspace=workspace,
            )

        projection = readiness_projection(
            home,
            provider="codex",
            session_id="same-native-session",
            workspace=workspace,
            expected_runtime_sha256="0" * 64,
        )

        self.assertEqual(projection["status"], "unobserved")
        self.assertEqual(projection["stale_runtime_rows"], 2)

    def test_hot_rebind_carries_active_turn_context_after_exact_roundtrip(self) -> None:
        home = self.root / "kb-hot-rebind"
        workspace = self.root / "hot-rebind-project"
        workspace.mkdir()
        previous_runtime = "1" * 64
        current_runtime = "2" * 64
        started = datetime(2026, 8, 17, 1, 0, tzinfo=timezone.utc)
        self.record_live(
            home,
            hook_event="SessionStart",
            session_id="hot-session",
            workspace=workspace,
            now=started,
            runtime_sha256=previous_runtime,
        )
        self.record_live(
            home,
            hook_event="UserPromptSubmit",
            session_id="hot-session",
            workspace=workspace,
            now=started + timedelta(minutes=1),
            runtime_sha256=previous_runtime,
        )
        for event, offset in (("PreToolUse", 0), ("PostToolUse", 1)):
            self.record_live(
                home,
                hook_event=event,
                session_id="hot-session",
                workspace=workspace,
                call_id="call-after-upgrade",
                now=started + timedelta(hours=2, seconds=offset),
                runtime_sha256=current_runtime,
            )

        projection = readiness_projection(
            home,
            provider="codex",
            session_id="hot-session",
            workspace=workspace,
            expected_runtime_sha256=current_runtime,
            now=started + timedelta(hours=2, minutes=1),
        )

        self.assertEqual(projection["status"], "interactive_ready")
        self.assertEqual(projection["supervision_status"], "live_verified")
        self.assertEqual(projection["runtime_continuity"]["status"], "verified")
        self.assertEqual(
            projection["runtime_continuity"]["carried_capabilities"],
            ["prompt_control", "session_context"],
        )
        self.assertEqual(
            projection["runtime_continuity"]["active_turn_capabilities"],
            ["prompt_control"],
        )
        self.assertEqual(
            projection["capabilities"]["session_context"]["runtime_binding"],
            "verified_hot_rebind",
        )

    def test_tool_roundtrip_requires_same_loaded_and_artifact_generation(self) -> None:
        home = self.root / "kb-dual-generation"
        workspace = self.root / "dual-generation-project"
        workspace.mkdir()
        started = datetime(2026, 9, 6, 1, 0, tzinfo=timezone.utc)
        previous_runtime = "1" * 64
        current_runtime = "2" * 64
        for event, offset in (("SessionStart", 0), ("UserPromptSubmit", 1)):
            self.record_live(
                home,
                hook_event=event,
                session_id="dual-generation-session",
                workspace=workspace,
                now=started + timedelta(seconds=offset),
                runtime_sha256=previous_runtime,
            )
        self.record_live(
            home,
            hook_event="PreToolUse",
            session_id="dual-generation-session",
            workspace=workspace,
            call_id="dual-generation-call",
            now=started + timedelta(minutes=1),
            runtime_sha256=current_runtime,
            loaded_module_generation="loaded-a",
            artifact_generation="artifact-a",
        )
        self.record_live(
            home,
            hook_event="PostToolUse",
            session_id="dual-generation-session",
            workspace=workspace,
            call_id="dual-generation-call",
            now=started + timedelta(minutes=1, seconds=1),
            runtime_sha256=current_runtime,
            loaded_module_generation="loaded-a",
            artifact_generation="artifact-b",
        )

        mismatched = readiness_projection(
            home,
            provider="codex",
            session_id="dual-generation-session",
            workspace=workspace,
            expected_runtime_sha256=current_runtime,
            now=started + timedelta(minutes=2),
        )
        self.assertEqual(
            mismatched["runtime_continuity"]["status"], "unverified"
        )

        self.record_live(
            home,
            hook_event="PostToolUse",
            session_id="dual-generation-session",
            workspace=workspace,
            call_id="dual-generation-call",
            now=started + timedelta(minutes=1, seconds=2),
            runtime_sha256=current_runtime,
            loaded_module_generation="loaded-a",
            artifact_generation="artifact-a",
        )
        matched = readiness_projection(
            home,
            provider="codex",
            session_id="dual-generation-session",
            workspace=workspace,
            expected_runtime_sha256=current_runtime,
            now=started + timedelta(minutes=2),
        )
        self.assertEqual(matched["runtime_continuity"]["status"], "verified")

    def test_hook_failure_receipts_are_idempotent_redacted_and_non_authorizing(self) -> None:
        home = self.root / "kb-hook-failure"
        workspace = self.root / "private-workspace-name"
        workspace.mkdir()
        at = datetime(2026, 9, 6, 2, 0, tzinfo=timezone.utc)
        arguments = {
            "provider": "codex",
            "hook_event": "PostToolUse",
            "stage": "runtime",
            "error_kind": "RuntimeError",
            "session_id": "failure-session",
            "workspace": workspace,
            "call_id": "private-native-call-id",
            "exit_code": 1,
            "loaded_module_generation": "loaded-generation",
            "artifact_generation": "artifact-generation",
            "home": home,
            "now": at,
        }
        self.record_live(
            home,
            hook_event="PostToolUse",
            session_id="failure-session",
            workspace=workspace,
            call_id="private-native-call-id",
            now=at - timedelta(seconds=1),
            loaded_module_generation="loaded-generation",
            artifact_generation="artifact-generation",
        )
        first = record_hook_failure(**arguments)
        second = record_hook_failure(**arguments)

        self.assertEqual(first["failure_id"], second["failure_id"])
        receipts = list(hook_failure_path(home).glob("*.json"))
        self.assertEqual(len(receipts), 1)
        encoded = receipts[0].read_text(encoding="utf-8")
        self.assertNotIn(str(workspace), encoded)
        self.assertNotIn("private-native-call-id", encoded)
        self.assertEqual(first["effect_claim"], "none")
        projection = hook_failure_projection(
            home,
            provider="codex",
            session_id="failure-session",
            workspace=workspace,
        )
        self.assertEqual(projection["status"], "observed")
        self.assertEqual(projection["current_lane_total"], 1)
        self.assertEqual(
            projection["current_lane"][0]["effect_outcome"], "inconclusive"
        )
        self.assertEqual(
            projection["current_lane"][0]["status"], "inconclusive"
        )

        self.record_live(
            home,
            hook_event="PostToolUse",
            session_id="failure-session",
            workspace=workspace,
            call_id="private-native-call-id",
            now=at + timedelta(seconds=61),
            loaded_module_generation="loaded-generation",
            artifact_generation="artifact-generation",
        )
        recovered = hook_failure_projection(
            home,
            provider="codex",
            session_id="failure-session",
            workspace=workspace,
        )
        self.assertEqual(
            recovered["current_lane"][0]["status"], "callback_recovered"
        )
        self.assertEqual(
            recovered["current_lane"][0]["effect_outcome"], "inconclusive"
        )

    def test_hook_observation_prefers_signed_session_workspace_over_launch_cwd(self) -> None:
        home = self.root / "kb-session-workspace"
        launch_workspace = self.root / "launch-workspace"
        lane_workspace = self.root / "task-worktree"
        launch_workspace.mkdir()
        lane_workspace.mkdir()
        at = datetime.now(timezone.utc)
        provision_provenance_key(home)
        proof = issue_host_provenance(
            provider="codex",
            hook_event="PreToolUse",
            session_id="mapped-session",
            workspace=lane_workspace,
            call_id="mapped-call",
            loaded_module_generation="loaded-mapped",
            artifact_generation="artifact-mapped",
            home=home,
            now=at,
        )

        observed = record_hook_observation(
            {
                "session_id": "mapped-session",
                "cwd": str(launch_workspace),
                "sulde_workspace_root": str(lane_workspace),
                "call_id": "mapped-call",
                "sulde_observation_source": "live_host_hook",
                "sulde_host_provenance": proof,
            },
            provider="codex",
            hook_event="PreToolUse",
            home=home,
        )

        self.assertTrue(observed)
        row = json.loads(
            observation_path(home).read_text(encoding="utf-8").splitlines()[-1]
        )
        self.assertEqual(
            row["workspace_id"],
            workspace_identifier(lane_workspace),
        )

    def test_concurrent_hook_failure_receipts_use_one_atomic_identity(self) -> None:
        home = self.root / "kb-hook-failure-race"
        workspace = self.root / "race-workspace"
        workspace.mkdir()
        at = datetime(2026, 9, 6, 3, 0, tzinfo=timezone.utc)

        def record(_index: int) -> dict:
            return record_hook_failure(
                provider="codex",
                hook_event="PostToolUse",
                stage="adapter",
                error_kind="nonzero_exit",
                session_id="race-session",
                workspace=workspace,
                call_id="race-call",
                exit_code=1,
                loaded_module_generation="loaded-race",
                artifact_generation="artifact-race",
                home=home,
                now=at,
            )

        with ThreadPoolExecutor(max_workers=8) as executor:
            rows = list(executor.map(record, range(32)))
        self.assertEqual(len({row["failure_id"] for row in rows}), 1)
        receipts = list(hook_failure_path(home).glob("*.json"))
        self.assertEqual(len(receipts), 1)

        receipts[0].write_text("{}\n", encoding="utf-8")
        projection = hook_failure_projection(
            home,
            provider="codex",
            session_id="race-session",
            workspace=workspace,
        )
        self.assertEqual(projection["status"], "invalid")
        self.assertEqual(projection["invalid_receipts"], 1)
        self.assertEqual(projection["current_lane_total"], 0)

    def test_hot_rebind_rejects_mismatched_calls_and_a_reconciled_turn(self) -> None:
        started = datetime(2026, 8, 17, 1, 0, tzinfo=timezone.utc)
        previous_runtime = "3" * 64
        current_runtime = "4" * 64
        for case, post_call, include_stop, post_offset in (
            ("mismatched-call", "call-b", False, 1),
            ("same-timestamp", "call-a", False, 0),
            ("turn-already-stopped", "call-a", True, 1),
        ):
            with self.subTest(case=case):
                home = self.root / f"kb-{case}"
                workspace = self.root / f"workspace-{case}"
                workspace.mkdir()
                for event, offset in (("SessionStart", 0), ("UserPromptSubmit", 1)):
                    self.record_live(
                        home,
                        hook_event=event,
                        session_id="hot-session",
                        workspace=workspace,
                        now=started + timedelta(minutes=offset),
                        runtime_sha256=previous_runtime,
                    )
                if include_stop:
                    self.record_live(
                        home,
                        hook_event="Stop",
                        session_id="hot-session",
                        workspace=workspace,
                        now=started + timedelta(minutes=2),
                        runtime_sha256=previous_runtime,
                    )
                self.record_live(
                    home,
                    hook_event="PreToolUse",
                    session_id="hot-session",
                    workspace=workspace,
                    call_id="call-a",
                    now=(
                        started + timedelta(minutes=5)
                        if include_stop
                        else started + timedelta(hours=2)
                    ),
                    runtime_sha256=current_runtime,
                )
                self.record_live(
                    home,
                    hook_event="PostToolUse",
                    session_id="hot-session",
                    workspace=workspace,
                    call_id=post_call,
                    now=(
                        started + timedelta(minutes=5, seconds=post_offset)
                        if include_stop
                        else started + timedelta(hours=2, seconds=post_offset)
                    ),
                    runtime_sha256=current_runtime,
                )
                projection = readiness_projection(
                    home,
                    provider="codex",
                    session_id="hot-session",
                    workspace=workspace,
                    expected_runtime_sha256=current_runtime,
                    now=(
                        started + timedelta(minutes=6)
                        if include_stop
                        else started + timedelta(hours=2, minutes=1)
                    ),
                )
                self.assertNotEqual(projection["status"], "interactive_ready")
                if case in {"mismatched-call", "same-timestamp"}:
                    self.assertEqual(
                        projection["runtime_continuity"]["status"], "unverified"
                    )
                else:
                    self.assertEqual(
                        projection["capabilities"]["prompt_control"]["status"],
                        "unobserved",
                    )

    def test_hot_rebind_never_carries_permission_request_authority(self) -> None:
        home = self.root / "kb-hot-approval"
        workspace = self.root / "hot-approval-project"
        workspace.mkdir()
        previous_runtime = "5" * 64
        current_runtime = "6" * 64
        started = datetime(2026, 8, 17, 1, 0, tzinfo=timezone.utc)
        for event in ("SessionStart", "UserPromptSubmit", "PermissionRequest"):
            self.record_live(
                home,
                hook_event=event,
                session_id="hot-session",
                workspace=workspace,
                now=started,
                runtime_sha256=previous_runtime,
            )
        for event, offset in (("PreToolUse", 0), ("PostToolUse", 1)):
            self.record_live(
                home,
                hook_event=event,
                session_id="hot-session",
                workspace=workspace,
                call_id="current-call",
                now=started + timedelta(minutes=1, seconds=offset),
                runtime_sha256=current_runtime,
            )

        projection = readiness_projection(
            home,
            provider="codex",
            session_id="hot-session",
            workspace=workspace,
            expected_runtime_sha256=current_runtime,
            approval_required=True,
            now=started + timedelta(minutes=2),
        )

        self.assertEqual(projection["interactive_status"], "partial")
        self.assertEqual(projection["approval_status"], "unobserved")
        self.assertNotIn(
            "host_approval", projection["runtime_continuity"]["carried_capabilities"]
        )

    def test_hot_rebind_scope_time_and_independent_predecessor_boundaries(self) -> None:
        started = datetime(2026, 8, 17, 1, 0, tzinfo=timezone.utc)
        current_runtime = "9" * 64
        cases = (
            {
                "name": "split-predecessor",
                "session_runtime": "a" * 64,
                "prompt_runtime": "b" * 64,
                "pre_at": started + timedelta(hours=1),
                "post_at": started + timedelta(hours=1, seconds=1),
                "project_at": started + timedelta(hours=1, minutes=1),
                "wrong_workspace": False,
                "roundtrip": "verified",
            },
            {
                "name": "wrong-workspace",
                "session_runtime": "a" * 64,
                "prompt_runtime": "a" * 64,
                "pre_at": started + timedelta(hours=1),
                "post_at": started + timedelta(hours=1, seconds=1),
                "project_at": started + timedelta(hours=1, minutes=1),
                "wrong_workspace": True,
                "roundtrip": "verified",
            },
            {
                "name": "roundtrip-too-long",
                "session_runtime": "a" * 64,
                "prompt_runtime": "a" * 64,
                "pre_at": started + timedelta(hours=1),
                "post_at": started + timedelta(hours=1, minutes=16),
                "project_at": started + timedelta(hours=1, minutes=17),
                "wrong_workspace": False,
                "roundtrip": "unverified",
            },
            {
                "name": "future-roundtrip",
                "session_runtime": "a" * 64,
                "prompt_runtime": "a" * 64,
                "pre_at": started + timedelta(hours=2),
                "post_at": started + timedelta(hours=2, seconds=1),
                "project_at": started + timedelta(hours=1),
                "wrong_workspace": False,
                "roundtrip": "unverified",
            },
        )
        for case in cases:
            with self.subTest(case=case["name"]):
                home = self.root / f"kb-boundary-{case['name']}"
                workspace = self.root / f"workspace-boundary-{case['name']}"
                other_workspace = self.root / f"other-boundary-{case['name']}"
                workspace.mkdir()
                other_workspace.mkdir()
                context_workspace = (
                    other_workspace if case["wrong_workspace"] else workspace
                )
                self.record_live(
                    home,
                    hook_event="SessionStart",
                    session_id="hot-session",
                    workspace=context_workspace,
                    now=started,
                    runtime_sha256=case["session_runtime"],
                )
                self.record_live(
                    home,
                    hook_event="UserPromptSubmit",
                    session_id="hot-session",
                    workspace=context_workspace,
                    now=started + timedelta(minutes=1),
                    runtime_sha256=case["prompt_runtime"],
                )
                self.record_live(
                    home,
                    hook_event="PreToolUse",
                    session_id="hot-session",
                    workspace=workspace,
                    call_id="boundary-call",
                    now=case["pre_at"],
                    runtime_sha256=current_runtime,
                )
                self.record_live(
                    home,
                    hook_event="PostToolUse",
                    session_id="hot-session",
                    workspace=workspace,
                    call_id="boundary-call",
                    now=case["post_at"],
                    runtime_sha256=current_runtime,
                )
                projection = readiness_projection(
                    home,
                    provider="codex",
                    session_id="hot-session",
                    workspace=workspace,
                    expected_runtime_sha256=current_runtime,
                    now=case["project_at"],
                )

                if case["name"] == "split-predecessor":
                    # R5: independently signed lifecycle facts need not have
                    # been observed by the same historical module generation.
                    self.assertEqual(projection["status"], "interactive_ready")
                    for capability, runtime in (("session_context", case["session_runtime"]),
                                                ("prompt_control", case["prompt_runtime"])):
                        self.assertEqual(projection["capabilities"][capability]["carried_from_runtime_sha256"], runtime)
                    self.assertNotIn("host_approval", projection["runtime_continuity"]["carried_capabilities"])
                else:
                    self.assertNotEqual(projection["status"], "interactive_ready")
                self.assertEqual(
                    projection["runtime_continuity"]["status"], case["roundtrip"]
                )

    def test_repeated_tool_hook_is_deduplicated_from_readiness_journal(self) -> None:
        home = self.root / "kb-deduplicated"
        workspace = self.root / "deduplicated-project"
        workspace.mkdir()
        for _ in range(5):
            self.record_live(
                home,
                hook_event="PreToolUse",
                session_id="one-session",
                workspace=workspace,
            )

        rows = observation_path(home).read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(rows), 1)

    def test_live_label_without_host_signature_is_non_authorizing(self) -> None:
        home = self.root / "kb-forged"
        workspace = self.root / "forged-project"
        workspace.mkdir()
        accepted = record_hook_observation(
            {
                "session_id": "forged-session",
                "cwd": str(workspace),
                "sulde_observation_source": "live_host_hook",
            },
            provider="codex",
            hook_event="UserPromptSubmit",
            home=home,
        )
        projection = readiness_projection(
            home,
            provider="codex",
            session_id="forged-session",
            workspace=workspace,
        )
        row = json.loads(observation_path(home).read_text(encoding="utf-8"))
        self.assertFalse(accepted)
        self.assertEqual(row["source"], "unclassified")
        self.assertEqual(projection["interactive_status"], "unobserved")

    def test_permission_request_is_a_conditional_codex_interactive_gate(self) -> None:
        home = self.root / "kb-approval"
        workspace = self.root / "approval-project"
        workspace.mkdir()
        for event in ("SessionStart", "UserPromptSubmit"):
            self.record_live(
                home,
                hook_event=event,
                session_id="approval-session",
                workspace=workspace,
            )
        ordinary = readiness_projection(
            home,
            provider="codex",
            session_id="approval-session",
            workspace=workspace,
        )
        pending = readiness_projection(
            home,
            provider="codex",
            session_id="approval-session",
            workspace=workspace,
            approval_required=True,
        )
        self.assertEqual(ordinary["status"], "interactive_ready")
        self.assertEqual(pending["status"], "interactive_partial")
        self.assertEqual(pending["approval_status"], "unobserved")

        self.record_live(
            home,
            hook_event="PermissionRequest",
            session_id="approval-session",
            workspace=workspace,
        )
        approved_surface = readiness_projection(
            home,
            provider="codex",
            session_id="approval-session",
            workspace=workspace,
            approval_required=True,
        )
        self.assertEqual(approved_surface["status"], "interactive_ready")
        self.assertEqual(approved_surface["approval_status"], "live_verified")

    def test_repeated_observation_refreshes_before_freshness_expires(self) -> None:
        home = self.root / "kb-refresh"
        workspace = self.root / "refresh-project"
        workspace.mkdir()
        started = datetime(2026, 8, 17, 1, 0, tzinfo=timezone.utc)
        self.record_live(
            home,
            hook_event="UserPromptSubmit",
            session_id="refresh-session",
            workspace=workspace,
            now=started,
        )
        self.record_live(
            home,
            hook_event="UserPromptSubmit",
            session_id="refresh-session",
            workspace=workspace,
            now=started + timedelta(seconds=61),
        )
        rows = observation_path(home).read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(rows), 2)
        fresh = readiness_projection(
            home,
            provider="codex",
            session_id="refresh-session",
            workspace=workspace,
            now=started + timedelta(minutes=30),
        )
        stale = readiness_projection(
            home,
            provider="codex",
            session_id="refresh-session",
            workspace=workspace,
            now=started + timedelta(minutes=31, seconds=2),
        )
        self.assertEqual(fresh["capabilities"]["prompt_control"]["status"], "live_verified")
        self.assertEqual(stale["capabilities"]["prompt_control"]["status"], "unobserved")
        self.assertEqual(stale["capabilities"]["prompt_control"]["stale_observations"], 2)

    def test_session_start_is_lineage_while_prompt_remains_activity_freshness(self) -> None:
        home = self.root / "kb-long-session"
        workspace = self.root / "long-session-project"
        workspace.mkdir()
        started = datetime(2026, 8, 17, 1, 0, tzinfo=timezone.utc)
        self.record_live(
            home,
            hook_event="SessionStart",
            session_id="long-session",
            workspace=workspace,
            now=started,
        )
        self.record_live(
            home,
            hook_event="UserPromptSubmit",
            session_id="long-session",
            workspace=workspace,
            now=started + timedelta(hours=3),
        )
        active = readiness_projection(
            home,
            provider="codex",
            session_id="long-session",
            workspace=workspace,
            now=started + timedelta(hours=3, minutes=1),
        )
        idle = readiness_projection(
            home,
            provider="codex",
            session_id="long-session",
            workspace=workspace,
            now=started + timedelta(hours=4),
        )
        self.assertEqual(active["status"], "interactive_ready")
        self.assertEqual(
            active["capabilities"]["session_context"]["freshness_policy"],
            "session_lifetime",
        )
        self.assertIsNone(
            active["capabilities"]["session_context"]["freshness_ttl_seconds"]
        )
        self.assertEqual(
            idle["capabilities"]["session_context"]["status"],
            "live_verified",
        )
        self.assertEqual(idle["capabilities"]["prompt_control"]["status"], "unobserved")
        self.assertEqual(idle["status"], "interactive_partial")

    def test_test_mode_refuses_explicit_production_observation_home(self) -> None:
        production = self.root / "production-kb"
        isolated = self.root / "isolated-kb"
        with mock.patch.dict(
            os.environ,
            {
                "SULDE_TEST_MODE": "1",
                "SULDE_KB_HOME": str(isolated),
                "SULDE_PRODUCTION_KB_HOME": str(production),
            },
            clear=False,
        ):
            with self.assertRaisesRegex(HostCapabilityError, "production KB"):
                record_observation(
                    provider="codex",
                    hook_event="UserPromptSubmit",
                    session_id="test-session",
                    workspace=self.root,
                    source="synthetic_smoke",
                    home=production / "nested",
                )
        self.assertFalse(production.exists())

    def test_provenance_key_provision_is_atomic_under_concurrency(self) -> None:
        home = self.root / "concurrent-key-home"
        with ThreadPoolExecutor(max_workers=12) as executor:
            paths = list(executor.map(lambda _index: provision_provenance_key(home), range(48)))
        self.assertEqual(set(paths), {home / "runtime" / "host-provenance.key"})
        key = paths[0]
        self.assertEqual(len(key.read_bytes()), 32)
        self.assertEqual(key.stat().st_mode & 0o077, 0)

    @unittest.skipIf(os.name == "nt", "symlink creation may require Windows developer mode")
    def test_provenance_key_never_follows_a_preplanted_symlink(self) -> None:
        home = self.root / "symlink-key-home"
        key = home / "runtime" / "host-provenance.key"
        key.parent.mkdir(parents=True)
        outside = self.root / "outside-authority.key"
        outside.write_bytes(b"x" * 32)
        outside.chmod(0o600)
        key.symlink_to(outside)

        with self.assertRaisesRegex(HostCapabilityError, "must not be a symlink"):
            provision_provenance_key(home)

        self.assertTrue(key.is_symlink())
        self.assertEqual(outside.read_bytes(), b"x" * 32)


if __name__ == "__main__":
    unittest.main()
