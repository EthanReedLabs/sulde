from __future__ import annotations

from pathlib import Path
import shlex
import sys
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "kb"))

from command_template import (  # noqa: E402
    git_execution_passthrough,
    has_unquoted_shell_control,
    is_read_only_command,
    literal_git_add_paths,
    literal_git_worktree_lifecycle_action,
    read_pipeline_segments,
)


# Production-shaped R1 source edit; classification only, never execution.
PRODUCTION_SOURCE_WRITE_COMMAND = shlex.join(["python3", "-c", """from pathlib import Path
p=Path('tests/test_command_policy.py')
s=p.read_text().replace('import unittest\\n', 'import unittest\\nfrom unittest import mock\\n', 1)
pos=s.index('    def test_git_is_an_execution_domain')
s=s[:pos]+'''    def test_negative(self):
        command = "rm -rf output"
        self.assertEqual(classify(command), "destructive")

'''+s[pos:]
p.write_text(s)
"""])
SHELL_DATA_COMMANDS = (
    PRODUCTION_SOURCE_WRITE_COMMAND,
    "printf '%s\\n' 'rm -rf output'",
    "printf '%s\\n' \"nested 'rm -rf output'\"",
    "rg 'rm -rf output' README.md",
    "opaque --pattern 'rm -rf output'",
    "printf okay # rm -rf output",
    "printf '%s' '$(rm -rf output)'",
    "printf '%s' '`rm -rf output`'",
    "printf '%s' 'data; rm -rf output' > output",
)
SHELL_DESTRUCTIVE_COMMANDS = (
    "rm -rf output",
    "/bin/rm output",
    "printf okay ; rm -rf output",
    "printf okay && rm -rf output",
    "printf okay || rm -rf output",
    "printf okay | rm -rf output",
    "printf okay & rm -rf output",
    "printf '%s' $(rm -rf output)",
    'printf "%s" "$(rm -rf output)"',
    'printf "%s" "`rm -rf output`"',
    "cat <(rm -rf output)",
    'printf "%s" "$(printf "%s" "$(rm -rf output)")"',
    "printf okay # data\nrm -rf output",
    "python3 -c 'print(1)' ; rm -rf output",
    "env NAME=value /bin/rm -rf output",
)


