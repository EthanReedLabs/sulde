from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import venv
import runpy


ROOT = Path(__file__).resolve().parents[1]
STAGER = ROOT / "scripts" / "release" / "stage_plugin.py"


def _corpus_count() -> int:
    manifest = json.loads((ROOT / "knowledge" / "MANIFEST.json").read_text(encoding="utf-8"))
    documents = manifest.get("documents", manifest)
    return len(documents)


class StagePluginTests(unittest.TestCase):
    def test_claude_release_excludes_only_private_publishing_inputs(self) -> None:
        select = runpy.run_path(str(STAGER))["is_claude_release_path"]
        excluded = (
            "scripts/release/export_public_harness.py",
            "scripts/release/verify_public_harness_candidate.py",
            "scripts/release/public_harness_overlay/README.md",
            "scripts/release/public_harness_overlay/hooks/run-hook.sh",
            "scripts/release/public_harness_overlay/knowledge/SEDIMENTATION-STANDARD.md",
            "tests/test_export_public_harness.py",
        )
        retained = (
            "scripts/release/stage_plugin.py",
            "scripts/release/install_codex_plugin.py",
            "scripts/release/candidate_codex_plugin.py",
            "scripts/kb/intent-guardian.py",
            "hooks/pre_tool_use.py",
            "tools/kb-mcp/server.py",
            "scripts/release/export_public_harness_extra.py",
            "scripts/release/public_harness_overlay_extra/README.md",
        )
        for relative in excluded:
            with self.subTest(excluded=relative):
                self.assertFalse(select(Path(relative)))
        for relative in retained:
            with self.subTest(retained=relative):
                self.assertTrue(select(Path(relative)))

    def assert_distributed_task_inputs(self, runtime: Path) -> None:
        license_paths = (
            "LICENSE", "NOTICE", "LICENSE-v0.1.0-MIT-archive",
            "LICENSE-BSL-1.1-archive", "CONTRIBUTING.md", "docs/LICENSING.md",
        )
        paths = (
            "spec/task-authoring.md", "spec/task-contract.md",
            "template/_project/docs-hub/00_shared-rules/task-brief.md.template",
            "docs/kb-retrieval-contract.md",
        )
        for relative in (*license_paths, *paths):
            with self.subTest(distributed_input=relative):
                self.assertEqual((runtime / relative).read_bytes(), (ROOT / relative).read_bytes())
        plugin = runtime.parent if runtime.name == "runtime" else runtime
        manifest_dir = ".codex-plugin" if runtime.name == "runtime" else ".claude-plugin"
        descriptor = plugin / manifest_dir / "plugin.json"
        self.assertEqual(
            json.loads(descriptor.read_text(encoding="utf-8"))["license"],
            "PolyForm-Noncommercial-1.0.0",
        )
        for relative in license_paths:
            with self.subTest(plugin_license_input=relative):
                self.assertEqual((plugin / relative).read_bytes(), (ROOT / relative).read_bytes())
        spec = runtime / "spec/task-authoring.md"
        for relative in re.findall(r"\]\(([^)]+)\)", spec.read_text(encoding="utf-8")):
            target = (spec.parent / relative).resolve()
            self.assertTrue(target.is_relative_to(runtime.resolve()))
            self.assertTrue(target.is_file())

    def test_required_runtime_source_inventory_is_exact_and_unique(self) -> None:
        module = runpy.run_path(str(STAGER))
        required = module["REQUIRED_RUNTIME_SOURCE_FILES"]
        self.assertEqual(
            required,
            (
                Path("scripts/kb/approval_timeout_policy.py"),
                Path("scripts/kb/codex_cli_contract.py"),
                Path("scripts/kb/decision_kernel.py"),
                Path("scripts/kb/local_file_operations.py"),
                Path("scripts/kb/native_decision_journal.py"),
                Path("scripts/kb/intent_guardian_parts/figma_read_recovery.py"),
                Path("scripts/kb/intent_guardian_parts/intervention_control.py"),
                Path("scripts/kb/intent_guardian_parts/native_grant.py"),
                Path("scripts/kb/intent_guardian_parts/orchestrator_resources.py"),
                Path("scripts/kb/intent_guardian_parts/pre_execution_control.py"),
                Path("scripts/kb/intent_guardian_parts/pre_execution_proof.py"),
                Path("scripts/kb/intent_guardian_parts/session_workspace.py"),
                Path("scripts/kb/operational_readiness.py"),
                Path("scripts/kb/production_recovery.py"),
                Path("scripts/kb/production_recovery_readiness.py"),
                Path("scripts/kb/production-recovery.py"),
                Path("scripts/kb/production_recovery_control.py"),
                Path("scripts/kb/production_recovery_targets.py"),
                Path("scripts/kb/sulde_paths.py"),
                Path("scripts/kb/sulde-statusline.py"),
                Path("scripts/kb/sulde_status_snapshot.py"),
                Path("scripts/kb/task_ownership.py"),
            ),
        )
        self.assertEqual(len(required), len(set(required)))

    def test_codex_cli_contract_is_only_production_version_literal(self) -> None:
        pattern = re.compile(r"codex-cli [0-9]+\.[0-9]+\.[0-9]+")
        production_roots = ("scripts", "hooks", "integrations", "tools", "commands")
        text_suffixes = frozenset(
            {
                ".bash",
                ".cjs",
                ".js",
                ".json",
                ".jsx",
                ".mjs",
                ".ps1",
                ".py",
                ".sh",
                ".toml",
                ".ts",
                ".tsx",
                ".yaml",
                ".yml",
                ".zsh",
            }
        )
        non_production_parts = frozenset(
            {
                "docs",
                "fixtures",
                "guardian-program",
                "guardian-r2-program",
                "knowledge",
                "test",
                "tests",
            }
        )

        def locations(
            injected: tuple[tuple[str, str], ...] = (),
        ) -> list[tuple[str, str]]:
            sources: list[tuple[str, str]] = []
            for root_name in production_roots:
                source_root = ROOT / root_name
                if not source_root.is_dir():
                    continue
                for path in source_root.rglob("*"):
                    relative = path.relative_to(ROOT)
                    if (
                        not path.is_file()
                        or path.is_symlink()
                        or path.suffix.casefold() not in text_suffixes
                        or non_production_parts.intersection(
                            part.casefold() for part in relative.parts
                        )
                    ):
                        continue
                    sources.append(
                        (
                            relative.as_posix(),
                            path.read_text(encoding="utf-8"),
                        )
                    )
            sources.extend(injected)
            found: list[tuple[str, str]] = []
            for relative, source in sorted(sources):
                for match in pattern.findall(source):
                    found.append((relative, match))
            return found

        self.assertEqual(
            locations(),
            [("scripts/kb/codex_cli_contract.py", "codex-cli 0.154.0")],
        )
        self.assertEqual(
            locations(
                (
                    (
                        "integrations/codex/copied-contract.toml",
                        'VERSION = "codex-cli 0.153.4"\n',
                    ),
                )
            ),
            [
                ("integrations/codex/copied-contract.toml", "codex-cli 0.153.4"),
                ("scripts/kb/codex_cli_contract.py", "codex-cli 0.154.0"),
            ],
        )

    def test_history_module_is_a_tracked_runtime_input(self) -> None:
        module = runpy.run_path(str(STAGER))
        relative = Path("tools/kb-index/knowledge_history.py")
        self.assertNotIn(relative, module["REQUIRED_RUNTIME_SOURCE_FILES"])
        tracked = subprocess.run(
            ["git", "ls-files", "--error-unmatch", relative.as_posix()],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        self.assertEqual(tracked.returncode, 0, tracked.stderr)

    def test_generation_digest_rejects_git_and_python_bytecode(self) -> None:
        module = runpy.run_path(str(STAGER))
        digest = module["tree_digest"]
        with tempfile.TemporaryDirectory() as directory_name:
            runtime = Path(directory_name) / "runtime"
            runtime.mkdir()
            (runtime / "main.py").write_text("print('ok')\n", encoding="utf-8")
            baseline = digest(runtime)
            self.assertEqual(len(baseline), 64)

            git = runtime / ".git"
            git.mkdir()
            with self.assertRaisesRegex(ValueError, "immutable artifact tree"):
                digest(runtime)
            git.rmdir()

            cache = runtime / "__pycache__"
            cache.mkdir()
            (cache / "main.cpython-313.pyc").write_bytes(b"executable-bytecode")
            with self.assertRaisesRegex(ValueError, "Python bytecode"):
                digest(runtime)

    def assert_no_developer_paths(self, root: Path) -> None:
        forbidden = str(ROOT.resolve())
        offenders: list[str] = []
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            try:
                source = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                continue
            if forbidden in source:
                offenders.append(path.relative_to(root).as_posix())
        self.assertEqual(offenders, [])

    def assert_hook_output(
        self,
        completed: subprocess.CompletedProcess[str],
    ) -> None:
        self.assertEqual(completed.returncode, 0, completed.stderr)
        lines = completed.stdout.strip().splitlines()
        self.assertEqual(len(lines), 1, completed.stdout)
        output = json.loads(lines[0])
        self.assertIn("hookSpecificOutput", output)

    def bash(self) -> str:
        if os.name != "nt":
            bash = shutil.which("bash")
            self.assertIsNotNone(bash, "bash not found")
            return str(bash)

        git = shutil.which("git")
        candidates: list[Path] = []
        if git:
            git_root = Path(git).resolve().parent.parent
            candidates.extend((git_root / "bin" / "bash.exe", git_root / "usr" / "bin" / "bash.exe"))
        for variable in ("ProgramFiles", "ProgramFiles(x86)"):
            root = os.environ.get(variable)
            if root:
                candidates.extend(
                    (Path(root) / "Git" / "bin" / "bash.exe", Path(root) / "Git" / "usr" / "bin" / "bash.exe")
                )
        bash = next((candidate for candidate in candidates if candidate.is_file()), None)
        self.assertIsNotNone(bash, "Git Bash not found")
        return str(bash)

    def assert_shell_syntax(self, paths: tuple[Path, ...]) -> None:
        bash = self.bash()
        for path in paths:
            with tempfile.TemporaryDirectory(prefix="sulde-stage-bash-") as temp_dir:
                target = path
                if path.suffix == ".template":
                    target = Path(temp_dir) / path.name.removesuffix(".template")
                    rendered = path.read_text(encoding="utf-8")
                    rendered = rendered.replace("<<FRONTENDS>>", '"android" "ios"')
                    rendered = rendered.replace("<<DOCS_HUB>>", "docs-hub")
                    target.write_text(rendered, encoding="utf-8")
                completed = subprocess.run(
                    [bash, "-n", target.as_posix()],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    check=False,
                )
            self.assertEqual(completed.returncode, 0, f"{path}: {completed.stderr}")

    def assert_python_syntax(self, paths: tuple[Path, ...]) -> None:
        for path in paths:
            source = path.read_bytes()
            self.assertTrue(source.startswith(b"#!/usr/bin/env python3\n"), str(path))
            compile(source, str(path), "exec")

    def stage(
        self,
        target: str,
        output: Path,
        *,
        platform: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        command = [
            sys.executable,
            str(STAGER),
            "--target",
            target,
            "--output",
            str(output),
        ]
        if platform is not None:
            command.extend(("--platform", platform))
        return subprocess.run(
            command,
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            check=False,
        )

    def test_stages_self_contained_claude_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            claude = Path(temp_dir) / "claude"
            completed = self.stage("claude", claude)

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertTrue((claude / ".claude-plugin" / "plugin.json").is_file())
            self.assert_distributed_task_inputs(claude)
            self.assertTrue((claude / "knowledge" / "MANIFEST.json").is_file())
            self.assertTrue((claude / "knowledge" / "HISTORY.json").is_file())
            self.assertTrue(
                (claude / "tools" / "kb-index" / "knowledge_history.py").is_file()
            )
            self.assertTrue((claude / "scripts" / "kb" / "install-agents.ps1").is_file())
            self.assertTrue((claude / "scripts" / "kb" / "windows-task.py").is_file())
            self.assertTrue((claude / "scripts" / "kb" / "llm-runtime.py").is_file())
            self.assertTrue((claude / "scripts" / "kb" / "model-dispatch.py").is_file())
            self.assertTrue((claude / "scripts" / "kb" / "agent-runtime.py").is_file())
            self.assertTrue((claude / "scripts" / "kb" / "execution_backend.py").is_file())
            self.assertTrue((claude / "scripts" / "kb" / "event_projection_cache.py").is_file())
            self.assertTrue((claude / "scripts" / "kb" / "sulde-statusline.py").is_file())
            self.assertTrue((claude / "scripts" / "kb" / "sulde_status_snapshot.py").is_file())
            self.assertTrue((claude / "scripts" / "kb" / "observation_privacy.py").is_file())
            self.assertTrue((claude / "scripts" / "kb" / "managed_process_wrapper.py").is_file())
            self.assertTrue((claude / "scripts" / "kb" / "terminal_invariants.py").is_file())
            self.assertTrue((claude / "scripts" / "kb" / "correction_intervention.py").is_file())
            self.assertTrue((claude / "scripts" / "kb" / "approval_invariant.py").is_file())
            self.assertTrue((claude / "scripts" / "kb" / "intent-guardian.py").is_file())
            self.assertTrue((claude / "scripts" / "kb" / "host_capabilities.py").is_file())
            self.assertTrue((claude / "scripts" / "kb" / "session_continuity.py").is_file())
            self.assertTrue((claude / "scripts" / "kb" / "intervention.py").is_file())
            self.assertTrue((claude / "scripts" / "kb" / "sedimentation_schema.py").is_file())
            self.assertTrue((claude / "scripts" / "kb" / "lint-sedimentation.py").is_file())
            self.assertTrue((claude / "scripts" / "kb" / "sedimentation-eval.py").is_file())
            self.assertTrue((claude / "skills" / "intent-guardian" / "SKILL.md").is_file())
            self.assertTrue((claude / "skills" / "dispatch-task" / "SKILL.md").is_file())
            self.assertTrue((claude / "templates" / "self-repair-brief.md").is_file())
            self.assertTrue((claude / "templates" / "knowledge" / "schema.json").is_file())
            self.assertTrue((claude / "templates" / "knowledge" / "problem-card.md").is_file())
            self.assertTrue((claude / "tools" / "kb-index" / "search_contract.py").is_file())
            self.assertTrue((claude / "docs" / "dual-runtime-contract.md").is_file())
            self.assertTrue((claude / "docs" / "intent-guardian.md").is_file())
            claude_hooks = json.loads((claude / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]
            self.assertIn("PostToolUseFailure", claude_hooks)
            self.assertIn("Stop", claude_hooks)
            self.assertTrue((claude / "hooks" / "stop.py").is_file())
            self.assertTrue((claude / "hooks" / "lib" / "recall_log.py").is_file())
            self.assertFalse((claude / ".git").exists())
            self.assertFalse((claude / "tests").exists())
            for relative in (
                "scripts/release/export_public_harness.py",
                "scripts/release/verify_public_harness_candidate.py",
                "scripts/release/public_harness_overlay",
            ):
                with self.subTest(private_publishing_input=relative):
                    self.assertFalse((claude / relative).exists())
            for name in ("stage_plugin.py", "install_codex_plugin.py", "candidate_codex_plugin.py"):
                self.assertTrue((claude / "scripts/release" / name).is_file())
            self.assert_no_developer_paths(claude)
            self.assertIn(f"{_corpus_count()} corpus documents", completed.stdout)
            self.assert_shell_syntax((
                claude / "scripts" / "kb" / "bootstrap.sh",
                claude / "scripts" / "kb" / "install-agents.sh",
                claude / "template" / "_project" / "scripts" / "coordinator-baseline.sh.template",
                claude / "template" / "_project" / "scripts" / "health-check.sh.template",
                *tuple(
                    claude / "template" / stack / "scripts" / "pre-commit-installer.sh"
                    for stack in ("android", "ios", "flutter", "harmony")
                ),
            ))
            self.assert_python_syntax((
                claude / "scripts" / "kb" / "kb-index",
                claude / "scripts" / "kb" / "kb-mcp",
            ))

    def test_stages_self_contained_codex_windows_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            codex = Path(temp_dir) / "codex"
            completed = self.stage("codex", codex, platform="windows")

            self.assertEqual(completed.returncode, 0, completed.stderr)
            plugin = codex / "plugins" / "sulde"
            self.assert_distributed_task_inputs(plugin / "runtime")
            generation = json.loads(
                (plugin / ".codex-plugin" / "generation.json").read_text(
                    encoding="utf-8"
                )
            )
            stage_module = runpy.run_path(str(STAGER))
            runtime_digest = stage_module["tree_digest"](plugin / "runtime")
            self.assertFalse(
                any(path.name == "__pycache__" for path in plugin.rglob("*"))
            )
            self.assertFalse(any(path.suffix == ".pyc" for path in plugin.rglob("*")))
            self.assertEqual(generation["schema"], "sulde-delivery-generation-v1")
            self.assertEqual(generation["platform"], "windows")
            self.assertEqual(generation["runtime_tree_sha256"], runtime_digest)
            self.assertEqual(
                generation["generation"],
                f"{generation['plugin_version']}:{runtime_digest}",
            )
            self.assertTrue(
                (codex / ".agents" / "plugins" / "marketplace.json").is_file()
            )
            self.assertTrue(
                (plugin / "runtime" / "knowledge" / "MANIFEST.json").is_file()
            )
            self.assertTrue(
                (plugin / "runtime" / "knowledge" / "HISTORY.json").is_file()
            )
            self.assertTrue(
                (
                    plugin
                    / "runtime"
                    / "tools"
                    / "kb-index"
                    / "knowledge_history.py"
                ).is_file()
            )
            aging_home = Path(temp_dir) / "aging-home"
            aging = subprocess.run(
                [
                    sys.executable,
                    str(plugin / "runtime" / "scripts" / "kb" / "kb-aging.py"),
                    "--repo",
                    str(plugin / "runtime"),
                    "--dry-run",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env={**os.environ, "SULDE_KB_HOME": str(aging_home)},
                timeout=60,
                check=False,
            )
            self.assertEqual(aging.returncode, 0, aging.stderr)
            self.assertIn("KB AGING RESULT: PASS", aging.stdout)
            self.assertIn(f"documents: {_corpus_count()}", aging.stdout)
            self.assertFalse((aging_home / "governance").exists())
            self.assertTrue(
                (plugin / "runtime" / "hooks" / "user_prompt_submit.py").is_file()
            )
            self.assertTrue(
                (plugin / "runtime" / "hooks" / "lib" / "recall_log.py").is_file()
            )
            self.assertTrue(
                (plugin / "runtime" / "scripts" / "kb" / "install-agents.ps1").is_file()
            )
            self.assertTrue(
                (plugin / "runtime" / "scripts" / "kb" / "windows-task.py").is_file()
            )
            self.assertTrue(
                (plugin / "runtime" / "scripts" / "kb" / "llm-runtime.py").is_file()
            )
            self.assertTrue(
                (plugin / "runtime" / "scripts" / "kb" / "model-dispatch.py").is_file()
            )
            self.assertTrue(
                (plugin / "runtime" / "scripts" / "kb" / "agent-runtime.py").is_file()
            )
            contract = (
                plugin
                / "runtime"
                / "scripts"
                / "kb"
                / "codex_cli_contract.py"
            )
            self.assertTrue(contract.is_file())
            imported = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    "-c",
                    (
                        "import codex_cli_contract as contract; "
                        "print(contract.AUDITED_CODEX_VERSION)"
                    ),
                ],
                cwd=contract.parent,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                check=False,
            )
            self.assertEqual(imported.returncode, 0, imported.stderr)
            self.assertEqual(imported.stdout.strip(), "codex-cli 0.154.0")
            mcp_manifest = json.loads(
                (plugin / ".mcp.json").read_text(encoding="utf-8")
            )["mcpServers"]["sulde_kb"]
            self.assertEqual(mcp_manifest["command"], "powershell.exe")
            self.assertEqual(mcp_manifest["cwd"], ".")
            self.assertEqual(
                mcp_manifest["args"][-1],
                "./scripts/run-mcp.ps1",
            )
            self.assertTrue((plugin / "scripts" / "run-mcp.ps1").is_file())
            self.assertTrue(
                (
                    plugin
                    / "runtime"
                    / "scripts"
                    / "kb"
                    / "execution_backend.py"
                ).is_file()
            )
            self.assertTrue(
                (
                    plugin
                    / "runtime"
                    / "scripts"
                    / "kb"
                    / "managed_process_wrapper.py"
                ).is_file()
            )
            self.assertTrue(
                (
                    plugin
                    / "runtime"
                    / "scripts"
                    / "kb"
                    / "terminal_invariants.py"
                ).is_file()
            )
            self.assertTrue(
                (
                    plugin
                    / "runtime"
                    / "scripts"
                    / "kb"
                    / "correction_intervention.py"
                ).is_file()
            )
            self.assertTrue(
                (
                    plugin
                    / "runtime"
                    / "scripts"
                    / "kb"
                    / "approval_invariant.py"
                ).is_file()
            )
            self.assertTrue(
                (plugin / "runtime" / "scripts" / "kb" / "event-observer.py").is_file()
            )
            self.assertTrue(
                (plugin / "runtime" / "scripts" / "kb" / "event_contract.py").is_file()
            )
            self.assertTrue(
                (plugin / "runtime" / "scripts" / "kb" / "event_observer.py").is_file()
            )
            self.assertTrue(
                (
                    plugin
                    / "runtime"
                    / "scripts"
                    / "kb"
                    / "event_projection_cache.py"
                ).is_file()
            )
            self.assertTrue(
                (
                    plugin
                    / "runtime"
                    / "scripts"
                    / "kb"
                    / "observation_privacy.py"
                ).is_file()
            )
            self.assertTrue(
                (plugin / "runtime" / "scripts" / "kb" / "intent-guardian.py").is_file()
            )
            self.assertTrue(
                (plugin / "runtime" / "scripts" / "kb" / "session_continuity.py").is_file()
            )
            self.assertTrue(
                (plugin / "runtime" / "scripts" / "kb" / "intervention.py").is_file()
            )
            self.assertTrue(
                (plugin / "runtime" / "scripts" / "kb" / "human_control.py").is_file()
            )
            self.assertTrue(
                (plugin / "runtime" / "scripts" / "kb" / "sedimentation_schema.py").is_file()
            )
            self.assertTrue(
                (plugin / "runtime" / "scripts" / "kb" / "lint-sedimentation.py").is_file()
            )
            self.assertTrue(
                (plugin / "runtime" / "scripts" / "kb" / "sedimentation-eval.py").is_file()
            )
            self.assertTrue(
                (plugin / "runtime" / "scripts" / "kb" / "launcher_contract.py").is_file()
            )
            self.assertTrue(
                (plugin / "runtime" / "docs" / "intent-guardian.md").is_file()
            )
            self.assertTrue(
                (plugin / "runtime" / "docs" / "event-observability.md").is_file()
            )
            self.assertTrue(
                (plugin / "runtime" / "templates" / "self-repair-brief.md").is_file()
            )
            self.assertTrue(
                (plugin / "runtime" / "templates" / "SELF.md").is_file()
            )
            self.assertTrue(
                (plugin / "runtime" / "templates" / "knowledge" / "schema.json").is_file()
            )
            self.assertTrue(
                (
                    plugin
                    / "runtime"
                    / "templates"
                    / "events"
                    / "sulde-observation-event-v1.schema.json"
                ).is_file()
            )
            self.assertTrue(
                (plugin / "runtime" / "templates" / "knowledge" / "problem-card.md").is_file()
            )
            self.assertTrue(
                (plugin / "runtime" / "tools" / "kb-index" / "search_contract.py").is_file()
            )
            self.assertTrue(
                (plugin / "runtime" / "tools" / "kb-mcp" / "server.py").is_file()
            )
            self.assertTrue(
                (
                    plugin
                    / "runtime"
                    / "scripts"
                    / "kb"
                    / "host_capabilities.py"
                ).is_file()
            )
            self.assertTrue(
                (plugin / "runtime" / "skills" / "sediment" / "SKILL.md").is_file()
            )
            self.assertTrue(
                (plugin / "runtime" / "templates" / "launchagents" / "com.sulde.heartbeat.plist").is_file()
            )
            descriptor = json.loads(
                (plugin / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
            )
            self.assertEqual(descriptor["skills"], "./skills/")
            self.assertEqual(descriptor["mcpServers"], "./.mcp.json")
            mcp_manifest = json.loads(
                (plugin / ".mcp.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                mcp_manifest["mcpServers"]["sulde_kb"]["command"],
                "powershell.exe",
            )
            self.assertTrue((plugin / "scripts" / "run-mcp.sh").is_file())
            self.assertTrue((plugin / "scripts" / "run-mcp.ps1").is_file())
            self.assertNotIn("hooks", descriptor)
            for skill in ("dispatch-task", "intent-guardian", "kb-search", "memory-distill", "sediment"):
                self.assertTrue((plugin / "skills" / skill / "SKILL.md").is_file())
            self.assertNotIn(
                "/Users/",
                (plugin / "scripts" / "session-start.py").read_text(
                    encoding="utf-8"
                ),
            )
            hook_config = plugin / "hooks" / "hooks.json"
            self.assertIn(
                "run-hook.ps1",
                hook_config.read_text(encoding="utf-8"),
            )
            hooks = json.loads(hook_config.read_text(encoding="utf-8"))["hooks"]
            self.assertIn("PreToolUse", hooks)
            self.assertIn("PermissionRequest", hooks)
            self.assertIn("PostToolUse", hooks)
            self.assertIn("Stop", hooks)
            self.assertIn("SessionStart", hooks)
            self.assertIn("UserPromptSubmit", hooks)
            permission_command = hooks["PermissionRequest"][0]["hooks"][0]["command"]
            self.assertIn("permission-request", permission_command)
            self.assertTrue((plugin / "scripts" / "stop.py").is_file())
            self.assertFalse((plugin / "hooks.json").exists())
            self.assertFalse((plugin / "hooks.posix.json").exists())
            self.assertFalse((plugin / "hooks.windows.json").exists())
            self.assertIn(f"{_corpus_count()} corpus documents", completed.stdout)
            self.assert_shell_syntax((
                plugin / "runtime" / "scripts" / "kb" / "bootstrap.sh",
                plugin / "runtime" / "scripts" / "kb" / "install-agents.sh",
                plugin / "scripts" / "run-hook.sh",
            ))
            self.assert_python_syntax((
                plugin / "runtime" / "scripts" / "kb" / "kb-index",
                plugin / "runtime" / "scripts" / "kb" / "kb-mcp",
            ))

            for forbidden in ("mem-sync.key", "memory.db", "kb.db"):
                self.assertFalse(any(path.name == forbidden for path in codex.rglob("*")))
            self.assert_no_developer_paths(codex)

            kb_home = Path(temp_dir) / "状态-home"
            kb_home.mkdir()
            (kb_home / "distill-state.json").write_text(
                json.dumps({"ts": "2026-08-11T00:00:00+00:00"}),
                encoding="utf-8",
            )
            env = os.environ.copy()
            env["SULDE_KB_HOME"] = str(kb_home)
            env["PYTHONIOENCODING"] = "cp936:strict"
            for script, payload in (
                (plugin / "scripts" / "session-start.py", "{}"),
                (
                    plugin / "scripts" / "user-prompt-submit.py",
                    '{"prompt":"artifact smoke"}',
                ),
            ):
                adapter = subprocess.run(
                    [sys.executable, str(script)],
                    input=payload,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    env=env,
                    timeout=20,
                    check=False,
                )
                self.assertEqual(adapter.returncode, 0, adapter.stderr)
                output = json.loads(adapter.stdout.strip().splitlines()[-1])
                self.assertIn("hookSpecificOutput", output)
                if script.name == "session-start.py":
                    context = output["hookSpecificOutput"]["additionalContext"]
                    status_line = context.splitlines()[0]
                    self.assertIn("状态快照待刷新", status_line)
                    self.assertNotIn("状态脚本无输出", status_line)
                    self.assertNotIn("\ufffd", status_line)

    def test_staged_codex_mcp_completes_initialize_handshake(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            codex = temp / "codex"
            completed = self.stage(
                "codex",
                codex,
                platform="windows" if os.name == "nt" else "posix",
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)

            home = temp / "kb-home"
            home.mkdir()
            venv.EnvBuilder(with_pip=False).create(home / "venv")
            request = json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "stage-test", "version": "1"},
                    },
                },
                separators=(",", ":"),
            )
            environment = os.environ.copy()
            environment.update(
                {
                    "SULDE_HOME": str(home),
                    "SULDE_KB_HOME": str(home),
                    "PYTHONDONTWRITEBYTECODE": "1",
                }
            )
            plugin = codex / "plugins" / "sulde"
            stable_launcher = home / "bin" / "sulde-kb-mcp"
            stable_launcher.parent.mkdir()
            packaged_server = plugin / "runtime" / "tools" / "kb-mcp" / "server.py"
            stable_launcher.write_text(
                "#!/usr/bin/env python3\n"
                "import os, sys\n"
                f"os.execv(sys.executable, [sys.executable, {str(packaged_server)!r}, *sys.argv[1:]])\n",
                encoding="utf-8",
            )
            stable_launcher.chmod(0o755)
            route = json.loads(
                (plugin / ".mcp.json").read_text(encoding="utf-8")
            )["mcpServers"]["sulde_kb"]
            self.assertEqual(route["cwd"], ".")
            mcp = subprocess.run(
                [route["command"], *route.get("args", [])],
                input=request + "\n",
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=environment,
                cwd=plugin,
                timeout=20,
                check=False,
            )
            self.assertEqual(mcp.returncode, 0, mcp.stderr)
            lines = [line for line in mcp.stdout.splitlines() if line.strip()]
            self.assertEqual(len(lines), 1, mcp.stdout)
            response = json.loads(lines[0])
            self.assertEqual(response["result"]["serverInfo"]["name"], "sulde-kb")

    def test_raw_local_marketplace_cache_resolves_repository_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            codex_home = root / ".codex"
            cached = codex_home / "plugins/cache/sulde-local/sulde/0.1.3"
            shutil.copytree(ROOT / "integrations/codex/plugins/sulde", cached)
            self.assertFalse((cached / "runtime").exists())
            codex_home.mkdir(parents=True, exist_ok=True)
            (codex_home / "config.toml").write_text(
                '[marketplaces.sulde-local]\n'
                'source_type = "local"\n'
                f'source = {json.dumps(str(ROOT / "integrations/codex"))}\n',
                encoding="utf-8",
            )
            kb_home = root / "kb-home"
            kb_home.mkdir()
            env = os.environ.copy()
            env.update({"CODEX_HOME": str(codex_home), "SULDE_KB_HOME": str(kb_home)})
            completed = subprocess.run(
                [sys.executable, str(cached / "scripts/session-start.py")],
                input=json.dumps({"cwd": str(ROOT)}),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                timeout=20,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertNotIn("状态脚本无输出", completed.stderr)
            output = json.loads(completed.stdout.strip().splitlines()[-1])
            self.assertIn("sulde", output["hookSpecificOutput"]["additionalContext"])

    @unittest.skipUnless(os.name == "nt", "requires native Windows PowerShell")
    def test_windows_launchers_fall_back_from_broken_python3(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            codex = temp / "codex"
            completed = self.stage("codex", codex, platform="windows")
            self.assertEqual(completed.returncode, 0, completed.stderr)

            shims = temp / "shims"
            shims.mkdir()
            (shims / "python3.cmd").write_text(
                "@echo off\r\nexit /b 7\r\n",
                encoding="utf-8",
            )
            (shims / "python.cmd").write_text(
                f'@echo off\r\n"{sys.executable}" %*\r\n',
                encoding="utf-8",
            )

            env = os.environ.copy()
            env["PATH"] = str(shims) + os.pathsep + env.get("PATH", "")
            env["SULDE_KB_HOME"] = str(temp / "empty-kb-home")
            env["PYTHONDONTWRITEBYTECODE"] = "1"
            launcher = codex / "plugins" / "sulde" / "scripts" / "run-hook.ps1"
            powershell = shutil.which("powershell.exe")
            self.assertIsNotNone(powershell, "powershell.exe not found")

            for hook, payload in (
                ("session-start", "{}"),
                ("user-prompt-submit", '{"prompt":"launcher smoke"}'),
            ):
                invoked = subprocess.run(
                    [
                        str(powershell),
                        "-NoProfile",
                        "-ExecutionPolicy",
                        "Bypass",
                        "-File",
                        str(launcher),
                        hook,
                    ],
                    input=payload,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    env=env,
                    timeout=20,
                    check=False,
                )
                self.assert_hook_output(invoked)

    @unittest.skipIf(os.name == "nt", "requires a POSIX host")
    def test_posix_artifact_launchers_emit_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            codex = temp / "codex"
            completed = self.stage("codex", codex, platform="posix")
            self.assertEqual(completed.returncode, 0, completed.stderr)

            env = os.environ.copy()
            env["SULDE_KB_HOME"] = str(temp / "empty-kb-home")
            env.pop("PYTHONDONTWRITEBYTECODE", None)
            launcher = codex / "plugins" / "sulde" / "scripts" / "run-hook.sh"
            for hook, payload in (
                ("session-start", "{}"),
                ("user-prompt-submit", '{"prompt":"launcher smoke"}'),
            ):
                for _ in range(2):
                    invoked = subprocess.run(
                        [self.bash(), launcher.as_posix(), hook],
                        input=payload,
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        env=env,
                        timeout=20,
                        check=False,
                    )
                    self.assert_hook_output(invoked)
            runtime = codex / "plugins" / "sulde" / "runtime"
            self.assert_distributed_task_inputs(runtime)
            self.assertEqual(list(runtime.rglob("*.pyc")), [])
            self.assertEqual(list(runtime.rglob("__pycache__")), [])

    @unittest.skipIf(os.name == "nt", "requires a POSIX host")
    def test_posix_staged_guardian_blocks_unapproved_mcp_write(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            codex = temp / "codex"
            completed = self.stage("codex", codex, platform="posix")
            self.assertEqual(completed.returncode, 0, completed.stderr)
            plugin = codex / "plugins" / "sulde"
            runtime = plugin / "runtime"
            project = temp / "project"
            project.mkdir()
            (project / ".git").mkdir()
            contract = temp / "intent.json"
            created = subprocess.run(
                [
                    sys.executable,
                    str(runtime / "scripts" / "kb" / "intent-guardian.py"),
                    "create",
                    "--intent-id",
                    "staged-smoke",
                    "--objective",
                    "Only inspect the document",
                    "--accept",
                    "No unapproved external write",
                    "--workspace",
                    str(project),
                    "--output",
                    str(contract),
                    "--mode",
                    "enforce",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            self.assertEqual(created.returncode, 0, created.stderr)
            environment = os.environ.copy()
            environment.pop("SULDE_GUARDIAN_STREAM_OWNER", None)
            modules = temp / "modules"
            modules.mkdir()
            (modules / "yaml.py").write_text(
                "def safe_load(stream):\n    return {}\n",
                encoding="utf-8",
            )
            environment.update(
                {
                    "SULDE_INTENT_CONTRACT": str(contract),
                    "SULDE_KB_HOME": str(temp / "kb-home"),
                    "SULDE_TEST_MODE": "1",
                    "PYTHONPATH": str(modules),
                }
            )
            environment.pop("PYTHONDONTWRITEBYTECODE", None)
            launcher = plugin / "scripts" / "run-hook.sh"
            for hook_name, hook_payload in (
                (
                    "session-start",
                    {"sessionId": "thread", "cwd": str(project)},
                ),
                (
                    "user-prompt-submit",
                    {
                        "sessionId": "thread",
                        "cwd": str(project),
                        "prompt": "inspect only",
                    },
                ),
            ):
                for _ in range(2):
                    observed = subprocess.run(
                        [self.bash(), str(launcher), hook_name],
                        input=json.dumps(hook_payload),
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        env=environment,
                        timeout=20,
                        check=False,
                    )
                    self.assertEqual(observed.returncode, 0, observed.stderr)
            for _ in range(2):
                invoked = subprocess.run(
                    [self.bash(), str(launcher), "pre-tool-use"],
                    input=json.dumps(
                        {
                            "sessionId": "thread",
                            "cwd": str(project),
                            "toolName": "mcp__docs__update_document",
                            "toolInput": {"uri": "doc://resume", "content": "new"},
                        }
                    ),
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    env=environment,
                    timeout=20,
                    check=False,
                )
                self.assertEqual(invoked.returncode, 0, invoked.stderr)
                self.assertTrue(
                    invoked.stdout.strip(),
                    f"staged hook returned no decision; stderr={invoked.stderr}",
                )
                output = json.loads(invoked.stdout.strip())
                decision = output["hookSpecificOutput"]
                self.assertEqual(decision["permissionDecision"], "deny")
                self.assertIn("blocked this action", decision["permissionDecisionReason"])
                self.assertNotIn("event_fingerprint=", decision["permissionDecisionReason"])
                self.assertNotIn("批准事件", decision["permissionDecisionReason"])
            self.assertEqual(list(runtime.rglob("*.pyc")), [])
            self.assertEqual(list(runtime.rglob("__pycache__")), [])

    def test_refuses_to_replace_non_empty_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "occupied"
            output.mkdir()
            sentinel = output / "keep-me.txt"
            sentinel.write_text("preserve", encoding="utf-8")

            completed = self.stage("claude", output)

            self.assertNotEqual(completed.returncode, 0)
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "preserve")
            self.assertEqual([sentinel], list(output.iterdir()))

    def test_source_hook_configuration_defaults_to_posix(self) -> None:
        plugin = ROOT / "integrations" / "codex" / "plugins" / "sulde"
        self.assertEqual(
            (plugin / "hooks.posix.json").read_bytes(),
            (plugin / "hooks.json").read_bytes(),
        )

    def test_posix_entrypoints_are_tracked_executable(self) -> None:
        for tracked_path in (
            "integrations/codex/plugins/sulde/scripts/run-hook.sh",
            "scripts/kb/agent-runtime.py",
            "scripts/kb/kb-index",
            "scripts/kb/kb-mcp",
            "scripts/kb/llm-runtime.py",
        ):
            with self.subTest(path=tracked_path):
                completed = subprocess.run(
                    ["git", "ls-files", "-s", "--", tracked_path],
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    check=True,
                )
                self.assertTrue(
                    completed.stdout.startswith("100755 "), completed.stdout
                )

    @unittest.skipIf(os.name == "nt", "POSIX executable bits are not authoritative")
    def test_posix_artifact_retains_executable_scripts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            claude = Path(temp_dir) / "claude"
            codex = Path(temp_dir) / "codex"
            claude_completed = self.stage("claude", claude)
            codex_completed = self.stage("codex", codex, platform="posix")

            self.assertEqual(claude_completed.returncode, 0, claude_completed.stderr)
            self.assertEqual(codex_completed.returncode, 0, codex_completed.stderr)
            plugin = codex / "plugins" / "sulde"
            targets = (
                claude / "scripts" / "kb" / "bootstrap.sh",
                claude / "scripts" / "kb" / "agent-runtime.py",
                claude / "scripts" / "kb" / "event-observer.py",
                claude / "scripts" / "kb" / "kb-index",
                claude / "scripts" / "kb" / "kb-mcp",
                claude / "scripts" / "kb" / "llm-runtime.py",
                claude / "template" / "_project" / "scripts" / "coordinator-baseline.sh.template",
                claude / "template" / "_project" / "scripts" / "health-check.sh.template",
                *tuple(
                    claude / "template" / stack / "scripts" / "pre-commit-installer.sh"
                    for stack in ("android", "ios", "flutter", "harmony")
                ),
                plugin / "runtime" / "scripts" / "kb" / "bootstrap.sh",
                plugin / "runtime" / "scripts" / "kb" / "agent-runtime.py",
                plugin / "runtime" / "scripts" / "kb" / "event-observer.py",
                plugin / "runtime" / "scripts" / "kb" / "kb-index",
                plugin / "runtime" / "scripts" / "kb" / "kb-mcp",
                plugin / "runtime" / "scripts" / "kb" / "llm-runtime.py",
                plugin / "scripts" / "run-hook.sh",
            )
            for target in targets:
                self.assertNotEqual(
                    target.stat().st_mode & 0o111,
                    0,
                    str(target),
                )


if __name__ == "__main__":
    unittest.main()
