"""R3 repair tests: five boundary counterexamples from independent review.

R3-01 shared-target reclamation is closed (no caller declaration can prove
complete coverage); R3-02 a vanished declared scope is never recreated and
nothing is deleted; R3-03 the generation-switch fence linearizes lease
admission against the switch; R3-04 retry operations carry stable,
idempotent identities; R3-05 recovery persists the task conclusion so
repeated replays never degrade the original facts.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "scripts" / "kb"
RUNTIME = SCRIPT_DIR / "agent-runtime.py"
GC_CLI = SCRIPT_DIR / "generation-gc.py"

sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(ROOT / "scripts" / "release"))

import dispatch_registry  # noqa: E402
import generation_guard  # noqa: E402
import run_concurrency  # noqa: E402

sys.path.insert(0, str(ROOT / "tests"))
from test_orchestration_r2 import _CliFixture, GOOD_REPORT  # noqa: E402

_FENCE_PROBE = None


def fence_probe():
    """Load the production admission fence check from agent-runtime."""
    global _FENCE_PROBE
    if _FENCE_PROBE is None:
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "r3_agent_runtime", RUNTIME
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _FENCE_PROBE = module._generation_switch_fence_refusal
    return _FENCE_PROBE


EVIDENCE = (
    "✅ 验证通过：`python -m unittest`，exit 0；输出 OK；"
    "candidate_sha256=" + "a" * 64
    + "；execution_binding_sha256=" + "b" * 64
    + "；environment_sha256=" + "c" * 64
    + "；command_sha256=88d1e4ef3a5e210c702e32c1f294a637fcac036aae538cf3e0500c2c054b49c7"
    + "；count=1"
)
GOOD_REPORT = (
    "## 结果\n任务完成。\n" + EVIDENCE
    + "\n## 过程\np\n## 遇到的问题\n无\n"
    "## 解决方式\ns\n## 遗留风险与建议\n无\n"
)


class ReclamationClosedTests(unittest.TestCase):
    """R3-01/R3-02: coverage declarations never authorize deletion."""

    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)
        self.retired_dir = self.root / "retired" / "sulde"
        self.retired_dir.mkdir(parents=True)
        self.scope_a = self.root / "ws-a"
        self.scope_b = self.root / "ws-b"
        (self.scope_a / "run-leases").mkdir(parents=True)
        (self.scope_b / "run-leases").mkdir(parents=True)

    def _record(self, version: str, tree: str) -> tuple[Path, Path]:
        name = f"{version}-{tree[:20]}"
        target = self.retired_dir / name
        target.mkdir()
        record = self.retired_dir / f"{name}.retirement.json"
        record.write_text(
            json.dumps(
                {
                    "schema": "sulde-retired-codex-cache-v1",
                    "schema_version": 1,
                    "alias": f"/plugins/cache/{version}",
                    "target": str(target),
                    "version": version,
                    "tree_sha256": tree,
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        aged = time.time() - 7200.0
        os.utime(record, (aged, aged))
        return target, record

    def test_b_reference_with_a_only_declaration_is_not_actionable(self) -> None:
        generation = "0.1.0:" + "a" * 64
        target, _record = self._record("0.1.0", "a" * 64)
        lease = run_concurrency.acquire_run_slot(
            self.scope_b,
            max_concurrent=1,
            timeout_seconds=0.0,
            runtime_generation=generation,
        )
        try:
            plan = generation_guard.plan_retired_reclamation(
                self.retired_dir,
                leases_dirs=[self.scope_a / "run-leases"],
                retention_seconds=0.0,
            )
            # Even with scope A looking clear, the actionable verdict is
            # always false: coverage cannot be proven by declaration.
            self.assertEqual(plan["reclaimable_count"], 0)
            self.assertFalse(hasattr(generation_guard, "apply_retired_reclamation"))
        finally:
            lease.release()
        self.assertTrue(target.exists(), "nothing may delete the target")

    def test_vanished_declared_scope_stays_vanished(self) -> None:
        self._record("0.1.0", "a" * 64)
        plan = generation_guard.plan_retired_reclamation(
            self.retired_dir,
            leases_dirs=[self.scope_a / "run-leases"],
            retention_seconds=0.0,
        )
        import shutil

        shutil.rmtree(self.scope_a)
        plan2 = generation_guard.plan_retired_reclamation(
            self.retired_dir,
            leases_dirs=[self.scope_a / "run-leases"],
            retention_seconds=0.0,
        )
        self.assertEqual(plan2["scopes"][0]["status"], "missing")
        self.assertEqual(plan2["coverage"], "insufficient")
        self.assertFalse(
            self.scope_a.exists(),
            "the planner must not recreate a vanished reference source",
        )
        self.assertFalse(hasattr(generation_guard, "apply_retired_reclamation"))

    def test_cli_has_no_apply_path(self) -> None:
        self._record("0.1.0", "a" * 64)
        for flag in ("--apply", "--certify-scope-coverage"):
            completed = subprocess.run(
                [
                    sys.executable,
                    str(GC_CLI),
                    "--retired-dir",
                    str(self.retired_dir),
                    "--leases-dir",
                    str(self.scope_a / "run-leases"),
                    flag,
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                timeout=30,
            )
            self.assertEqual(completed.returncode, 2, completed.stdout)
        self.assertTrue(
            list(self.retired_dir.iterdir()), "diagnostic output only"
        )

    def test_eligible_diagnostic_flips_without_deletion(self) -> None:
        target, _record = self._record("0.1.0", "a" * 64)
        lease = run_concurrency.acquire_run_slot(
            self.scope_a,
            max_concurrent=1,
            timeout_seconds=0.0,
            runtime_generation="0.1.0:" + "a" * 64,
        )
        try:
            plan = generation_guard.plan_retired_reclamation(
                self.retired_dir,
                leases_dirs=[self.scope_a / "run-leases"],
                retention_seconds=0.0,
            )
            self.assertEqual(plan["targets"][0]["eligible"], False)
        finally:
            lease.release()
        plan = generation_guard.plan_retired_reclamation(
            self.retired_dir,
            leases_dirs=[self.scope_a / "run-leases"],
            retention_seconds=0.0,
        )
        self.assertEqual(plan["targets"][0]["eligible"], True)
        self.assertEqual(plan["reclaimable_count"], 0)
        self.assertTrue(target.exists())


class GenerationSwitchFenceTests(unittest.TestCase):
    """R3-03: the admission fence linearizes the re-check-to-switch window."""

    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.kb_home = Path(self._temporary.name) / "kb-home"
        self.kb_home.mkdir(parents=True)

    def _fence(self, to_generation: str) -> None:
        (self.kb_home / ".generation-switch-fence.json").write_text(
            json.dumps(
                {
                    "schema": "sulde-generation-switch-fence-v1",
                    "state": "in-switch",
                    "to_generation": to_generation,
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

    def test_in_switch_fence_refuses_superseded_generation(self) -> None:
        self._fence("gen-new:" + "b" * 64)
        probe = fence_probe()
        refusal = probe(self.kb_home, run_generation="gen-old:" + "a" * 64)
        self.assertIsNotNone(refusal)
        self.assertIn("generation switch in progress", refusal)
        # The target generation itself is admitted.
        self.assertIsNone(
            probe(self.kb_home, run_generation="gen-new:" + "b" * 64)
        )

    def test_missing_or_committed_or_damaged_fence_does_not_block(self) -> None:
        probe = fence_probe()
        self.assertIsNone(
            probe(self.kb_home, run_generation="gen-old:" + "a" * 64)
        )
        (self.kb_home / ".generation-switch-fence.json").write_text(
            json.dumps(
                {
                    "schema": "sulde-generation-switch-fence-v1",
                    "state": "committed",
                    "to_generation": "gen-new:" + "b" * 64,
                }
            )
            + "\n",
            encoding="utf-8",
        )
        self.assertIsNone(
            probe(self.kb_home, run_generation="gen-old:" + "a" * 64)
        )
        (self.kb_home / ".generation-switch-fence.json").write_text(
            "{damaged", encoding="utf-8"
        )
        self.assertIsNone(
            probe(self.kb_home, run_generation="gen-old:" + "a" * 64)
        )

    def test_install_level_writes_no_untracked_fence(self) -> None:
        # R3 followup 3: the fence is written inside the REAL transaction
        # (bound to its identity) — the mocked harness proves the install
        # level itself no longer writes an untracked fence, and the real
        # chain evidence lives in
        # tests.test_codex_plugin_install.GenerationSwitchFenceChainTests.
        import install_codex_plugin as installer

        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            kb_home = root / "kb-home"
            (kb_home / "venv" / "bin").mkdir(parents=True)
            (kb_home / "venv" / "bin" / "python").write_text("#!/bin/sh\n")
            artifact = root / "artifact"
            (artifact / "plugins" / "sulde" / "runtime").mkdir(parents=True)
            state_dir = root / "state"
            (state_dir / "run-leases").mkdir(parents=True)
            environment = {
                "SULDE_ACTIVE_LEASES_DIRS": str(state_dir / "run-leases"),
                "SULDE_GENERATION_SWITCH_POLICY": "block",
                "SULDE_TEST_MODE": "1",
                "SULDE_TEST_PREPARED_ARTIFACT": "1",
            }
            with mock.patch.dict(os.environ, environment, clear=False):
                with (
                    mock.patch.object(
                        installer, "_codex_host_preflight", return_value={}
                    ),
                    mock.patch.object(
                        installer,
                        "invoking_environment",
                        return_value={"executable": "py"},
                    ),
                    mock.patch(
                        "launcher_contract.runtime_interpreter",
                        return_value=Path("/nonexistent/python"),
                    ),
                    mock.patch.object(
                        installer,
                        "inspect_python",
                        return_value={"executable": "py"},
                    ),
                    mock.patch.object(installer, "same_runtime", return_value=True),
                    mock.patch.object(
                        installer, "plugin_version", return_value="0.0.0-test"
                    ),
                    mock.patch.object(installer, "tree_digest", return_value="a" * 64),
                    mock.patch.object(
                        installer, "validate_staged_marketplace", return_value={}
                    ),
                    mock.patch.object(
                        installer,
                        "_scheduler_actor_preflight",
                        return_value={
                            "loaded_labels_before": [],
                            "desired_labels": [],
                        },
                    ),
                    mock.patch.object(
                        installer, "_legacy_home_migration_source", return_value=None
                    ),
                    mock.patch.object(
                        installer,
                        "_install_locked",
                        side_effect=installer.InstallError(
                            "simulated mid-switch failure (rollback path)"
                        ),
                    ),
                ):
                    with self.assertRaises(installer.InstallError):
                        installer.install(
                            artifact=artifact,
                            kb_home=kb_home,
                            codex="codex-fake",
                            platform="posix",
                        )
            # No untracked fence at the install level; the transaction-bound
            # fence lifecycle is covered by the real-chain tests.
            self.assertFalse(
                (kb_home / ".generation-switch-fence.json").exists()
            )


    def test_recover_only_clears_a_leftover_fence(self) -> None:
        import install_codex_plugin as installer

        with tempfile.TemporaryDirectory() as directory_name:
            kb_home = Path(directory_name) / "kb-home"
            kb_home.mkdir(parents=True)
            self._fence("gen-new:" + "b" * 64)
            result = installer.recover_only(
                kb_home=kb_home, codex="codex-fake"
            )
            self.assertEqual(result["status"], "no_recovery_required")
            self.assertFalse(
                (kb_home / ".generation-switch-fence.json").exists()
            )


class RetryIdentityTests(unittest.TestCase):
    """R3-04: stable retry-operation identities (registry level)."""

    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.registry = Path(self._temporary.name) / "slug.dispatch.jsonl"

    def _seed_timeout_attempt(self, run_suffix: str) -> str:
        dispatch_registry.open_request(
            self.registry,
            request_id="req-1",
            request_sha256="a" * 64,
            slug="slug",
        )
        run_id = "run-" + run_suffix.encode().hex().rjust(24, "0")[-24:]
        dispatch_registry.record_launched(
            self.registry, request_id="req-1", attempt=1, run_id=run_id
        )
        dispatch_registry.record_closed(
            self.registry,
            request_id="req-1",
            attempt=1,
            run_id=run_id,
            outcome="terminal",
            stop_reason="timeout",
        )
        return run_id

    def test_same_retry_op_resolves_to_its_own_attempt_after_failure(self) -> None:
        run1 = self._seed_timeout_attempt("one")
        first = dispatch_registry.open_retry(
            self.registry,
            retry_op_id="op-1",
            request_id="req-1",
            request_sha256="a" * 64,
            slug="slug",
            from_run_id=run1,
        )
        self.assertTrue(first["created"])
        self.assertEqual(first["attempt"], 2)
        run2 = "run-" + "c" * 24
        dispatch_registry.record_launched(
            self.registry, request_id="req-1", attempt=2, run_id=run2
        )
        dispatch_registry.record_closed(
            self.registry,
            request_id="req-1",
            attempt=2,
            run_id=run2,
            outcome="terminal",
            stop_reason="timeout",
        )
        # Repeating the SAME retry operation after its own timeout resolves
        # to attempt 2 — it never becomes attempt 3.
        repeat = dispatch_registry.open_retry(
            self.registry,
            retry_op_id="op-1",
            request_id="req-1",
            request_sha256="a" * 64,
            slug="slug",
            from_run_id=run1,
        )
        self.assertFalse(repeat["created"])
        self.assertEqual(repeat["attempt"], 2)

    def test_new_retry_op_is_required_for_a_third_attempt(self) -> None:
        run1 = self._seed_timeout_attempt("one")
        dispatch_registry.open_retry(
            self.registry,
            retry_op_id="op-1",
            request_id="req-1",
            request_sha256="a" * 64,
            slug="slug",
            from_run_id=run1,
        )
        run2 = "run-" + "c" * 24
        dispatch_registry.record_launched(
            self.registry, request_id="req-1", attempt=2, run_id=run2
        )
        dispatch_registry.record_closed(
            self.registry,
            request_id="req-1",
            attempt=2,
            run_id=run2,
            outcome="terminal",
            stop_reason="timeout",
        )
        second = dispatch_registry.open_retry(
            self.registry,
            retry_op_id="op-2",
            request_id="req-1",
            request_sha256="a" * 64,
            slug="slug",
            from_run_id=run2,
        )
        self.assertTrue(second["created"])
        self.assertEqual(second["attempt"], 3)
        self.assertEqual(second["retries_of_run_id"], run2)

    def test_retry_op_with_wrong_predecessor_conflicts(self) -> None:
        run1 = self._seed_timeout_attempt("one")
        dispatch_registry.open_retry(
            self.registry,
            retry_op_id="op-1",
            request_id="req-1",
            request_sha256="a" * 64,
            slug="slug",
            from_run_id=run1,
        )
        with self.assertRaises(dispatch_registry.DispatchConflictError):
            dispatch_registry.open_retry(
                self.registry,
                retry_op_id="op-1",
                request_id="req-1",
                request_sha256="a" * 64,
                slug="slug",
                from_run_id="run-" + "f" * 24,
            )

    def test_retry_refuses_active_and_completed_chains(self) -> None:
        run1 = self._seed_timeout_attempt("one")
        # An ACTIVE chain refuses a retry registration outright.
        registry_active = self.registry.parent / "active.dispatch.jsonl"
        dispatch_registry.open_request(
            registry_active, request_id="req-2", request_sha256="a" * 64, slug="slug"
        )
        run_active = "run-" + "e" * 24
        dispatch_registry.record_launched(
            registry_active, request_id="req-2", attempt=1, run_id=run_active
        )
        with self.assertRaises(dispatch_registry.DispatchRegistryError):
            dispatch_registry.open_retry(
                registry_active,
                retry_op_id="op-active",
                request_id="req-2",
                request_sha256="a" * 64,
                slug="slug",
                from_run_id=run_active,
            )
        # A completed chain has no retry at all.
        registry_done = self.registry.parent / "done.dispatch.jsonl"
        dispatch_registry.open_request(
            registry_done, request_id="req-9", request_sha256="a" * 64, slug="slug"
        )
        dispatch_registry.record_launched(
            registry_done, request_id="req-9", attempt=1, run_id="run-" + "e" * 24
        )
        dispatch_registry.record_closed(
            registry_done,
            request_id="req-9",
            attempt=1,
            run_id="run-" + "e" * 24,
            outcome="terminal",
            stop_reason="completed",
        )
        with self.assertRaises(dispatch_registry.DispatchRegistryError):
            dispatch_registry.open_retry(
                registry_done,
                retry_op_id="op-done",
                request_id="req-9",
                request_sha256="a" * 64,
                slug="slug",
                from_run_id="run-" + "e" * 24,
            )


class RepeatedReplayTests(unittest.TestCase, _CliFixture):
    """R3-05: N repeated submissions replay the same conclusion forever.

    The fixture helpers (prepare/write_provider/environment/status_file/
    registry_rows/run_cli) are shared with the R2 suite.
    """

    def _multi_replay(self, slug: str, report_text: str, timeout: str, sleep: int):
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            worktree, brief = self.prepare(directory, slug)
            executable = self.write_provider(
                directory, report_text=report_text, sleep_seconds=sleep
            )
            environment = self.environment(directory, executable)
            first = self.run_cli(
                worktree, slug, brief, environment, timeout=timeout
            )
            self.assertEqual(first.returncode, 1, first.stdout + first.stderr)
            original_status = self.status_file(worktree, slug)
            # Drop the close row each round to force the recovery-close path.
            registry = worktree / ".codex-agent" / f"{slug}.dispatch.jsonl"
            conclusions = []
            for round_index in range(3):
                rows = [
                    json.loads(line)
                    for line in registry.read_text(encoding="utf-8").splitlines()
                    if line.strip()
                ]
                kept = [
                    row for row in rows if row["type"] != "dispatch.closed"
                ]
                registry.write_text(
                    "".join(
                        json.dumps(row, sort_keys=True) + "\n" for row in kept
                    ),
                    encoding="utf-8",
                )
                replay = self.run_cli(
                    worktree, slug, brief, environment, timeout=timeout
                )
                self.assertEqual(
                    replay.returncode,
                    1,
                    f"replay round {round_index + 1}: "
                    + replay.stdout
                    + replay.stderr,
                )
                self.assertIn("duplicate_of_run", replay.stdout)
                conclusions.append(replay.stdout)
                launched = [
                    row
                    for row in self.registry_rows(worktree, slug)
                    if row["type"] == "dispatch.launched"
                ]
                self.assertEqual(len(launched), 1, "no new launch, ever")
            # The original status facts were never overwritten.
            self.assertEqual(self.status_file(worktree, slug), original_status)
            # Every replay resolved to the same conclusion.
            self.assertEqual(len(set(conclusions)), 1)

    def test_failed_task_replays_failed_across_repeated_replays(self) -> None:
        self._multi_replay("r3-failed", "## drill\n", timeout="15", sleep=0)

    def test_timeout_task_replays_timeout_across_repeated_replays(self) -> None:
        self._multi_replay(
            "r3-timeout", GOOD_REPORT + "\n", timeout="1", sleep=4
        )

    def test_successful_task_replays_success_across_repeated_replays(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            slug = "r3-success"
            worktree, brief = self.prepare(directory, slug)
            executable = self.write_provider(
                directory, report_text=GOOD_REPORT
            )
            environment = self.environment(directory, executable)
            first = self.run_cli(worktree, slug, brief, environment)
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            registry = worktree / ".codex-agent" / f"{slug}.dispatch.jsonl"
            rows = [
                json.loads(line)
                for line in registry.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            kept = [row for row in rows if row["type"] != "dispatch.closed"]
            registry.write_text(
                "".join(json.dumps(row, sort_keys=True) + "\n" for row in kept),
                encoding="utf-8",
            )
            for _ in range(3):
                replay = self.run_cli(worktree, slug, brief, environment)
                self.assertEqual(replay.returncode, 0)
                self.assertIn("status=success", replay.stdout)
            launched = [
                row
                for row in self.registry_rows(worktree, slug)
                if row["type"] == "dispatch.launched"
            ]
            self.assertEqual(len(launched), 1)


if __name__ == "__main__":
    unittest.main()
