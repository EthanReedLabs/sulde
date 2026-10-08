"""Explicit opt-in for the real CLI gates inside the isolated test runner.

The normal runner intentionally removes inherited SULDE_* state. Discover the
binary only at this installation/audit boundary, then bind its physical bytes.
No mocked CLI, model request, production install or interactive approval occurs.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest
from unittest import mock


@unittest.skipUnless(os.environ.get("CODEX_CONTRACT_AUDIT_LIVE") == "1",
                     "explicit CLI contract audit required")
class CodexLiveContractAuditTests(unittest.TestCase):
    def test_real_installer_staged_runtime_and_pty_contract(self):
        from tests.test_agent_runtime import (
            observe_audited_codex_help_from_parent,
        )
        from tests.test_codex_plugin_install import (
            exercise_audited_codex_native_authority_roundtrip,
        )
        executable = shutil.which("codex")
        self.assertIsNotNone(executable, "requested live audit requires Codex")
        path = Path(executable).resolve(strict=True)
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        version = subprocess.run([str(path), "--version"], capture_output=True,
                                 text=True, encoding="utf-8", errors="replace", timeout=15, check=False)
        self.assertEqual(version.returncode, 0)
        self.assertEqual(version.stdout.rstrip("\n"), "codex-cli 0.160.0")
        with mock.patch.dict(os.environ, {"SULDE_TEST_CODEX_EXECUTABLE": str(path)}):
            # Failure to allocate PTY is a failure, never a passing skip.
            pipe = observe_audited_codex_help_from_parent(pseudo_terminal=False)
            pty = observe_audited_codex_help_from_parent(pseudo_terminal=True)
            self.assertEqual(pipe, pty)
            evidence = exercise_audited_codex_native_authority_roundtrip()
        self.assertTrue(evidence["preflight"]["supported"])
        self.assertTrue(evidence["field_drift_rejected"])
        self.assertEqual(evidence["authority"]["codex_version"], "codex-cli 0.160.0")
        self.assertEqual(before, hashlib.sha256(path.read_bytes()).hexdigest())
        print("LIVE_CLI_CONTRACT_EVIDENCE=" + json.dumps({
            "cli_sha256": before, "version": version.stdout.strip(),
            "help_observation_sha256": pipe["digest"],
            "pty_matches_pipe": True, "staged_runtime": evidence["staged_runtime"],
            "preflight": evidence["preflight"],
            "field_drift_rejected": evidence["field_drift_rejected"],
            "production_install_requested": False,
        }, sort_keys=True), flush=True)
