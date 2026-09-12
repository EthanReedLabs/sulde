"""Real dependency probes, with no global installation or fallback search."""
import importlib.util
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/release"))
import python_environment as pe
import candidate_codex_plugin as candidate


class PythonEnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def venv(self):
        subprocess.run([sys.executable, "-B", "-m", "venv", "--without-pip", str(self.root / "venv")], check=True, capture_output=True)
        return self.root / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")

    def test_missing_default_dependency_stops_before_source_or_candidate_creation(self):
        python = self.venv()
        env = {**os.environ, "SULDE_CANDIDATE_PYTHON": str(python)}
        code = ("import sys; sys.path.insert(0, " + repr(str(ROOT / "scripts/release")) + "); "
                "from pathlib import Path; import candidate_codex_plugin as c; "
                "c.prepare(candidate_home=Path(" + repr(str(self.root / "candidates")) + "), codex='unavailable', platform='posix')")
        result = subprocess.run([str(python), "-B", "-c", code], env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("No module named 'yaml'", result.stderr)
        self.assertIn("No system Python was modified", result.stderr)
        self.assertFalse((self.root / "candidates").exists())

    def test_available_environment_binds_contents_and_dependency_drift_invalidates(self):
        import yaml
        python = self.venv()
        purelib = subprocess.run([str(python), "-I", "-B", "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"],
                                 check=True, capture_output=True, text=True, encoding="utf-8", errors="replace").stdout.strip()
        copied = Path(purelib) / "yaml"
        shutil.copytree(Path(yaml.__file__).parent, copied, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        identity = pe.inspect_python(python)
        self.assertEqual(pe.validate_python(identity), identity)
        # Cache/log noise has no content identity impact.
        (copied / "irrelevant.log").write_text("noise")
        self.assertEqual(pe.validate_python(identity), identity)
        module = copied / "reader.py"
        module.write_text(module.read_text() + "\n# isolated dependency drift\n")
        with self.assertRaisesRegex(pe.PythonEnvironmentError, "identity changed"):
            pe.validate_python(identity)
        self.assertEqual(identity["environment"]["dependencies"]["PyYAML"]["version"], yaml.__version__)
        self.assertEqual(identity["executable"], str(python.absolute()))

    def test_explicit_invalid_environment_never_tries_another_interpreter(self):
        with mock.patch.dict(os.environ, {"SULDE_CANDIDATE_PYTHON": str(self.root / "missing-python")}):
            with self.assertRaisesRegex(candidate.CandidateError, "preflight unavailable"):
                candidate._candidate_python()

    def test_same_runtime_accepts_identical_dependency_at_another_venv_path(self):
        import yaml
        python = self.venv()
        purelib = subprocess.run(
            [str(python), "-I", "-B", "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"],
            check=True, capture_output=True, text=True, encoding="utf-8", errors="replace",
        ).stdout.strip()
        shutil.copytree(Path(yaml.__file__).parent, Path(purelib) / "yaml",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        selected = pe.inspect_python(Path(sys.executable))
        isolated = pe.inspect_python(python)
        before = copy.deepcopy((selected, isolated))
        self.assertNotEqual(selected["environment"]["dependencies"]["PyYAML"]["root"],
                            isolated["environment"]["dependencies"]["PyYAML"]["root"])
        self.assertTrue(pe.same_runtime(selected, isolated))
        self.assertEqual((selected, isolated), before)

    def test_same_runtime_rejects_material_drift_despite_dependency_relocation(self):
        selected = pe.inspect_python(Path(sys.executable))
        mutations = (
            ("binary", lambda value: value.update(executable_sha256="0" * 64)),
            ("python", lambda value: value["environment"].update(version=[3, 14, 0])),
            ("base", lambda value: value["environment"].update(base_prefix="different-base")),
            ("dependency_version", lambda value: value["environment"]["dependencies"]["PyYAML"].update(version="0.0.0")),
            ("dependency_content", lambda value: value["environment"]["dependencies"]["PyYAML"].update(content_sha256="0" * 64)),
            ("ssl", lambda value: value["environment"]["dependencies"].update(ssl="different-ssl")),
        )
        for label, mutate in mutations:
            with self.subTest(drift=label):
                isolated = copy.deepcopy(selected)
                isolated["environment"]["prefix"] = "isolated-venv"
                isolated["environment"]["dependencies"]["PyYAML"]["root"] = "relocated-yaml"
                mutate(isolated)
                self.assertFalse(pe.same_runtime(selected, isolated))

    def test_exact_receipt_still_rejects_dependency_path_drift(self):
        identity = pe.inspect_python(Path(sys.executable))
        identity["environment"]["dependencies"]["PyYAML"]["root"] = "relocated-yaml"
        with self.assertRaisesRegex(pe.PythonEnvironmentError, "identity changed"):
            pe.validate_python(identity)

    def test_old_binary_only_receipt_is_not_a_dependency_proof(self):
        with self.assertRaisesRegex(pe.PythonEnvironmentError, "identity is missing"):
            pe.validate_python({"executable": sys.executable, "executable_sha256": "a" * 64})

    def test_missing_mcp_runtime_venv_fails_before_lock_or_registry(self):
        installer = candidate.installer
        kb = self.root / "empty-data-root"
        with mock.patch.object(installer, "_codex_host_preflight", return_value={"status": "clear"}), \
                mock.patch.object(installer, "_deployment_lock") as lock, \
                mock.patch.object(installer, "_registry_remove") as switch:
            with self.assertRaisesRegex(installer.InstallError, "runtime venv is missing"):
                installer.install(artifact=self.root / "artifact", kb_home=kb, codex="codex", platform="posix")
        lock.assert_not_called()
        switch.assert_not_called()
        self.assertFalse(kb.exists())
