from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "hooks" / "user_prompt_submit.py"


def load_module():
    spec = importlib.util.spec_from_file_location("sulde_user_prompt_control_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class UserPromptControlPlaneTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.kb_home = root / "kb"
        self.environment = mock.patch.dict(
            os.environ,
            {
                "HOME": str(root / "home"),
                "CODEX_HOME": str(root / "codex-home"),
                "SULDE_KB_HOME": str(self.kb_home),
                "SULDE_TEST_MODE": "1",
            },
            clear=False,
        )
        self.environment.start()

    def tearDown(self) -> None:
        self.environment.stop()
        self.temporary.cleanup()

    def test_exact_human_control_is_not_captured_recalled_or_skill_triggered(self) -> None:
        module = load_module()
        payload = {
            "client": "codex",
            "session_id": "thread-one",
            "prompt": "先暂停执行",
        }
        with (
            mock.patch.object(module, "read_json_stdin", return_value=payload),
            mock.patch.object(
                module,
                "observe_user_prompt",
                return_value="[sulde intent] CONTROL_RECORDED action=pause",
            ),
            mock.patch.object(module.mem_capture, "run") as capture,
            mock.patch.object(module.kb_recall, "run") as kb_recall,
            mock.patch.object(module.mem_recall, "run") as mem_recall,
            mock.patch.object(module.skill_trigger, "run") as skill_trigger,
            mock.patch.object(module.perf_gate, "run") as perf_gate,
        ):
            self.assertEqual(module.main(), 0)
        capture.assert_not_called()
        kb_recall.assert_not_called()
        mem_recall.assert_not_called()
        skill_trigger.assert_not_called()
        perf_gate.assert_not_called()
        self.assertTrue((self.kb_home / "host-capabilities.jsonl").is_file())

    def test_readable_current_proposal_choice_is_control_not_task_content(self) -> None:
        module = load_module()
        payload = {
            "client": "codex",
            "session_id": "thread-two",
            "prompt": "批准当前方案",
        }
        with (
            mock.patch.object(module, "read_json_stdin", return_value=payload),
            mock.patch.object(
                module,
                "observe_user_prompt",
                return_value=(
                    "[sulde intent] CONTROL_RECORDED action=approve-proposal "
                    f"target={'a' * 64}"
                ),
            ),
            mock.patch.object(module.mem_capture, "run") as capture,
            mock.patch.object(module.kb_recall, "run") as kb_recall,
            mock.patch.object(module.mem_recall, "run") as mem_recall,
            mock.patch.object(module.skill_trigger, "run") as skill_trigger,
            mock.patch.object(module.perf_gate, "run") as perf_gate,
        ):
            self.assertEqual(module.main(), 0)
        capture.assert_not_called()
        kb_recall.assert_not_called()
        mem_recall.assert_not_called()
        skill_trigger.assert_not_called()
        perf_gate.assert_not_called()

    def test_readable_observation_export_choice_is_control_not_task_content(self) -> None:
        module = load_module()
        payload = {
            "client": "codex",
            "session_id": "thread-export",
            "prompt": "批准观察导出",
        }
        with (
            mock.patch.object(module, "read_json_stdin", return_value=payload),
            mock.patch.object(
                module,
                "observe_user_prompt",
                return_value=(
                    "[sulde intent] CONTROL_RECORDED "
                    "action=approve-observation-export "
                    f"target={'a' * 64}"
                ),
            ),
            mock.patch.object(module.mem_capture, "run") as capture,
            mock.patch.object(module.kb_recall, "run") as kb_recall,
            mock.patch.object(module.mem_recall, "run") as mem_recall,
            mock.patch.object(module.skill_trigger, "run") as skill_trigger,
            mock.patch.object(module.perf_gate, "run") as perf_gate,
        ):
            self.assertEqual(module.main(), 0)
        capture.assert_not_called()
        kb_recall.assert_not_called()
        mem_recall.assert_not_called()
        skill_trigger.assert_not_called()
        perf_gate.assert_not_called()

    def test_readable_effect_intervention_choice_is_control_not_task_content(self) -> None:
        module = load_module()
        payload = {
            "client": "codex",
            "session_id": "thread-intervention",
            "prompt": "确认外部操作失败：远端记录不存在",
        }
        with (
            mock.patch.object(module, "read_json_stdin", return_value=payload),
            mock.patch.object(
                module,
                "observe_user_prompt",
                return_value=(
                    "[sulde intent] CONTROL_RECORDED "
                    "action=intervention-resolve "
                    "target=int-0123456789abcdef01234567"
                ),
            ),
            mock.patch.object(module.mem_capture, "run") as capture,
            mock.patch.object(module.kb_recall, "run") as kb_recall,
            mock.patch.object(module.mem_recall, "run") as mem_recall,
            mock.patch.object(module.skill_trigger, "run") as skill_trigger,
            mock.patch.object(module.perf_gate, "run") as perf_gate,
        ):
            self.assertEqual(module.main(), 0)
        capture.assert_not_called()
        kb_recall.assert_not_called()
        mem_recall.assert_not_called()
        skill_trigger.assert_not_called()
        perf_gate.assert_not_called()


if __name__ == "__main__":
    unittest.main()
