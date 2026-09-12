"""Synthetic regressions for portable, installation-bound CLI identities."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "portable_codex_contract_test", ROOT / "scripts/kb/codex_cli_contract.py"
)
contract = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(contract)


class CodexExecutableBindingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="sulde-cli-binding-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.executable = self.root / "custom tool with spaces"
        self.executable.write_bytes(b"synthetic executable identity")
        self.binding = {
            "production_codex_executable": str(self.executable),
            "production_codex_resolved_executable": str(self.executable),
            "codex_executable_sha256": hashlib.sha256(self.executable.read_bytes()).hexdigest(),
        }

    def assert_rejected(self, binding):
        with self.assertRaises(contract.CodexCliContractError):
            contract.bound_codex_executable(binding)

    def test_nondefault_path_is_verified_without_path_or_environment_discovery(self):
        before = dict(self.binding)
        with (
            mock.patch.dict(os.environ, {"PATH": "", "SULDE_CODEX_EXE": "other-codex"}),
            mock.patch("shutil.which", side_effect=AssertionError("no runtime discovery")),
        ):
            self.assertEqual(contract.bound_codex_executable(self.binding), self.executable)
        self.assertEqual(self.binding, before)
        self.assertEqual(contract.DEFAULT_CODEX_EXECUTABLE, "codex")
        self.assertEqual(contract.NATIVE_AUTHORITY_SPEC_VERSION, 2)
        self.assertFalse(hasattr(contract, "AUDITED_CODEX_EXECUTABLE"))

    def test_noncanonical_or_malformed_paths_do_not_become_authority(self):
        for value in (None, True, [], "descriptor"):
            self.assert_rejected(value)
        for value in (None, True, 42, [], "", "codex", "./codex", "~/bin/codex",
                      str(self.root) + "/./custom tool with spaces",
                      str(self.root) + "//custom tool with spaces",
                      str(self.executable) + "\n"):
            with self.subTest(value=value):
                self.assert_rejected({**self.binding, "production_codex_executable": value})

    def test_content_or_recorded_resolved_path_drift_is_rejected(self):
        self.assert_rejected({**self.binding, "production_codex_resolved_executable": "codex"})
        for value in (None, False, 1, [], "A" * 64, "g" * 64, "0" * 63, "0" * 64):
            with self.subTest(digest=value):
                self.assert_rejected({**self.binding, "codex_executable_sha256": value})
        self.executable.write_bytes(b"changed after installation")
        self.assert_rejected(self.binding)

    def test_missing_and_directory_targets_are_rejected(self):
        self.executable.unlink()
        self.assert_rejected(self.binding)
        self.executable.mkdir()
        self.assert_rejected(self.binding)

    def test_missing_deployment_never_falls_back_to_path_or_environment(self):
        from tests.test_agent_runtime import load_runtime_module
        runtime = load_runtime_module()
        with (
            mock.patch.dict(os.environ, {"SULDE_KB_HOME": str(self.root),
                                         "SULDE_CODEX_EXE": str(self.executable)}),
            mock.patch.object(runtime.subprocess, "run") as probe,
            self.assertRaisesRegex(runtime.AgentRuntimeError, "descriptor is unavailable"),
        ):
            runtime.codex_capability_preflight(str(self.executable), [], test_mode=False)
        probe.assert_not_called()

    def test_installation_rejects_changes_during_cli_or_broker_probes(self):
        from tests.test_codex_plugin_install import load_installer
        installer = load_installer()
        plugin = self.root / "plugin"
        runtime_kb = plugin / "runtime/scripts/kb"
        runtime_kb.mkdir(parents=True)
        for name in ("agent-runtime.py", "codex_cli_contract.py", "native_agent_broker.py"):
            (runtime_kb / name).write_text("# synthetic installed module\n")
        broker = runtime_kb / "native_agent_broker.py"
        broker_result = json.dumps({
            "schema": "sulde-native-broker-self-check-v1",
            "broker_protocol_spec_version": installer.BROKER_PROTOCOL_SPEC_VERSION,
            "broker_sha256": hashlib.sha256(broker.read_bytes()).hexdigest(),
            "broker_path": str(broker.resolve()),
        })
        cli_result = {"version": installer.AUDITED_CODEX_VERSION,
                      "help_observation_sha256": hashlib.sha256(b"synthetic help").hexdigest()}
        generation = {"generation": "synthetic:runtime", "runtime_tree_sha256": "a" * 64}
        for boundary in ("cli", "broker"):
            def smoke(*args):
                if boundary == "cli":
                    self.executable.write_bytes(b"changed during CLI probe")
                return cli_result
            def runner(command, **kwargs):
                if boundary == "broker":
                    self.executable.write_bytes(b"changed during broker probe")
                return installer.CommandResult(tuple(command), 0, broker_result, "")
            self.executable.write_bytes(b"synthetic initial identity")
            with (
                self.subTest(boundary=boundary),
                mock.patch.dict(os.environ, {"SULDE_TEST_MODE": "0"}),
                mock.patch.object(installer, "_codex_cli_installed_smoke", side_effect=smoke),
                self.assertRaisesRegex(installer.InstallError, "changed"),
            ):
                installer._installed_native_runtime_authority(
                    plugin, generation, registry_codex=str(self.executable), runner=runner,
                )

    @unittest.skipIf(os.name == "nt", "POSIX symlink fixture")
    def test_alias_retarget_cannot_redirect_a_bound_executable(self):
        alias = self.root / "package-manager-alias"
        alias.symlink_to(self.executable)
        other = self.root / "other-executable"
        other.write_bytes(self.executable.read_bytes())
        alias.unlink()
        alias.symlink_to(other)
        self.assertEqual(contract.bound_codex_executable(self.binding), self.executable)
        # Even equal bytes do not authorize replacing the bound target by a symlink.
        self.executable.unlink()
        self.executable.symlink_to(other)
        self.assert_rejected(self.binding)


if __name__ == "__main__":
    unittest.main()
