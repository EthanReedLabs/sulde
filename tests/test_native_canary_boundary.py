"""Exact candidate-owned writable roots; actual execution lives in native tests."""
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts/release'))
from native_pretool_canary import NativeCanary, NativeCanaryError


class NativeCanaryBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.slot = Path(self.directory.name).resolve()
        self.isolated = self.slot / 'isolated'
        self.sulde = self.isolated / 'sulde-home'
        self.workspace = self.sulde / 'workspace'
        self.target = self.sulde / 'target'
        self.env = {'SULDE_HOME': str(self.sulde),
                    'CODEX_HOME': str(self.isolated / 'codex-home'),
                    'SULDE_KB_HOME': str(self.sulde / 'data/kb'),
                    'TMPDIR': str(self.isolated / 'tmp')}
        for path in (*self.env.values(), self.workspace, self.target):
            Path(path).mkdir(parents=True, exist_ok=True)

    def test_exact_roots_are_canonical_deduplicated_and_no_implicit_tmp(self):
        alias = self.sulde / 'alias'
        alias.symlink_to(self.target, target_is_directory=True)
        host = NativeCanary('fixture', self.workspace, self.env,
                            writable_workspaces=(alias, self.target))
        config = host.workspace_sandbox_config()
        self.assertEqual(config, {
            'writable_roots': sorted({str(self.workspace), str(self.target),
                                      self.env['SULDE_KB_HOME'], self.env['TMPDIR']}),
            'exclude_slash_tmp': True, 'exclude_tmpdir_env_var': True, 'network_access': False})
        self.assertNotIn(self.env['CODEX_HOME'], config['writable_roots'])

    def test_missing_state_or_temp_root_fails_closed(self):
        for key in ('SULDE_KB_HOME', 'TMPDIR'):
            with self.subTest(key=key):
                env = dict(self.env)
                del env[key]
                with self.assertRaisesRegex(NativeCanaryError, key):
                    NativeCanary('fixture', self.workspace, env).workspace_sandbox_config()

    def test_broad_and_external_roots_are_rejected(self):
        alias = self.sulde / 'external-alias'
        alias.symlink_to(self.slot, target_is_directory=True)
        for root in (self.slot, self.isolated, self.sulde, alias):
            with self.subTest(root=root), self.assertRaisesRegex(NativeCanaryError, 'exact candidate-owned'):
                NativeCanary('fixture', self.workspace, self.env,
                             writable_workspaces=(root,)).workspace_sandbox_config()

    def test_nonexistent_and_file_roots_are_rejected(self):
        with self.assertRaises(FileNotFoundError):
            NativeCanary('fixture', self.workspace, self.env,
                         writable_workspaces=(self.sulde / 'missing',)).workspace_sandbox_config()
        target = self.workspace / 'file'
        target.touch()
        with self.assertRaises(NativeCanaryError):
            NativeCanary('fixture', self.workspace, self.env,
                         writable_workspaces=(target,)).workspace_sandbox_config()
