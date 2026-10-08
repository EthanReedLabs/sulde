"""Paired real binder tests and deterministic dependency-recovery injections."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path(os.environ.get("SULDE_TEST_SOURCE_ROOT", ROOT))
sys.path.insert(0, str(SOURCE / "scripts/kb"))
import intent_guardian as guardian

spec = importlib.util.spec_from_file_location(
    "dependency_restore", ROOT / "docs/guardian-effect-recovery-20261004/restore_dependency.py")
recovery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recovery)


class BinderDependencyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="sulde-effect-recovery-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.repo = self.root / "repo"
        self.repo.mkdir()
        manifest = self.repo / "integrations/codex/plugins/sulde/.codex-plugin/plugin.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text(json.dumps({"name": "sulde", "version": "0.2.5"}), encoding="utf-8")
        for relative in guardian.EXPLICIT_RELEASE_RUNTIME_INPUTS:
            path = self.repo / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# fixture\n", encoding="utf-8")
        for args in (["init"], ["add", "."]):
            subprocess.run(["git", *args], cwd=self.repo, check=True, capture_output=True)
        self.home = self.root / "codex"
        self.helper = self.home / "skills/.system/plugin-creator/scripts/update_plugin_cachebuster.py"
        self.helper.parent.mkdir(parents=True)
        self.helper.write_text("from identifier_validation import validate_plugin_identifier\n", encoding="utf-8")
        self.companion = self.helper.parent / "identifier_validation.py"
        self.companion.write_text("def validate_plugin_identifier(name): pass\n", encoding="utf-8")

    def bind(self, helper=None):
        with mock.patch.dict(os.environ, {"CODEX_HOME": str(self.home)}):
            return guardian._codex_plugin_cachebuster_binding(
                self.repo, cachebuster="test-1", interpreter=Path(sys.executable), helper=helper)

    def test_normal_pair_complete_dependency(self):
        binding, content = self.bind()
        self.assertEqual(binding["helper_sha256"], hashlib.sha256(self.helper.read_bytes()).hexdigest())
        self.assertEqual(json.loads(content)["version"], "0.2.5+codex.test-1")

    def test_missing_companion_rejected_before_seal(self):
        self.companion.unlink()
        with self.assertRaisesRegex(guardian.IntentGuardianError, "dependency is incomplete"):
            self.bind()

    def test_missing_helper_reports_actionable_path(self):
        self.helper.unlink()
        with self.assertRaisesRegex(guardian.IntentGuardianError, "restore a reviewed dependency"):
            self.bind()

    def test_alternate_helper_stays_rejected(self):
        other = self.root / "other.py"
        other.write_bytes(self.helper.read_bytes())
        with self.assertRaises(guardian.IntentGuardianError):
            self.bind(other)

    def test_broken_companion_rejected(self):
        self.companion.write_text("def (", encoding="utf-8")
        with self.assertRaisesRegex(guardian.IntentGuardianError, "cannot be inspected"):
            self.bind()


class RestoreDependencyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="sulde-effect-recovery-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.src, self.dst = self.root / "source", self.root / "target"
        self.src.mkdir()
        self.pins = {}
        for name in recovery.PINS:
            content = ("# synthetic fixture " + name).encode()
            (self.src / name).write_bytes(content)
            self.pins[name] = hashlib.sha256(content).hexdigest()
        self.patch = mock.patch.object(recovery, "PINS", self.pins)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_normal_recovery_dry_run_and_idempotent_readback(self):
        recovery.restore(self.src, self.dst)
        self.assertFalse(self.dst.exists())
        recovery.restore(self.src, self.dst, apply=True)
        before = {p.name: p.read_bytes() for p in self.dst.iterdir()}
        recovery.restore(self.src, self.dst, apply=True)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.dst.iterdir()})

    def test_source_drift_zero_destination_writes(self):
        (self.src / next(iter(self.pins))).write_bytes(b"drift")
        with self.assertRaisesRegex(ValueError, "archive digest mismatch"):
            recovery.restore(self.src, self.dst, apply=True)
        self.assertFalse(self.dst.exists())

    def test_destination_conflict_preserved_zero_other_writes(self):
        self.dst.mkdir()
        target = self.dst / "identifier_validation.py"
        target.write_bytes(b"user bytes")
        with self.assertRaisesRegex(ValueError, "destination conflict"):
            recovery.restore(self.src, self.dst, apply=True)
        self.assertEqual(target.read_bytes(), b"user bytes")
        self.assertEqual(len(list(self.dst.iterdir())), 1)

    def test_symlink_target_not_followed(self):
        self.dst.symlink_to(self.src, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlink"):
            recovery.restore(self.src, self.dst, apply=True)


if __name__ == "__main__":
    unittest.main()
