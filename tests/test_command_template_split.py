from __future__ import annotations

import ast
import runpy
import shlex
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPLITTER = ROOT / "scripts" / "kb" / "command_template.py"
SCANNED_ROOTS = ("scripts", "hooks", "tools")
DIRECT_SHLEX_SPLIT_EXEMPTIONS = {
    # Canonical shared parser POSIX branch: preserves the original semantics.
    ("scripts/kb/command_template.py", 29): "canonical POSIX parser branch",
    # Canonical shared parser Windows branch: disables POSIX backslash escapes.
    ("scripts/kb/command_template.py", 32): "canonical Windows parser branch",
    # Fleet tokenizes shell-like file contents, not a subprocess command template.
    ("scripts/kb/fleet.py", 130): "parses response-file contents, not a command template",
}


def load_template_helpers():
    return runpy.run_path(str(SPLITTER))


def load_splitter():
    return load_template_helpers()["split_command_template"]


def find_unapproved_direct_shlex_splits() -> list[str]:
    violations: list[str] = []
    used_exemptions: set[tuple[str, int]] = set()
    for root_name in SCANNED_ROOTS:
        for path in sorted((ROOT / root_name).rglob("*.py")):
            relative = path.relative_to(ROOT).as_posix()
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            modules = {"shlex"}
            functions: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name == "shlex":
                            modules.add(alias.asname or alias.name)
                elif isinstance(node, ast.ImportFrom) and node.module == "shlex":
                    for alias in node.names:
                        if alias.name == "split":
                            functions.add(alias.asname or alias.name)

            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                direct_split = (
                    isinstance(node.func, ast.Name) and node.func.id in functions
                ) or (
                    isinstance(node.func, ast.Attribute)
                    and node.func.attr == "split"
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id in modules
                )
                if not direct_split:
                    continue
                exemption = (relative, node.lineno)
                if exemption in DIRECT_SHLEX_SPLIT_EXEMPTIONS:
                    used_exemptions.add(exemption)
                    continue
                violations.append(f"{relative}:{node.lineno}")

    for (relative, lineno), reason in DIRECT_SHLEX_SPLIT_EXEMPTIONS.items():
        if not reason.strip():
            violations.append(f"undocumented exemption:{relative}:{lineno}")
        if (relative, lineno) not in used_exemptions:
            violations.append(f"unused exemption:{relative}:{lineno}")
    return violations


class CommandTemplateSplitTests(unittest.TestCase):
    def test_windows_backslash_paths_are_preserved(self) -> None:
        split_command_template = load_splitter()

        actual = split_command_template(
            r"C:\Users\me\Python313\python.exe C:\Temp\mock_llm.py",
            os_name="nt",
        )

        self.assertEqual(
            actual,
            [r"C:\Users\me\Python313\python.exe", r"C:\Temp\mock_llm.py"],
        )

    def test_windows_quoted_paths_with_spaces_are_unquoted(self) -> None:
        split_command_template = load_splitter()

        actual = split_command_template(
            r'"C:\Program Files\Python313\python.exe" "C:\Temp Dir\mock_llm.py"',
            os_name="nt",
        )

        self.assertEqual(
            actual,
            [
                r"C:\Program Files\Python313\python.exe",
                r"C:\Temp Dir\mock_llm.py",
            ],
        )

    def test_posix_quotes_escapes_and_word_splitting_match_shlex(self) -> None:
        split_command_template = load_splitter()
        command_template = r'''tool --label "two words" escaped\ space 'single quoted' '''.strip()

        actual = split_command_template(command_template, os_name="posix")

        self.assertEqual(actual, shlex.split(command_template))
        self.assertEqual(
            actual,
            ["tool", "--label", "two words", "escaped space", "single quoted"],
        )

    def test_comments_mode_preserves_policy_parser_semantics(self) -> None:
        split_command_template = load_splitter()

        self.assertEqual(
            split_command_template("rm target # ignored", comments=True),
            ["rm", "target"],
        )
        self.assertEqual(
            split_command_template("echo '# data'", comments=True),
            ["echo", "# data"],
        )

    def test_exact_shell_wrapper_exposes_only_one_literal_payload(self) -> None:
        shell_wrapper_payload = load_template_helpers()["shell_wrapper_payload"]

        self.assertEqual(
            shell_wrapper_payload("/bin/sh -c 'git push origin main'"),
            "git push origin main",
        )
        self.assertIsNone(
            shell_wrapper_payload("/bin/sh -c 'git push origin main' attacker")
        )
        self.assertIsNone(shell_wrapper_payload("/bin/sh -n run-hook.sh"))

    def test_single_heredoc_requires_a_noncomposed_header(self) -> None:
        split_single_heredoc = load_template_helpers()["split_single_heredoc"]

        self.assertEqual(
            split_single_heredoc("python3 - <<'PY'\nprint('fixture')\nPY\n"),
            ("python3 -", "print('fixture')\n"),
        )
        self.assertIsNone(
            split_single_heredoc(
                "python3 - <<'PY' | /bin/sh\nprint('git push origin main')\nPY\n"
            )
        )

    def test_unquoted_heredoc_with_shell_expansion_is_not_treated_as_data(self) -> None:
        split_single_heredoc = load_template_helpers()["split_single_heredoc"]

        self.assertIsNone(
            split_single_heredoc(
                'python3 - <<PY\nprint("$(git push origin main)")\nPY\n'
            )
        )


class CommandTemplateDriftGuardTests(unittest.TestCase):
    def test_repository_has_no_unapproved_direct_shlex_split(self) -> None:
        violations = find_unapproved_direct_shlex_splits()

        self.assertFalse(
            violations,
            "direct shlex.split bypasses the shared parser:\n"
            + "\n".join(violations),
        )


if __name__ == "__main__":
    unittest.main()
