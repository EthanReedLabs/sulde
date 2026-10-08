"""Stable-entry migration and transaction tests: real installer, fake host I/O."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock

from tests.test_codex_plugin_install import CodexPluginInstallFixture, load_installer


@unittest.skipIf(os.name == "nt", "POSIX stable transport only")
class StableEntryInstallTests(CodexPluginInstallFixture, unittest.TestCase):
    hook_protocol = "stable-v1"

    def _legacy(self):
        old = self.codex_home / "plugins/cache/sulde-local/sulde/0.0.7-legacy"
        (old / "hooks").mkdir(parents=True)
        (old / ".codex-plugin").mkdir()
        (old / ".codex-plugin/plugin.json").write_text(
            json.dumps({"name": "sulde", "version": old.name}), encoding="utf-8")
        (old / "hooks/hooks.json").write_text(json.dumps({"hooks": {"PreToolUse": [
            {"hooks": [{"type": "command", "command": "bash ${PLUGIN_ROOT}/scripts/run-hook.sh pre-tool-use"}]}]
        }}), encoding="utf-8")
        return old

    def test_legacy_route_refuses_before_any_production_mutation(self):
        old = self._legacy()
        before = {str(path.relative_to(old)): path.read_bytes() for path in old.rglob("*") if path.is_file()}
        result = self.run_installer()
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("migration_required", result.stderr)
        self.assertFalse((self.kb_home / ".deployment.lock").exists())
        self.assertFalse((self.kb_home / ".install-recovery").exists())
        self.assertFalse((self.kb_home / "bin/sulde-codex-hook").exists())
        self.assertEqual(before, {str(path.relative_to(old)): path.read_bytes() for path in old.rglob("*") if path.is_file()})
        if self.state.is_file():
            self.assertEqual(json.loads(self.state.read_text(encoding="utf-8"))["effects"], {})

    def test_registry_garbage_missing_fields_and_duplicates_are_not_fresh(self):
        installer = load_installer()
        row = {"pluginId": "sulde@sulde-local", "name": "sulde", "marketplaceName": "sulde-local",
               "version": "1", "installed": True, "source": {"source": "local", "path": "/fixture"}}
        for value in ("garbage", "{}", '{"installed":null}',
                      json.dumps({"installed": [{"name": "sulde"}]}),
                      json.dumps({"installed": [row, row]})):
            with self.subTest(value=value):
                def host(command, **kwargs):
                    return installer.CommandResult(tuple(command), 0, value, "")
                with self.assertRaisesRegex(installer.InstallError, "migration_required"):
                    installer._stable_registry_installation(str(self.fake), host)

    def test_empty_inventory_preserves_codex_residues_but_allows_shared_claude(self):
        self.prepare_artifact()
        installer = load_installer()
        def host(command, **kwargs):
            return installer.CommandResult(tuple(command), 0, '{"installed":[]}' if "--json" in command else "", "")
        candidate = self.artifact / "plugins/sulde"
        for relative in ("deployment-generation.json", "bin/sulde-codex-hook"):
            path = self.kb_home / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("damaged historical identity", encoding="utf-8")
            with self.subTest(residue=relative):
                with self.assertRaisesRegex(installer.InstallError, "migration_required"):
                    installer._stable_entry_migration_gate(candidate, self.kb_home, str(self.fake), host, platform="posix")
                self.assertEqual(path.read_text(encoding="utf-8"), "damaged historical identity")
            path.unlink()
        shared = self.kb_home / "bin/.sulde-launchers.json"
        shared.write_text(json.dumps({"provider": "claude", "source_root": str(self.root / "claude")}), encoding="utf-8")
        self.assertEqual(installer._stable_entry_migration_gate(
            candidate, self.kb_home, str(self.fake), host, platform="posix")["status"], "fresh_install")

    def test_final_admission_refusal_never_publishes_bootstrap(self):
        self.assertEqual(self.run_installer().returncode, 0)
        bootstrap = self.kb_home / "bin/sulde-codex-hook"
        before = bootstrap.read_bytes()
        marker = self.root / "bootstrap-publish-called"
        shim = self.root / "admission-refusal.py"
        real = Path(__file__).resolve().parents[1] / "scripts/release/install_codex_plugin.py"
        shim.write_text(
            "import sys\nfrom pathlib import Path\n"
            f"sys.path.insert(0, {str(real.parent)!r})\n"
            "import install_codex_plugin as m\nimport codex_hook_entry as entry\n"
            "original=entry.publish\n"
            "def publish(*a, **k):\n"
            f" Path({str(marker)!r}).write_text('called', encoding='utf-8')\n"
            " return original(*a, **k)\nentry.publish=publish\n"
            "calls=0\ndef projection(generation):\n global calls\n calls+=1\n"
            " return {'policy':'block','compatible': calls == 1}\n"
            "m._generation_switch_projection=projection\nsys.exit(m.main())\n", encoding="utf-8")
        with mock.patch("tests.test_codex_plugin_install.INSTALLER", shim):
            result = self.run_installer()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("generation switch blocked at re-check", result.stderr)
        self.assertFalse(marker.exists(), "rollback is not a substitute for zero bootstrap publication")
        self.assertEqual(bootstrap.read_bytes(), before)

    def test_fresh_install_and_stable_update_keep_fresh_origin(self):
        first = self.run_installer()
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(json.loads(first.stdout)["hook_entry_migration"]["status"], "fresh_install")
        deployment = json.loads((self.kb_home / "deployment-generation.json").read_text(encoding="utf-8"))
        self.assertEqual(deployment["stable_hook_entry"]["lineage_origin"], "fresh-cache-root")
        second = self.run_installer()
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(json.loads(second.stdout)["hook_entry_migration"]["status"], "stable_update")

    def test_stable_update_accepts_old_sealed_bootstrap_from_previous_loader(self):
        first = self.run_installer()
        self.assertEqual(first.returncode, 0, first.stderr)
        bootstrap = self.kb_home / "bin/sulde-codex-hook"
        old = bootstrap.read_bytes()
        shim = self.root / "next-loader-install.py"
        real = Path(__file__).resolve().parents[1] / "scripts/release/install_codex_plugin.py"
        # Isolated producer implementation variant; no production source edit.
        # Both installs run the full real CLI transaction, not a mocked gate.
        shim.write_text(
            "import sys\n"
            f"sys.path.insert(0, {str(real.parent)!r})\n"
            "import codex_hook_entry as entry\n"
            "entry.LOADER += '\\n# next loader implementation revision\\n'\n"
            "import install_codex_plugin as m\nsys.exit(m.main())\n", encoding="utf-8")
        with mock.patch("tests.test_codex_plugin_install.INSTALLER", shim):
            second = self.run_installer()
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(json.loads(second.stdout)["hook_entry_migration"]["status"], "stable_update")
        self.assertNotEqual(bootstrap.read_bytes(), old)

    def test_stable_template_without_lineage_is_not_migration_proof(self):
        self.prepare_artifact()
        candidate = self.artifact / "plugins/sulde"
        old = self._legacy()
        (old / "hooks/hooks.json").write_bytes((candidate / "hooks/hooks.json").read_bytes())
        installer = load_installer()
        # The only host state injected is its read-only plugin inventory.
        def host(command, **kwargs):
            return installer.CommandResult(tuple(command), 0, '{"installed": []}' if "--json" in command else "", "")
        with self.assertRaisesRegex(installer.InstallError, "migration_required"):
            installer._stable_entry_migration_gate(candidate, self.kb_home, str(self.fake), host, platform="posix")

    def test_new_legacy_path_before_prune_invalidates_empty_inventory(self):
        self.prepare_artifact()
        installer = load_installer()
        def host(command, **kwargs):
            return installer.CommandResult(tuple(command), 0, '{"installed": []}' if "--json" in command else "", "")
        projection = installer._stable_entry_migration_gate(
            self.artifact / "plugins/sulde", self.kb_home, str(self.fake), host, platform="posix")
        self.assertEqual(projection["status"], "fresh_install")
        self._legacy()
        with self.assertRaisesRegex(installer.InstallError, "migration_required"):
            installer._recheck_stable_entry_before_prune(projection, str(self.fake), host)

    def test_legacy_candidate_does_not_claim_stable_migration(self):
        old = self._legacy()
        installer = load_installer()
        def no_host_call(command, **kwargs):
            self.fail("legacy transport must not gain a stable-lineage claim")
        result = installer._stable_entry_migration_gate(
            old, self.kb_home, str(self.fake), no_host_call, platform="posix")
        self.assertEqual(result, {"status": "legacy_unverified", "coverage": "not_assessed"})

    def test_stable_lineage_cannot_downgrade_to_cache_command(self):
        old = self._legacy()
        self.kb_home.mkdir(parents=True)
        (self.kb_home / "deployment-generation.json").write_text(
            json.dumps({"stable_hook_entry": {"lineage_origin": "fresh-cache-root"}}), encoding="utf-8")
        installer = load_installer()
        with self.assertRaisesRegex(installer.InstallError, "cannot downgrade"):
            installer._stable_entry_migration_gate(old, self.kb_home, str(self.fake),
                                                  installer.run_command, platform="posix")

    def test_entry_publish_hard_exit_recovers_bootstrap_but_keeps_bundle(self):
        result = self.run_installer(failpoint="hook_entry.after_publish")
        self.assertEqual(result.returncode, 86, result.stderr)
        bootstrap = self.kb_home / "bin/sulde-codex-hook"
        self.assertTrue(bootstrap.is_file())
        bundles = sorted((self.kb_home / "hook-entry").iterdir())
        self.assertTrue(bundles)
        recovery = self.run_installer(recover_only=True)
        self.assertEqual(recovery.returncode, 0, recovery.stderr)
        self.assertFalse(bootstrap.exists())
        self.assertEqual(sorted((self.kb_home / "hook-entry").iterdir()), bundles)
        self.assertFalse((self.kb_home / ".install-recovery/active.json").exists())

    def test_new_registered_command_survives_cache_removal_then_rolls_back(self):
        first = self.run_installer()
        self.assertEqual(first.returncode, 0, first.stderr)
        result = json.loads(first.stdout)
        installed = Path(result["installed_path"])
        document = json.loads((installed / "hooks/hooks.json").read_text(encoding="utf-8"))
        command = document["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
        self.assertNotIn("PLUGIN_ROOT", command)
        before = (self.kb_home / "bin/sulde-codex-hook").read_bytes()
        interrupted = self.run_installer(failpoint="registry.after_remove")
        self.assertEqual(interrupted.returncode, 86, interrupted.stderr)
        self.assertFalse(installed.exists())
        # Start NEW processes after the old versioned path was deleted, using
        # the actual registered command string, never the cached wrapper.
        for tool in ("Read", "Write", "new-unknown-tool"):
            with self.subTest(tool=tool):
                payload = {"hook_event_name": "PreToolUse", "session_id": "stable-window",
                           "call_id": "stable-" + tool, "tool_name": tool,
                           "tool_input": {"file_path": "private-sentinel"}}
                probe = subprocess.run(["/bin/sh", "-c", command], input=json.dumps(payload),
                                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15,
                                       env={**os.environ, "SULDE_KB_HOME": str(self.kb_home),
                                            "PYTHONDONTWRITEBYTECODE": "1"})
                self.assertEqual(probe.returncode, 0, probe.stderr)
                output = json.loads(probe.stdout) if probe.stdout.strip() else {}
                self.assertEqual(output.get("hookSpecificOutput", {}).get("permissionDecision"),
                                 None if tool == "Read" else "deny", (probe.stdout, probe.stderr))
        recovery = self.run_installer(recover_only=True)
        self.assertEqual(recovery.returncode, 0, recovery.stderr)
        self.assertEqual((self.kb_home / "bin/sulde-codex-hook").read_bytes(), before)
        self.assertTrue(installed.is_dir())


if __name__ == "__main__":
    unittest.main()