class CommandPolicyTests(unittest.TestCase):
    def test_destructive_evidence_uses_execution_boundaries(self) -> None:
        from intent_guardian_parts import resources

        for command in SHELL_DATA_COMMANDS:
            with self.subTest(command=command):
                self.assertFalse(resources._composition_has_destructive_segment(command))
                self.assertNotEqual(resources._command_effect(command), "destructive")
        for command in SHELL_DESTRUCTIVE_COMMANDS:
            with self.subTest(command=command):
                self.assertTrue(resources._composition_has_destructive_segment(command))
                self.assertEqual(resources._command_effect(command), "destructive")
                self.assertFalse(is_read_only_command(command))
    def test_quoted_operator_data_is_not_composition(self) -> None:
        self.assertFalse(has_unquoted_shell_control("rg 'a;b|c&&d' README.md"))
        self.assertFalse(has_unquoted_shell_control('rg "a;b|c&&d" README.md'))
        self.assertTrue(has_unquoted_shell_control("rg 'unterminated README.md"))

    def test_shell_substitution_is_rejected_even_inside_double_quotes(self) -> None:
        for command in (
            "rg $(pwd) README.md",
            'rg "$(pwd)" README.md',
            'rg "`pwd`" README.md',
            'rg "${HOME}" README.md',
        ):
            with self.subTest(command=command):
                self.assertTrue(has_unquoted_shell_control(command))
                self.assertIsNone(read_pipeline_segments(command))

    def test_read_composition_segments_are_lexically_split(self) -> None:
        self.assertEqual(
            read_pipeline_segments("rg 'a|b' README.md | head -5 && git status"),
            ["rg 'a|b' README.md", "head -5", "git status"],
        )
        for command in (
            "rg a README.md || true",
            "rg a README.md &",
            "rg a README.md > result.txt",
            "rg a README.md |",
        ):
            with self.subTest(command=command):
                self.assertIsNone(read_pipeline_segments(command))

    def test_every_segment_must_independently_be_read_only(self) -> None:
        for command in (
            "rg guardian scripts | head -5",
            "sed -n '1,20p' README.md 2>/dev/null",
        ):
            with self.subTest(command=command):
                self.assertTrue(is_read_only_command(command))
        for command in (
            "git status; git add README.md",
            "sed -i '' README.md",
            "rg guardian scripts > result.txt",
            "intent-guardian skill-end --help ; jq -n true",
        ):
            with self.subTest(command=command):
                self.assertFalse(is_read_only_command(command))

    def test_trusted_script_composition_invalidity_is_not_a_destructive_effect(self) -> None:
        from intent_guardian_parts import resources

        prefix = "python3 /installed/agent-runtime.py verify /task task"
        identity = {"effect": "unknown", "invalid_composition": True}
        for tail, expected in (
            (" | jq .status", "unknown"),
            (" ; opaque-diagnostic", "unknown"),
            (" || opaque-diagnostic", "unknown"),
            (" > output", "unknown"),
            (" ; rm -rf output", "destructive"),
            (" && rm -rf output", "destructive"),
            (" || rm -rf output", "destructive"),
            (" & rm -rf output", "destructive"),
            (" | rm -rf output", "destructive"),
            (" ; rg 'rm -rf output' README.md", "unknown"),
        ):
            with self.subTest(tail=tail), mock.patch.object(
                resources, "_trusted_script_command",
                side_effect=lambda command, **kwargs: identity if command.startswith(prefix) else None,
            ):
                self.assertEqual(resources._command_effect(prefix + tail), expected)
                self.assertFalse(is_read_only_command(prefix + tail))

    def test_only_digest_pinned_runtime_diagnostics_are_read_only(self) -> None:
        from intent_guardian_parts import resources

        installed = "/installed/runtime/scripts/kb/agent-runtime.py"
        identity = {
            "argv_contract": "agent-runtime-git-lifecycle-v1",
            "profile_id": "sulde-agent-runtime-git-lifecycle-v1",
            "script_sha256": "a" * 64,
        }

        def identify(tokens, **_kwargs):
            return identity if len(tokens) > 1 and tokens[1] == installed else None

        with (
            mock.patch.object(
                resources, "identify_trusted_script_command", side_effect=identify
            ),
            mock.patch.object(
                resources, "classify_trusted_script_command", return_value=None
            ),
        ):
            for arguments in (
                ["--help"],
                ["verify", "--help"],
                ["verify", "/task", "task-slug"],
                [
                    "verify",
                    "/task",
                    "task-slug",
                    "--brief-sha256",
                    "b" * 64,
                    "--task-id",
                    "TASK-1",
                ],
            ):
                command = shlex.join(["python3", installed, *arguments])
                self.assertEqual(
                    resources._trusted_script_command(command),
                    {**identity, "effect": "read"},
                    arguments,
                )
                self.assertEqual(resources._command_effect(command), "read")

            for script, arguments in (
                ("/candidate/scripts/kb/agent-runtime.py", ["verify", "--help"]),
                (installed, ["run", "--help"]),
                (installed, ["verify", "relative-task", "task-slug"]),
                (installed, ["verify", "/task", "bad/slug"]),
                (installed, ["verify", "/task", "task-slug", "--unknown", "x"]),
            ):
                command = shlex.join(["python3", script, *arguments])
                classified = resources._trusted_script_command(command)
                self.assertFalse(
                    classified is not None and classified.get("effect") == "read",
                    command,
                )

    def test_git_is_an_execution_domain_not_a_read_write_policy(self) -> None:
        for command in (
            "git status",
            "/usr/bin/git -C /tmp worktree add /tmp/task branch",
            "git status; git add README.md",
        ):
            with self.subTest(command=command):
                self.assertTrue(git_execution_passthrough(command))
                self.assertFalse(is_read_only_command(command))
        self.assertFalse(git_execution_passthrough("git status | tee status.txt"))

    def test_literal_git_add_requires_separator_and_explicit_paths(self) -> None:
        self.assertEqual(
            literal_git_add_paths("git add -- one.md 'dir/two words.md'"),
            ["one.md", "dir/two words.md"],
        )
        self.assertEqual(
            literal_git_add_paths("git add -- name,with-comma.md name,with-comma.md"),
            ["name,with-comma.md"],
        )
        for command in (
            "git add one.md",
            "git add --",
            "git -C repo add -- one.md",
            "git add -A",
            "git add -u -- one.md",
            "git add -- .",
            "git add -- '*.md'",
            "git add -- ':(glob)*.md'",
            "git add -- ../outside.md",
            "git add -- .git/config",
            "git add -- .GIT/config",
            "git add -- dir/./one.md",
            "git add -- one.md && git status",
        ):
            with self.subTest(command=command):
                self.assertIsNone(literal_git_add_paths(command))

    def test_literal_git_worktree_lifecycle_has_two_exact_capabilities(self) -> None:
        self.assertEqual(
            literal_git_worktree_lifecycle_action(
                "git worktree add .worktrees/restored dev/as-eric/restored"
            ),
            {
                "schema": "sulde-git-worktree-lifecycle-classification-v1",
                "operation": "attach_existing",
                "repository": "",
                "target": ".worktrees/restored",
                "branch": "dev/as-eric/restored",
                "base": "dev/as-eric/restored",
                "effect": "local_write",
                "execution_authorized": False,
            },
        )
        self.assertEqual(
            literal_git_worktree_lifecycle_action(
                "git -C /repo worktree add -b task/new /repo/.worktrees/new dev"
            )["operation"],
            "create_branch",
        )

    def test_literal_git_worktree_lifecycle_rejects_broad_or_composed_forms(self) -> None:
        for command in (
            "git worktree add --force .worktrees/task task/one",
            "git worktree add -b task/new .worktrees/new dev extra",
            "git worktree add --detach .worktrees/task HEAD",
            "git worktree add .worktrees/task refs/heads/task/one",
            "git worktree add ../task task/one",
            "git worktree add .worktrees//task task/one",
            "git worktree add .worktrees/task task/one && git status",
        ):
            with self.subTest(command=command):
                self.assertIsNone(literal_git_worktree_lifecycle_action(command))


if __name__ == "__main__":
    unittest.main()
