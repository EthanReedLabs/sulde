"""R1 repair tests: counterexamples from the independent review.

R1-01 retired-generation identity/apply safety; R1-02 lease atomicity under
real multiprocess races; R1-03 durable-report preflight through the real
production CLI entry; R1-04 request idempotency crash windows; R1-05 the
real producer sample; R1-06 installer-side generation-switch projection.
"""

from __future__ import annotations

import hashlib
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
REAL_SAMPLE = Path(
    "/Volumes/Optimus/Sulde/fixtures/life-status-20260924/"
    "p14-9b7319/sulde-clone/.codex-agent/comparison.events.jsonl"
)

sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(ROOT / "scripts" / "release"))

import dispatch_registry  # noqa: E402
import generation_guard  # noqa: E402
import run_concurrency  # noqa: E402
import launch_description  # noqa: E402


def _retirement_record(
    directory: Path,
    name: str,
    *,
    version: str = "0.1.0",
    tree_sha: str = "a" * 64,
    age_seconds: float | None = None,
    target: Path | None = None,
) -> tuple[Path, Path]:
    real_target = target if target is not None else directory / name
    real_target.mkdir(parents=True, exist_ok=True)
    record_path = directory / f"{name}.retirement.json"
    record_path.write_text(
        json.dumps(
            {
                "schema": "sulde-retired-codex-cache-v1",
                "schema_version": 1,
                "alias": f"/plugins/cache/{version}",
                "target": str(real_target),
                "version": version,
                "tree_sha256": tree_sha,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    if age_seconds is not None:
        aged = time.time() - age_seconds
        os.utime(record_path, (aged, aged))
    return real_target, record_path


class ReclaimIdentitySafetyTests(unittest.TestCase):
    """R3-01/R3-02: identity safety and the closed-reclamation boundary."""

    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)
        self.retired_dir = self.root / "retired" / "sulde"
        self.retired_dir.mkdir(parents=True)
        self.state_dir = self.root / "state"
        (self.state_dir / "run-leases").mkdir(parents=True)

    def _plan(self, *, leases_dirs=None):
        return generation_guard.plan_retired_reclamation(
            self.retired_dir,
            leases_dirs=leases_dirs or [self.state_dir / "run-leases"],
            retention_seconds=0.0,
            now=__import__("datetime").datetime.now(
                __import__("datetime").timezone.utc
            ),
        )

    def test_b_scope_reference_blocks_and_is_seen_with_full_declaration(
        self,
    ) -> None:
        generation = "0.1.0:" + "a" * 64
        scope_b = self.root / "workspace-b" / "run-leases"
        lease = run_concurrency.acquire_run_slot(
            self.root / "workspace-b",
            max_concurrent=1,
            timeout_seconds=0.0,
            runtime_generation=generation,
        )
        try:
            _target, _record = _retirement_record(
                self.retired_dir,
                "0.1.0-" + "a" * 20,
                version="0.1.0",
                tree_sha="a" * 64,
                age_seconds=60.0,
            )
            full = self._plan(leases_dirs=[self.state_dir / "run-leases", scope_b])
            self.assertEqual(full["coverage"], "complete")
            self.assertEqual(
                full["reclaimable_count"], 0, "B holds the reference"
            )
            self.assertIn(
                "shares the retired version", full["targets"][0]["reason"]
            )
        finally:
            lease.release()

    def test_a_only_plan_is_diagnostic_only_even_when_it_looks_clear(self) -> None:
        # R3-01 counterexample: B holds the identity; an A-only declaration
        # looks clear but must never be actionable.
        generation = "0.1.0:" + "a" * 64
        scope_b = self.root / "workspace-b" / "run-leases"
        lease = run_concurrency.acquire_run_slot(
            self.root / "workspace-b",
            max_concurrent=1,
            timeout_seconds=0.0,
            runtime_generation=generation,
        )
        try:
            _target, _record = _retirement_record(
                self.retired_dir,
                "0.1.0-" + "a" * 20,
                version="0.1.0",
                tree_sha="a" * 64,
                age_seconds=60.0,
            )
            plan = self._plan()
            self.assertEqual(plan["reclaimable_count"], 0)
            self.assertFalse(hasattr(generation_guard, "apply_retired_reclamation"))
        finally:
            lease.release()

    def test_vanished_scope_is_never_recreated_and_nothing_is_deleted(
        self,
    ) -> None:
        # R3-02 counterexample: a declared scope that disappears after
        # planning must stay vanished — never recreated as an empty
        # all-clear source — and nothing is deleted.
        _target, _record = _retirement_record(
            self.retired_dir,
            "0.1.0-" + "a" * 20,
            version="0.1.0",
            tree_sha="a" * 64,
            age_seconds=60.0,
        )
        plan = self._plan()
        self.assertEqual(plan["reclaimable_count"], 0)
        import shutil

        shutil.rmtree(self.state_dir / "run-leases")
        plan2 = self._plan()
        self.assertEqual(plan2["scopes"][0]["status"], "missing")
        self.assertFalse(
            (self.state_dir / "run-leases").exists(),
            "planning is read-only: no scope directory may be recreated",
        )
        self.assertFalse(hasattr(generation_guard, "apply_retired_reclamation"))

    def test_identity_and_retention_diagnostics_stay_correct(self) -> None:
        _target, _record = _retirement_record(
            self.retired_dir,
            "0.1.0-" + "b" * 20,
            version="0.1.0",
            tree_sha="b" * 64,
            age_seconds=10.0,
        )
        plan = generation_guard.plan_retired_reclamation(
            self.retired_dir,
            leases_dirs=[self.state_dir / "run-leases"],
            retention_seconds=3600.0,
            now=__import__("datetime").datetime.now(
                __import__("datetime").timezone.utc
            ),
        )
        self.assertEqual(plan["reclaimable_count"], 0)
        self.assertEqual(plan["targets"][0]["eligible"], False)
        self.assertIn("retention window not met", plan["targets"][0]["reason"])

    def test_unknown_schema_record_is_kept(self) -> None:
        name = "0.1.0-" + "d" * 20
        d_target = self.retired_dir / name
        d_target.mkdir()
        d_record = self.retired_dir / f"{name}.retirement.json"
        d_record.write_text(
            json.dumps(
                {
                    "schema": "sulde-retired-codex-cache-v0",
                    "version": "0.1.0",
                    "tree_sha256": "d" * 64,
                    "alias": "/p",
                    "target": str(d_target),
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        plan = self._plan()
        self.assertEqual(plan["reclaimable_count"], 0)
        self.assertIn("unrecognized", plan["targets"][0]["reason"])

    def test_reclamation_is_closed_for_every_entry(self) -> None:
        _target, _record = _retirement_record(
            self.retired_dir,
            "0.1.0-" + "a" * 20,
            version="0.1.0",
            tree_sha="a" * 64,
            age_seconds=60.0,
        )
        plan = self._plan()
        self.assertEqual(plan["reclaimable_count"], 0)
        self.assertFalse(hasattr(generation_guard, "apply_retired_reclamation"))

class LeaseAtomicityTests(unittest.TestCase):
    """R1-02: atomicity under real multiprocess races."""

    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.state_dir = Path(self._temporary.name) / "state"
        self.state_dir.mkdir()

    def test_readonly_projection_does_not_prune(self) -> None:
        stale = self.state_dir / "run-leases" / "1-2.lease"
        stale.parent.mkdir(parents=True, exist_ok=True)
        stale.write_text("{}", encoding="utf-8")
        projection = run_concurrency.active_run_leases(
            self.state_dir / "run-leases"
        )
        self.assertEqual(len(projection), 1)
        self.assertTrue(
            stale.exists(), "read-only observers must not mutate the directory"
        )

    def test_crashed_holder_is_reaped_by_next_acquisition(self) -> None:
        holder_source = textwrap.dedent(
            f"""
            import os, sys
            from pathlib import Path
            sys.path.insert(0, {str(SCRIPT_DIR)!r})
            from run_concurrency import acquire_run_slot
            lease = acquire_run_slot(
                Path({str(self.state_dir)!r}), max_concurrent=1, timeout_seconds=0.0,
                runtime_generation="gen-crash",
            )
            print("held", flush=True)
            os.kill(os.getpid(), 9)
            """
        )
        completed = subprocess.run(
            [sys.executable, "-c", holder_source],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        self.assertEqual(completed.returncode, -9, completed.stderr)
        lease_files = list((self.state_dir / "run-leases").glob("*.lease"))
        self.assertEqual(len(lease_files), 1, "crashed lease file stays on disk")
        # The next acquisition prunes the dead holder and succeeds.
        lease = run_concurrency.acquire_run_slot(
            self.state_dir,
            max_concurrent=1,
            timeout_seconds=5.0,
            runtime_generation="gen-next",
        )
        try:
            generations = generation_guard.active_generations(
                self.state_dir / "run-leases"
            )
            self.assertEqual(
                generations,
                {"gen-next": 1},
                "the crashed holder must be reaped, the new holder kept",
            )
        finally:
            lease.release()

    def test_held_lease_survives_concurrent_acquisition(self) -> None:
        holder_source = textwrap.dedent(
            f"""
            import os, sys, time
            from pathlib import Path
            sys.path.insert(0, {str(SCRIPT_DIR)!r})
            from run_concurrency import acquire_run_slot
            lease = acquire_run_slot(
                Path({str(self.state_dir)!r}), max_concurrent=1, timeout_seconds=0.0,
                runtime_generation="gen-live",
            )
            print("held", flush=True)
            time.sleep(3)
            lease.release()
            """
        )
        holder = subprocess.Popen(
            [sys.executable, "-c", holder_source],
            stdout=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        try:
            holder.stdout.readline()
            with self.assertRaises(run_concurrency.RunConcurrencyLimitError):
                run_concurrency.acquire_run_slot(
                    self.state_dir, max_concurrent=1, timeout_seconds=0.5
                )
            # The live lease must still be there (never pruned as stale).
            projection = run_concurrency.active_run_leases(
                self.state_dir / "run-leases"
            )
            self.assertEqual(
                projection[0]["runtime_generation"], "gen-live"
            )
        finally:
            holder.wait(timeout=30)


class DurableReportPreflightTests(unittest.TestCase):
    """R1-03: the finalize-time durable-report parse, pre-launch, real entry."""

    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.directory = Path(self._temporary.name)

    def _production_fixture(self, owned_paths: list[str]) -> tuple[Path, Path, Path]:
        """Production-shape brief + task definition (no SULDE_TEST_MODE)."""
        worktree = self.directory / "worktree"
        worktree.mkdir()
        (worktree / "base.txt").write_text("base\n", encoding="utf-8")
        subprocess.run(
            ["git", "init", "-q"], cwd=worktree, check=True, capture_output=True
        )
        subprocess.run(
            ["git", "config", "user.email", "r1@example.invalid"],
            cwd=worktree, check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "R1 Test"],
            cwd=worktree, check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "add", "base.txt"], cwd=worktree, check=True, capture_output=True
        )
        subprocess.run(
            ["git", "commit", "-qm", "fixture"], cwd=worktree, check=True,
            capture_output=True,
        )
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=worktree, check=True,
            capture_output=True, text=True,
            encoding="utf-8",
            errors="replace",
        ).stdout.strip()
        # Owned report paths must exist in the worktree for the preflight
        # and for any legitimate run.
        for owned_path in owned_paths:
            existing = worktree / owned_path
            existing.parent.mkdir(parents=True, exist_ok=True)
            existing.write_text("# durable report placeholder\n", encoding="utf-8")
        # The production control root must share the worktree git common dir.
        control = worktree / "coordinator" / "guardian-program"
        (control / "briefs").mkdir(parents=True)
        (control / "task-definitions").mkdir()
        brief = control / "briefs" / "T91.md"
        brief.write_text("# Task\n\nDo the work.\n", encoding="utf-8")
        task = control / "task-definitions" / "T91.json"
        task.write_text(
            json.dumps(
                {
                    "schema": "sulde-guardian-program-task-v1",
                    "task_id": "T91",
                    "title": "Fixture",
                    "owner": "r1-test",
                    "capability_tier": "light",
                    "base_commit": head,
                    "depends_on": [],
                    "supersedes": [],
                    "owned_paths": owned_paths,
                    "requirements": [],
                    "acceptance": ["anything"],
                    "evidence_gates": {
                        "implemented": ["task_report"],
                        "task_verified": ["targeted_tests"],
                        "integrated": ["integration_tests"],
                        "system_verified": ["system_tests"],
                    },
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        return worktree, brief, task

    def _run_production(self, owned_paths: list[str], slug: str = "dur-report"):
        worktree, brief, task = self._production_fixture(owned_paths)
        environment = os.environ.copy()
        environment.pop("SULDE_TEST_MODE", None)
        environment["SULDE_AGENT_PROVIDER"] = "codex"
        completed = subprocess.run(
            [
                sys.executable,
                str(RUNTIME),
                "run",
                str(worktree),
                slug,
                str(brief),
                "--brief-sha256",
                hashlib.sha256(brief.read_bytes()).hexdigest(),
                "--control-root",
                str(worktree / "coordinator" / "guardian-program"),
                "--task-definition",
                str(task),
                "--task-definition-sha256",
                hashlib.sha256(task.read_bytes()).hexdigest(),
                "--task-id",
                "T91",
                *[
                    argument
                    for owned_path in owned_paths
                    for argument in ("--owned-path", owned_path)
                ],
                "--timeout",
                "5",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=environment,
            check=False,
            timeout=60,
        )
        return completed, worktree

    def test_root_report_md_is_rejected_before_any_provider_launch(self) -> None:
        completed, worktree = self._run_production(["REPORT.md"])
        self.assertEqual(completed.returncode, 2, completed.stdout + completed.stderr)
        self.assertIn(
            "task must own exactly one supported program durable report",
            completed.stderr,
        )
        self.assertFalse(
            (worktree / ".codex-agent/dur-report.run.jsonl").is_file(),
            "rejection must happen before any provider launch",
        )

    def test_missing_durable_report_is_rejected_before_launch(self) -> None:
        completed, worktree = self._run_production(["base.txt"])
        self.assertEqual(completed.returncode, 2)
        self.assertIn(
            "task must own exactly one supported program durable report",
            completed.stderr,
        )
        self.assertFalse((worktree / ".codex-agent/dur-report.run.jsonl").is_file())

    def test_conflicting_durable_reports_are_rejected_before_launch(self) -> None:
        completed, worktree = self._run_production(
            ["guardian-program/reports/one.md", "life-program/reports/two.md"]
        )
        self.assertEqual(completed.returncode, 2)
        self.assertIn(
            "task must own exactly one supported program durable report",
            completed.stderr,
        )
        self.assertFalse((worktree / ".codex-agent/dur-report.run.jsonl").is_file())

    def test_legitimate_single_report_passes_the_preflight(self) -> None:
        completed, worktree = self._run_production(
            ["guardian-program/reports/one.md"], slug="dur-ok"
        )
        # The durable-report preflight passes; the run then proceeds to the
        # production provider gates (no installed native authority in the
        # test host), which is a *different*, later failure.
        self.assertNotIn(
            "task must own exactly one supported program durable report",
            completed.stderr,
        )
        self.assertNotIn(
            "durable report authority drifted", completed.stderr
        )
        # The durable-report preflight passed; the run proceeds to the
        # production provider gates, whose failure message differs between a
        # developer host (no installed authority) and the isolated runner
        # (no deployment descriptor). Either proves the gate order.
        self.assertTrue(
            "not from the installed generation" in completed.stderr
            or "installed deployment descriptor is unavailable" in completed.stderr,
            completed.stderr,
        )
        self.assertFalse(
            (worktree / ".codex-agent/dur-ok.run.jsonl").is_file(),
            "still pre-provider: no model process was ever launched",
        )


class PreflightProbeSafetyTests(unittest.TestCase):
    def test_probe_never_overwrites_existing_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_dir = Path(directory) / "state"
            state_dir.mkdir()
            probe = state_dir / ".launch-preflight-report-probe"
            probe.write_text("precious", encoding="utf-8")
            with self.assertRaises(launch_description.LaunchPreflightError):
                launch_description.preflight_launch_description(
                    {
                        "provider": "claude",
                        "report_relative_path": "state/slug.last.md",
                        "report_contract": {
                            "schema": "s",
                            "headings": ["结果"],
                            "evidence_schema": "e",
                        },
                    },
                    state_dir=state_dir,
                    provider_executable_evidence="resolved",
                )
            self.assertEqual(probe.read_text(encoding="utf-8"), "precious")


class RequestIdempotencyWindowsTests(unittest.TestCase):
    """R1-04: crash windows, driven through the real CLI."""

    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.directory = Path(self._temporary.name)

    def prepare(self, slug: str) -> tuple[Path, Path]:
        worktree = self.directory / slug / "worktree"
        state = worktree / ".codex-agent"
        state.mkdir(parents=True)
        (worktree / "base.txt").write_text("base\n", encoding="utf-8")
        brief = state / f"{slug}.md"
        brief.write_text("# Task\n\nDo the work.\n", encoding="utf-8")
        brief.chmod(0o400)
        return worktree, brief

    def provider(self, directory: Path) -> Path:
        executable = directory / "codex"
        evidence = (
            "✅ 验证通过：`python -m unittest`，exit 0；输出 OK；"
            "candidate_sha256=" + "a" * 64 + "；execution_binding_sha256=" + "b" * 64
            + "；environment_sha256=" + "c" * 64
            + "；command_sha256=88d1e4ef3a5e210c702e32c1f294a637fcac036aae538cf3e0500c2c054b49c7"
            + "；count=1"
        )
        report_text = (
            "## 结果\n任务完成。\n" + evidence
            + "\n## 过程\np\n## 遇到的问题\n无\n"
            "## 解决方式\ns\n## 遗留风险与建议\n无\n"
        )
        executable.write_text(
            textwrap.dedent(
                f"""\
                #!/usr/bin/python3
                import sys
                from pathlib import Path
                args = sys.argv[1:]
                report = Path(args[args.index('--output-last-message') + 1])
                report.write_text({report_text!r}, encoding='utf-8')
                print('{{"type":"done"}}')
                """
            ),
            encoding="utf-8",
        )
        executable.chmod(0o755)
        return executable

    def _run(self, worktree: Path, slug: str, brief: Path, environment: dict):
        return subprocess.run(
            [
                sys.executable,
                str(RUNTIME),
                "run",
                str(worktree),
                slug,
                str(brief),
                "--timeout",
                "15",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=environment,
            check=False,
            timeout=60,
        )

    def _windows(self, slug: str, drop: set[str]) -> None:
        """Drop selected row types from the registry to simulate crash windows."""
        registry = self.directory / slug / "worktree" / ".codex-agent" / f"{slug}.dispatch.jsonl"
        rows = [
            json.loads(line)
            for line in registry.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        kept = [row for row in rows if row["type"] not in drop]
        registry.write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in kept),
            encoding="utf-8",
        )

    def _duplicate_case(self, slug: str, drop: set[str]) -> None:
        worktree, brief = self.prepare(slug)
        environment = os.environ.copy()
        environment.update(
            {
                "SULDE_TEST_MODE": "1",
                "SULDE_AGENT_PROVIDER": "codex",
                "SULDE_CODEX_EXE": str(self.provider(self.directory / slug)),
            }
        )
        first = self._run(worktree, slug, brief, environment)
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        self._windows(slug, drop)
        second = self._run(worktree, slug, brief, environment)
        self.assertEqual(
            second.returncode, 0, second.stdout + second.stderr
        )
        self.assertIn("duplicate_of_run", second.stdout)
        state = worktree / ".codex-agent"
        self.assertFalse(
            (state / f"{slug}.round1.run.jsonl").is_file(),
            "a completed request duplicate must never relaunch",
        )
        rows = [
            json.loads(line)
            for line in (state / f"{slug}.dispatch.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        opened = [row for row in rows if row["type"] == "dispatch.opened"]
        launched = [row for row in rows if row["type"] == "dispatch.launched"]
        self.assertEqual(
            len(opened), 1, "one request, one attempt — no new attempt on duplicate"
        )
        self.assertLessEqual(
            len(launched), 1, "at most one effective launch across all submissions"
        )
        self.assertFalse(
            (state / f"{slug}.round1.run.jsonl").exists(),
            "no second run round was ever started",
        )

    def test_crash_after_launched_row_lost_returns_existing_result(self) -> None:
        self._duplicate_case("win-launched", {"dispatch.launched", "dispatch.closed"})

    def test_crash_after_closed_row_lost_returns_existing_result(self) -> None:
        self._duplicate_case("win-closed", {"dispatch.closed"})


class RealProducerSampleTests(unittest.TestCase):
    """R1-05: the real producer sample, read-only, when the drive is present."""

    @unittest.skipUnless(
        REAL_SAMPLE.is_file(), "R1-05 evidence sample not mounted"
    )
    def test_real_comparison_sample_parses_as_complete(self) -> None:
        report = __import__("usage_ledger").scan_usage(
            REAL_SAMPLE,
            provider="codex",
            run_id="run-" + "e" * 24,
            slug="comparison",
        )
        self.assertEqual(report["state"], "complete")
        self.assertEqual(report["metrics"]["input_tokens"]["value"], 516328)
        self.assertEqual(report["metrics"]["cached_input_tokens"]["value"], 462720)
        self.assertEqual(report["metrics"]["output_tokens"]["value"], 8651)


class InstallerGenerationSwitchTests(unittest.TestCase):
    """R1-06: the installer-side projection with explicit scopes."""

    def test_projection_observes_and_blocks(self) -> None:
        import install_codex_plugin as installer

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state_dir = root / "state"
            state_dir.mkdir()
            lease = run_concurrency.acquire_run_slot(
                state_dir,
                max_concurrent=1,
                timeout_seconds=0.0,
                runtime_generation="gen-old:" + "a" * 64,
            )
            try:
                environment = {
                    "SULDE_ACTIVE_LEASES_DIRS": str(state_dir / "run-leases"),
                    "SULDE_GENERATION_SWITCH_POLICY": "observe",
                }
                with mock.patch.dict(os.environ, environment, clear=False):
                    report = installer._generation_switch_projection("gen-new:" + "b" * 64)
                self.assertFalse(report["compatible"])
                self.assertEqual(report["policy"], "observe")
                with mock.patch.dict(os.environ, environment, clear=False):
                    os.environ["SULDE_GENERATION_SWITCH_POLICY"] = "block"
                    with self.assertRaises(installer.InstallError):
                        installer._generation_switch_projection("gen-new:" + "b" * 64)
            finally:
                lease.release()

    def test_missing_scope_is_recorded_not_fatal_in_observe(self) -> None:
        import install_codex_plugin as installer

        with mock.patch.dict(
            os.environ,
            {
                "SULDE_ACTIVE_LEASES_DIRS": "/nonexistent/leases",
                "SULDE_GENERATION_SWITCH_POLICY": "observe",
            },
            clear=False,
        ):
            report = installer._generation_switch_projection("gen-new:" + "c" * 64)
        self.assertEqual(report["scopes"][0]["status"], "missing")
        # R2-04: a missing scope is UNKNOWN coverage — never "safe"; under
        # block policy it refuses the switch.
        self.assertIsNone(report["compatible"])
        self.assertEqual(report["coverage"], "unknown")


if __name__ == "__main__":
    unittest.main()
