from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent


class PublicToolkitTest(unittest.TestCase):
    def run_cli(
        self,
        *args: str,
        repo: Path = REPO,
        cwd: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env.update({"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"})
        return subprocess.run(
            [sys.executable, str(repo / "scripts" / "sulde.py"), *args],
            cwd=str(cwd or repo),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
            check=False,
        )

    def copy_repo(self, destination: Path) -> Path:
        root = destination / "sulde"
        shutil.copytree(
            REPO,
            root,
            ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc", ".DS_Store"),
        )
        return root

    def test_doctor_passes_without_git_checkout_metadata(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sulde-clean-install-") as temp:
            staged = self.copy_repo(Path(temp))
            result = self.run_cli("doctor", "--json", repo=staged)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["summary"]["error"], 0)
            names = {item["name"] for item in payload["checks"]}
            self.assertTrue({"python", "pyyaml", "manifest", "hooks", "extensions", "knowledge-kit"} <= names)

    def test_extension_generators_register_and_never_overwrite(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sulde-sdk-") as temp:
            staged = self.copy_repo(Path(temp))
            commands = (
                ("add-skill", "release-review", "--description", "Review a release"),
                (
                    "add-hook",
                    "ticket-gate",
                    "--event",
                    "PreToolUse",
                    "--matcher",
                    "Write|Edit",
                    "--description",
                    "Require a ticket",
                ),
                ("add-check", "repo-policy", "--description", "Check repository policy"),
                (
                    "add-knowledge-container",
                    "domain-notes",
                    "--description",
                    "Reusable domain notes",
                ),
            )
            for command in commands:
                result = self.run_cli(*command, repo=staged)
                self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

            skill = staged / "skills" / "community" / "release-review" / "SKILL.md"
            original = skill.read_text(encoding="utf-8")
            self.assertIn("Use when this project needs", original)
            duplicate = self.run_cli("add-skill", "release-review", repo=staged)
            self.assertEqual(duplicate.returncode, 2)
            self.assertEqual(skill.read_text(encoding="utf-8"), original)

            registry = json.loads((staged / "extensions" / "registry.json").read_text(encoding="utf-8"))
            self.assertEqual(len(registry["skills"]), 1)
            self.assertEqual(len(registry["hooks"]), 1)
            self.assertEqual(len(registry["checks"]), 1)
            self.assertEqual(len(registry["knowledge_containers"]), 1)
            container_registry = json.loads(
                (staged / "template" / "_project" / "knowledge" / "containers.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(container_registry["containers"][0]["name"], "domain-notes")

            doctor = self.run_cli("doctor", "--json", repo=staged)
            self.assertEqual(doctor.returncode, 0, doctor.stderr + doctor.stdout)
            doctor_payload = json.loads(doctor.stdout)
            self.assertTrue(any(item["name"] == "extension:repo-policy.py" for item in doctor_payload["checks"]))

    def test_generator_rejects_path_traversal_names(self) -> None:
        result = self.run_cli("add-skill", "../private")
        self.assertEqual(result.returncode, 2)
        self.assertIn("name must match", result.stderr)

    def test_skill_description_cannot_inject_frontmatter(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sulde-skill-injection-") as temp:
            staged = self.copy_repo(Path(temp))
            result = self.run_cli(
                "add-skill",
                "safe-skill",
                "--description",
                "Line one\nmalicious: true",
                repo=staged,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            content = (staged / "skills" / "community" / "safe-skill" / "SKILL.md").read_text(
                encoding="utf-8"
            )
            self.assertIn('description: "Line one\\nmalicious: true.', content)

    def test_knowledge_growth_loop(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sulde-kb-kit-") as temp:
            project = Path(temp) / "project"
            project.mkdir()
            initialized = self.run_cli("kb", "init", "--root", str(project))
            self.assertEqual(initialized.returncode, 0, initialized.stderr)

            body = project / "body.md"
            body.write_text(
                "## Problem\n\nCache refresh races lose the newest snapshot.\n\n"
                "## Cause\n\nTwo writers publish without a monotonic version gate.\n\n"
                "## Fix\n\nCompare versions before publishing.\n\n"
                "## Verification\n\nA concurrency regression test keeps the newest version.\n",
                encoding="utf-8",
            )
            added = self.run_cli(
                "kb",
                "add",
                "--root",
                str(project),
                "--container",
                "anti-patterns",
                "--title",
                "Monotonic cache publication",
                "--summary",
                "Concurrent cache writers must not replace a newer snapshot.",
                "--platform",
                "cross",
                "--body",
                str(body),
            )
            self.assertEqual(added.returncode, 0, added.stderr)

            lint = self.run_cli("kb", "lint", "--root", str(project))
            self.assertEqual(lint.returncode, 0, lint.stdout + lint.stderr)
            indexed = self.run_cli("kb", "index", "--root", str(project))
            self.assertEqual(indexed.returncode, 0, indexed.stderr)
            current = self.run_cli("kb", "index", "--root", str(project), "--check")
            self.assertEqual(current.returncode, 0, current.stdout + current.stderr)
            search = self.run_cli("kb", "search", "--root", str(project), "newest cache snapshot")
            self.assertEqual(search.returncode, 0, search.stderr)
            rows = json.loads(search.stdout)
            self.assertEqual(rows[0]["doc_id"], "anti-patterns/monotonic-cache-publication")

            duplicate = self.run_cli(
                "kb",
                "add",
                "--root",
                str(project),
                "--container",
                "anti-patterns",
                "--title",
                "Monotonic cache publish race",
                "--summary",
                "Concurrent cache writers must not replace a newer snapshot.",
                "--body",
                str(body),
            )
            self.assertEqual(duplicate.returncode, 2)
            self.assertIn("dedup gate", duplicate.stderr)

    def test_knowledge_init_preserves_existing_project_content(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sulde-kb-preserve-") as temp:
            project = Path(temp) / "project"
            knowledge = project / "knowledge"
            knowledge.mkdir(parents=True)
            readme = knowledge / "README.md"
            readme.write_text("# My project knowledge\n", encoding="utf-8")
            initialized = self.run_cli("kb", "init", "--root", str(project))
            self.assertEqual(initialized.returncode, 0, initialized.stderr)
            payload = json.loads(initialized.stdout)
            self.assertIn("README.md", payload["preserved"])
            self.assertEqual(readme.read_text(encoding="utf-8"), "# My project knowledge\n")
            self.assertTrue((knowledge / "schema.yaml").is_file())

    def test_custom_check_output_does_not_corrupt_doctor_json(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sulde-check-output-") as temp:
            staged = self.copy_repo(Path(temp))
            added = self.run_cli("add-check", "noisy-check", repo=staged)
            self.assertEqual(added.returncode, 0, added.stderr)
            check = staged / "extensions" / "checks" / "noisy-check.py"
            check.write_text(
                check.read_text(encoding="utf-8").replace(
                    '    _ = context\n',
                    '    _ = context\n    print("unexpected output")\n',
                ),
                encoding="utf-8",
            )
            doctor = self.run_cli("doctor", "--json", repo=staged)
            self.assertEqual(doctor.returncode, 1)
            payload = json.loads(doctor.stdout)
            noisy = next(item for item in payload["checks"] if item["name"] == "extension:noisy-check.py")
            self.assertEqual(noisy["status"], "error")
            self.assertIn("stdout/stderr", noisy["message"])

    def test_redaction_is_explicit_and_non_destructive(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sulde-redact-") as temp:
            root = Path(temp)
            source = root / "incident.md"
            output = root / "safe.md"
            source.write_text(
                "owner=alice@example.com\npath=/Users/alice/private\napi_key=abcdefghijk\n",
                encoding="utf-8",
            )
            result = self.run_cli("kb", "redact", "--root", str(root), str(source), "--output", str(output))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("alice@example.com", source.read_text(encoding="utf-8"))
            safe = output.read_text(encoding="utf-8")
            self.assertNotIn("alice@example.com", safe)
            self.assertNotIn("/Users/alice", safe)
            self.assertNotIn("abcdefghijk", safe)

    def test_manifest_uses_auto_discovery_and_hook_launcher(self) -> None:
        manifest = json.loads((REPO / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        hooks = json.loads((REPO / "hooks" / "hooks.json").read_text(encoding="utf-8"))
        self.assertNotIn("hooks", manifest)
        rendered = json.dumps(hooks)
        self.assertIn("run-hook.sh", rendered)
        self.assertNotIn("python3 ", rendered)
        self.assertEqual(rendered.count('"shell": "bash"'), 9)
        self.assertEqual(set(hooks["hooks"]), {
            "PreToolUse", "PostToolUse", "PostToolUseFailure", "UserPromptSubmit",
            "SessionStart", "PreCompact", "Notification", "Stop",
        })

    def test_launchers_pin_utf8_and_python_contract(self) -> None:
        shell = (REPO / "hooks" / "run-hook.sh").read_text(encoding="utf-8")
        powershell = (REPO / "hooks" / "run-hook.ps1").read_text(encoding="utf-8")
        self.assertIn("sys.version_info >= (3, 10)", shell)
        self.assertIn("PYTHONIOENCODING=utf-8", shell)
        self.assertIn('$env:PYTHONIOENCODING = "utf-8"', powershell)
        self.assertIn('Name = "py"', powershell)
        self.assertNotIn("\r\n", shell)


if __name__ == "__main__":
    unittest.main()
