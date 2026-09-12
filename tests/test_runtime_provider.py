from __future__ import annotations

import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "scripts" / "kb"
RUNTIME = SCRIPT_DIR / "llm-runtime.py"

sys.path.insert(0, str(SCRIPT_DIR))
from runtime_provider import (  # noqa: E402
    ProviderError,
    CODEX_MODEL_FOR_TIER,
    cognitive_command,
    legacy_task_profile,
    model_dispatch_plan,
    normalize_capability_tier,
    render_dispatch_instructions,
    select_provider,
    task_command,
    validate_dispatch_instructions,
)

MODEL_DISPATCH = SCRIPT_DIR / "model-dispatch.py"


def load_llm_runtime():
    spec = importlib.util.spec_from_file_location("test_llm_runtime", RUNTIME)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {RUNTIME}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class RuntimeProviderTests(unittest.TestCase):
    @staticmethod
    def fake_which(available: dict[str, str]):
        return lambda command: available.get(command)

    def test_explicit_provider_never_falls_back(self) -> None:
        with self.assertRaisesRegex(ProviderError, "will not fall back"):
            select_provider(
                "codex",
                environment={},
                which=self.fake_which({"claude": "/fake/claude"}),
            )

    def test_auto_selects_only_installed_provider(self) -> None:
        self.assertEqual(
            select_provider(
                environment={},
                which=self.fake_which({"codex": "/fake/codex"}),
            ),
            ("codex", "/fake/codex"),
        )

    def test_auto_refuses_ambiguous_coexistence(self) -> None:
        with self.assertRaisesRegex(ProviderError, "both Claude Code and Codex"):
            select_provider(
                environment={},
                which=self.fake_which(
                    {"claude": "/fake/claude", "codex": "/fake/codex"}
                ),
            )

    def test_host_evidence_selects_its_own_runtime(self) -> None:
        self.assertEqual(
            select_provider(
                environment={"CODEX_THREAD_ID": "thread"},
                which=self.fake_which(
                    {"claude": "/fake/claude", "codex": "/fake/codex"}
                ),
            ),
            ("codex", "/fake/codex"),
        )

    def test_cognitive_adapters_are_read_only_and_nonpersistent(self) -> None:
        claude = cognitive_command("claude", "/fake/claude")
        codex = cognitive_command("codex", "/fake/codex")
        self.assertIn("--safe-mode", claude)
        self.assertIn("--no-session-persistence", claude)
        self.assertEqual(claude[claude.index("--output-format") + 1], "text")
        self.assertNotIn("--include-hook-events", claude)
        self.assertIn("read-only", codex)
        self.assertIn("--ephemeral", codex)
        self.assertEqual(codex[-1], "-")

    def test_llm_runtime_hides_provider_console_on_windows(self) -> None:
        module = load_llm_runtime()
        command = [r"C:\fake\codex.exe", "exec", "-"]
        prompt = "Return exactly OK."

        with mock.patch.object(
            module,
            "parse_args",
            return_value=SimpleNamespace(provider="codex"),
        ), mock.patch.object(
            module,
            "select_provider",
            return_value=("codex", command[0]),
        ), mock.patch.object(
            module,
            "cognitive_command",
            return_value=command,
        ), mock.patch.object(
            module.os,
            "name",
            "nt",
        ), mock.patch.object(
            module.sys,
            "stdin",
            io.StringIO(prompt),
        ), mock.patch.object(
            module.subprocess,
            "run",
            return_value=SimpleNamespace(returncode=0),
        ) as child:
            result = module.main()

        self.assertEqual(result, 0)
        child.assert_called_once()
        arguments, keywords = child.call_args
        self.assertEqual(arguments, (command,))
        self.assertEqual(keywords["env"]["SULDE_ACTIVE_PROVIDER"], "codex")
        self.assertEqual(keywords.get("input"), prompt)
        self.assertTrue(keywords.get("text"))
        self.assertEqual(keywords.get("creationflags"), 0x08000000)

    def test_task_adapters_are_symmetric_and_workspace_scoped(self) -> None:
        root = Path("/tmp/worktree")
        report = root / ".codex-agent/task.last.md"
        claude = task_command(
            "claude", "/fake/claude", worktree=root, report=report, effort="high"
        )
        codex = task_command(
            "codex", "/fake/codex", worktree=root, report=report, effort="high"
        )
        expected_permission_mode = "auto" if os.name == "nt" else "acceptEdits"
        self.assertEqual(
            claude[claude.index("--permission-mode") + 1],
            expected_permission_mode,
        )
        self.assertIn("--no-session-persistence", claude)
        self.assertIn("--safe-mode", claude)
        self.assertIn("--settings", claude)
        self.assertEqual(claude[claude.index("--output-format") + 1], "stream-json")
        self.assertIn("--include-hook-events", claude)
        self.assertIn("allowUnsandboxedCommands", claude[claude.index("--settings") + 1])
        self.assertIn("workspace-write", codex)
        self.assertIn("--ignore-user-config", codex)
        self.assertIn("--ignore-rules", codex)
        self.assertIn(str(root), codex)
        self.assertIn(str(report), codex)

    def test_capability_tier_accepts_legacy_claude_labels_for_migration(self) -> None:
        self.assertEqual(normalize_capability_tier("opus"), "deep")
        self.assertEqual(normalize_capability_tier("sonnet"), "balanced")
        self.assertEqual(normalize_capability_tier("haiku"), "light")

    def test_legacy_task_profile_uses_the_stronger_archived_requirement(self) -> None:
        tier, warnings = legacy_task_profile(
            model="sonnet",
            thinking_mode="ultrathink",
        )
        self.assertEqual(tier, "deep")
        self.assertEqual(len(warnings), 2)

    def test_codex_dispatch_preserves_a_capable_current_session(self) -> None:
        plan = model_dispatch_plan(
            "codex",
            "deep",
            current_model="gpt-current",
            current_capability_tier="deep",
            current_effort="max",
            model_advice=True,
        )
        self.assertTrue(plan["ready"])
        self.assertEqual(plan["actions"], [])
        instructions = render_dispatch_instructions(
            plan,
            task_path=".ai-workspace/tasks/fix.md",
        )
        rendered = "\n".join(instructions).lower()
        self.assertIn("当前模型", rendered)
        self.assertIn("执行任务文件:", rendered)
        self.assertNotIn("/assign", rendered)
        for claude_label in ("opus", "sonnet", "haiku", "/mode "):
            self.assertNotIn(claude_label, rendered)

    def test_codex_dispatch_uses_native_selectors_when_below_floor(self) -> None:
        plan = model_dispatch_plan(
            "codex",
            "deep",
            current_model="gpt-current",
            current_capability_tier="balanced",
            current_effort="low",
            model_advice=True,
        )
        self.assertFalse(plan["ready"])
        self.assertEqual(
            [action["command"] for action in plan["actions"]],
            ["/model", "/reasoning"],
        )
        self.assertEqual(plan["target"]["model"], CODEX_MODEL_FOR_TIER["deep"])
        self.assertEqual(plan["target"]["minimum_reasoning_effort"], "high")
        self.assertIn(
            CODEX_MODEL_FOR_TIER["deep"],
            plan["actions"][0]["selection"],
        )
        rendered = json.dumps(plan, ensure_ascii=False).lower()
        for claude_label in ("opus", "sonnet", "haiku", "/mode "):
            self.assertNotIn(claude_label, rendered)

    def test_codex_dispatch_infers_known_current_model_tier(self) -> None:
        plan = model_dispatch_plan(
            "codex",
            "balanced",
            current_model="gpt-5.6-sol",
            current_effort="xhigh",
            model_advice=True,
        )
        self.assertTrue(plan["ready"])
        self.assertEqual(plan["current"]["capability_tier"], "deep")
        self.assertEqual(plan["actions"], [])

    def test_codex_dispatch_honors_explicit_max_reasoning_floor(self) -> None:
        plan = model_dispatch_plan(
            "codex",
            "deep",
            current_model="gpt-5.6-sol",
            current_effort="high",
            required_effort="max",
            model_advice=True,
        )
        self.assertEqual(
            [action["command"] for action in plan["actions"]],
            ["/reasoning"],
        )
        self.assertEqual(plan["target"]["minimum_reasoning_effort"], "max")

    def test_codex_dispatch_rejects_reported_claude_short_instruction(self) -> None:
        with self.assertRaisesRegex(ProviderError, "foreign-provider"):
            validate_dispatch_instructions(
                "codex",
                [
                    "/model opus",
                    "继续原任务，不 /clear、不切 task、不新建 branch。",
                ],
            )

    def test_claude_dispatch_translates_deep_tier_to_native_model(self) -> None:
        plan = model_dispatch_plan(
            "claude",
            "deep",
            current_model="claude-sonnet-current",
        )
        self.assertEqual(plan["actions"][0]["command"], "/model opus")
        self.assertEqual(plan["target"]["thinking_hint"], "ultrathink")
        instructions = render_dispatch_instructions(
            plan,
            task_path=".ai-workspace/tasks/fix.md",
            fresh_session=True,
        )
        self.assertEqual(instructions[0], "/clear")
        self.assertEqual(instructions[-1], "/assign 任务文件:.ai-workspace/tasks/fix.md")

    def test_codex_rejects_a_claude_label_as_current_model(self) -> None:
        with self.assertRaisesRegex(ProviderError, "Claude model label"):
            model_dispatch_plan(
                "codex",
                "balanced",
                current_model="opus",
                current_capability_tier="deep",
                current_effort="high",
                model_advice=True,
            )

    def test_model_dispatch_cli_emits_codex_native_json(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                str(MODEL_DISPATCH),
                "--provider",
                "codex",
                "--tier",
                "deep",
                "--current-model",
                "gpt-current",
                "--current-tier",
                "deep",
                "--current-effort",
                "max",
                "--task",
                ".ai-workspace/tasks/fix.md",
                "--format",
                "json",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["provider"], "codex")
        self.assertEqual(payload["target"]["model"], "gpt-current")
        self.assertEqual(payload["instructions"][-1], "执行任务文件:.ai-workspace/tasks/fix.md")

    def test_codex_default_dispatch_never_requests_model_changes(self) -> None:
        for tier in ("light", "balanced", "deep"):
            for state in ({}, {"current_model": "gpt-current", "current_effort": "low"}):
                with self.subTest(tier=tier, state=state):
                    plan = model_dispatch_plan("codex", tier, **state)
                    self.assertEqual(plan["actions"], [])
                    self.assertEqual(plan["notices"], [])
                    self.assertFalse(plan["model_advice"])
                    self.assertEqual(plan["target"]["model_policy"], "preserve-current-dispatch-only")
                    self.assertEqual(
                        render_dispatch_instructions(plan, task_path="task.md"),
                        ["执行任务文件:task.md"],
                    )

    def test_codex_cli_advice_is_explicit_opt_in(self) -> None:
        for advice in (False, True):
            for output_format in ("text", "json"):
                with self.subTest(advice=advice, output_format=output_format):
                    argv = [sys.executable, str(MODEL_DISPATCH), "--provider", "codex",
                            "--tier", "deep", "--task", "task.md", "--format", output_format]
                    if advice:
                        argv.append("--model-advice")
                    result = subprocess.run(argv, capture_output=True, text=True,
                                            encoding="utf-8", errors="replace", check=False)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    if output_format == "json":
                        payload = json.loads(result.stdout)
                        lines = payload["instructions"]
                        self.assertEqual(payload["model_advice"], advice)
                        if not advice:
                            self.assertEqual(payload["actions"], [])
                    else:
                        lines = result.stdout.splitlines()
                    if advice:
                        self.assertIn("/model", lines)
                        self.assertIn("/reasoning", lines)
                    else:
                        self.assertEqual(lines, ["执行任务文件:task.md"])

    def test_codex_required_effort_needs_explicit_advice(self) -> None:
        with self.assertRaisesRegex(ProviderError, "model.advice"):
            model_dispatch_plan("codex", "deep", required_effort="max")

    def test_codex_fresh_dispatch_does_not_claim_model_readiness(self) -> None:
        plan = model_dispatch_plan("codex", "deep")
        self.assertEqual(render_dispatch_instructions(plan, task_path="task.md", fresh_session=True),
                         ["/new", "执行任务文件:task.md"])

    @unittest.skipIf(os.name == "nt", "POSIX executable fixture")
    def test_llm_runtime_sends_prompt_over_stdin_for_each_provider(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake = root / "provider"
            fake.write_text(
                "#!/bin/sh\nIFS= read -r line\nprintf '%s\\n' \"$line\"\n",
                encoding="utf-8",
            )
            fake.chmod(0o755)
            for provider, variable in (
                ("claude", "SULDE_CLAUDE_EXE"),
                ("codex", "SULDE_CODEX_EXE"),
            ):
                environment = os.environ.copy()
                environment.update(
                    {"SULDE_LLM_PROVIDER": provider, variable: str(fake)}
                )
                completed = subprocess.run(
                    [sys.executable, str(RUNTIME)],
                    input=f"prompt-{provider}\n",
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    env=environment,
                    check=False,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertEqual(completed.stdout.strip(), f"prompt-{provider}")


if __name__ == "__main__":
    unittest.main()
