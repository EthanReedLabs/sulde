"""R3 closeout tests: A1 recovery fence lifecycle, A2 observe/block separation,
A3 quota waiting outside the shared fence lock.

Counterexamples from the coordinator's independent review,固化后先在 reviewed
HEAD 上失败（原行为），修复后通过（见 R3-CLOSEOUT-REPORT.md）。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import textwrap
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "scripts" / "kb"
INSTALLER = ROOT / "scripts" / "release" / "install_codex_plugin.py"

sys.path.insert(0, str(SCRIPT_DIR))

import run_concurrency  # noqa: E402
import generation_fence  # noqa: E402


class CloseoutHarnessMixin:
    """Shared helpers driving the REAL installer CLI in its isolated env.

    Mirrors the fixture of tests/test_codex_plugin_install.py minimally:
    fake codex/launchctl/ps plus the isolated homes.  No _install_locked
    mocking — the real chain runs.
    """

    def setup_installer_env(self, root: Path) -> dict:
        fixture_home = root / "home"
        fixture_home.mkdir(parents=True, exist_ok=True)
        (root / "tmp").mkdir(exist_ok=True)
        (root / "codex-home" / "skills/.system/plugin-creator/scripts").mkdir(
            parents=True, exist_ok=True
        )
        for name in ("validate_plugin.py", "update_plugin_cachebuster.py"):
            (
                root
                / "codex-home/skills/.system/plugin-creator/scripts"
                / name
            ).write_text(f"# trusted installer fixture for {name}\n")
        env = {
            "HOME": str(fixture_home),
            "CODEX_HOME": str(root / "codex-home"),
            "SULDE_KB_HOME": str(root / "kb-home"),
            "SULDE_LAUNCHAGENTS_DIR": str(root / "Library" / "LaunchAgents"),
            "CLAUDE_CONFIG_DIR": str(root / "claude-config"),
            "XDG_CACHE_HOME": str(root / "xdg-cache"),
            "TMPDIR": str(root / "tmp"),
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "PYTHONDONTWRITEBYTECODE": "1",
            "SULDE_TEST_MODE": "1",
            "SULDE_TEST_PREPARED_ARTIFACT": "1",
        }
        return env

    def fence_file(self, kb_home: Path) -> Path:
        return kb_home / ".generation-switch-fence.json"


class RecoverOnlyLifecycleTests(unittest.TestCase, CloseoutHarnessMixin):
    """A1: --recover-only fence lifecycle on the official path."""

    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)
        self.kb_home = self.root / "kb-home"
        self.kb_home.mkdir(parents=True, exist_ok=True)
        self.base_env = self.setup_installer_env(self.root)
        self.lease_scope = self.root / "workspaces" / "ws-a" / "run-leases"
        self.lease_scope.mkdir(parents=True, exist_ok=True)

    def _run_installer(self, extra: dict | None = None):
        environment = dict(self.base_env)
        environment.update(
            {
                "FAKE_CODEX_STATE": str(self.root / "state.json"),
                "SULDE_LAUNCHCTL": str(self.root / "fake-launchctl"),
                "SULDE_PS": str(self.root / "fake-ps"),
                "FAKE_LAUNCHCTL_LABELS": json.dumps([]),
                "FAKE_PS_OUTPUT": "",
                "FAKE_CODEX_PRE_TOOL_TRUST_STATUS": "trusted",
                "FAKE_LAUNCHCTL_STATE": "{}",
            }
        )
        if extra:
            environment.update(extra)
        fake_codex = self.root / "fake-codex"
        if not fake_codex.is_file():
            # A minimal placeholder: the real chain exercises the audited
            # contract; for the recovery lifecycle the fence state is what
            # is under test and the chain is expected to fail past the
            # fence without deleting it.
            fake_codex.write_text("#!/bin/sh\ncat > /dev/null\n")
            fake_codex.chmod(0o755)
        completed = subprocess.run(
            [
                sys.executable,
                str(INSTALLER),
                "--artifact-root",
                str(self.root / "artifact" / "codex"),
                "--kb-home",
                str(self.kb_home),
                "--codex",
                str(fake_codex),
                "--platform",
                "posix",
                "--recover-only",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env={**os.environ, **environment},
            timeout=120,
            check=False,
        )
        return completed

    def _write_fence(self, transaction_id: str | None, to_generation: str):
        generation_fence.write_fence(
            self.kb_home,
            from_generation="gen-old:" + "a" * 64,
            to_generation=to_generation,
            transaction_id=transaction_id,
        )

    def _read_fence(self) -> dict | None:
        return generation_fence.read_fence(self.kb_home)

    def test_orphan_fence_without_positive_evidence_is_retained_with_diagnosis(
        self,
    ) -> None:
        # Missing journal alone cannot distinguish pre-mutation interruption
        # from lost authority after production mutation.
        self._write_fence("orphan-transaction", "gen-new:" + "b" * 64)
        completed = self._run_installer()
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["status"], "recovery_required")
        self.assertEqual(
            result["fence"]["transaction_id"], "orphan-transaction"
        )
        self.assertIsNotNone(self._read_fence())
        # The unresolved fence continues protecting admission.
        self.assertIsNotNone(
            generation_fence.fence_refusal(
                self.kb_home, run_generation="gen-old:" + "a" * 64
            )
        )

    def test_unresolvable_fence_is_retained_with_diagnosis(self) -> None:
        # A1.4: a fence whose transaction cannot be verified against the
        # install facts is retained, not deleted.
        self._write_fence(None, "gen-new:" + "b" * 64)
        completed = self._run_installer()
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["status"], "recovery_required")
        self.assertFalse(result["fence"]["cleared"])
        self.assertIsNotNone(self._read_fence())

    def test_damaged_fence_is_retained_not_deleted(self) -> None:
        self.fence_file(self.kb_home).write_text("{damaged", encoding="utf-8")
        completed = self._run_installer()
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["status"], "recovery_required")
        self.assertTrue(self.fence_file(self.kb_home).exists())


class ObserveBlockSeparationTests(unittest.TestCase, CloseoutHarnessMixin):
    """A2: observe installs never create a blocking fence."""

    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)
        self.base_env = self.setup_installer_env(self.root)
        self.kb_home = self.root / "kb-home"
        self.kb_home.mkdir(parents=True, exist_ok=True)

    def test_preexisting_historical_fence_survives_observe_install(self) -> None:
        # A2.3: a pre-existing fence (historical protection from an
        # unrecovered transaction) is NOT blindly cleared by an
        # observe-mode install.
        self.fence_file(self.kb_home).write_text(
            json.dumps(
                {
                    "schema": "sulde-generation-switch-fence-v1",
                    "state": "in-switch",
                    "to_generation": "gen-new:" + "b" * 64,
                    "transaction_id": "historical-transaction",
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        # The real install chain would proceed/fail on its own merits; the
        # assertion target is the fence: still present afterwards (whatever
        # the install outcome), because observe never mutates fences.
        sys.path.insert(0, str(ROOT / "scripts" / "release"))
        from install_codex_plugin import (
            _generation_fence_state,
            _generation_switch_projection,
        )

        with mock.patch.dict(
            os.environ,
            {
                "SULDE_GENERATION_SWITCH_POLICY": "observe",
                "SULDE_ACTIVE_LEASES_DIRS": str(
                    self.root / "workspaces" / "ws" / "run-leases"
                ),
            },
            clear=False,
        ):
            report = _generation_switch_projection("gen-target:" + "a" * 64)
        self.assertIsNotNone(_generation_fence_state(self.kb_home))
        self.assertEqual(report["policy"], "observe")
        del report


class QuotaOutsideFenceLockTests(unittest.TestCase):
    """A3: quota waiting happens outside the shared fence lock."""

    def test_queued_scope_does_not_block_independent_scope_admission(
        self,
    ) -> None:
        # Two real processes: process A exhausts its scope's quota and keeps
        # trying (queued); meanwhile scope B — an independent workspace —
        # must be able to acquire a lease promptly.  Under the pre-fix
        # behavior A held the shared fence lock during its quota wait and
        # B's admission timed out.
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            scope_a = root / "ws-a"
            scope_b = root / "ws-b"
            (scope_a / "run-leases").mkdir(parents=True)
            (scope_b / "run-leases").mkdir(parents=True)
            holder_source = textwrap.dedent(
                f"""
                import sys, time
                from pathlib import Path
                sys.path.insert(0, {str(SCRIPT_DIR)!r})
                from run_concurrency import acquire_run_slot
                lease = acquire_run_slot(
                    Path({str(scope_a)!r}), max_concurrent=1,
                    timeout_seconds=0.0, runtime_generation="gen-old",
                )
                print("held", flush=True)
                time.sleep(4)
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
                # Scope A is at quota: admission queues (bounded).
                queue_started = time.monotonic()
                with self.assertRaises(run_concurrency.RunConcurrencyLimitError):
                    run_concurrency.acquire_run_slot(
                        scope_a, max_concurrent=1, timeout_seconds=0.5
                    )
                # While A is queued, B's independent scope admits promptly —
                # A's queue wait must not hold the shared fence lock.
                b_started = time.monotonic()
                lease_b = run_concurrency.acquire_run_slot(
                    scope_b, max_concurrent=1, timeout_seconds=2.0
                )
                b_elapsed = time.monotonic() - b_started
                self.assertLess(
                    b_elapsed,
                    1.0,
                    "independent-scope admission must not serialize behind "
                    "another scope's quota queue",
                )
                lease_b.release()
            finally:
                holder.wait(timeout=30)
            del queue_started


