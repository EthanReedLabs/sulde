from __future__ import annotations

import contextlib
import importlib
import io
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import venv
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK_LIB = REPO_ROOT / "hooks" / "lib"
KB_INDEX_LIB = REPO_ROOT / "tools" / "kb-index"
MEMORY_CLI = REPO_ROOT / "tools" / "kb-index" / "memory.py"
SEARCH_CLI = KB_INDEX_LIB / "search.py"
BUILD_CLI = KB_INDEX_LIB / "build.py"
FLEET_CLI = REPO_ROOT / "scripts" / "kb" / "fleet.py"
STATUS_CLI = REPO_ROOT / "scripts" / "kb" / "sulde-status.py"
sys.path.insert(0, str(HOOK_LIB))
sys.path.insert(0, str(KB_INDEX_LIB))

claude_md_inject = importlib.import_module("claude_md_inject")
kb_cli = importlib.import_module("kb_cli")
kb_recall = importlib.import_module("kb_recall")
mem_recall = importlib.import_module("mem_recall")
sulde_common = importlib.import_module("sulde_common")
kb_index_common = importlib.import_module("common")


def _utf8_result(kwargs: dict, stdout: str):
    if kwargs.get("encoding") == "utf-8" and kwargs.get("errors") == "replace":
        decoded = stdout
    else:
        decoded = stdout.encode("utf-8").decode("cp936", errors="replace")
    return __import__("subprocess").CompletedProcess([], 0, decoded, "")


