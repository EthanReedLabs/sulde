import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import venv
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
HOOK_LIB = ROOT / "hooks" / "lib"
sys.path.insert(0, str(HOOK_LIB))

import kb_freshness  # noqa: E402
import kb_cli  # noqa: E402
import kb_recall  # noqa: E402


def create_test_venv(home: Path) -> Path:
    venv.EnvBuilder(with_pip=False).create(home / "venv")
    if os.name == "nt":
        return home / "venv" / "Scripts" / "python.exe"
    return home / "venv" / "bin" / "python"


def write_cli_fixture(root: Path, search_body: str = 'print("[]")\n') -> None:
    entries = {
        Path("tools/kb-index/build.py"): "pass\n",
        Path("tools/kb-index/search.py"): search_body,
    }
    for relative, content in entries.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    launcher = root / "scripts" / "kb" / "kb-index"
    launcher.parent.mkdir(parents=True, exist_ok=True)
    launcher.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    launcher.chmod(0o755)


class HookCliLaunchTest(unittest.TestCase):
    def test_kb_recall_really_launches_venv_interpreter(self) -> None:
        payload = {
            "prompt": "diagnose the actual Windows KB launcher failure",
            "cwd": "",
            "session_id": "",
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "root"
            home = Path(temp_dir) / "home"
            write_cli_fixture(root)
            expected_python = create_test_venv(home)
            with mock.patch.dict(os.environ, {"SULDE_KB_HOME": str(home)}), \
                 mock.patch.object(kb_recall, "_plugin_root", return_value=root), \
                 mock.patch.object(
                     kb_cli.subprocess,
                     "run",
                     wraps=subprocess.run,
                 ) as run_spy:
                kb_recall.run(payload)

            command = run_spy.call_args.args[0]
            self.assertEqual(Path(command[0]).resolve(), expected_python.resolve())
            record = json.loads((home / "recall-log.jsonl").read_text(encoding="utf-8"))
            self.assertEqual(record["source"], "kb")
            self.assertEqual(record["cli_status"], "ok")
            self.assertEqual(record["top_scores"], [])

    def test_kb_freshness_really_launches_venv_interpreter(self) -> None:
        processes: list[subprocess.Popen[bytes]] = []
        original_popen = subprocess.Popen

        def launch(command, **kwargs):
            process = original_popen(command, **kwargs)
            processes.append(process)
            return process

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "root"
            home = Path(temp_dir) / "home"
            write_cli_fixture(root)
            expected_python = create_test_venv(home)
            stdout = io.StringIO()
            with mock.patch.dict(os.environ, {"SULDE_KB_HOME": str(home)}), \
                 mock.patch.object(kb_freshness, "_plugin_root", return_value=root), \
                 mock.patch.object(kb_freshness, "_corpus_fingerprint", return_value="new"), \
                 mock.patch.object(kb_freshness, "_indexed_fingerprint", return_value="old"), \
                 mock.patch.object(
                     kb_cli.subprocess,
                     "Popen",
                     side_effect=launch,
                 ) as popen_spy, \
                 contextlib.redirect_stdout(stdout):
                kb_freshness.run({})

            for process in processes:
                process.wait(timeout=10)
            commands = [call.args[0] for call in popen_spy.call_args_list]
            self.assertEqual(len(commands), 2)
            self.assertTrue(
                all(
                    Path(command[0]).resolve() == expected_python.resolve()
                    for command in commands
                )
            )
            log = (home / "build.log").read_text(encoding="utf-8")
            self.assertIn("command=search status=ok", log)

    def test_recall_log_distinguishes_launch_failure_from_empty_results(self) -> None:
        payload = {
            "prompt": "diagnose the actual Windows KB launcher failure",
            "cwd": "",
            "session_id": "",
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "root"
            write_cli_fixture(root)

            empty_home = base / "empty-home"
            create_test_venv(empty_home)
            with mock.patch.dict(os.environ, {"SULDE_KB_HOME": str(empty_home)}), \
                 mock.patch.object(kb_recall, "_plugin_root", return_value=root):
                kb_recall.run(payload)
            empty_record = json.loads(
                (empty_home / "recall-log.jsonl").read_text(encoding="utf-8")
            )

            failed_home = base / "failed-home"
            failed_python = (
                failed_home / "venv" / "Scripts" / "python.exe"
                if os.name == "nt"
                else failed_home / "venv" / "bin" / "python"
            )
            failed_python.parent.mkdir(parents=True)
            failed_python.write_text("not an executable\n", encoding="utf-8")
            with mock.patch.dict(os.environ, {"SULDE_KB_HOME": str(failed_home)}), \
                 mock.patch.object(kb_recall, "_plugin_root", return_value=root):
                kb_recall.run(payload)
            failed_record = json.loads(
                (failed_home / "recall-log.jsonl").read_text(encoding="utf-8")
            )

            self.assertEqual(empty_record["cli_status"], "ok")
            self.assertEqual(empty_record["top_scores"], [])
            self.assertEqual(failed_record["cli_status"], "launch_failed")
            self.assertNotEqual(empty_record["cli_status"], failed_record["cli_status"])


class SharedCliTest(unittest.TestCase):
    def test_mapping_covers_direct_and_translated_commands(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "root"
            home = base / "home"
            python = home / "venv" / "bin" / "python"
            python.parent.mkdir(parents=True)
            python.touch()

            search = kb_cli.build_command(root, home, "search", ["query"])
            annotate = kb_cli.build_command(root, home, "mem-annotate", ["a", "b"])

            self.assertEqual(Path(search[1]), root / "tools/kb-index/search.py")
            self.assertEqual(search[2:], ["query"])
            self.assertEqual(Path(annotate[1]), root / "tools/kb-index/memory.py")
            self.assertEqual(annotate[2:], ["annotate", "a", "b"])

    def test_resolver_supports_both_venv_layouts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            posix = home / "venv" / "bin" / "python"
            windows = home / "venv" / "Scripts" / "python.exe"
            posix.parent.mkdir(parents=True)
            windows.parent.mkdir(parents=True)
            posix.touch()
            windows.touch()

            self.assertEqual(kb_cli.resolve_venv_python(home), posix)
            posix.unlink()
            self.assertEqual(kb_cli.resolve_venv_python(home), windows)

    def test_real_launch_failure_emits_diagnostic(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "root"
            home = base / "home"
            write_cli_fixture(root)
            invalid_python = (
                home / "venv" / "Scripts" / "python.exe"
                if os.name == "nt"
                else home / "venv" / "bin" / "python"
            )
            invalid_python.parent.mkdir(parents=True)
            invalid_python.write_text("not an executable\n", encoding="utf-8")
            diagnostics: list[str] = []

            result = kb_cli.run_cli(
                root,
                home,
                "search",
                ["query"],
                timeout=1,
                diagnostic=diagnostics.append,
            )

            self.assertEqual(result.status, "launch_failed")
            self.assertTrue(any("status=launch_failed" in item for item in diagnostics))

    def test_background_nonzero_and_timeout_are_logged(self) -> None:
        search_body = """\
import sys
import time
if sys.argv[1] == "slow":
    time.sleep(2)
if sys.argv[1] == "fail":
    raise SystemExit(7)
print("[]")
"""
        processes: list[subprocess.Popen[bytes]] = []
        original_popen = subprocess.Popen

        def launch(command, **kwargs):
            process = original_popen(command, **kwargs)
            processes.append(process)
            return process

        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "root"
            home = base / "home"
            write_cli_fixture(root, search_body)
            create_test_venv(home)
            nonzero_log = base / "nonzero.log"
            timeout_log = base / "timeout.log"

            with mock.patch.object(kb_cli.subprocess, "Popen", side_effect=launch):
                self.assertTrue(
                    kb_cli.spawn_cli(
                        root,
                        home,
                        "search",
                        ["fail"],
                        timeout=1,
                        log_path=nonzero_log,
                    ).started
                )
                self.assertTrue(
                    kb_cli.spawn_cli(
                        root,
                        home,
                        "search",
                        ["slow"],
                        timeout=0.05,
                        log_path=timeout_log,
                    ).started
                )

            for process in processes:
                process.wait(timeout=10)
            self.assertIn("status=nonzero_exit exit_code=7", nonzero_log.read_text("utf-8"))
            self.assertIn("status=timeout", timeout_log.read_text("utf-8"))

    def test_missing_venv_is_nonfatal_and_logged(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "root"
            home = base / "home"
            log_path = home / "build.log"
            write_cli_fixture(root)

            with mock.patch.dict(os.environ, {"SULDE_KB_HOME": str(home)}), \
                 mock.patch.object(kb_freshness, "_plugin_root", return_value=root), \
                 mock.patch.object(kb_freshness, "_corpus_fingerprint", return_value=None):
                kb_freshness.run({})

            self.assertIn("command=search status=unavailable", log_path.read_text("utf-8"))

    def test_module_unavailable_is_nonfatal_and_logged(self) -> None:
        payload = {
            "prompt": "diagnose the actual Windows KB launcher failure",
            "cwd": "",
            "session_id": "",
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "root"
            recall_home = base / "recall-home"
            freshness_home = base / "freshness-home"
            write_cli_fixture(root)

            with mock.patch.dict(os.environ, {"SULDE_KB_HOME": str(recall_home)}), \
                 mock.patch.object(kb_recall, "_plugin_root", return_value=root), \
                 mock.patch.object(kb_recall, "kb_cli", None), \
                 mock.patch.object(kb_recall, "_KB_CLI_IMPORT_ERROR", "missing"):
                kb_recall.run(payload)
            record = json.loads(
                (recall_home / "recall-log.jsonl").read_text(encoding="utf-8")
            )
            self.assertEqual(record["cli_status"], "module_unavailable")
            self.assertEqual(record["source"], "kb")

            with mock.patch.dict(os.environ, {"SULDE_KB_HOME": str(freshness_home)}), \
                 mock.patch.object(kb_freshness, "_plugin_root", return_value=root), \
                 mock.patch.object(kb_freshness, "kb_cli", None), \
                 mock.patch.object(kb_freshness, "_KB_CLI_IMPORT_ERROR", "missing"):
                kb_freshness.run({})
            self.assertIn(
                "status=module_unavailable",
                (freshness_home / "build.log").read_text(encoding="utf-8"),
            )

    def test_migrated_callers_have_no_entrypoint_or_venv_mapping(self) -> None:
        for relative in ("hooks/lib/kb_recall.py", "hooks/lib/kb_freshness.py"):
            source = (ROOT / relative).read_text(encoding="utf-8")
            self.assertNotIn('scripts" / "kb" / "kb-index', source)
            self.assertNotIn('tools" / "kb-index" / "memory.py', source)
            self.assertNotIn("venv\" / \"bin", source)
            self.assertNotIn("venv\" / \"Scripts", source)


if __name__ == "__main__":
    unittest.main()
