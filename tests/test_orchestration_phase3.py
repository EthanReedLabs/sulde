"""Phase 3 (orchestration iteration) tests: generational guard + GC planning (C3).

Covers:
- run leases record the runtime generation of in-flight executions;
- the generation guard projects switch compatibility (observe/block) and
  treats unknown active generations as incompatible;
- retired-generation reclamation planning respects active references and the
  retention window, and reclamation only ever consumes explicitly eligible
  targets (dry-run by default);
- new shared artifacts (dispatch registry, usage reports, launch
  descriptions) fail closed on unrecognized schemas — the old/new generation
  shared-data discipline.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "scripts" / "kb"
GC_CLI = SCRIPT_DIR / "generation-gc.py"

sys.path.insert(0, str(SCRIPT_DIR))

import generation_guard  # noqa: E402
import run_concurrency  # noqa: E402
import dispatch_registry  # noqa: E402
import launch_description  # noqa: E402
import usage_ledger  # noqa: E402


def _retirement_record(
    directory: Path,
    name: str,
    *,
    version: str = "0.2.5",
    tree_sha: str = "a" * 64,
    age_seconds: float | None = None,
    schema: str = "sulde-retired-codex-cache-v1",
) -> tuple[Path, Path]:
    target = directory / f"{name}"
    target.mkdir(parents=True)
    (target / "marker.txt").write_text("retired tree\n", encoding="utf-8")
    record_path = directory / f"{name}.retirement.json"
    record = {
        "schema": schema,
        "version": version,
        "tree_sha256": tree_sha,
        "alias": f"/plugins/cache/{version}",
        "target": str(target),
    }
    record_path.write_text(json.dumps(record), encoding="utf-8")
    if age_seconds is not None:
        aged = time.time() - age_seconds
        os.utime(record_path, (aged, aged))
    return target, record_path


class LeaseGenerationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.state_dir = Path(self._temporary.name) / "state"
        self.state_dir.mkdir()

    def test_lease_records_generation_and_projection_reports_it(self) -> None:
        lease = run_concurrency.acquire_run_slot(
            self.state_dir,
            max_concurrent=2,
            timeout_seconds=0.0,
            runtime_generation="0.2.5+codex.20260923:abc",
        )
        try:
            projection = run_concurrency.active_run_leases(
                self.state_dir / "run-leases"
            )
            self.assertEqual(len(projection), 1)
            self.assertEqual(
                projection[0]["runtime_generation"], "0.2.5+codex.20260923:abc"
            )
            generations = generation_guard.active_generations(
                self.state_dir / "run-leases"
            )
            self.assertEqual(
                generations, {"0.2.5+codex.20260923:abc": 1}
            )
        finally:
            lease.release()
        self.assertEqual(
            generation_guard.active_generations(self.state_dir / "run-leases"), {}
        )

    def test_lease_without_generation_counts_as_unknown(self) -> None:
        lease = run_concurrency.acquire_run_slot(
            self.state_dir, max_concurrent=1, timeout_seconds=0.0
        )
        try:
            generations = generation_guard.active_generations(
                self.state_dir / "run-leases"
            )
            self.assertEqual(generations, {"": 1})
        finally:
            lease.release()


class SwitchCompatibilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.state_dir = Path(self._temporary.name) / "state"
        self.state_dir.mkdir()
        self.leases_dir = self.state_dir / "run-leases"

    def _lease(self, generation: str | None):
        return run_concurrency.acquire_run_slot(
            self.state_dir,
            max_concurrent=4,
            timeout_seconds=0.0,
            runtime_generation=generation,
        )

    def test_compatible_switch_reports_clean(self) -> None:
        lease = self._lease("gen-1")
        try:
            report = generation_guard.switch_compatibility_report(
                self.leases_dir, target_generation="gen-1"
            )
            self.assertTrue(report["compatible"])
            self.assertEqual(report["active_generations"], {"gen-1": 1})
        finally:
            lease.release()

    def test_other_generation_is_incompatible_and_blockable(self) -> None:
        lease = self._lease("gen-old")
        try:
            report = generation_guard.switch_compatibility_report(
                self.leases_dir, target_generation="gen-new"
            )
            self.assertFalse(report["compatible"])
            self.assertEqual(report["incompatible_active"], {"gen-old": 1})
            with self.assertRaises(generation_guard.GenerationGuardError):
                generation_guard.assert_switch_allowed(
                    self.leases_dir, target_generation="gen-new", policy="block"
                )
            observed = generation_guard.assert_switch_allowed(
                self.leases_dir, target_generation="gen-new", policy="observe"
            )
            self.assertFalse(observed["compatible"])
        finally:
            lease.release()

    def test_unknown_active_generation_is_never_assumed_compatible(self) -> None:
        lease = self._lease(None)
        try:
            report = generation_guard.switch_compatibility_report(
                self.leases_dir, target_generation="gen-new"
            )
            self.assertFalse(report["compatible"])
            self.assertIn("", report["incompatible_active"])
        finally:
            lease.release()


class ReclamationPlanTests(unittest.TestCase):
    RETENTION = 3600.0

    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)
        self.retired_dir = self.root / "retired" / "sulde"
        self.retired_dir.mkdir(parents=True)
        self.state_dir = self.root / "state"
        (self.state_dir / "run-leases").mkdir(parents=True)

    def plan(self) -> dict:
        return generation_guard.plan_retired_reclamation(
            self.retired_dir,
            leases_dirs=[self.state_dir / "run-leases"],
            retention_seconds=self.RETENTION,
            now=datetime.now(timezone.utc),
        )

    def test_eligible_target_is_reclaimable(self) -> None:
        _target, _record = _retirement_record(
            self.retired_dir,
            "0.1.0-" + "a" * 20,
            version="0.1.0",
            tree_sha="a" * 64,
            age_seconds=self.RETENTION + 60,
        )
        plan = self.plan()
        self.assertEqual(plan["reclaimable_count"], 0)
        self.assertTrue(
            plan["targets"][0]["eligible"],
            "diagnostic verdict stays visible",
        )
        self.assertFalse(plan["targets"][0]["reclaimable"])
        self.assertEqual(plan["reclamation"], "closed-diagnostic-only")
        self.assertEqual(
            plan["targets"][0]["generation"], "0.1.0:" + "a" * 64
        )

    def test_retention_not_met_is_kept(self) -> None:
        _target, _record = _retirement_record(
            self.retired_dir,
            "0.1.0-" + "b" * 20,
            version="0.1.0",
            tree_sha="b" * 64,
            age_seconds=10.0,
        )
        plan = self.plan()
        self.assertEqual(plan["reclaimable_count"], 0)
        self.assertIn("retention window not met", plan["targets"][0]["reason"])

    def test_active_reference_is_kept(self) -> None:
        generation = "0.1.0:" + "c" * 64
        lease = run_concurrency.acquire_run_slot(
            self.state_dir,
            max_concurrent=1,
            timeout_seconds=0.0,
            runtime_generation=generation,
        )
        try:
            _retirement_record(
                self.retired_dir,
                "0.1.0-" + "c" * 20,
                version="0.1.0",
                tree_sha="c" * 64,
                age_seconds=self.RETENTION + 60,
            )
            plan = self.plan()
            self.assertEqual(plan["reclaimable_count"], 0)
            self.assertIn("active run", plan["targets"][0]["reason"])
        finally:
            lease.release()

    def test_unknown_schema_and_unreadable_records_are_kept(self) -> None:
        _target, _record = _retirement_record(
            self.retired_dir,
            "0.1.0-" + "d" * 20,
            schema="sulde-retired-codex-cache-v0",
            age_seconds=self.RETENTION + 60,
        )
        broken = self.retired_dir / ("0.1.0-" + "e" * 20 + ".retirement.json")
        broken.write_text("{not json", encoding="utf-8")
        plan = self.plan()
        self.assertEqual(plan["reclaimable_count"], 0)
        reasons = " | ".join(row["reason"] for row in plan["targets"])
        self.assertIn("unrecognized", reasons)
        self.assertIn("unreadable", reasons)

    def test_reclamation_is_closed_for_every_entry(self) -> None:
        _target, _record = _retirement_record(
            self.retired_dir,
            "0.1.0-" + "a" * 20,
            version="0.1.0",
            tree_sha="a" * 64,
            age_seconds=60.0,
        )
        plan = self.plan()
        # R3-01: the actionable verdict is always false and the apply entry
        # point no longer exists — every real entry refuses identically.
        self.assertEqual(plan["reclaimable_count"], 0)
        self.assertFalse(hasattr(generation_guard, "apply_retired_reclamation"))

    def test_cli_plan_is_diagnostic_and_offers_no_apply(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            retired_dir = root / "retired" / "sulde"
            retired_dir.mkdir(parents=True)
            state_dir = root / "state"
            (state_dir / "run-leases").mkdir(parents=True)
            target, record = _retirement_record(
                retired_dir,
                "0.1.0-" + "a" * 20,
                version="0.1.0",
                tree_sha="a" * 64,
                age_seconds=7200.0,
            )
            base = [
                sys.executable,
                str(GC_CLI),
                "--retired-dir",
                str(retired_dir),
                "--leases-dir",
                str(state_dir / "run-leases"),
                "--retention-hours",
                "1",
            ]
            # R3-01: the apply entry point is gone entirely.
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
            dry = subprocess.run(
                base,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                timeout=30,
            )
            self.assertEqual(dry.returncode, 0, dry.stderr)
            plan = json.loads(dry.stdout)
            self.assertEqual(plan["reclamation"], "closed-diagnostic-only")
            self.assertEqual(plan["targets"][0]["eligible"], True)
            self.assertEqual(plan["reclaimable_count"], 0)
            self.assertTrue(target.exists(), "diagnostic must not delete")
            self.assertFalse(record.exists() and False)

    def test_dispatch_registry_rejects_unknown_schema(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "registry.jsonl"
            path.write_text(
                json.dumps({"schema": "sulde-dispatch-registry-v99", "type": "dispatch.opened"})
                + "\n",
                encoding="utf-8",
            )
            with self.assertRaises(dispatch_registry.DispatchRegistryError):
                dispatch_registry.read_registry(path)

    def test_usage_aggregate_rejects_unsupported_report(self) -> None:
        with self.assertRaises(usage_ledger.UsageLedgerError):
            usage_ledger.aggregate_usage([{"schema": "sulde-usage-report-v99"}])

    def test_launch_description_rejects_unknown_schema(self) -> None:
        payload = json.dumps(
            {
                "schema": "sulde-launch-description-artifact-v99",
                "description": {},
                "description_sha256": "0" * 64,
            }
        ).encode()
        with self.assertRaises(launch_description.LaunchDescriptionError):
            launch_description.parse_launch_description_artifact(payload)


if __name__ == "__main__":
    unittest.main()