class Utf8SubprocessBoundaryTests(unittest.TestCase):
    @staticmethod
    def cp936_environment(**overrides: str) -> dict[str, str]:
        environment = os.environ.copy()
        environment["PYTHONIOENCODING"] = "cp936:strict"
        environment.update(overrides)
        return environment

    @staticmethod
    def cli_environment(root: Path, **overrides: str) -> dict[str, str]:
        modules = root / "modules"
        modules.mkdir()
        (modules / "jieba.py").write_text(
            "def cut_for_search(text): return text.split()\n", encoding="ascii"
        )
        (modules / "numpy.py").write_text("", encoding="ascii")
        (modules / "fastembed.py").write_text(
            "class TextEmbedding:\n"
            "    def __init__(self, *args, **kwargs):\n"
            "        raise AssertionError('embedding model should not load')\n",
            encoding="ascii",
        )
        inherited = os.environ.get("PYTHONPATH")
        python_path = str(modules)
        if inherited:
            python_path += os.pathsep + inherited
        return Utf8SubprocessBoundaryTests.cp936_environment(
            PYTHONPATH=python_path, **overrides
        )

    def test_memory_cli_forces_utf8_output_under_cp936(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            environment = os.environ.copy()
            environment["SULDE_KB_HOME"] = str(home)
            environment["PYTHONIOENCODING"] = "cp936:strict"
            initialized = subprocess.run(
                [sys.executable, str(MEMORY_CLI), "init"],
                capture_output=True,
                env=environment,
                check=False,
            )
            self.assertEqual(initialized.returncode, 0, initialized.stderr)

            connection = sqlite3.connect(home / "memory.db")
            try:
                connection.execute(
                    """
                    INSERT INTO mem_entries(
                        project, session_id, role, content, content_hash, ts, embedded
                    ) VALUES (?, ?, ?, ?, ?, ?, 0)
                    """,
                    (
                        "编码项目",
                        "session-cp936",
                        "user",
                        "包含项目符号 • 与中文的真实记忆内容",
                        "cp936-fixture",
                        "2026-08-09T00:00:00+00:00",
                    ),
                )
                connection.commit()
            finally:
                connection.close()

            completed = subprocess.run(
                [sys.executable, str(MEMORY_CLI), "recent", "-n", "1"],
                capture_output=True,
                env=environment,
                check=False,
            )

        stderr = completed.stderr.decode("utf-8", errors="replace").strip().splitlines()
        self.assertEqual(completed.returncode, 0, stderr[-1] if stderr else "")
        output = completed.stdout.decode("utf-8")
        self.assertIn("包含项目符号 • 与中文", output)
        self.assertEqual(json.loads(output)[0]["content"], "包含项目符号 • 与中文的真实记忆内容")

    def test_search_cli_forces_utf8_output_under_cp936(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sulde search ") as td:
            home = Path(td) / "search-home"
            home.mkdir()
            launcher = home / "bin" / "kb-index"
            launcher.parent.mkdir()
            launcher.write_text(
                "import runpy, sys\n"
                "from pathlib import Path\n"
                f"target = {str(SEARCH_CLI)!r}\n"
                "sys.path.insert(0, str(Path(target).parent))\n"
                "if len(sys.argv) < 2 or sys.argv[1] != 'search': raise SystemExit(2)\n"
                "sys.argv = [target, *sys.argv[2:]]\n"
                "runpy.run_path(target, run_name='__main__')\n",
                encoding="utf-8",
            )
            venv.EnvBuilder(with_pip=False).create(home / "venv")
            if os.name == "nt":
                venv_python = home / "venv" / "Scripts" / "python.exe"
            else:
                venv_python = home / "venv" / "bin" / "python"
            connection = kb_index_common.connect(home / "kb.db")
            try:
                kb_index_common.create_schema(connection)
                cursor = connection.execute(
                    """
                    INSERT INTO chunks(
                        chunk_id, doc_id, title, section, container, platform,
                        source_path, text
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "cp936#0000",
                        "cp936-search",
                        "状态栏 ❌",
                        "输出编码",
                        "anti-patterns",
                        "cross",
                        "knowledge/anti-patterns/cp936.md",
                        "状态栏乱码，项目符号 • 会触发真实输出编码。",
                    ),
                )
                connection.execute(
                    "INSERT INTO chunks_fts(rowid, seg_text) VALUES (?, ?)",
                    (cursor.lastrowid, "乱码"),
                )
                connection.commit()
            finally:
                connection.close()

            command = [
                str(venv_python),
                str(launcher),
                "search",
                "状态栏 乱码",
                "-k",
                "2",
                "--json",
            ]
            completed = subprocess.run(
                command,
                capture_output=True,
                env=self.cli_environment(
                    Path(td), SULDE_KB_HOME=str(home)
                ),
                check=False,
            )

        stderr = completed.stderr.decode("utf-8", errors="replace")
        self.assertEqual(completed.returncode, 0, stderr)
        output = completed.stdout.decode("utf-8")
        print("command=" + subprocess.list2cmdline(command))
        print("output_tail=" + output.rstrip().splitlines()[-1])
        payload = json.loads(output)
        self.assertEqual(output.rstrip().splitlines()[-1], "]")
        self.assertEqual(payload[0]["title"], "状态栏 ❌")
        self.assertIn("项目符号 •", payload[0]["excerpt"])

    def test_build_cli_forces_utf8_output_under_cp936(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            home = Path(td) / "构建 ❌ •"
            home.mkdir()
            connection = kb_index_common.connect(home / "kb.db")
            try:
                kb_index_common.create_schema(connection)
                documents = [
                    kb_index_common.parse_document(REPO_ROOT, path)
                    for path in kb_index_common.tracked_documents(REPO_ROOT)
                ]
                connection.executemany(
                    "INSERT INTO manifest(path, sha256) VALUES (?, ?)",
                    ((document.path.as_posix(), document.sha256) for document in documents),
                )
                connection.commit()
            finally:
                connection.close()

            completed = subprocess.run(
                [sys.executable, str(BUILD_CLI)],
                capture_output=True,
                env=self.cli_environment(
                    Path(td), SULDE_KB_HOME=str(home)
                ),
                check=False,
            )

        stderr = completed.stderr.decode("utf-8", errors="replace")
        self.assertEqual(completed.returncode, 0, stderr)
        output = completed.stdout.decode("utf-8")
        self.assertIn("build complete:", output)
        self.assertIn("构建 ❌ •", output)

    def test_fleet_cli_forces_utf8_output_under_cp936(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            projects = root / "projects"
            projects.mkdir()
            completed = subprocess.run(
                [sys.executable, str(FLEET_CLI)],
                capture_output=True,
                env=self.cp936_environment(
                    SULDE_KB_HOME=str(root / "kb-home"),
                    SULDE_CLAUDE_PROJECTS_HOME=str(projects),
                ),
                check=False,
            )

        stderr = completed.stderr.decode("utf-8", errors="replace")
        self.assertEqual(completed.returncode, 0, stderr)
        self.assertIn("在飞", completed.stdout.decode("utf-8"))

    def test_status_cli_forces_utf8_output_under_cp936(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            home = Path(td) / "状态目录"
            home.mkdir()
            (home / "distill-state.json").write_text(
                json.dumps({"ts": "2026-08-11T00:00:00+00:00"}),
                encoding="utf-8",
            )
            completed = subprocess.run(
                [sys.executable, str(STATUS_CLI), "--statusline"],
                capture_output=True,
                env=self.cp936_environment(SULDE_KB_HOME=str(home)),
                check=False,
            )

        stderr = completed.stderr.decode("utf-8", errors="replace")
        # A missing bounded snapshot is degraded without synchronously probing
        # launcher or operational history during interactive startup.
        self.assertEqual(completed.returncode, 1, stderr)
        output = completed.stdout.decode("utf-8")
        self.assertIn("状态快照待刷新", output)
        self.assertNotIn("\ufffd", output)

    def test_optional_session_script_preserves_utf8_output(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project = Path(td)
            script = project / "baseline.sh"
            script.write_text("placeholder", encoding="utf-8")
            config = sulde_common.SuldeConfig(
                config_path=project / ".sulde-config.yaml",
                project_root=project,
                role="coordinator",
                frontends=(),
                enforcement_level="balanced",
                grace_period_days=7,
                lang="en",
                enabled=True,
                raw={"session_baseline": {"baseline_script": str(script)}},
            )

            def run_boundary(*_args, **kwargs):
                return _utf8_result(kwargs, "基线正常 🙂\n")

            with mock.patch.object(claude_md_inject.subprocess, "run", run_boundary):
                output = claude_md_inject._run_optional_script(config, "baseline_script")

        self.assertEqual(output, "基线正常 🙂")

    def test_kb_recall_preserves_utf8_search_output(self) -> None:
        payload = {"prompt": "请检查这个严重性能回归问题", "cwd": "", "session_id": ""}
        search_output = json.dumps(
            [{"doc_id": "性能", "title": "性能排查", "source_path": "知识库", "score": 0.9}],
            ensure_ascii=False,
        )

        def run_boundary(*_args, **kwargs):
            return _utf8_result(kwargs, search_output)

        stdout = io.StringIO()
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            python = home / "venv" / "bin" / "python"
            python.parent.mkdir(parents=True)
            python.touch()
            with mock.patch.object(kb_recall, "_state_dir", return_value=home), \
                 mock.patch.object(kb_cli.subprocess, "run", run_boundary), \
                 contextlib.redirect_stdout(stdout):
                kb_recall.run(payload)

        self.assertIn("性能排查", stdout.getvalue())

    def test_memory_recall_preserves_utf8_search_output(self) -> None:
        payload = {"prompt": "请检查性能回归", "cwd": "示例项目", "session_id": ""}
        search_output = json.dumps(
            [{
                "id": 1,
                "content": "这是一次可复用的性能排查记录，包含足够长的诊断上下文。",
                "project": "示例项目",
                "ts": "2026-08-07",
                "score": 0.9,
                "cosine": 0.9,
            }],
            ensure_ascii=False,
        )

        def run_boundary(*_args, **kwargs):
            return _utf8_result(kwargs, search_output)

        stdout = io.StringIO()
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            (home / "memory.db").touch()
            python = home / "venv" / "Scripts" / "python.exe"
            python.parent.mkdir(parents=True)
            python.touch()
            with mock.patch.object(mem_recall, "_home", return_value=home), \
                 mock.patch.object(mem_recall.subprocess, "run", run_boundary), \
                 contextlib.redirect_stdout(stdout):
                mem_recall.run(payload)

        self.assertIn("可复用的性能排查记录", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
