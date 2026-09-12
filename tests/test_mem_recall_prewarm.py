from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MEM_RECALL = ROOT / "hooks" / "lib" / "mem_recall.py"


def load_mem_recall():
    spec = importlib.util.spec_from_file_location("test_mem_recall_prewarm", MEM_RECALL)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {MEM_RECALL}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class MemRecallPrewarmTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = load_mem_recall()

    def test_prewarm_launches_memory_with_venv_python(self) -> None:
        for relative_python in (
            Path("venv/bin/python"),
            Path("venv/Scripts/python.exe"),
        ):
            with self.subTest(relative_python=relative_python), \
                 tempfile.TemporaryDirectory() as temp_dir:
                home = Path(temp_dir)
                (home / "memory.db").touch()
                python = home / relative_python
                python.parent.mkdir(parents=True)
                python.touch()

                with mock.patch.object(self.module, "_home", return_value=home), \
                     mock.patch.object(self.module.subprocess, "Popen") as popen:
                    self.module.prewarm(limit=7)

                command = popen.call_args.args[0]
                self.assertEqual(Path(command[0]), python)
                self.assertEqual(Path(command[1]), ROOT / "hooks" / "lib" / "kb_cli.py")
                self.assertEqual(command[2], "__supervise__")
                self.assertEqual(command[7:], ["mem-embed", "--limit", "7"])
                popen.return_value.wait.assert_not_called()

    def test_prewarm_without_database_returns_without_spawning(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)

            with mock.patch.object(self.module, "_home", return_value=home), \
                 mock.patch.object(self.module.subprocess, "Popen") as popen:
                self.module.prewarm()

            popen.assert_not_called()

    def test_prewarm_keeps_session_state_cleanup_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            state_dir = home / "session-recall"
            state_dir.mkdir()
            expired = state_dir / "expired.json"
            current = state_dir / "current.json"
            expired.touch()
            current.touch()
            expired_time = self.module.time.time() - (
                self.module.SESSION_STATE_MAX_AGE_DAYS + 1
            ) * 24 * 60 * 60
            self.module.os.utime(expired, (expired_time, expired_time))

            with mock.patch.object(self.module, "_home", return_value=home), \
                 mock.patch.object(self.module.subprocess, "Popen") as popen:
                self.module.prewarm()

            self.assertFalse(expired.exists())
            self.assertTrue(current.exists())
            popen.assert_not_called()

    def test_prewarm_missing_venv_python_is_nonfatal_and_logged(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            (home / "memory.db").touch()

            with mock.patch.object(self.module, "_home", return_value=home), \
                 mock.patch.object(self.module.subprocess, "Popen") as popen:
                self.module.prewarm()

            popen.assert_not_called()
            self.assertIn("venv Python not found", (home / "mem-recall.log").read_text("utf-8"))

    def test_prewarm_spawn_failure_is_nonfatal_and_logged(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            (home / "memory.db").touch()
            python = home / "venv" / "Scripts" / "python.exe"
            python.parent.mkdir(parents=True)
            python.touch()

            with mock.patch.object(self.module, "_home", return_value=home), \
                 mock.patch.object(
                     self.module.subprocess,
                     "Popen",
                     side_effect=OSError("synthetic spawn failure"),
                 ):
                self.module.prewarm()

            trace = (home / "mem-recall.log").read_text("utf-8")
            self.assertIn("embedding launch failed", trace)
            self.assertIn("synthetic spawn failure", trace)

    def test_recall_launches_search_with_venv_python(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            (home / "memory.db").touch()
            python = home / "venv" / "Scripts" / "python.exe"
            python.parent.mkdir(parents=True)
            python.touch()

            def run_boundary(command, **kwargs):
                self.assertEqual(kwargs.get("encoding"), "utf-8")
                self.assertEqual(kwargs.get("errors"), "replace")
                self.assertEqual(kwargs.get("timeout"), self.module.SEARCH_TIMEOUT_SECONDS)
                return subprocess.CompletedProcess(command, 0, "[]", "")

            with mock.patch.object(self.module, "_home", return_value=home), \
                 mock.patch.object(
                     self.module.subprocess,
                     "run",
                     side_effect=run_boundary,
                 ) as run:
                self.module.run(
                    {
                        "prompt": "请召回这条历史诊断记录",
                        "cwd": str(home / "示例项目"),
                        "session_id": "session-1",
                    }
                )

            command = run.call_args.args[0]
            self.assertEqual(Path(command[0]), python)
            self.assertEqual(Path(command[1]), ROOT / "tools" / "kb-index" / "memory.py")
            self.assertEqual(
                command[2:],
                [
                    "search",
                    "请召回这条历史诊断记录",
                    "-k",
                    "5",
                    "--json",
                    "--skip-pending-embed",
                    "--project",
                    "示例项目",
                    "--session-id",
                    "claude:session-1",
                ],
            )
            record = json.loads(
                (home / "recall-log.jsonl").read_text(encoding="utf-8")
            )
            self.assertEqual(record["source"], "mem")
            self.assertEqual(record["session_id"], "claude:session-1")
            self.assertEqual(record["channel"], "claude")
            self.assertEqual(record["source_host"], "claude")
            self.assertRegex(record["opportunity_id"], r"^[0-9a-f]{20}$")

    def test_long_prompt_search_keeps_bounded_head_and_tail(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            (home / "memory.db").touch()
            python = home / "venv" / "Scripts" / "python.exe"
            python.parent.mkdir(parents=True)
            python.touch()
            head = "请召回并诊断并行搜索超时："
            tail = "尾部症状是嵌入查询时进程停顿"
            prompt = head + ("长" * 30_000) + tail

            with mock.patch.object(self.module, "_home", return_value=home), \
                 mock.patch.object(
                     self.module.subprocess,
                     "run",
                     return_value=subprocess.CompletedProcess([], 0, "[]", ""),
                 ) as run:
                self.module.run({"prompt": prompt, "cwd": str(home / "示例项目")})

            query = run.call_args.args[0][3]
            self.assertEqual(
                len(query), self.module.prompt_noise.MAX_RECALL_QUERY_CHARS
            )
            self.assertTrue(query.startswith(head))
            self.assertTrue(query.endswith(tail))

    def test_recall_spawn_failure_is_nonfatal_and_logged(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            (home / "memory.db").touch()
            python = home / "venv" / "Scripts" / "python.exe"
            python.parent.mkdir(parents=True)
            python.touch()

            with mock.patch.object(self.module, "_home", return_value=home), \
                 mock.patch.object(
                     self.module.subprocess,
                     "run",
                     side_effect=OSError("synthetic recall failure"),
                 ):
                self.module.run(
                    {
                        "prompt": "请召回这条历史诊断记录",
                        "cwd": str(home / "示例项目"),
                    }
                )

            trace = (home / "mem-recall.log").read_text("utf-8")
            self.assertIn("memory search failed", trace)
            self.assertIn("synthetic recall failure", trace)

    def test_recall_nonzero_exit_is_nonfatal_and_logged(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            (home / "memory.db").touch()
            python = home / "venv" / "Scripts" / "python.exe"
            python.parent.mkdir(parents=True)
            python.touch()
            failure = subprocess.CompletedProcess(
                [],
                7,
                "",
                "synthetic child stderr",
            )

            with mock.patch.object(self.module, "_home", return_value=home), \
                 mock.patch.object(self.module.subprocess, "run", return_value=failure):
                self.module.run(
                    {
                        "prompt": "请召回这条历史诊断记录",
                        "cwd": str(home / "示例项目"),
                    }
                )

            trace = (home / "mem-recall.log").read_text("utf-8")
            self.assertIn("memory search failed with exit code 7", trace)
            self.assertIn("synthetic child stderr", trace)


if __name__ == "__main__":
    unittest.main()
