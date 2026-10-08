"""Real venv invocation identity at the Guardian -> installer boundary.

Synthetic candidate receipts live only in a temporary tree. Git/artifact/host
facts are fixtures; Python paths, binary hashes and dependency probes are real.
No production install, native authority, scheduler or model call is performed.
"""
from contextlib import ExitStack
import copy
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import venv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/kb"))
sys.path.insert(0, str(ROOT / "scripts/release"))
from intent_guardian_parts import resource_preflight as preflight
import install_codex_plugin as installer
import python_environment as pe


def seal(value, field):
    unsigned = {k: v for k, v in value.items() if k != field}
    return {**unsigned, field: hashlib.sha256(
        installer._canonical_json_bytes(unsigned)).hexdigest()}


class CandidatePromotionIdentityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="promotion identity ")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        environment = self.root / "venv"
        venv.EnvBuilder(with_pip=False, symlinks=os.name != "nt").create(environment)
        self.python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        purelib = subprocess.run(
            [str(self.python), "-I", "-B", "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"],
            check=True, capture_output=True, text=True, errors="replace", encoding="utf-8").stdout.strip()
        import yaml
        self.yaml = Path(purelib) / "yaml"
        shutil.copytree(Path(yaml.__file__).parent, self.yaml,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        self.identity = pe.inspect_python(self.python)
        self.workspace = self.root / "workspace"
        self.script = self.workspace / "scripts/release/candidate_codex_plugin.py"
        self.script.parent.mkdir(parents=True)
        self.script.write_text("# inert fixture\n", encoding="utf-8")
        self.slot = self.root / "candidates/one"
        artifact = self.slot / "artifact"
        generation = {"generation": "test:" + "a" * 64, "plugin_version": "test",
                      "runtime_tree_sha256": "a" * 64, "platform": "posix"}
        manifest = artifact / "plugins/sulde/.codex-plugin/generation.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text(json.dumps(generation), encoding="utf-8")
        self.binding = {"kb_home": str(self.root / "live-kb"), "plugin_version": "test",
                        "codex_path": "/fixture/codex", "interpreter_path": str(self.python.resolve()),
                        "interpreter_sha256": self.identity["executable_sha256"]}
        ready = {key: {"status": "ready"} for key in (
            "artifact", "isolated_registry", "hooks", "preexecution_chain", "mcp", "doctor", "scheduler_entrypoint")}
        ready["preexecution_chain"].update(
            transport="codex-cli-app-server", native_tool="exec_command", executor="unified_exec",
            positive_executed=True, outside_plan_write_executed=True, destructive_pre_denied=True,
            marker_absent=True, artifact_generation=generation["generation"], loaded_module_generation="b" * 64,
            proof_id="c" * 64, session_id="synthetic", started_event_id="synthetic",
            scope_denial_event_id="synthetic", native_denial_run_id="synthetic")
        ready.update(native_permission_ui={"status": "unobserved", "exit_code": 78},
                     scheduler_host={"status": "unobserved", "exit_code": 79})
        self.receipt = {"schema": installer.CANDIDATE_RECEIPT_SCHEMA, "schema_version": 1,
                        "status": "verified", "candidate_id": "one", "python": self.identity,
                        "source": {"commit": "d" * 40, "tree": "e" * 40},
                        "artifact": {"path": str(artifact), "plugin_tree_sha256": "f" * 64, **generation},
                        "codex": {"executable": "/fixture/codex", "executable_sha256": "c" * 64,
                                  "version": "codex-cli 0.160.0"},
                        "live_prestate": {}, "live_prestate_sha256": hashlib.sha256(
                            installer._canonical_json_bytes({})).hexdigest(), "verifications": ready}
        self.prepared = installer.PreparedArtifact(artifact, {"delivery_generation": generation}, "f" * 64)
        self.write_receipt()
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name in ("_codex_plugin_install_binding", "_codex_plugin_install_v2_binding"):
            self.stack.enter_context(mock.patch.object(preflight, name, return_value=self.binding))
        self.stack.enter_context(mock.patch.object(preflight, "_candidate_git_output",
            side_effect=lambda _root, *args: self.receipt["source"]["commit" if args[-1] == "HEAD" else "tree"]))

    def write_receipt(self):
        self.receipt = seal(self.receipt, "receipt_sha256")
        (self.slot / "verification-receipt.json").write_text(json.dumps(self.receipt), encoding="utf-8")
        state = seal({"schema": "sulde-codex-candidate-state-v1", "status": "verified",
                      "candidate_id": "one", "receipt_sha256": self.receipt["receipt_sha256"]}, "state_sha256")
        (self.slot / "state.json").write_text(json.dumps(state), encoding="utf-8")

    def recognize(self, python=None, sealed=False):
        argv = [str(python or self.python)] + (["-B"] if sealed else []) + [str(self.script),
            "--candidate-home", str(self.slot.parent), "--json", "promote", "one", "--kb-home", self.binding["kb_home"]]
        return preflight.codex_candidate_promotion_candidate(shlex.join(argv), cwd=self.workspace)

    def validate_installer(self):
        def run(argv, **_kwargs):
            value = self.receipt["source"]["commit" if argv[-1] == "HEAD" else "tree"]
            return installer.CommandResult(tuple(argv), 0, value, "")
        with mock.patch.object(installer, "run_command", side_effect=run), \
                mock.patch.object(installer, "_codex_command_identity", return_value={
                    "codex_command": "/fixture/codex", "codex_command_sha256": "c" * 64}):
            return installer._validated_candidate_receipt(self.receipt, prepared=self.prepared,
                expected_live_state={}, codex="/fixture/codex", runner=lambda argv, **kwargs:
                installer.CommandResult(tuple(argv), 0, "codex-cli 0.160.0", ""))

    def test_real_venv_is_recognized_by_v1_and_v2_and_validated_by_installer(self):
        if os.name != "nt":
            self.assertNotEqual(str(self.python), str(self.python.resolve()))
        before = copy.deepcopy(self.receipt)
        for sealed in (False, True):
            with self.subTest(sealed=sealed):
                candidate = self.recognize(sealed=sealed)
                self.assertIsNotNone(candidate)
                self.assertEqual(candidate["profile_id"], "codex-plugin-install-v2" if sealed else "codex-plugin-install-v1")
                self.assertEqual(candidate["binding"]["interpreter_path"], str(self.python.resolve()))
        self.assertEqual(self.validate_installer(), before)
        self.assertEqual(self.receipt, before)

    def test_relative_and_path_lookup_preserve_invocation_identity(self):
        self.assertIsNotNone(self.recognize(os.path.relpath(self.python, self.workspace)))
        with mock.patch.dict(os.environ, {"PATH": str(self.python.parent)}):
            self.assertIsNotNone(self.recognize(self.python.name))

    def test_other_invocation_of_same_binary_cannot_consume_venv_receipt(self):
        alias = self.root / "other/python"
        alias.parent.mkdir()
        if os.name == "nt":
            shutil.copy2(self.python, alias)
        else:
            alias.symlink_to(self.python.resolve())
        self.assertEqual(hashlib.sha256(alias.read_bytes()).hexdigest(), self.identity["executable_sha256"])
        self.assertIsNone(self.recognize(alias))

    def test_direct_interpreter_receipt_still_supported(self):
        direct = Path(sys.executable).resolve()
        self.receipt["python"] = pe.inspect_python(direct)
        self.write_receipt()
        self.assertIsNotNone(self.recognize(direct))

    def test_binary_hash_mismatch_and_missing_executable_rejected(self):
        self.receipt["python"]["executable_sha256"] = "0" * 64
        self.write_receipt()
        self.assertIsNone(self.recognize())
        self.assertIsNone(self.recognize(self.root / "missing/python"))

    def test_corrupted_receipt_rejected(self):
        self.receipt["python"]["executable"] = "tampered"
        (self.slot / "verification-receipt.json").write_text(json.dumps(self.receipt), encoding="utf-8")
        self.assertIsNone(self.recognize())

    def test_dependency_drift_remains_blocked_by_real_installer_gate(self):
        self.assertIsNotNone(self.recognize())
        reader = self.yaml / "reader.py"
        reader.write_text(reader.read_text(encoding="utf-8") + "\n# isolated drift\n", encoding="utf-8")
        with self.assertRaisesRegex(installer.InstallError, "identity changed"):
            self.validate_installer()


if __name__ == "__main__":
    unittest.main()
