from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "kb"))

from session_continuity import (  # noqa: E402
    ContinuationError,
    build_capsule,
    locate_codex_rollout,
    recent_dialogue,
    render_context,
    validate_capsule,
)
from intent_guardian import prepare_workspace_proposal  # noqa: E402


class SessionContinuityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def review(self) -> dict:
        return {
            "intent_id": "synthetic-application-visual-grammar",
            "base_revision": 1,
            "proposed_revision": 2,
            "proposal_digest": "a" * 64,
            "decision_route": "human",
            "decision_card": {
                "要完成的结果": "建立 SyntheticApplication 测试样例页面",
                "为什么要做": "先冻结视觉语言再替换组件",
                "允许改变": ["独立母题页"],
                "必须保持": ["Gate C", "现有产品代码"],
                "明确禁止": ["通用线性图标换皮"],
                "如何验收": ["去掉颜色和文字后仍可识别"],
                "风险与恢复": "删除独立母题页即可回退",
                "仍未确定": [],
            },
        }

    def test_capsule_is_digest_bound_redacted_and_authority_free(self) -> None:
        capsule = build_capsule(
            contract_path=self.root / "intent.active.json",
            proposal_path=self.root / "proposal.json",
            review=self.review(),
            workspace_root=self.root,
            created_at="2026-08-15T00:00:00+00:00",
            provider="codex",
            session_id="thread-one",
            dialogue=[
                {
                    "role": "user",
                    "content": "继续，token=private-value ghp_" + "A" * 32,
                },
                {"role": "assistant", "content": "先恢复可见任务上下文"},
            ],
        )

        rendered = json.dumps(capsule, ensure_ascii=False)
        self.assertNotIn("private-value", rendered)
        self.assertNotIn("ghp_" + "A" * 32, rendered)
        self.assertFalse(capsule["authority"]["transferred"])
        self.assertEqual(capsule["authority"]["approval_receipts_transferred"], 0)
        self.assertEqual(capsule["authority"]["tool_grants_transferred"], 0)
        context = render_context(capsule)
        self.assertIn("建立 SyntheticApplication 测试样例页面", context)
        self.assertIn("不转移人工批准", context)

        capsule["next_action"] = "skip review"
        with self.assertRaisesRegex(ContinuationError, "content digest changed"):
            validate_capsule(capsule)

    def test_recent_dialogue_keeps_only_visible_deduplicated_messages(self) -> None:
        rollout = self.root / "rollout-thread.jsonl"
        rows = [
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "developer",
                    "content": [{"type": "input_text", "text": "hidden instruction"}],
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "确认原方案"}],
                },
            },
            {
                "type": "event_msg",
                "payload": {"type": "user_message", "message": "确认原方案"},
            },
            {
                "type": "response_item",
                "payload": {"type": "function_call", "name": "dangerous-tool"},
            },
            {
                "type": "event_msg",
                "payload": {
                    "type": "agent_message",
                    "message": "已冻结，api_key: private-key",
                },
            },
        ]
        rollout.write_text(
            "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
            encoding="utf-8",
        )

        dialogue = recent_dialogue(rollout, max_tail_bytes=16_384)

        self.assertEqual([row["role"] for row in dialogue], ["user", "assistant"])
        rendered = json.dumps(dialogue, ensure_ascii=False)
        self.assertEqual(rendered.count("确认原方案"), 1)
        self.assertNotIn("hidden instruction", rendered)
        self.assertNotIn("dangerous-tool", rendered)
        self.assertNotIn("private-key", rendered)

    def test_rollout_lookup_is_exact_and_rejects_unsafe_session_ids(self) -> None:
        session_id = "00000000-0000-7000-8000-000000000001"
        sessions = self.root / "sessions" / "2026" / "08" / "15"
        sessions.mkdir(parents=True)
        expected = sessions / f"rollout-2026-08-15T00-00-00-{session_id}.jsonl"
        expected.write_text("{}\n", encoding="utf-8")

        self.assertEqual(
            locate_codex_rollout(session_id, codex_home=self.root),
            expected,
        )
        self.assertIsNone(locate_codex_rollout("../../escape", codex_home=self.root))

    def test_codex_session_start_injects_frozen_context_for_new_thread(self) -> None:
        home = self.root / "kb-home"
        workspace = self.root / "workspace"
        workspace.mkdir()
        (workspace / ".git").mkdir()
        prepare_workspace_proposal(
            home,
            workspace,
            intent_id="synthetic-application-context-resume",
            objective="建立 SyntheticApplication 测试样例页面",
            acceptance_criteria=["不覆盖现有产品代码"],
            mode="enforce",
            decision_route="human",
            provider="codex",
            session_id="old-thread",
        )
        env = os.environ.copy()
        env.update(
            {
                "SULDE_KB_HOME": str(home),
                "SULDE_SOURCE_ROOT": str(ROOT),
                "CODEX_THREAD_ID": "new-thread",
            }
        )

        completed = subprocess.run(
            [
                sys.executable,
                str(
                    ROOT
                    / "integrations"
                    / "codex"
                    / "plugins"
                    / "sulde"
                    / "scripts"
                    / "session-start.py"
                ),
            ],
            input=json.dumps({"cwd": str(workspace), "session_id": "new-thread"}),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=20,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        output = json.loads(completed.stdout.strip().splitlines()[-1])
        context = output["hookSpecificOutput"]["additionalContext"]
        self.assertIn("[sulde-continuation]", context)
        self.assertIn("建立 SyntheticApplication 测试样例页面", context)
        self.assertIn("不转移人工批准", context)

        claude = subprocess.run(
            [sys.executable, str(ROOT / "hooks" / "session_start.py")],
            input=json.dumps({"cwd": str(workspace), "session_id": "claude-new-thread"}),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=20,
            check=False,
        )
        self.assertEqual(claude.returncode, 0, claude.stderr)
        contexts = [
            json.loads(line)["hookSpecificOutput"]["additionalContext"]
            for line in claude.stdout.splitlines()
            if line.strip()
        ]
        self.assertTrue(any("[sulde-continuation]" in item for item in contexts))
        self.assertTrue(any("建立 SyntheticApplication 测试样例页面" in item for item in contexts))


if __name__ == "__main__":
    unittest.main()
