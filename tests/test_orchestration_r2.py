"""R2 repair tests: five coordinator-verified counterexamples.

R2-01 duplicate requests replay the original TASK conclusion (a provider
exit 0 with a failed report verdict is never replayed as success);
R2-02 ordinary duplicates never auto-retry — retries are explicit,
idempotent operations that refuse human gates; R2-03 the installer's
switch gate runs before the first production mutation; R2-04 reference
coverage is explicit and uncertified/missing scopes disable actual
reclamation; R2-05 the candidate drill runs the full protection entry
with a report-contract-correct fixture and reaches task success.
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
import usage_ledger  # noqa: E402


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


class _CliFixture:
    def temporary_directory(self) -> tempfile.TemporaryDirectory:
        return tempfile.TemporaryDirectory()

    @staticmethod
    def prepare(directory: Path, slug: str) -> tuple[Path, Path]:
        worktree = directory / "worktree"
        state = worktree / ".codex-agent"
        state.mkdir(parents=True)
        (worktree / "base.txt").write_text("base\n", encoding="utf-8")
        brief = state / f"{slug}.md"
        brief.write_text("# Task\n\nDo the work.\n", encoding="utf-8")
        brief.chmod(0o400)
        return worktree, brief

    @staticmethod
    def write_provider(
        directory: Path,
        *,
        report_text: str,
        sleep_seconds: int = 0,
        exit_code: int = 0,
    ) -> Path:
        executable = directory / "codex"
        executable.write_text(
            textwrap.dedent(
                f"""\
                #!/usr/bin/python3
                import sys, time
                args = sys.argv[1:]
                if {sleep_seconds}:
                    time.sleep({sleep_seconds})
                from pathlib import Path
                report = Path(args[args.index('--output-last-message') + 1])
                report.write_text({report_text!r}, encoding='utf-8')
                print('{{"type":"done"}}')
                sys.exit({exit_code})
                """
            ),
            encoding="utf-8",
        )
        executable.chmod(0o755)
        return executable

    @staticmethod
    def environment(directory: Path, executable: Path) -> dict:
        environment = os.environ.copy()
        environment.update(
            {
                "SULDE_TEST_MODE": "1",
                "SULDE_INTENT_CONTRACT": "",
                "SULDE_GUARDIAN_STREAM_OWNER": "",
                "SULDE_GUARDIAN_STREAM_PROVIDER": "",
                "SULDE_AGENT_PROVIDER": "codex",
                "SULDE_CODEX_EXE": str(executable),
                "PYTHONDONTWRITEBYTECODE": "1",
            }
        )
        return environment

    def run_cli(self, worktree: Path, slug: str, brief: Path, environment: dict, *, extra=(), timeout: str = "15"):
        return subprocess.run(
            [
                sys.executable,
                str(RUNTIME),
                "run",
                str(worktree),
                slug,
                str(brief),
                *extra,
                "--timeout",
                timeout,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=environment,
            check=False,
            timeout=90,
        )

    @staticmethod
    def registry_rows(worktree: Path, slug: str) -> list[dict]:
        registry = worktree / ".codex-agent" / f"{slug}.dispatch.jsonl"
        return [
            json.loads(line)
            for line in registry.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    @staticmethod
    def status_file(worktree: Path, slug: str) -> str:
        return (
            worktree / ".codex-agent" / f"{slug}.status"
        ).read_text(encoding="utf-8")


class DuplicateReplaysTaskConclusionTests(unittest.TestCase, _CliFixture):
    """R2-01: provider exit 0 with a failed report verdict is a FAILED task."""

    def test_failed_report_verdict_is_replayed_as_failure(self) -> None:
        with self.temporary_directory() as directory_name:
            directory = Path(directory_name)
            slug = "r2-failed"
            worktree, brief = self.prepare(directory, slug)
            # Provider process exits 0 but the report fails the contract.
            executable = self.write_provider(
                directory, report_text="## drill\n"
            )
            environment = self.environment(directory, executable)
            first = self.run_cli(worktree, slug, brief, environment)
            self.assertEqual(first.returncode, 1, first.stdout + first.stderr)
            self.assertIn("status=failed", self.status_file(worktree, slug))
            second = self.run_cli(worktree, slug, brief, environment)
            self.assertEqual(
                second.returncode,
                1,
                "the duplicate must replay the FAILED task conclusion: "
                + second.stdout
                + second.stderr,
            )
            self.assertIn("status=failed", second.stdout)
            self.assertIn("duplicate_of_run", second.stdout)
            # The original failure state is preserved, not rewritten.
            self.assertIn("status=failed", self.status_file(worktree, slug))
            launched = [
                row
                for row in self.registry_rows(worktree, slug)
                if row["type"] == "dispatch.launched"
            ]
            self.assertEqual(len(launched), 1, "no new launch for the duplicate")
            closed = [
                row
                for row in self.registry_rows(worktree, slug)
                if row["type"] == "dispatch.closed"
            ]
            self.assertEqual(closed[0].get("task_status"), "failed")
            # task_returncode preserves the provider process exit as evidence;
            # the task conclusion (status=failed) is what replays.
            self.assertEqual(closed[0].get("task_returncode"), 0)

    def test_genuine_success_is_replayed_as_success(self) -> None:
        with self.temporary_directory() as directory_name:
            directory = Path(directory_name)
            slug = "r2-success"
            worktree, brief = self.prepare(directory, slug)
            executable = self.write_provider(directory, report_text=GOOD_REPORT)
            environment = self.environment(directory, executable)
            first = self.run_cli(worktree, slug, brief, environment)
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            second = self.run_cli(worktree, slug, brief, environment)
            self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
            self.assertIn("status=success", second.stdout)
            launched = [
                row
                for row in self.registry_rows(worktree, slug)
                if row["type"] == "dispatch.launched"
            ]
            self.assertEqual(len(launched), 1)

    def test_nonzero_provider_exit_replays_as_failure(self) -> None:
        with self.temporary_directory() as directory_name:
            directory = Path(directory_name)
            slug = "r2-nonzero"
            worktree, brief = self.prepare(directory, slug)
            executable = self.write_provider(
                directory, report_text=GOOD_REPORT, exit_code=3
            )
            environment = self.environment(directory, executable)
            first = self.run_cli(worktree, slug, brief, environment)
            self.assertEqual(first.returncode, 1, first.stdout + first.stderr)
            second = self.run_cli(worktree, slug, brief, environment)
            self.assertEqual(second.returncode, 1)
            self.assertIn("status=failed", second.stdout)
            self.assertIn("duplicate_of_run", second.stdout)

    def test_crash_window_replays_original_failure_not_success(self) -> None:
        with self.temporary_directory() as directory_name:
            directory = Path(directory_name)
            slug = "r2-window"
            worktree, brief = self.prepare(directory, slug)
            executable = self.write_provider(directory, report_text="## drill\n")
            environment = self.environment(directory, executable)
            first = self.run_cli(worktree, slug, brief, environment)
            self.assertEqual(first.returncode, 1)
            # Crash window: the registry loses its closed row.
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
            second = self.run_cli(worktree, slug, brief, environment)
            self.assertEqual(
                second.returncode,
                1,
                "reconciliation must find the original failed conclusion: "
                + second.stdout
                + second.stderr,
            )
            self.assertIn("status=failed", second.stdout)
            self.assertFalse(
                (worktree / ".codex-agent" / f"{slug}.round1.run.jsonl").is_file()
            )

    def test_unresolvable_conclusion_blocks_without_relaunch(self) -> None:
        with self.temporary_directory() as directory_name:
            directory = Path(directory_name)
            slug = "r2-unresolved"
            worktree, brief = self.prepare(directory, slug)
            executable = self.write_provider(directory, report_text="## drill\n")
            environment = self.environment(directory, executable)
            first = self.run_cli(worktree, slug, brief, environment)
            self.assertEqual(first.returncode, 1)
            # Remove both the close row AND the authoritative status file:
            # the conclusion is now genuinely unresolvable.
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
            (worktree / ".codex-agent" / f"{slug}.status").unlink()
            second = self.run_cli(worktree, slug, brief, environment)
            self.assertEqual(second.returncode, 1)
            self.assertIn("status=awaiting_human", second.stdout)
            self.assertIn("duplicate_of_run", second.stdout)
            launched = [
                row
                for row in self.registry_rows(worktree, slug)
                if row["type"] == "dispatch.launched"
            ]
            self.assertEqual(len(launched), 1, "no blind relaunch")

    def test_late_receipt_on_closed_attempt_is_a_noop(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            registry = Path(directory_name) / "slug.dispatch.jsonl"
            dispatch_registry.open_request(
                registry, request_id="req-1", request_sha256="a" * 64, slug="slug"
            )
            dispatch_registry.record_launched(
                registry, request_id="req-1", attempt=1, run_id="run-" + "a" * 24
            )
            dispatch_registry.record_closed(
                registry,
                request_id="req-1",
                attempt=1,
                run_id="run-" + "a" * 24,
                outcome="terminal",
                stop_reason="completed",
                task_status="success",
                returncode=0,
            )
            # A late duplicate receipt must not downgrade or impersonate.
            dispatch_registry.record_closed(
                registry,
                request_id="req-1",
                attempt=1,
                run_id="run-" + "a" * 24,
                outcome="terminal",
                stop_reason="timeout",
                task_status="failed",
                returncode=1,
            )
            rows = dispatch_registry.read_registry(registry)
            closes = [row for row in rows if row["type"] == "dispatch.closed"]
            self.assertEqual(len(closes), 1)
            self.assertEqual(closes[0]["stop_reason"], "completed")
            self.assertEqual(closes[0]["task_status"], "success")


class ExplicitRetryTests(unittest.TestCase, _CliFixture):
    """R2-02: ordinary duplicates never auto-retry; --retry is explicit."""

    def test_timeout_duplicate_does_not_relaunch_without_explicit_retry(self) -> None:
        with self.temporary_directory() as directory_name:
            directory = Path(directory_name)
            slug = "r2-timeout"
            worktree, brief = self.prepare(directory, slug)
            executable = self.write_provider(
                directory, report_text=GOOD_REPORT, sleep_seconds=4
            )
            environment = self.environment(directory, executable)
            first = self.run_cli(
                worktree, slug, brief, environment, timeout="1"
            )
            self.assertEqual(first.returncode, 1)
            self.assertIn("status=timeout", self.status_file(worktree, slug))
            second = self.run_cli(
                worktree, slug, brief, environment, timeout="1"
            )
            self.assertEqual(
                second.returncode,
                1,
                "an ordinary duplicate of a timed-out request must not "
                "auto-retry: " + second.stdout + second.stderr,
            )
            rows = self.registry_rows(worktree, slug)
            launched = [row for row in rows if row["type"] == "dispatch.launched"]
            self.assertEqual(len(launched), 1, "exactly one effective launch")
            attempts = [row for row in rows if row["type"] == "dispatch.opened"]
            self.assertEqual(len(attempts), 1, "no new attempt identity")

    def test_explicit_retry_launches_once_and_is_idempotent(self) -> None:
        # R3-04: the retry operation carries a stable identity; repeating the
        # identical operation after its own timeout replays it (launched
        # stays 2) instead of advancing the chain.
        with self.temporary_directory() as directory_name:
            directory = Path(directory_name)
            slug = "r2-retry"
            worktree, brief = self.prepare(directory, slug)
            executable = self.write_provider(
                directory, report_text=GOOD_REPORT, sleep_seconds=4
            )
            environment = self.environment(directory, executable)
            first = self.run_cli(
                worktree, slug, brief, environment, timeout="1"
            )
            self.assertEqual(first.returncode, 1)
            # The explicit retry operation starts exactly one new attempt.
            retry = self.run_cli(
                worktree, slug, brief, environment, extra=("--retry", "--retry-op", "op-1"), timeout="15"
            )
            self.assertEqual(
                retry.returncode, 0, retry.stdout + retry.stderr
            )
            rows = self.registry_rows(worktree, slug)
            opened = [row for row in rows if row["type"] == "dispatch.opened"]
            self.assertEqual(len(opened), 2)
            self.assertEqual(opened[1].get("retries_of_run_id"), opened_run1(rows))
            # Repeating the identical retry operation replays ITS OWN
            # attempt 2 conclusion (here: success) — never attempt 3.
            repeat = self.run_cli(
                worktree, slug, brief, environment, extra=("--retry", "--retry-op", "op-1"), timeout="15"
            )
            self.assertEqual(repeat.returncode, 0, repeat.stdout + repeat.stderr)
            self.assertIn("status=success", repeat.stdout)
            rows = self.registry_rows(worktree, slug)
            opened = [row for row in rows if row["type"] == "dispatch.opened"]
            self.assertEqual(len(opened), 2, "no attempt 3 for the repeated retry")
            launched = [row for row in rows if row["type"] == "dispatch.launched"]
            self.assertEqual(len(launched), 2, "attempt 1 + explicit attempt 2")

    def test_failed_retry_repeated_does_not_advance(self) -> None:
        # R3-04 acceptance: initial timeout + same retry times out + repeat
        # that same retry -> still exactly 2 launches.
        with self.temporary_directory() as directory_name:
            directory = Path(directory_name)
            slug = "r2-retry-fail"
            worktree, brief = self.prepare(directory, slug)
            executable = self.write_provider(
                directory, report_text=GOOD_REPORT, sleep_seconds=4
            )
            environment = self.environment(directory, executable)
            first = self.run_cli(worktree, slug, brief, environment, timeout="1")
            self.assertEqual(first.returncode, 1)
            second = self.run_cli(
                worktree, slug, brief, environment,
                extra=("--retry", "--retry-op", "op-A"), timeout="1",
            )
            self.assertEqual(second.returncode, 1)
            third = self.run_cli(
                worktree, slug, brief, environment,
                extra=("--retry", "--retry-op", "op-A"), timeout="1",
            )
            self.assertEqual(third.returncode, 1)
            rows = self.registry_rows(worktree, slug)
            opened = [row for row in rows if row["type"] == "dispatch.opened"]
            launched = [row for row in rows if row["type"] == "dispatch.launched"]
            self.assertEqual(len(opened), 2, "no attempt 3 for the repeated op")
            self.assertEqual(len(launched), 2, "launches stay at 2")

    def test_retry_refuses_human_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            registry = Path(directory_name) / "slug.dispatch.jsonl"
            dispatch_registry.open_request(
                registry, request_id="req-1", request_sha256="a" * 64, slug="slug"
            )
            dispatch_registry.record_launched(
                registry, request_id="req-1", attempt=1, run_id="run-" + "a" * 24
            )
            dispatch_registry.record_closed(
                registry,
                request_id="req-1",
                attempt=1,
                run_id="run-" + "a" * 24,
                outcome="terminal",
                stop_reason="awaiting_human",
                task_status="awaiting_human",
                returncode=1,
            )
            segment = dispatch_registry.lookup(registry, "req-1")
            self.assertIsNotNone(segment)
            self.assertFalse(
                dispatch_registry.retryable("awaiting_human"),
                "awaiting_human is a human gate, never auto-permitted",
            )


def opened_run1(rows: list[dict]) -> str | None:
    launched = [row for row in rows if row["type"] == "dispatch.launched"]
    return launched[0]["run_id"] if launched else None


class InstallerGateOrderTests(unittest.TestCase):
    """R2-03: the gate runs before the first production mutation."""

    def test_block_refuses_before_any_mutation(self) -> None:
        import install_codex_plugin as installer

        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            kb_home = root / "kb-home"
            (kb_home / "venv" / "bin").mkdir(parents=True)
            (kb_home / "venv" / "bin" / "python").write_text("#!/bin/sh\n")
            artifact = root / "artifact"
            (artifact / "plugins" / "sulde" / "runtime").mkdir(parents=True)
            # This test isolates generation admission, not stable-entry
            # migration. Give its synthetic artifact an explicit legacy Hook
            # protocol rather than implicitly selecting the source template.
            hooks = artifact / "plugins/sulde/hooks/hooks.json"
            hooks.parent.mkdir()
            hooks.write_text(json.dumps({"hooks": {"PreToolUse": [{"hooks": [{
                "type": "command",
                "command": 'bash "${PLUGIN_ROOT}/scripts/run-hook.sh" pre-tool-use',
            }]}]}}), encoding="utf-8")
            state_dir = root / "state"
            (state_dir / "run-leases").mkdir(parents=True)
            lease = run_concurrency.acquire_run_slot(
                state_dir,
                max_concurrent=1,
                timeout_seconds=0.0,
                # Same version, different tree: an incompatible in-flight run
                # under the switch-compatibility contract.
                runtime_generation="0.0.0-test:" + "b" * 64,
            )
            try:
                environment = {
                    "SULDE_ACTIVE_LEASES_DIRS": str(state_dir / "run-leases"),
                    "SULDE_GENERATION_SWITCH_POLICY": "block",
                    "SULDE_TEST_MODE": "1",
                    "SULDE_TEST_PREPARED_ARTIFACT": "1",
                }
                with mock.patch.dict(os.environ, environment, clear=False):
                    with (
                        mock.patch.object(
                            installer,
                            "_codex_host_preflight",
                            return_value={},
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
                            "_scheduler_actor_preflight",
                            return_value={
                                "loaded_labels_before": [],
                                "desired_labels": [],
                            },
                        ),
                        mock.patch.object(
                            installer,
                            "_legacy_home_migration_source",
                            return_value=None,
                        ),
                        mock.patch.object(
                            installer,
                            "inspect_python",
                            return_value={"executable": "py"},
                        ),
                        mock.patch.object(
                            installer, "same_runtime", return_value=True
                        ),
                        mock.patch.object(
                            installer,
                            "plugin_version",
                            return_value="0.0.0-test",
                        ),
                        mock.patch.object(
                            installer, "tree_digest", return_value="a" * 64
                        ),
                        mock.patch.object(
                            installer,
                            "validate_staged_marketplace",
                            return_value={},
                        ),
                        mock.patch.object(
                            installer,
                            "_install_locked",
                            side_effect=AssertionError(
                                "mutation reached despite block gate"
                            ),
                        ) as locked_mock,
                    ):
                        with self.assertRaises(installer.InstallError) as ctx:
                            installer.install(
                                artifact=artifact,
                                kb_home=kb_home,
                                codex="codex-fake",
                                platform="posix",
                            )
                        # Either the projection itself or the install-level
                        # gate refuses; both happen before any mutation.
                        self.assertIn(
                            "generation switch blocked",
                            str(ctx.exception),
                        )
                # The mutation entry point was never reached.
                locked_mock.assert_not_called()
            finally:
                lease.release()

    def test_observe_records_unverified_without_refusing(self) -> None:
        import install_codex_plugin as installer

        with mock.patch.dict(
            os.environ,
            {
                "SULDE_ACTIVE_LEASES_DIRS": "/nonexistent/leases",
                "SULDE_GENERATION_SWITCH_POLICY": "observe",
            },
            clear=False,
        ):
            report = installer._generation_switch_projection("gen:" + "a" * 64)
        self.assertIsNone(report["compatible"], "unverified coverage is not safe")
        self.assertEqual(report["coverage"], "unknown")


class CoverageProofTests(unittest.TestCase):
    """R2-04: cross-scope references and certification-gated reclamation."""

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

    def test_full_coverage_diagnoses_reference_and_reclamation_stays_closed(self) -> None:
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
                leases_dirs=[self.scope_a / "run-leases", self.scope_b / "run-leases"],
                retention_seconds=0.0,
            )
            self.assertEqual(plan["coverage"], "complete")
            self.assertEqual(
                plan["reclaimable_count"], 0, "scope B holds the reference"
            )
        finally:
            lease.release()
        # R3-01: after the reference is gone the diagnostic flips to
        # eligible, but the actionable verdict stays false and no apply
        # entry point exists.
        plan = generation_guard.plan_retired_reclamation(
            self.retired_dir,
            leases_dirs=[self.scope_a / "run-leases", self.scope_b / "run-leases"],
            retention_seconds=0.0,
        )
        self.assertEqual(plan["targets"][0]["eligible"], True)
        self.assertEqual(plan["reclaimable_count"], 0)
        self.assertEqual(plan["reclamation"], "closed-diagnostic-only")
        self.assertFalse(hasattr(generation_guard, "apply_retired_reclamation"))
        self.assertTrue(target.exists(), "diagnostic must not delete")

    def test_new_scope_lease_after_plan_keeps_target_not_closed(self) -> None:
        self._record("0.1.0", "a" * 64)
        plan = generation_guard.plan_retired_reclamation(
            self.retired_dir,
            leases_dirs=[self.scope_a / "run-leases", self.scope_b / "run-leases"],
            retention_seconds=0.0,
        )
        self.assertEqual(plan["targets"][0]["eligible"], True)
        lease = run_concurrency.acquire_run_slot(
            self.scope_b,
            max_concurrent=1,
            timeout_seconds=0.0,
            runtime_generation="0.1.0:" + "a" * 64,
        )
        try:
            fresh = generation_guard.plan_retired_reclamation(
                self.retired_dir,
                leases_dirs=[
                    self.scope_a / "run-leases",
                    self.scope_b / "run-leases",
                ],
                retention_seconds=0.0,
            )
            self.assertEqual(fresh["reclaimable_count"], 0)
            self.assertFalse(
                fresh["targets"][0]["eligible"],
                "the new reference must flip the diagnostic",
            )
        finally:
            lease.release()

    def test_cli_is_diagnostic_only(self) -> None:
        self._record("0.1.0", "a" * 64)
        base = [
            sys.executable,
            str(GC_CLI),
            "--retired-dir",
            str(self.retired_dir),
            "--leases-dir",
            str(self.scope_a / "run-leases"),
            "--leases-dir",
            str(self.scope_b / "run-leases"),
            "--retention-hours",
            "1",
        ]
        for flag in ("--apply", "--certify-scope-coverage"):
            refused = subprocess.run(
                [*base, flag],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                timeout=30,
            )
            self.assertEqual(refused.returncode, 2, refused.stdout)
        plan_run = subprocess.run(
            base,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=30,
        )
        self.assertEqual(plan_run.returncode, 0, plan_run.stderr)
        plan = json.loads(plan_run.stdout)
        self.assertEqual(plan["reclamation"], "closed-diagnostic-only")
        self.assertEqual(plan["reclaimable_count"], 0)


class CandidateDrillTests(unittest.TestCase):
    """R2-05: the full generation-protection drill reaches task success."""

    def test_full_drill_entry_reaches_task_success_and_repeats(self) -> None:
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "candidate_codex_plugin_r2",
            ROOT / "scripts" / "release" / "candidate_codex_plugin.py",
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        def runner(command, **kwargs):
            if "environment" in kwargs:
                kwargs["env"] = kwargs.pop("environment")
            kwargs.setdefault("capture_output", True)
            kwargs.setdefault("text", True)
            kwargs.setdefault("encoding", "utf-8")
            kwargs.setdefault("errors", "replace")
            kwargs.pop("check", None)
            return subprocess.run(command, check=False, **kwargs)

        environment = {"SULDE_HOME": None, "PYTHONDONTWRITEBYTECODE": "1"}
        for attempt_index in range(2):
            with tempfile.TemporaryDirectory() as directory_name:
                environment = {
                    "SULDE_HOME": str(Path(directory_name) / "sulde-home"),
                    "PYTHONDONTWRITEBYTECODE": "1",
                }
                installed = Path(directory_name) / "installed"
                installed.mkdir(parents=True)
                # Point the drill at the repo runtime via the expected layout.
                os.symlink(ROOT, installed / "runtime")
                evidence = module._verify_generation_protection(
                    installed,
                    environment=environment,
                    runner=runner,
                    candidate_generation="9.9.9-drill:" + "b" * 64,
                )
                self.assertEqual(evidence["status"], "ready")
                drill = evidence["evidence"]
                self.assertEqual(drill["run_exit"], 0)
                self.assertEqual(drill["run_task_status"], "success")
                self.assertFalse(drill["foreign_switch_compatible"])
                self.assertTrue(drill["own_switch_compatible"])
                self.assertEqual(drill["reclaimable_while_running"], 0)
                # R3-01: reclamation is closed — the diagnostic flips to
                # eligible, the actionable verdict stays false.
                self.assertEqual(drill["eligible_after"], True)
                self.assertEqual(drill["reclaimable_after"], 0)
                self.assertEqual(drill["reclaim_state"], "closed-diagnostic-only")


if __name__ == "__main__":
    unittest.main()