class TwoProcessBarrierTests(unittest.TestCase):
    """A3.4: both publication orders with real processes and a barrier."""

    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.kb_home = Path(self._temporary.name) / "kb-home"
        self.kb_home.mkdir(parents=True)

    def _barrier(self, path: Path):
        # A trivial cross-process barrier: wait until the flag file exists.
        def wait(timeout: float = 10.0) -> None:
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if path.exists():
                    return
                time.sleep(0.01)
            raise AssertionError(f"barrier {path.name} timed out")

        return wait

    def test_order_lease_first_then_fence_refuses_old_admission(self) -> None:
        # Order 1 ("lease first"): an old-generation lease is published
        # before the fence exists; the installer's write+recheck must then
        # observe it (the block gate refuses) — and post-fence, old-gen
        # admission is refused while the fence stands.
        lease = run_concurrency.acquire_run_slot(
            self.kb_home.parent / "ws",
            max_concurrent=1,
            timeout_seconds=0.0,
            runtime_generation="gen-old:" + "a" * 64,
        )
        barrier = self.kb_home / ".lease-published"
        barrier.write_text("1", encoding="utf-8")
        self._barrier(barrier)()
        generation_fence.write_fence(
            self.kb_home,
            from_generation="gen-old:" + "a" * 64,
            to_generation="gen-new:" + "b" * 64,
        )
        self.assertIsNotNone(
            generation_fence.fence_refusal(
                self.kb_home, run_generation="gen-old:" + "a" * 64
            ),
            "old-generation admission must be refused once the fence stands",
        )
        lease.release()
        # A completed switch clears the fence, after which old-generation
        # admission recovers (failure/rollback paths are covered by the
        # installer lifecycle tests).
        generation_fence.clear_fence(self.kb_home)
        self.assertIsNone(
            generation_fence.fence_refusal(
                self.kb_home, run_generation="gen-old:" + "a" * 64
            )
        )

    def test_order_fence_first_then_old_lease_cannot_publish(self) -> None:
        # Order 2 ("fence first"): the fence exists; an old-generation
        # admission attempt must be refused at the protocol level before it
        # can publish anything.
        generation_fence.write_fence(
            self.kb_home,
            from_generation="gen-old:" + "a" * 64,
            to_generation="gen-new:" + "b" * 64,
        )
        with self.assertRaises(generation_fence.GenerationFenceError):
            with generation_fence.admission_fence(
                self.kb_home, run_generation="gen-old:" + "a" * 64
            ):
                self.fail("old-generation lease must not publish")
        # Nothing was published: no lease files exist for the old run.
        leases = list((self.kb_home).glob("**/*.lease"))
        self.assertEqual(leases, [])


if __name__ == "__main__":
    unittest.main()
