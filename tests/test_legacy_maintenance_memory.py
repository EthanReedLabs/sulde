"""Real temporary databases and installer entry; host/provider remain fixtures."""
import json
import os
from pathlib import Path
import stat
import sqlite3
import tempfile
import unittest
from unittest import mock

from tests import test_legacy_maintenance_install as harness
from tests.test_memory_home_reconcile import create_db, plan, reconcile


@unittest.skipIf(os.name == 'nt', 'POSIX legacy retirement and maintenance')
class MaintenanceMemoryTests(harness.CodexPluginInstallFixture, unittest.TestCase):
    prepare_transition = harness.MaintenanceInstallTests.prepare_transition
    transition = harness.MaintenanceInstallTests.transition

    def memory_pair(self):
        source = self.fixture_home / '.claude/plugins/data/sulde-cc/kb/memory.db'
        destination = self.kb_home / 'memory.db'
        source.parent.mkdir(parents=True)
        self.assertFalse(destination.exists())
        create_db(source, [(1, 'same-session', 'same-content', 1)])
        create_db(destination, [(1, 'same-session', 'same-content', 1)])
        result = reconcile(source, destination, archive_root=self.root / 'memory-archive')
        self.assertFalse(plan(source, destination)['reconcile_required'])
        facts = (source, destination, source.parent / '.sulde-memory-retired.json',
                 Path(result['archive_root']) / 'receipt.json')
        return source, destination, facts

    def test_settled_archive_does_not_block_or_reconcile(self):
        shim, _ = self.prepare_transition()
        source, destination, facts = self.memory_pair()
        before = {p: p.read_bytes() for p in facts}
        result = self.transition(shim, extra_environment={'MAINTENANCE_FORBID_MEMORY_WRITE': '1'})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(json.loads(result.stdout)['operational_ready'])
        self.assertEqual({p: p.read_bytes() for p in facts}, before)
        self.assertEqual(stat.S_IMODE(source.stat().st_mode), 0o444)
        self.assertFalse(plan(source, destination)['reconcile_required'])

    def test_writable_legacy_refuses_before_claim_and_publication(self):
        shim, _ = self.prepare_transition()
        source, _, _ = self.memory_pair()
        source.chmod(0o644)
        before = (self.kb_home / 'deployment-generation.json').read_bytes()
        result = self.transition(shim, extra_environment={'MAINTENANCE_FORBID_MEMORY_WRITE': '1'})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('maintenance cannot silently include', result.stderr)
        self.assertEqual((self.kb_home / 'deployment-generation.json').read_bytes(), before)
        self.assertFalse((self.kb_home / '.install-recovery/maintenance-claims').exists())
        self.assertFalse((self.kb_home / '.install-recovery/active.json').exists())

    def test_ordinary_install_still_reconciles_pending_memory(self):
        initial = self.run_installer()
        self.assertEqual(initial.returncode, 0, initial.stderr)
        source, destination, _ = self.memory_pair()
        source.chmod(0o644)
        result = self.run_installer()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)['memory_reconciliation']['ready'])
        self.assertFalse(plan(source, destination)['reconcile_required'])

    def test_missing_entries_refuse_before_claim(self):
        shim, _ = self.prepare_transition()
        _, destination, facts = self.memory_pair()
        with sqlite3.connect(destination) as db:
            db.execute('DELETE FROM mem_entries')
        before = {p: p.read_bytes() for p in facts}
        deployment = (self.kb_home / 'deployment-generation.json').read_bytes()
        result = self.transition(shim, extra_environment={'MAINTENANCE_FORBID_MEMORY_WRITE': '1'})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('maintenance cannot silently include', result.stderr)
        self.assertEqual({p: p.read_bytes() for p in facts}, before)
        self.assertEqual((self.kb_home / 'deployment-generation.json').read_bytes(), deployment)
        self.assertFalse((self.kb_home / '.install-recovery/maintenance-claims').exists())
        self.assertFalse((self.kb_home / '.install-recovery/active.json').exists())

    def test_drift_after_publication_refuses_without_memory_write(self):
        shim, _ = self.prepare_transition()
        _, _, facts = self.memory_pair()
        before = {p: p.read_bytes() for p in facts}
        deployment = (self.kb_home / 'deployment-generation.json').read_bytes()
        result = self.transition(shim, extra_environment={
            'MAINTENANCE_FORBID_MEMORY_WRITE': '1', 'MAINTENANCE_CASE': 'memory-drift-after-publish'})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('maintenance cannot silently include', result.stderr)
        self.assertEqual({p: p.read_bytes() for p in facts}, before)
        self.assertEqual((self.kb_home / 'deployment-generation.json').read_bytes(), deployment)
        self.assertFalse((self.kb_home / '.install-recovery/active.json').exists())

    def test_captured_home_source_cannot_enter_migration_writer(self):
        shim, _ = self.prepare_transition()
        deployment = (self.kb_home / 'deployment-generation.json').read_bytes()
        result = self.transition(shim, extra_environment={
            'MAINTENANCE_CASE': 'home-source-observation-race'})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('maintenance cannot silently include', result.stderr)
        self.assertNotIn('maintenance reached home migration writer', result.stderr)
        self.assertEqual((self.kb_home / 'deployment-generation.json').read_bytes(), deployment)
        self.assertFalse((self.kb_home / '.install-recovery/active.json').exists())


class MaintenanceMemoryPreflightTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.home = self.root / 'home'
        self.kb = self.root / 'sulde/data/kb'
        self.source = self.home / '.claude/plugins/data/sulde-cc/kb/memory.db'
        self.kb.mkdir(parents=True)
        self.source.parent.mkdir(parents=True)
        self.destination = self.kb / 'memory.db'
        create_db(self.source, [(1, 'same', 'content', 1)])
        create_db(self.destination, [(1, 'same', 'content', 1)])
        self.source.chmod(0o444)
        patch = mock.patch.dict(os.environ, {'HOME': str(self.home), 'SULDE_HOME': str(self.root/'sulde')})
        patch.start()
        self.addCleanup(patch.stop)
        self.installer = harness.load_installer()

    def test_no_archive_and_settled_archive(self):
        self.installer._maintenance_migration_preflight(self.kb)
        self.source.rename(self.source.with_suffix('.retired'))
        self.installer._maintenance_migration_preflight(self.kb)

    def test_missing_entries_refuse(self):
        with sqlite3.connect(self.destination) as db:
            db.execute('DELETE FROM mem_entries')
        self.assertTrue(plan(self.source, self.destination)['reconcile_required'])
        with self.assertRaisesRegex(self.installer.InstallError, 'cannot silently include'):
            self.installer._maintenance_migration_preflight(self.kb)

    def test_writable_archive_and_later_drift_refuse(self):
        self.installer._maintenance_migration_preflight(self.kb)
        self.source.chmod(0o644)
        with self.assertRaisesRegex(self.installer.InstallError, 'cannot silently include'):
            self.installer._maintenance_migration_preflight(self.kb)

    def test_corrupt_database_refuses(self):
        self.source.chmod(0o644)
        self.source.write_bytes(b'not a sqlite database')
        self.source.chmod(0o444)
        with self.assertRaisesRegex(self.installer.InstallError, 'preflight failed'):
            self.installer._maintenance_migration_preflight(self.kb)

    def test_home_migration_remains_forbidden(self):
        self.kb.rename(self.root / 'saved-kb')
        with self.assertRaisesRegex(self.installer.InstallError, 'cannot silently include'):
            self.installer._maintenance_migration_preflight(self.kb)

    def test_unknown_plan_and_read_failure_refuse(self):
        for value in ({}, {'ready': True}, {'ready': 1, 'reconcile_required': False},
                      {'ready': True, 'reconcile_required': 0}, None):
            with self.subTest(value=value), mock.patch.object(self.installer, 'plan_memory_reconciliation', return_value=value):
                with self.assertRaises(self.installer.InstallError):
                    self.installer._maintenance_migration_preflight(self.kb)
        with mock.patch.object(self.installer, 'plan_memory_reconciliation', side_effect=PermissionError('fixture denied')):
            with self.assertRaisesRegex(self.installer.InstallError, 'preflight failed'):
                self.installer._maintenance_migration_preflight(self.kb)

    def test_prepare_draft_rechecks_real_database_before_artifact_or_draft(self):
        import legacy_maintenance
        import candidate_codex_plugin as candidate
        state = {'status': 'verified', 'receipt_sha256': 'a'*64,
                 'codex': {'executable': str(self.root/'fake-codex')},
                 'artifact': {'path': str(self.root/'artifact')}}
        kwargs = dict(candidate_home=str(self.root), candidate_id='fixture',
                      kb_home=str(self.kb), codex_home=str(self.root/'codex'),
                      launcher_home=str(self.root/'sulde'), user_home=str(self.home),
                      launchagents_dir=str(self.root/'launchagents'), output=str(self.root/'draft.json'))
        with mock.patch.object(candidate, '_load_state', return_value=state), \
                mock.patch.object(candidate, '_load_sealed', return_value={'receipt_sha256': 'a'*64}), \
                mock.patch.object(candidate.installer, 'validate_staged_marketplace', side_effect=RuntimeError('artifact boundary')) as boundary:
            with self.assertRaisesRegex(RuntimeError, 'artifact boundary'):
                legacy_maintenance.prepare_draft(**kwargs)
            boundary.assert_called_once()
            boundary.reset_mock()
            self.source.chmod(0o644)
            with self.assertRaisesRegex(candidate.installer.InstallError, 'cannot silently include'):
                legacy_maintenance.prepare_draft(**kwargs)
            boundary.assert_not_called()
        self.assertFalse((self.root/'draft.json').exists())


if __name__ == '__main__':
    unittest.main()
