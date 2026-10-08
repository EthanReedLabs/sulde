"""R2-02: the baseline reaches the feedback consumer through the REAL run.

End-to-end over the actual `agent-runtime run` command with a fake provider
(protocol scope): a seeded prediction for the task is rebound to the started
attempt and the post-monitor consumer records a feedback disclosure whose
baseline handling follows R2-02 (unresolvable in a non-git worktree ->
degraded, never checked).
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path
import tempfile
import unittest

SCRIPT_DIR = Path(__file__).resolve().parents[1]
RUNTIME = SCRIPT_DIR / "scripts" / "kb" / "agent-runtime.py"

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


def load_runtime_module():
    spec = importlib.util.spec_from_file_location("r2_agent_runtime", RUNTIME)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class R2BaselineBindingTests(unittest.TestCase):
    def test_feedback_consumer_receives_the_run_and_degrades_without_git_baseline(self) -> None:
        runtime = load_runtime_module()
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            worktree = directory / "worktree"
            state = worktree / ".codex-agent"
            state.mkdir(parents=True)
            (worktree / "base.txt").write_text("base\n", encoding="utf-8")
            brief = state / "embed.md"
            brief.write_text("# Task\n\nDo the work.\n", encoding="utf-8")
            brief.chmod(0o400)
            executable = directory / "codex"
            executable.write_text(
                textwrap.dedent(
                    f"""\
                    #!/usr/bin/python3
                    import sys
                    from pathlib import Path
                    args = sys.argv[1:]
                    report = Path(args[args.index('--output-last-message') + 1])
                    report.write_text({REPORT!r}, encoding='utf-8')
                    print('{{"type":"done"}}')
                    """
                ),
                encoding="utf-8",
            )
            executable.chmod(0o755)

            # seed an open prediction for this task (slug identity), bound to
            # a placeholder run: the attempt start must explicitly rebind it.
            import impact_prediction as ip  # noqa: E402
            store = state / "predictions.jsonl"
            ip.open_prediction(store, {
                "kind": "lightweight", "task_id": "test-fixture",
                "run_id": "run-pending0000000000000000", "session_id": "s-pending",
                "project_id": str(worktree), "contract_version": "r1",
                "source_identities": {},
                "objective": "do the work",
                "assumptions": [{"text": "a", "confidence": "low"}],
                "expected_touch": {"entries": ["base.txt"]},
                "impact_bounds": {"lower": "l", "upper": "u", "unknown": "?"},
            }, at="2026-09-27T15:00:00+00:00", task_id="test-fixture")

            environment = os.environ.copy()
            environment.update({
                "SULDE_AGENT_PROVIDER": "codex",
                "SULDE_CODEX_EXE": str(executable),
                "SULDE_TEST_MODE": "1",
            })
            completed = subprocess.run(
                [sys.executable, str(RUNTIME), "run", str(worktree), "embed",
                 str(brief), "--timeout", "15"],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                env=environment, check=False, timeout=120,
            )
            self.assertEqual(completed.returncode, 0,
                             completed.stdout + completed.stderr)

            ledger_rows = [json.loads(line) for line in
                           (state / "embed.run.jsonl").read_text(encoding="utf-8")
                           .splitlines() if line.strip()]
            run_id = ledger_rows[0]["run_id"]
            rebound = [r for r in ledger_rows if r.get("type") == "prediction.attempt_started"]
            feedback = [r for r in ledger_rows if r.get("type") == "prediction.feedback"]
            self.assertEqual(len(rebound), 1,
                             "attempt start must bind the prediction to the spawned run")
            self.assertEqual(rebound[0]["payload"]["status"], "attempt_started",
                             rebound[0]["payload"])

            # R2-02: the worktree is not a git repository, so the frozen
            # baseline is unresolvable -> explicit degradation, never checked.
            self.assertEqual(len(feedback), 1)
            self.assertEqual(feedback[0]["payload"]["status"], "degraded")
            self.assertIn("not resolvable", feedback[0]["payload"]["error"])

            # the rebind bound the prediction to the ACTUAL run id
            projection = ip.load_projection(store)
            entry = projection["tasks"][ip.digest("test-fixture")]
            self.assertEqual(entry["current"]["run_id_sha256"],
                             ip.digest(run_id))


if __name__ == "__main__":
    unittest.main()
