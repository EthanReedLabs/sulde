"""R3-03/R3-closeout: real-entry chain through the actual run command.

The fake provider replaces ONLY the model.  It captures its full stdin (the
execution input composed by the real runner) and, in markerdriven mode,
branches on it:

- 执行输入包含「监督端预测对照反馈」→ 修复分支,exit 0;
- 否则 → 越权分支(破坏 consumer.py),exit 1(错误 → 可重试)。

wellbehaved 模式:无论反馈与否都在范围内一次到位(exit 0)——用于
"正常修改,无反馈也成功"的路径 A。

Task identity is unified via --task-id embed on every run command; the frozen
baseline is the real HEAD OID of a real git repository.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

SCRIPT_DIR = Path(os.environ.get(
    "SULDE_R3_SOURCE_ROOT", str(Path(__file__).resolve().parents[1])
)).resolve()
RUNTIME = SCRIPT_DIR / "scripts" / "kb" / "agent-runtime.py"
sys.path.insert(0, str(SCRIPT_DIR / "scripts" / "kb"))

import impact_prediction as ip  # noqa: E402
import prediction_feedback as pf  # noqa: E402

REPORT = """## 结果
任务完成。
✅ 验证通过：`python -m unittest`，exit 0；输出 OK；candidate_sha256=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa；execution_binding_sha256=bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb；environment_sha256=cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc；command_sha256=88d1e4ef3a5e210c702e32c1f294a637fcac036aae538cf3e0500c2c054b49c7；count=1
## 过程
执行最小改动。
## 遇到的问题
无。
## 解决方式
按任务书实现。
## 遗留风险与建议
无已知风险。
"""

BASE = {"value.py": "VALUE = 1\n",
        "consumer.py": "import value\nprint('ok', value.VALUE)\n"}
OVERREACH = {"value.py": "VALUE = 2\n",
             "consumer.py": "import value\nprint('broken', value.TYPO)\n"}
FIXED = {"value.py": "VALUE = 2\n"}
FEEDBACK_MARKER = "监督端预测对照反馈"


def load_runtime_module():
    spec = importlib.util.spec_from_file_location("r3_agent_runtime", RUNTIME)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Chain:
    """One disposable git worktree + fake provider + prediction store."""

    def __init__(self, tmp: Path, *, mode: str = "markerdriven"):
        self.tmp = tmp
        self.mode = mode
        self.worktree = tmp / "worktree"
        self.state = self.worktree / ".codex-agent"
        self.state.mkdir(parents=True)
        (self.worktree / "value.py").write_text(BASE["value.py"], encoding="utf-8")
        (self.worktree / "consumer.py").write_text(BASE["consumer.py"], encoding="utf-8")
        (self.worktree / ".gitignore").write_text(".codex-agent/\n", encoding="utf-8")
        for args in (["init", "-q"], ["add", "."],
                     ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "base"],
                     ["tag", "baseline"]):
            subprocess.run(["git", "-C", str(self.worktree), *args],
                           capture_output=True, check=True)
        self.brief = self.state / "embed.md"
        self.brief.write_text("# Task\n\nbump VALUE to 2 (value.py only).\n",
                              encoding="utf-8")
        self.brief.chmod(0o400)
        self.prompt_capture = tmp / "captured-prompt.txt"
        self.store = pf.prediction_store_path(self.state)
        self.executable = self._provider(tmp / "provider-codex", mode)

    def _provider(self, target: Path, mode: str) -> Path:
        target.mkdir(parents=True, exist_ok=True)
        executable = target / "codex"
        if mode == "wellbehaved":
            change_block = (
                "(root / 'value.py').write_text("
                f"{FIXED['value.py']!r}, encoding='utf-8')\n"
                "code = 0\n")
        else:
            change_block = (
                "if " + repr(FEEDBACK_MARKER) + " in prompt:\n"
                "    (root / 'value.py').write_text("
                f"{FIXED['value.py']!r}, encoding='utf-8')\n"
                "    (root / 'consumer.py').write_text("
                f"{BASE['consumer.py']!r}, encoding='utf-8')\n"
                "    code = 0\n"
                "else:\n"
                "    (root / 'value.py').write_text("
                f"{OVERREACH['value.py']!r}, encoding='utf-8')\n"
                "    (root / 'consumer.py').write_text("
                f"{OVERREACH['consumer.py']!r}, encoding='utf-8')\n"
                "    code = 1\n")
        executable.write_text(
            "#!/usr/bin/python3\n"
            "import sys\n"
            "import os\n"
            "from pathlib import Path\n"
            "root = Path(os.environ['SULDE_R3_WORKTREE'])\n"
            "prompt = sys.stdin.read()\n"
            f"Path({str(self.prompt_capture)!r}).write_text(prompt, encoding='utf-8')\n"
            "args = sys.argv[1:]\n"
            f"mode = {mode!r}\n"
            + change_block +
            "report = Path(args[args.index('--output-last-message') + 1])\n"
            f"report.write_text({REPORT!r}, encoding='utf-8')\n"
            "print('{\"type\":\"done\"}')\n"
            "sys.exit(code)\n",
            encoding="utf-8",
        )
        executable.chmod(0o755)
        return executable

    def environment(self) -> dict:
        environment = os.environ.copy()
        environment.update({
            "SULDE_AGENT_PROVIDER": "codex",
            "SULDE_CODEX_EXE": str(self.executable),
            "SULDE_TEST_MODE": "1",
            "SULDE_KB_HOME": str(self.tmp / "kb-home"),
            "SULDE_TEST_EVIDENCE_HOME": str(self.tmp / "test-evidence"),
            "SULDE_INTENT_CONTRACT": "",
            "SULDE_GUARDIAN_STREAM_OWNER": "",
            "SULDE_GUARDIAN_STREAM_PROVIDER": "",
            "SULDE_R3_WORKTREE": str(self.worktree),
        })
        return environment

    def run(self, *, slug: str = "embed", retry_op: str | None = None,
            task_id: str = "embed") -> subprocess.CompletedProcess:
        command = [sys.executable, "-B", str(RUNTIME), "run", str(self.worktree), slug,
                   str(self.brief), "--timeout", "15", "--task-id", task_id]
        if retry_op:
            command += ["--retry", "--retry-op", retry_op]
        return subprocess.run(command, capture_output=True, text=True,
                              encoding="utf-8", errors="replace",
                              env=self.environment(), check=False, timeout=180)

    def seed_prediction(self, *, expected=("value.py",), source=("value.py",),
                        contract_version="l3:embed#1"):
        import hashlib
        digests = {p: hashlib.sha256((self.worktree / p).read_bytes()).hexdigest()[:16]
                   for p in source}
        ip.open_prediction(self.store, {
            "kind": "lightweight", "task_id": "embed",
            "run_id": "run-pending0000000000000000", "session_id": "s-pending",
            "project_id": str(self.worktree), "contract_version": contract_version,
            "source_identities": digests,
            "objective": "bump VALUE to 2 (value.py only)",
            "assumptions": [{"text": "consumer.py untouched", "confidence": "high"}],
            "expected_touch": {"entries": list(expected)},
            "impact_bounds": {"lower": "constant", "upper": "module", "unknown": "-"},
        }, at="2026-09-27T15:30:00+00:00", task_id="embed")

    def feedback_events(self):
        events = []
        for path in sorted(self.state.glob("*.run.jsonl")):
            rows = [json.loads(line)
                    for line in path.read_text(encoding="utf-8").splitlines()
                    if line.strip()]
            events += [row for row in rows
                       if row.get("type") == "prediction.feedback"]
        return events

    def captured_prompt(self) -> str:
        return self.prompt_capture.read_text(encoding="utf-8")

    def probe(self):
        return subprocess.run(
            [sys.executable, "-B", str(self.worktree / "consumer.py")],
            capture_output=True, text=True, check=False,
            encoding="utf-8", errors="replace",
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})


class R3RealEntryChainTests(unittest.TestCase):
    def test_a_normal_in_scope_change_succeeds_without_feedback(self):
        """路径 A:正常预计修改,无反馈也成功(checked,无反馈工件)。"""
        with tempfile.TemporaryDirectory() as tmpname:
            chain = _Chain(Path(tmpname), mode="wellbehaved")
            chain.seed_prediction()
            completed = chain.run()
            self.assertEqual(completed.returncode, 0,
                             completed.stdout + completed.stderr)
            feedback = chain.feedback_events()
            self.assertEqual(len(feedback), 1)
            self.assertEqual(feedback[0]["payload"]["verdict"], "as_predicted")
            artifact = chain.state / f"prediction-feedback-{ip.digest('embed')}.json"
            self.assertFalse(artifact.exists())  # as_predicted 不产生反馈工件
            self.assertNotIn(FEEDBACK_MARKER, chain.captured_prompt())
            probe = chain.probe()
            self.assertEqual(probe.returncode, 0)
            self.assertIn("ok 2", probe.stdout)

    def test_b_delivered_feedback_drives_the_fix_and_probe_passes(self):
        """路径 B:attempt 1 失败可重试 → 反馈实际进入执行输入 → 修复 → 独立探针通过。"""
        with tempfile.TemporaryDirectory() as tmpname:
            chain = _Chain(Path(tmpname), mode="markerdriven")
            chain.seed_prediction()
            # attempt 1: 无反馈 → 越权 → provider exit 1(可重试的错误)
            failed = chain.run()
            self.assertNotEqual(failed.returncode, 0)
            artifact = chain.state / f"prediction-feedback-{ip.digest('embed')}.json"
            self.assertTrue(artifact.exists())
            self.assertNotIn(FEEDBACK_MARKER, chain.captured_prompt())
            # attempt 2: 正式续接(--retry,同合同),prompt 含反馈段 → 修复分支
            completed = chain.run(retry_op="embed-fix-attempt-2")
            self.assertEqual(completed.returncode, 0,
                             completed.stdout + completed.stderr)
            prompt = chain.captured_prompt()
            self.assertIn(FEEDBACK_MARKER, prompt)  # 反馈进入了执行输入
            self.assertIn("larger_than_predicted", prompt)
            feedback = chain.feedback_events()
            verdicts = [row["payload"].get("verdict") for row in feedback]
            self.assertEqual(verdicts, ["larger_than_predicted", "as_predicted"])
            probe = chain.probe()
            self.assertEqual(probe.returncode, 0)
            self.assertIn("ok 2", probe.stdout)

    def test_c_without_delivery_the_overreach_is_not_auto_fixed(self):
        """路径 C:不投递反馈 → 越权不会被自动修好(反例)。"""
        with tempfile.TemporaryDirectory() as tmpname:
            chain = _Chain(Path(tmpname), mode="markerdriven")
            chain.seed_prediction()
            failed = chain.run()  # attempt 1 only: 无反馈
            self.assertNotEqual(failed.returncode, 0)
            # 越权破坏仍在,未被自动修好
            broken = chain.probe()
            self.assertNotEqual(broken.returncode, 0)
            self.assertNotIn(FEEDBACK_MARKER, chain.captured_prompt())

    def test_wrong_task_feedback_is_not_consumed(self):
        """反例:错任务的反馈不进入执行输入。"""
        with tempfile.TemporaryDirectory() as tmpname:
            chain = _Chain(Path(tmpname), mode="markerdriven")
            chain.seed_prediction()
            other_digest = ip.digest("task/other")
            artifact = chain.state / f"prediction-feedback-{other_digest}.json"
            artifact.write_text(json.dumps({
                "schema": "sulde-prediction-feedback-v1",
                "task_id_sha256": other_digest,
                "verdict": "larger_than_predicted",
                "facts": ["other task"], "run_id_sha256": "x" * 64,
                "request_id": "req-other",
            }, ensure_ascii=False), encoding="utf-8")
            failed = chain.run()
            self.assertNotIn(FEEDBACK_MARKER, chain.captured_prompt())
            self.assertTrue(artifact.exists())  # 错任务工件原样保留


if __name__ == "__main__":
    unittest.main()
