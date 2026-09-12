from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
ADAPTER_DIR = ROOT / "integrations" / "codex" / "plugins" / "sulde" / "scripts"
ADAPTER = ADAPTER_DIR / "user-prompt-submit.py"


def load_adapter():
    sys.path.insert(0, str(ADAPTER_DIR))
    spec = importlib.util.spec_from_file_location("test_codex_user_prompt_adapter_module", ADAPTER)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load Codex UserPromptSubmit adapter")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CodexUserPromptAdapterTests(unittest.TestCase):
    def run_adapter(self, prompt: str, completed=None, error=None, environment=None):
        module = load_adapter()
        stdout = io.StringIO()
        stderr = io.StringIO()
        payload = json.dumps({"cwd": str(ROOT), "sessionId": "thread", "prompt": prompt})
        if error is not None:
            runner = mock.Mock(side_effect=error)
        else:
            runner = mock.Mock(return_value=completed)
        with (
            mock.patch.object(module, "run_runtime", runner),
            mock.patch.object(sys, "stdin", io.StringIO(payload)),
            mock.patch.dict("os.environ", environment or {}, clear=False),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            exit_code = module.main()
        output = json.loads(stdout.getvalue())
        context = output["hookSpecificOutput"]["additionalContext"]
        return exit_code, context, stderr.getvalue(), runner.call_args

    def test_missing_payload_session_uses_current_codex_thread(self) -> None:
        module = load_adapter()
        payload = json.dumps({"cwd": str(ROOT), "prompt": "continue"})
        with (
            mock.patch.object(sys, "stdin", io.StringIO(payload)),
            mock.patch.dict(
                "os.environ",
                {"CODEX_THREAD_ID": "thread-from-host"},
                clear=False,
            ),
        ):
            normalized = module._payload()

        self.assertEqual(normalized["session_id"], "thread-from-host")

    def test_ordinary_prompt_runtime_failure_is_visible_but_non_blocking(self) -> None:
        completed = subprocess.CompletedProcess([], 7, "", "runtime failed\n")

        exit_code, context, stderr, _ = self.run_adapter("continue", completed=completed)

        self.assertEqual(exit_code, 0)
        self.assertIn("UNAVAILABLE reason=runtime_exit_7", context)
        self.assertIn("runtime failed", stderr)

    def test_native_only_text_prompt_runtime_failure_is_non_blocking(self) -> None:
        completed = subprocess.CompletedProcess([], 7, "", "runtime failed\n")

        exit_code, context, _, _ = self.run_adapter(
            "批准当前方案",
            completed=completed,
        )

        self.assertEqual(exit_code, 0)
        self.assertIn("UNAVAILABLE reason=runtime_exit_7", context)
        self.assertNotIn("CONTROL_NOT_RECORDED", context)

    def test_native_only_text_prompt_does_not_require_a_receipt_marker(self) -> None:
        completed = subprocess.CompletedProcess([], 0, "[sulde intent] ACTIVE", "")

        exit_code, context, _, _ = self.run_adapter(
            "批准当前方案",
            completed=completed,
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(context, "[sulde intent] ACTIVE")

    def test_control_prompt_with_receipt_marker_succeeds(self) -> None:
        digest = "c" * 64
        completed = subprocess.CompletedProcess(
            [],
            0,
            (
                "[sulde intent] CONTROL_RECORDED action=approve-proposal "
                f"target={digest} receipt={'d' * 64} provider=codex session=thread.\n"
                "[sulde intent] ACTIVE"
            ),
            "",
        )

        exit_code, context, _, call = self.run_adapter(
            "批准当前方案",
            completed=completed,
            environment={"SULDE_HOOK_OBSERVATION_SOURCE": "synthetic_smoke"},
        )

        self.assertEqual(exit_code, 0)
        self.assertIn("CONTROL_RECORDED", context)
        forwarded = json.loads(call.kwargs["input_text"])
        self.assertEqual(forwarded["client"], "codex")
        self.assertEqual(forwarded["session_id"], "thread")
        self.assertEqual(forwarded["sulde_observation_source"], "synthetic_smoke")

    def test_native_only_text_prompt_timeout_is_non_blocking(self) -> None:
        exit_code, context, _, _ = self.run_adapter(
            "批准当前方案",
            error=subprocess.TimeoutExpired(cmd="hook", timeout=115),
        )

        self.assertEqual(exit_code, 0)
        self.assertIn("UNAVAILABLE reason=timeout", context)

    def test_pause_and_external_attestation_remain_fail_closed(self) -> None:
        module = load_adapter()

        pause = module._fallback_control_request("先暂停修改")
        attestation = module._fallback_control_request(
            "确认外部操作失败：远端记录不存在"
        )
        retry = module._fallback_control_request("授权重试外部操作")

        self.assertTrue(module._text_control_requires_receipt(pause))
        self.assertTrue(module._text_control_requires_receipt(attestation))
        self.assertFalse(module._text_control_requires_receipt(retry))

    def test_fallback_parser_keeps_pause_and_resume_fail_closed(self) -> None:
        module = load_adapter()

        pause = module._fallback_control_request("先暂停修改")
        resume = module._fallback_control_request("确认意图并恢复")
        approve = module._fallback_control_request("批准当前方案")
        reject = module._fallback_control_request("拒绝当前方案")
        opaque = module._fallback_control_request("批准意图提案 " + "a" * 64)
        export_approve = module._fallback_control_request("批准观察导出")
        export_reject = module._fallback_control_request("拒绝观察导出")
        confirm_intent = module._fallback_control_request("确认当前意图")
        reject_intent = module._fallback_control_request("拒绝当前意图")
        intervention_failed = module._fallback_control_request(
            "确认外部操作失败：远端记录不存在"
        )
        intervention_retry = module._fallback_control_request("授权重试外部操作")
        retired_event = module._fallback_control_request("批准事件 " + "b" * 64)
        natural_resume = module._fallback_control_request(
            "确认意图镜像并恢复，这个问题也需要改掉"
        )

        self.assertEqual((pause.action, pause.target), ("pause", ""))
        self.assertEqual((resume.action, resume.target), ("resume", ""))
        self.assertEqual((approve.action, approve.target), ("approve-proposal", "current"))
        self.assertEqual((reject.action, reject.target), ("reject-proposal", "current"))
        self.assertEqual(
            (opaque.action, opaque.target),
            ("reject-opaque-proposal-approval", "a" * 64),
        )
        self.assertEqual(
            (export_approve.action, export_approve.target),
            ("approve-observation-export", "current"),
        )
        self.assertEqual(
            (export_reject.action, export_reject.target),
            ("reject-observation-export", "current"),
        )
        self.assertFalse(module._text_control_requires_receipt(export_approve))
        self.assertFalse(module._text_control_requires_receipt(export_reject))
        self.assertEqual(
            (confirm_intent.action, confirm_intent.target),
            ("confirm-intent", "current"),
        )
        self.assertEqual(
            (reject_intent.action, reject_intent.target),
            ("reject-intent", "current"),
        )
        self.assertEqual(
            (
                intervention_failed.action,
                intervention_failed.target,
                intervention_failed.decision,
                intervention_failed.evidence,
            ),
            (
                "intervention-resolve",
                "current",
                "confirmed_failed",
                "远端记录不存在",
            ),
        )
        self.assertEqual(
            (intervention_retry.action, intervention_retry.decision),
            ("intervention-resolve", "retry_authorized"),
        )
        self.assertEqual(
            (retired_event.action, retired_event.target),
            ("retired-event-approval", "b" * 64),
        )
        self.assertEqual((natural_resume.action, natural_resume.target), ("resume", ""))
        self.assertIsNone(module._fallback_control_request("示例：先暂停修改"))
        self.assertIsNone(
            module._fallback_control_request("不要确认意图镜像并恢复，这只是示例")
        )

    def test_pause_accepts_persisted_reason_as_receipt_target(self) -> None:
        completed = subprocess.CompletedProcess(
            [],
            0,
            (
                "[sulde intent] CONTROL_RECORDED action=pause "
                f"target=用户明确暂停 receipt={'f' * 64} provider=codex session=thread.\n"
                "[sulde intent] PAUSED"
            ),
            "",
        )

        exit_code, context, _, _ = self.run_adapter(
            "先暂停修改",
            completed=completed,
        )

        self.assertEqual(exit_code, 0)
        self.assertIn("CONTROL_RECORDED action=pause", context)


if __name__ == "__main__":
    unittest.main()
