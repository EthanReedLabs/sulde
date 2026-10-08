from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "kb"))
sys.path.insert(0, str(ROOT / "scripts" / "release"))

import install_codex_plugin as installer
from sulde_paths import launcher_home as canonical_launcher_home, layout
from sulde_paths import (
    CONTRACT_IDENTITY_SCHEMA,
    CURRENT_HOME_SCHEMA,
    SuldePathError,
    _protected_json,
    contract_identity_digest,
)


class SuldePathTests(unittest.TestCase):
    def test_fresh_codex_home_is_provider_neutral(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            user = Path(name) / "user"
            with mock.patch.object(Path, "home", return_value=user), mock.patch.dict(
                os.environ, {}, clear=False
            ):
                os.environ.pop("SULDE_HOME", None)
                os.environ.pop("SULDE_KB_HOME", None)
                selected = layout()
                neutral = (user / ".sulde").resolve()
                self.assertEqual(selected.root, neutral)
                self.assertEqual(selected.bin, neutral / "bin")
                self.assertEqual(selected.kb, neutral / "data" / "kb")
                self.assertEqual(installer.default_kb_home(), selected.kb)
                self.assertEqual(installer.launcher_home(selected.kb), selected.root)
                self.assertEqual(canonical_launcher_home(selected.kb), selected.root)

    def test_explicit_compatibility_kb_keeps_self_contained_launchers(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            explicit = Path(name) / "portable-kb"
            self.assertEqual(installer.launcher_home(explicit), explicit.resolve())
            self.assertEqual(canonical_launcher_home(explicit), explicit.resolve())

    def test_codex_hook_bridge_has_no_claude_home_dependency(self) -> None:
        for relative in (
            "integrations/codex/plugins/sulde/scripts/run-hook.sh",
            "integrations/codex/plugins/sulde/scripts/run-hook.ps1",
        ):
            source = (ROOT / relative).read_text(encoding="utf-8")
            self.assertNotIn(".claude/plugins/data/sulde-cc/kb", source)
            self.assertIn(".sulde", source)


class ProtectedJsonCompatibilityTests(unittest.TestCase):
    """Run on the scheduler's Python 3.9 as well as the developer interpreter."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.path = self.root / "private.json"
        self.original = b'{"synthetic": true}\n'
        self.path.write_bytes(self.original)
        self.path.chmod(0o600)

    def test_private_regular_file_preserves_bytes_and_permissions(self) -> None:
        for mode in (0o600, 0o400):
            with self.subTest(mode=oct(mode)):
                self.path.chmod(mode)
                before = self.path.lstat()
                self.assertEqual(
                    _protected_json(self.path, "fixture"),
                    ({"synthetic": True}, self.original),
                )
                after = self.path.lstat()
                self.assertEqual(after.st_mode, before.st_mode)
                self.assertEqual(after.st_mtime_ns, before.st_mtime_ns)
                self.assertEqual(self.path.read_bytes(), self.original)

    @unittest.skipIf(os.name == "nt", "symlink privilege varies on Windows")
    def test_symlinks_and_broken_symlinks_are_rejected(self) -> None:
        for name, target in (("link", self.path), ("broken", self.root / "absent")):
            with self.subTest(name=name):
                link = self.root / name
                link.symlink_to(target)
                with self.assertRaises(SuldePathError):
                    _protected_json(link, "fixture")
                self.assertTrue(link.is_symlink())
        self.assertEqual(self.path.read_bytes(), self.original)

    @unittest.skipIf(os.name == "nt", "POSIX owner-only permissions")
    def test_non_owner_only_modes_are_rejected(self) -> None:
        for mode in (0o644, 0o640, 0o604):
            with self.subTest(mode=oct(mode)):
                self.path.chmod(mode)
                with self.assertRaisesRegex(SuldePathError, "not owner-only"):
                    _protected_json(self.path, "fixture")

    @unittest.skipIf(os.name == "nt", "POSIX ownership")
    def test_wrong_owner_is_rejected(self) -> None:
        with mock.patch("sulde_paths.os.getuid", return_value=self.path.stat().st_uid + 1):
            with self.assertRaisesRegex(SuldePathError, "not owner-only"):
                _protected_json(self.path, "fixture")

    def test_invalid_json_and_non_object_are_rejected(self) -> None:
        for payload in (b"{", b"\xff", b"[]", b"null"):
            with self.subTest(payload=payload):
                self.path.write_bytes(payload)
                with self.assertRaises(SuldePathError):
                    _protected_json(self.path, "fixture")
                self.assertEqual(self.path.read_bytes(), payload)

    def test_missing_and_directory_paths_are_rejected(self) -> None:
        for path in (self.root / "missing", self.root):
            with self.subTest(path=path.name):
                with self.assertRaises(SuldePathError):
                    _protected_json(path, "fixture")

    def _migration_fixture(self):
        # Construct an already-migrated home. Do not invoke a migration writer
        # to test readers, and never depend on the operator's current pointer.
        selected = layout(home=self.root / "neutral")
        selected.control.mkdir(parents=True)
        relative = "intent/workspaces/synthetic.active.json"
        legacy = self.root / "legacy" / relative
        legacy_digest = hashlib.sha256(str(legacy).encode()).hexdigest()
        identity = {
            "schema": CONTRACT_IDENTITY_SCHEMA,
            "transaction_id": "synthetic-migration",
            "source": str(self.root / "legacy"),
            "kb_home": str(selected.kb),
            "identities": {relative: legacy_digest},
        }
        identity_bytes = json.dumps(identity, sort_keys=True).encode()
        identity_path = selected.control / "contract-identities.json"
        identity_path.write_bytes(identity_bytes)
        identity_path.chmod(0o600)
        pointer = {
            "schema": CURRENT_HOME_SCHEMA,
            "status": "active",
            "sulde_home": str(selected.root),
            "kb_home": str(selected.kb),
            "source": str(self.root / "legacy"),
            "transaction_id": "synthetic-migration",
            "contract_identity_map_sha256": hashlib.sha256(identity_bytes).hexdigest(),
        }
        pointer_path = selected.control / "current-home.json"
        pointer_path.write_text(json.dumps(pointer), encoding="utf-8")
        pointer_path.chmod(0o600)
        patcher = mock.patch.dict(os.environ, {
            "SULDE_HOME": str(selected.root), "SULDE_KB_HOME": str(selected.kb),
        })
        patcher.start()
        self.addCleanup(patcher.stop)
        return selected, relative, legacy_digest, pointer_path, identity_path

    def test_migrated_identity_and_consumers_preserve_history(self) -> None:
        from approval_invariant import _contract_digest as approval_digest
        from correction_intervention import contract_digest as correction_digest
        from intervention import contract_digest as effect_digest
        from native_decision_journal import _contract_digest as native_digest

        selected, relative, expected, pointer, identity = self._migration_fixture()
        before = (pointer.read_bytes(), identity.read_bytes())
        for reader in (contract_identity_digest, approval_digest, correction_digest,
                       effect_digest, native_digest):
            with self.subTest(reader=reader.__module__):
                self.assertEqual(reader(selected.kb / relative), expected)
        self.assertEqual((pointer.read_bytes(), identity.read_bytes()), before)

    def test_new_contract_does_not_inherit_a_legacy_identity(self) -> None:
        selected, _, _, _, _ = self._migration_fixture()
        new = selected.kb / "intent/workspaces/new.active.json"
        self.assertEqual(contract_identity_digest(new), hashlib.sha256(str(new).encode()).hexdigest())

    def test_tampered_identity_map_is_rejected(self) -> None:
        selected, relative, _, _, identity = self._migration_fixture()
        identity.write_bytes(b"{}\n")
        with self.assertRaisesRegex(SuldePathError, "digest differs"):
            contract_identity_digest(selected.kb / relative)


if __name__ == "__main__":
    unittest.main()
