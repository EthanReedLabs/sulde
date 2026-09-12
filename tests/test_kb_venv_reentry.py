from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, relative: str):
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def make_windows_venv_python(home: Path) -> Path:
    python = home / "venv" / "Scripts" / "python.exe"
    python.parent.mkdir(parents=True)
    python.write_bytes(b"test interpreter fixture")
    python.chmod(0o755)
    return python


class SecretScanInterpreterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = load_module(
            "test_mem_secret_scan_reentry", "scripts/kb/mem-secret-scan.py"
        )

    def test_uses_shared_executable_resolver(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            expected = home / "venv" / "Scripts" / "python.exe"
            with mock.patch.object(
                self.module.importlib.util, "find_spec", return_value=None
            ), mock.patch.object(self.module, "kb_home", return_value=home), \
                 mock.patch.object(
                     self.module.kb_cli,
                     "resolve_venv_python",
                     return_value=expected,
                 ) as resolver, mock.patch.object(self.module.os, "execv"):
                self.module.ensure_redact_interpreter()
            resolver.assert_called_once_with(home, require_executable=True)

    def test_windows_venv_interpreter_is_used_for_reexec(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            expected = make_windows_venv_python(home)
            with mock.patch.object(
                self.module.importlib.util, "find_spec", return_value=None
            ), mock.patch.object(self.module, "kb_home", return_value=home), \
                 mock.patch.object(self.module.os, "execv") as execv:
                self.module.ensure_redact_interpreter()
            command, argv = execv.call_args.args
            self.assertEqual(command, str(expected))
            self.assertEqual(argv[0], str(expected))
            self.assertEqual(Path(argv[1]), Path(self.module.__file__).resolve())

    def test_reexec_failure_names_interpreter_and_os_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            expected = make_windows_venv_python(home)
            error = OSError("synthetic Windows launch failure")
            with mock.patch.object(
                self.module.importlib.util, "find_spec", return_value=None
            ), mock.patch.object(self.module, "kb_home", return_value=home), \
                 mock.patch.object(self.module.os, "execv", side_effect=error):
                with self.assertRaises(self.module.ScanError) as caught:
                    self.module.ensure_redact_interpreter()
            message = str(caught.exception)
            self.assertIn(str(expected), message)
            self.assertIn("synthetic Windows launch failure", message)


class MemSyncInterpreterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = load_module("test_mem_sync_reentry", "scripts/kb/mem-sync.py")

    def test_uses_shared_executable_resolver(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            home = base / "home"
            expected = home / "venv" / "Scripts" / "python.exe"
            with mock.patch.object(
                self.module.importlib.util, "find_spec", return_value=None
            ), mock.patch.object(self.module, "kb_home", return_value=home), \
                 mock.patch.object(
                     self.module.kb_cli,
                     "resolve_venv_python",
                     return_value=expected,
                 ) as resolver, mock.patch.object(
                     self.module.sys, "prefix", str(base / "external")
                 ), mock.patch.object(
                     self.module.sys, "base_prefix", str(base / "external")
                 ), mock.patch.object(self.module.os, "execv"):
                self.module.ensure_interpreter(("jieba",), "test")
            resolver.assert_called_once_with(home, require_executable=True)

    def test_target_venv_raises_without_reexec(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            home = base / "home"
            make_windows_venv_python(home)
            with mock.patch.object(
                self.module.importlib.util, "find_spec", return_value=None
            ), mock.patch.object(self.module, "kb_home", return_value=home), \
                 mock.patch.object(self.module.sys, "prefix", str(home / "venv")), \
                 mock.patch.object(
                     self.module.sys, "base_prefix", str(base / "base")
                 ), mock.patch.object(self.module.os, "execv") as execv:
                with self.assertRaisesRegex(
                    self.module.SyncError, "requires missing kb venv modules"
                ):
                    self.module.ensure_interpreter(("jieba",), "test")
            execv.assert_not_called()

    def test_pyenv_symlink_same_resolved_target_still_reexecs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            home = base / "home"
            expected = make_windows_venv_python(home)
            external = str(base / "pyenv" / "python")
            same_real_file = base / "shared-real-python"
            with mock.patch.object(
                self.module.importlib.util, "find_spec", return_value=None
            ), mock.patch.object(self.module, "kb_home", return_value=home), \
                 mock.patch.object(self.module.sys, "prefix", external), \
                 mock.patch.object(self.module.sys, "base_prefix", external), \
                 mock.patch.object(
                     self.module.Path, "resolve", return_value=same_real_file
                 ), mock.patch.object(self.module.os, "execv") as execv:
                self.module.ensure_interpreter(("jieba",), "test")
            self.assertEqual(execv.call_args.args[0], str(expected))


if __name__ == "__main__":
    unittest.main()
