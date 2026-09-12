from __future__ import annotations

import contextlib
import importlib.util
import io
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
AUTO_DISTILL = ROOT / "scripts" / "kb" / "auto-distill.py"
WINDOWS_INSTALLER = ROOT / "scripts" / "kb" / "install-agents.ps1"
WINDOWS_TASK = ROOT / "scripts" / "kb" / "windows-task.py"


def load_auto_distill():
    spec = importlib.util.spec_from_file_location("test_auto_distill", AUTO_DISTILL)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {AUTO_DISTILL}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_windows_task():
    spec = importlib.util.spec_from_file_location("test_windows_task", WINDOWS_TASK)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {WINDOWS_TASK}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class AutoDistillWindowsBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = load_auto_distill()

    def test_llm_stdin_boundary_is_explicit_utf8(self) -> None:
        def run_boundary(*_args, **kwargs):
            self.assertEqual(kwargs.get("encoding"), "utf-8")
            self.assertEqual(kwargs.get("errors"), "replace")
            self.assertEqual(kwargs.get("input"), "中文输入 🧪")
            return subprocess.CompletedProcess([], 0, '{"entities":[],"edges":[],"lessons":[]}', "")

        with mock.patch.object(self.module.subprocess, "run", run_boundary):
            output = self.module.run_llm("claude -p {prompt}", "中文输入 🧪")

        self.assertIn("entities", output)

    def test_llm_child_has_no_console_on_windows(self) -> None:
        def run_boundary(*_args, **kwargs):
            self.assertEqual(kwargs.get("creationflags"), 0x08000000)
            return subprocess.CompletedProcess(
                [], 0, '{"entities":[],"edges":[],"lessons":[]}', ""
            )

        with mock.patch.object(self.module.os, "name", "nt"), \
             mock.patch.object(self.module.subprocess, "run", run_boundary):
            output = self.module.run_llm("claude -p {prompt}", "background prompt")

        self.assertIn("entities", output)

    def test_annotate_uses_python_memory_entrypoint(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            python = home / "venv" / ("Scripts" if os.name == "nt" else "bin") / (
                "python.exe" if os.name == "nt" else "python"
            )
            python.parent.mkdir(parents=True)
            python.touch()

            def run_boundary(command, **kwargs):
                self.assertEqual(Path(command[0]), python)
                self.assertEqual(Path(command[1]), ROOT / "tools" / "kb-index" / "memory.py")
                self.assertEqual(command[2], "annotate")
                self.assertEqual(kwargs.get("encoding"), "utf-8")
                return subprocess.CompletedProcess(
                    command,
                    0,
                    json.dumps({"entities_inserted": 0, "inserted": 0}),
                    "",
                )

            with mock.patch.object(self.module, "kb_home", return_value=home), \
                 mock.patch.object(self.module.subprocess, "run", run_boundary):
                result = self.module.annotate({"entities": [], "edges": []})

        self.assertEqual(result, {"entities_inserted": 0, "inserted": 0})

    def test_structured_lesson_renders_layer1_problem_card(self) -> None:
        payload = {
            "entities": [],
            "edges": [],
            "lessons": [
                {
                    "text": "知识写入必须先形成隔离审稿分支",
                    "problem_type": "workflow",
                    "task_context": "自动沉淀候选准备写入知识库",
                    "symptom": "实际直接写真源，期望先形成审稿分支",
                    "root_cause": "写入链没有隔离边界",
                    "evidence_status": "verified",
                    "evidence_entry_ids": [42],
                    "route_positive": {
                        "text": "自动生成知识条目准备写入真源",
                        "reason": "命中自动生成与知识写入两个必要条件",
                        "source": "observed",
                    },
                    "route_negative": {
                        "text": "只读检索现有知识条目",
                        "reason": "没有产生知识写入",
                        "source": "constructed",
                    },
                    "outcome_positive": {
                        "text": "隔离分支通过门禁后等待人工合并",
                        "reason": "审稿边界与验证证据完整",
                        "source": "constructed",
                    },
                    "outcome_negative": {
                        "text": "直接修改主分支就宣称沉淀完成",
                        "reason": "绕过隔离审稿边界",
                        "source": "observed",
                    },
                }
            ],
        }

        parsed = self.module.parse_result(json.dumps(payload, ensure_ascii=False))
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "distill-candidates.md"
            self.module.append_candidates(path, parsed["lessons"])
            rendered = path.read_text(encoding="utf-8")

        self.assertIn("### Layer1 问题卡", rendered)
        self.assertIn("**证据状态**：verified", rendered)
        self.assertIn("**路由反例**（constructed）", rendered)
        self.assertIn("**判定原因**：没有产生知识写入", rendered)
        self.assertIn("**执行失败例**（observed）", rendered)
        self.assertIn("（待 /sediment 处理）", rendered)

    def test_legacy_string_lesson_is_rejected(self) -> None:
        with self.assertRaisesRegex(Exception, "problem-card schema"):
            self.module.parse_result(
                json.dumps(
                    {"entities": [], "edges": [], "lessons": ["旧的一行式教训"]},
                    ensure_ascii=False,
                )
            )


class WindowsAgentAssetsTests(unittest.TestCase):
    def test_windows_agent_assets_exist(self) -> None:
        self.assertTrue(WINDOWS_INSTALLER.is_file())
        self.assertTrue(WINDOWS_TASK.is_file())

    @unittest.skipUnless(os.name == "nt", "requires native Windows PowerShell")
    def test_installer_dry_run_is_non_mutating(self) -> None:
        powershell = shutil.which("powershell.exe")
        self.assertIsNotNone(powershell, "powershell.exe not found")
        task_names = ("Sulde-Codex-Harvest", "Sulde-Daily-Distill")
        before = {
            name: subprocess.run(
                ["schtasks.exe", "/Query", "/TN", name],
                capture_output=True,
                check=False,
            ).returncode
            for name in task_names
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir) / "kb"
            python = home / "venv" / "Scripts" / "python.exe"
            pythonw = python.with_name("pythonw.exe")
            python.parent.mkdir(parents=True)
            shutil.copy2(sys.executable, python)
            shutil.copy2(sys.executable, pythonw)
            env = os.environ.copy()
            env["SULDE_KB_HOME"] = str(home)
            env["SULDE_PLUGIN_ROOT"] = str(ROOT)
            completed = subprocess.run(
                [
                    str(powershell),
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(WINDOWS_INSTALLER),
                    "-DryRun",
                    "-AcceptDailyClaudeInvocation",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                timeout=30,
                check=False,
            )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn(f"Task Python: {pythonw}", completed.stdout)
        self.assertIn(f"Harvest action executable: {pythonw}", completed.stdout)
        self.assertIn(f"Distill action executable: {pythonw}", completed.stdout)
        for name in task_names:
            self.assertIn(name, completed.stdout)
            after = subprocess.run(
                ["schtasks.exe", "/Query", "/TN", name],
                capture_output=True,
                check=False,
            ).returncode
            self.assertEqual(after, before[name], name)

    @unittest.skipUnless(os.name == "nt", "requires native Windows PowerShell")
    def test_installer_prefers_current_native_binary_over_stale_exe(self) -> None:
        powershell = shutil.which("powershell.exe")
        self.assertIsNotNone(powershell, "powershell.exe not found")
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            home = root / "kb"
            python = home / "venv" / "Scripts" / "python.exe"
            pythonw = python.with_name("pythonw.exe")
            python.parent.mkdir(parents=True)
            shutil.copy2(sys.executable, python)
            shutil.copy2(sys.executable, pythonw)

            wrapper_bin = root / "current"
            stale_bin = root / "stale"
            wrapper_bin.mkdir()
            stale_bin.mkdir()
            (wrapper_bin / "codex.ps1").write_text("exit 0\n", encoding="utf-8")
            codex_cmd = wrapper_bin / "codex.cmd"
            codex_cmd.write_text("@exit /b 0\r\n", encoding="utf-8")
            native_codex = (
                wrapper_bin
                / "node_modules"
                / "@openai"
                / "codex"
                / "node_modules"
                / "@openai"
                / "codex-win32-x64"
                / "vendor"
                / "x86_64-pc-windows-msvc"
                / "bin"
                / "codex.exe"
            )
            native_codex.parent.mkdir(parents=True)
            shutil.copy2(sys.executable, native_codex)
            shutil.copy2(sys.executable, stale_bin / "codex.exe")

            env = os.environ.copy()
            env.update(
                {
                    "PATH": os.pathsep.join(
                        (str(wrapper_bin), str(stale_bin), env.get("PATH", ""))
                    ),
                    "SULDE_KB_HOME": str(home),
                    "SULDE_PLUGIN_ROOT": str(ROOT),
                }
            )
            completed = subprocess.run(
                [
                    str(powershell),
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(WINDOWS_INSTALLER),
                    "-DryRun",
                    "-Provider",
                    "Codex",
                    "-AcceptDailyLlmInvocation",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                timeout=30,
                check=False,
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn(f"Runtime provider: codex ({native_codex})", completed.stdout)


class WindowsTaskRunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = load_windows_task()

    def test_distill_runs_secret_scan_before_selected_provider(self) -> None:
        calls: list[list[str]] = []

        def run_boundary(command, **_kwargs):
            calls.append(command)
            if Path(command[1]).name == "mem-secret-scan.py":
                return subprocess.CompletedProcess(command, 0, '{"clean":true}', "")
            return subprocess.CompletedProcess(command, 0, "distilled", "")

        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            with mock.patch.object(self.module, "KB_HOME", home), \
                 mock.patch.object(self.module, "resolve_runtime", return_value=ROOT), \
                 mock.patch.object(self.module.subprocess, "run", run_boundary), \
                 contextlib.redirect_stdout(io.StringIO()):
                result = self.module.run_job("distill", "codex", Path(sys.executable))

        self.assertEqual(result, 0)
        self.assertEqual(Path(calls[0][1]).name, "mem-secret-scan.py")
        self.assertEqual(Path(calls[1][1]).name, "auto-distill.py")
        self.assertNotIn("--llm-cmd", calls[1])

    def test_distill_blocks_when_secret_scan_finds_matches(self) -> None:
        calls: list[list[str]] = []

        def run_boundary(command, **_kwargs):
            calls.append(command)
            return subprocess.CompletedProcess(
                command,
                1,
                '{"clean":false,"matched_entry_count":1}',
                "",
            )

        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            with mock.patch.object(self.module, "KB_HOME", home), \
                 mock.patch.object(self.module, "resolve_runtime", return_value=ROOT), \
                 mock.patch.object(self.module.subprocess, "run", run_boundary):
                with self.assertRaisesRegex(RuntimeError, "secret scan blocked"):
                    self.module.run_job("distill", "claude", Path(sys.executable))

        self.assertEqual(len(calls), 1)

    def test_windowless_runner_does_not_require_stdio(self) -> None:
        completed = subprocess.CompletedProcess([], 0, "harvested\n", "warning\n")

        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            with mock.patch.object(self.module, "KB_HOME", home), \
                 mock.patch.object(self.module, "resolve_runtime", return_value=ROOT), \
                 mock.patch.object(self.module.subprocess, "run", return_value=completed), \
                 mock.patch.object(self.module.sys, "stdout", None), \
                 mock.patch.object(self.module.sys, "stderr", None):
                result = self.module.run_job("harvest")

            stdout_log = (home / "harvest.stdout.log").read_text(encoding="utf-8")
            stderr_log = (home / "harvest.stderr.log").read_text(encoding="utf-8")

        self.assertEqual(result, 0)
        self.assertIn("harvested", stdout_log)
        self.assertIn("warning", stderr_log)


if __name__ == "__main__":
    unittest.main()
