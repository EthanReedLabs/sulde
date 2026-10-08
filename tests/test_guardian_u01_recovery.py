"""Real installer fixtures; crash and storage loss stay outside recovery logic."""
from __future__ import annotations

import json
from pathlib import Path
import unittest
from unittest import mock

from tests import test_codex_plugin_install as fixtures


class GuardianU01RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.CodexPluginInstallTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.root = self.fixture.root
        self.home = self.fixture.kb_home
        self.recovery = self.home / ".install-recovery"
        self.fence = self.home / ".generation-switch-fence.json"
        self.leases = self.root / "leases"
        self.leases.mkdir()
        self.block = {"SULDE_GENERATION_SWITCH_POLICY": "block", "SULDE_ACTIVE_LEASES_DIRS": str(self.leases)}

    def install(self, **kwargs):
        result = self.fixture.run_installer(extra_environment=self.block, **kwargs)
        return result

    def recover(self):
        result = self.fixture.run_installer(recover_only=True, extra_environment={
            "SULDE_TEST_MODE": "1",
            "FAKE_LAUNCHCTL_STATE": str(self.root / "launchctl-state.json")})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def cleanup_fault(self, fault, *, recovery=False):
        """External fixture injection around real fence cleanup, never success."""
        bootstrap = '''
import sys, runpy
from pathlib import Path
from contextlib import contextmanager
from unittest import mock
sys.path.insert(0, str(Path(sys.argv[1]).resolve().parents[1] / "kb"))
import generation_fence
fault = sys.argv[2]
sys.argv = [sys.argv[1], *sys.argv[3:]]
original_clear = generation_fence.clear_fence
original_lock = generation_fence.fence_lock
if fault == "fsync":
    def fail_clear(home):
        with mock.patch.object(generation_fence.os, "fsync", side_effect=OSError("fixture fence fsync EIO")):
            return original_clear(home)
    generation_fence.clear_fence = fail_clear
elif fault == "lock":
    @contextmanager
    def fail_lock(home):
        if generation_fence.fence_path(home).exists():
            raise TimeoutError("fixture cleanup lock timeout")
        with original_lock(home):
            yield
    generation_fence.fence_lock = fail_lock
runpy.run_path(sys.argv[0], run_name="__main__")
'''
        original_run = fixtures.subprocess.run

        def injected_run(command, **kwargs):
            if len(command) > 1 and command[1] == str(fixtures.INSTALLER):
                command = [command[0], "-B", "-c", bootstrap, command[1], fault, *command[2:]]
            return original_run(command, **kwargs)

        with mock.patch.object(fixtures.subprocess, "run", injected_run):
            if recovery:
                return self.fixture.run_installer(recover_only=True, extra_environment={
                    "SULDE_TEST_MODE": "1",
                    "FAKE_LAUNCHCTL_STATE": str(self.root / "launchctl-state.json")})
            return self.install()

    def test_committed_fsync_error_never_rolls_back_and_preserves_active_authority(self):
        result = self.cleanup_fault("fsync")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("post-commit cleanup incomplete", result.stderr)
        self.assertFalse(self.fence.exists())  # real unlink happened before EIO
        self.assertTrue((self.recovery / "active.json").is_file())
        transaction = fixtures.load_installer().load_active_transaction(self.recovery)
        self.assertEqual(transaction.stage, "committed")
        self.assertTrue((self.home / "deployment-generation.json").is_file())
        self.assertEqual(self.recover()["status"], "recovered_new_generation")
        self.assertEqual(self.recover()["status"], "no_recovery_required")

    def test_committed_cleanup_lock_error_is_not_a_rollback(self):
        result = self.cleanup_fault("lock")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("post-commit cleanup incomplete", result.stderr)
        self.assertTrue(self.fence.exists())
        self.assertEqual(fixtures.load_installer().load_active_transaction(self.recovery).stage, "committed")
        self.assertEqual(self.recover()["status"], "recovered_new_generation")
        self.assertFalse(self.fence.exists())

    def test_recovery_cleanup_error_retains_real_committed_authority(self):
        crashed = self.install(failpoint="fence.before_clear")
        self.assertEqual(crashed.returncode, 86, crashed.stderr)
        result = self.cleanup_fault("fsync", recovery=True)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("recovery cleanup incomplete", result.stderr)
        self.assertFalse(self.fence.exists())
        self.assertEqual(fixtures.load_installer().load_active_transaction(self.recovery).stage, "committed")
        self.assertEqual(self.recover()["status"], "recovered_new_generation")

    def test_rollback_recovery_cleanup_error_retains_real_terminal_authority(self):
        crashed = self.install(failpoint="normalization.before_publish")
        self.assertEqual(crashed.returncode, 86, crashed.stderr)
        result = self.cleanup_fault("fsync", recovery=True)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("recovery cleanup incomplete", result.stderr)
        self.assertFalse(self.fence.exists())
        transaction = fixtures.load_installer().load_active_transaction(self.recovery)
        self.assertEqual(transaction.stage, "rolled_back")
        self.assertTrue(transaction.verify_restored_snapshot())
        self.assertEqual(self.recover()["status"], "recovered_old_generation")
        self.assertEqual(self.recover()["status"], "no_recovery_required")

    def test_missing_journal_is_not_positive_premutation_evidence(self):
        self.assertEqual(self.recover()["status"], "no_recovery_required")
        crashed = self.install(failpoint="normalization.before_publish")
        self.assertEqual(crashed.returncode, 86, crashed.stderr)
        active = json.loads((self.recovery / "active.json").read_text(encoding="utf-8"))
        self.assertRegex(active["transaction_id"], r"^[0-9a-f]{32}$")
        self.assertTrue(self.fence.is_file())
        # External loss simulation, retaining originals for postmortem.
        (self.recovery / "active.json").rename(self.root / "held-active.json")
        before = self.fence.read_bytes()
        # A detached nonterminal journal cannot manufacture a new active owner.
        self.assertEqual(self.recover()["status"], "recovery_required")
        self.assertFalse((self.recovery / "active.json").exists())
        self.assertEqual(self.fence.read_bytes(), before)
        (self.recovery / "transactions" / active["transaction_id"]).rename(self.root / "held-transaction")
        self.assertEqual(self.recover()["status"], "recovery_required")
        self.assertEqual(self.fence.read_bytes(), before)

    def test_publication_boundaries_have_no_fence_or_positive_recovery_authority(self):
        for boundary in ("transaction.before_journal", "transaction.after_journal", "transaction.before_active",
                         "transaction.after_active", "journal.before.prepared", "journal.after.prepared",
                         "fence.after_publish"):
            with self.subTest(boundary=boundary):
                crashed = self.install(failpoint=boundary)
                self.assertEqual(crashed.returncode, 86, crashed.stderr)
                active = (self.recovery / "active.json").exists()
                self.assertEqual(self.fence.exists(), boundary == "fence.after_publish")
                result = self.recover()
                self.assertEqual(result["status"], "recovered_old_generation" if active else "no_recovery_required")
                self.assertFalse(self.fence.exists())
                self.assertFalse((self.home / "deployment-generation.json").exists())
                self.assertEqual(self.recover()["status"], "no_recovery_required")

    def test_terminal_commit_survives_active_cleanup_before_fence_cleanup(self):
        crashed = self.install(failpoint="fence.before_clear")
        self.assertEqual(crashed.returncode, 86, crashed.stderr)
        # Simulate the previously legal active-first cleanup window externally;
        # new installs deliberately retain active until durable fence cleanup.
        (self.recovery / "active.json").rename(self.root / "held-committed-active.json")
        self.assertFalse((self.recovery / "active.json").exists())
        self.assertTrue(self.fence.exists())
        fence = json.loads(self.fence.read_text(encoding="utf-8"))
        descriptor = json.loads((self.recovery / "transactions" / fence["transaction_id"] /
                                 "descriptor.json").read_text(encoding="utf-8"))
        # Terminal stage alone is insufficient: independently inspect all live
        # registry/deployment/launcher/scheduler projections before releasing.
        for target in (self.fixture.state, Path(descriptor["expected_postconditions"]["deployment"]),
                       Path(descriptor["expected_postconditions"]["launcher"]),
                       self.root / "launchctl-state.json"):
            with self.subTest(drift=target.name):
                saved = target.read_bytes()
                target.write_text("{}", encoding="utf-8")
                before = self.fence.read_bytes()
                try:
                    self.assertEqual(self.recover()["status"], "recovery_required")
                    self.assertEqual(self.fence.read_bytes(), before)
                finally:
                    target.write_bytes(saved)
        result = self.recover()
        self.assertEqual(result["status"], "recovered_new_generation", result)
        self.assertTrue(result["fence"]["cleared"])
        self.assertFalse(self.fence.exists())
        self.assertEqual(self.recover()["status"], "no_recovery_required")

    def test_terminal_rollback_survives_active_cleanup_before_fence_cleanup(self):
        crashed = self.install(failpoint="normalization.before_publish")
        self.assertEqual(crashed.returncode, 86, crashed.stderr)
        interrupted = self.fixture.run_installer(recover_only=True,
            extra_environment={"SULDE_INSTALL_FAILPOINT": "fence.before_clear"})
        self.assertEqual(interrupted.returncode, 86, interrupted.stderr)
        (self.recovery / "active.json").rename(self.root / "held-rolledback-active.json")
        self.assertFalse((self.recovery / "active.json").exists())
        self.assertTrue(self.fence.exists())
        deployment = self.home / "deployment-generation.json"
        deployment.write_text("{}", encoding="utf-8")
        self.assertEqual(self.recover()["status"], "recovery_required")
        self.assertTrue(self.fence.exists())
        deployment.rename(self.root / "held-drifted-deployment.json")
        result = self.recover()
        self.assertEqual(result["status"], "recovered_old_generation")
        self.assertTrue(result["fence"]["cleared"])
        self.assertEqual(self.recover()["status"], "no_recovery_required")

    def test_legacy_or_foreign_fence_never_gains_authority_by_repeating_recovery(self):
        crashed = self.install(failpoint="normalization.before_publish")
        self.assertEqual(crashed.returncode, 86, crashed.stderr)
        fence = json.loads(self.fence.read_text(encoding="utf-8"))
        fence.pop("transaction_descriptor_sha256")
        self.fence.write_text(json.dumps(fence), encoding="utf-8")
        before = self.fence.read_bytes()
        self.assertFalse(self.recover()["fence"]["cleared"])
        self.assertEqual(self.recover()["status"], "recovery_required")
        self.assertEqual(self.fence.read_bytes(), before)
        fence["transaction_id"] = "f" * 32
        self.fence.write_text(json.dumps(fence), encoding="utf-8")
        before = self.fence.read_bytes()
        self.assertEqual(self.recover()["status"], "recovery_required")
        self.assertEqual(self.fence.read_bytes(), before)

    def test_block_install_cannot_overwrite_existing_fence(self):
        self.home.mkdir(exist_ok=True)
        self.fence.write_text('{"schema":"sulde-generation-switch-fence-v1","state":"in-switch"}', encoding="utf-8")
        before = self.fence.read_bytes()
        result = self.install()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unresolved generation fence", result.stderr)
        self.assertEqual(self.fence.read_bytes(), before)
        self.assertFalse((self.home / "deployment-generation.json").exists())

    def test_damaged_fence_is_retained_and_clear_requires_same_token(self):
        self.home.mkdir(exist_ok=True)
        self.fence.write_text("{broken", encoding="utf-8")
        self.assertEqual(self.recover()["status"], "recovery_required")
        self.assertEqual(self.fence.read_text(encoding="utf-8"), "{broken")
        installer = fixtures.load_installer()
        expected = {"schema": "sulde-generation-switch-fence-v1", "token": "a" * 32}
        changed = {**expected, "token": "b" * 32}
        self.fence.write_text(json.dumps(changed), encoding="utf-8")
        self.assertFalse(installer._clear_verified_generation_fence(self.home, expected))
        self.assertEqual(json.loads(self.fence.read_text(encoding="utf-8")), changed)
        transaction = mock.Mock(transaction_id="a" * 32)
        with self.assertRaisesRegex(installer.InstallError, "cleanup incomplete"):
            installer._finish_verified_transaction_cleanup(self.home, transaction, expected)
        transaction.clear_active.assert_not_called()


if __name__ == "__main__":
    unittest.main()
