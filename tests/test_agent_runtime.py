from __future__ import annotations

import errno
import hashlib
import importlib.util
import json
import os
import select
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from unittest import mock
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "scripts" / "kb" / "agent-runtime.py"
GUARDIAN_CLI = ROOT / "scripts" / "kb" / "intent-guardian.py"


def observe_audited_codex_help_from_parent(*, pseudo_terminal: bool) -> dict[str, object]:
    """Run one production-contract probe under a pipe or a real parent PTY."""
    probe_source = "\n".join(
        (
            "import hashlib, importlib.util, json, os, subprocess, sys",
            "spec = importlib.util.spec_from_file_location('codex_contract', sys.argv[1])",
            "contract = importlib.util.module_from_spec(spec)",
            "spec.loader.exec_module(contract)",
            "probe = contract.codex_probe_spec(os.environ)",
            "version = subprocess.run([sys.argv[2], '--version'], input=probe.stdin, capture_output=True, "
            "text=True, encoding='utf-8', errors='strict', check=False, timeout=15, "
            "env=probe.environment)",
            "arguments = (('--help',), ('exec', '--help'), ('app-server', '--help'))",
            "rows = [subprocess.run([sys.argv[2], *arguments_row], input=probe.stdin, capture_output=True, "
            "text=True, encoding='utf-8', errors='strict', check=False, timeout=15, "
            "env=probe.environment) for arguments_row in arguments]",
            "surfaces, digest = contract.canonical_codex_help_observation(tuple("
            "(row.returncode, row.stdout, row.stderr) for row in rows))",
            "print(json.dumps({'version': contract.successful_version_identity("
            "version.returncode, version.stdout), 'digest': digest, "
            "'surface_sha256': [hashlib.sha256(surface).hexdigest() for surface in surfaces], "
            "'lengths': [len(surface) for surface in surfaces]}, sort_keys=True))",
        )
    )
    command = [
        sys.executable,
        "-I",
        "-B",
        "-c",
        probe_source,
        str(ROOT / "scripts" / "kb" / "codex_cli_contract.py"),
        os.environ["SULDE_TEST_CODEX_EXECUTABLE"],
    ]
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    if not pseudo_terminal:
        completed = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=environment,
            timeout=30,
            check=False,
        )
        if completed.returncode != 0:
            raise AssertionError(completed.stderr or completed.stdout)
        return json.loads(completed.stdout)

    if sys.stdin.isatty():
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=environment,
            timeout=30,
            check=False,
        )
        if completed.returncode != 0:
            raise AssertionError(completed.stderr or completed.stdout)
        return json.loads(completed.stdout)

    master, slave = os.openpty()
    process = subprocess.Popen(
        command,
        stdin=slave,
        stdout=slave,
        stderr=slave,
        env=environment,
        close_fds=True,
    )
    os.close(slave)
    output = bytearray()
    deadline = time.monotonic() + 30
    try:
        while True:
            if time.monotonic() >= deadline:
                process.kill()
                raise AssertionError("real PTY Codex help probe timed out")
            readable, _, _ = select.select([master], [], [], 0.1)
            if readable:
                try:
                    chunk = os.read(master, 65536)
                except OSError as error:
                    if error.errno == errno.EIO:
                        break
                    raise
                if not chunk:
                    break
                output.extend(chunk)
            elif process.poll() is not None:
                break
        returncode = process.wait(timeout=1)
    finally:
        os.close(master)
        if process.poll() is None:
            process.kill()
            process.wait(timeout=1)
    rendered = output.decode("utf-8", "strict")
    if returncode != 0:
        raise AssertionError(rendered)
    return json.loads(rendered)


def load_runtime_module():
    name = "_sulde_test_agent_runtime"
    spec = importlib.util.spec_from_file_location(name, RUNTIME)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module

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

H06H_RUN_LEDGER = b'{"at": "2000-01-01T00:00:00+00:00", "command_sha256": "4a8b09a3e804e920a9802fdb85d5ce29287cf5936d0f34b21c4b6666cc2cb104", "execution_binding_sha256": "6e8f5a6f80d2c1c672f2608a2413464eae8bcb38c16af26f9014a4e7b85225d9", "parent_death_watchdog": true, "provider": "codex", "run_id": "run-111111111111111111111111", "schema": "sulde-run-event-v1", "type": "execution.requested", "workspace_id": "sha256:963e56ac345cfb66855dff09"}\n{"at": "2000-01-01T00:00:01+00:00", "parent_death_watchdog": true, "pid": 4242, "provider": "codex", "run_id": "run-111111111111111111111111", "schema": "sulde-run-event-v1", "tree_scope": "posix-process-group", "type": "execution.started"}\n{"at": "2000-01-01T00:00:02+00:00", "provider": "codex", "reason": "external_effect_outcome_unknown", "run_id": "run-111111111111111111111111", "schema": "sulde-run-event-v1", "type": "execution.interrupt_requested"}\n{"at": "2000-01-01T00:00:03+00:00", "output_present": false, "output_sha256": null, "provider": "codex", "returncode": 0, "run_id": "run-111111111111111111111111", "schema": "sulde-run-event-v1", "stop_reason": "awaiting_human", "type": "execution.result"}\n{"at": "2000-01-01T00:00:04+00:00", "error_count": 0, "errors_sha256": null, "provider": "codex", "quiescent": true, "run_id": "run-111111111111111111111111", "schema": "sulde-run-event-v1", "tree_scope": "posix-process-group", "type": "execution.disposed"}\n'
H06H_STDERR = (
    b"managed local interruption: awaiting_human\n"
    b"AgentRuntimeError: local interruption evidence is mismatched, out of order, or not quiescent\n"
)
H06H_EVENTS_SUMMARY = {'line_count': 48, 'valid_json_line_count': 48, 'sha256': '4927cd668f68e80761b75f47fa0e822baa729f1f47dc347de04aa43d4c687839', 'terminal_event': 'none', 'terminal_event_count': 0}


# Private release clone audit is retained only in the private source.

SYNTHETIC_BRIEF_SHA256 = '85465da8d519f3f5b5747b5ebdbb0f6649936ac888fe301e81fd3adeb6bc6edb'
SYNTHETIC_CURRENT_BASE_COMMIT = '2222222222222222222222222222222222222222'
SYNTHETIC_LEGACY_TASK_V1 = {'schema': 'sulde-guardian-program-task-v1', 'task_id': 'synthetic-legacy-task', 'title': 'Synthetic legacy schema boundary', 'owner': 'synthetic-worker', 'capability_tier': 'deep', 'base_commit': '1111111111111111111111111111111111111111', 'depends_on': [], 'supersedes': [], 'owned_paths': ['scripts/kb/agent-runtime.py', 'tests/test_agent_runtime.py'], 'requirements': [], 'acceptance': ['Reject a mismatched base binding', 'Preserve exact owned paths'], 'evidence_gates': {'implemented': ['task_report', 'changed_files'], 'task_verified': ['targeted_tests', 'failure_injection'], 'integrated': ['integration_tests'], 'system_verified': ['system_tests']}}


@unittest.skipIf(os.name == "nt", "POSIX executable fixtures")
class AgentRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.environment_patch = mock.patch.dict(
            os.environ,
            {
                "SULDE_TEST_MODE": "1",
                "SULDE_INTENT_CONTRACT": "",
                "SULDE_GUARDIAN_STREAM_OWNER": "",
                "SULDE_GUARDIAN_STREAM_PROVIDER": "",
            },
            clear=False,
        )
        self.environment_patch.start()
        self.addCleanup(self.environment_patch.stop)
        cli_temp = tempfile.TemporaryDirectory(prefix="sulde-bound-cli-fixture-")
        self.addCleanup(cli_temp.cleanup)
        self.codex_path = (Path(cli_temp.name) / "codex").resolve()
        self.codex_path.write_bytes(b"synthetic CLI; execution is mocked in these unit tests")
        self.codex_path.chmod(0o755)
        help_surfaces = (
            b"--config --strict-config\n",
            b"--ignore-user-config --ignore-rules --dangerously-bypass-hook-trust "
            b"--config --strict-config\n",
            b"--config --strict-config --listen\n",
        )
        self.codex_binding = {
            "production_codex_executable": str(self.codex_path),
            "production_codex_resolved_executable": str(self.codex_path),
            "codex_executable_sha256": hashlib.sha256(self.codex_path.read_bytes()).hexdigest(),
            "codex_help_observation_sha256": hashlib.sha256(b"\0".join(help_surfaces)).hexdigest(),
        }

    def synthetic_preflight(self, module, executable, profile_arguments, **kwargs):
        """Exercise production preflight with a synthetic, content-bound CLI."""
        authority = dict(self.codex_binding)
        authority.update(kwargs.pop("installed_authority", None) or {})
        return module.codex_capability_preflight(
            executable, profile_arguments, installed_authority=authority, **kwargs
        )

    def temporary_directory(self) -> tempfile.TemporaryDirectory[str]:
        return tempfile.TemporaryDirectory()

    def test_runtime_imports_exact_shared_codex_cli_authority(self) -> None:
        module = load_runtime_module()
        contract = sys.modules[module.successful_version_identity.__module__]
        self.assertEqual(module.AUDITED_CODEX_VERSION, "codex-cli 0.154.0")
        self.assertEqual(
            module.NATIVE_AUTHORITY_SPEC_VERSION,
            contract.NATIVE_AUTHORITY_SPEC_VERSION,
        )
        self.assertIs(
            module.successful_version_identity,
            contract.successful_version_identity,
        )
        self.assertIs(
            module.canonical_codex_help_observation,
            contract.canonical_codex_help_observation,
        )
        self.assertIs(
            module.codex_probe_environment,
            contract.codex_probe_environment,
        )
        self.assertIs(module.codex_probe_spec, contract.codex_probe_spec)
        self.assertEqual(
            module.successful_version_identity(
                0, module.AUDITED_CODEX_VERSION + "\n"
            ),
            module.AUDITED_CODEX_VERSION,
        )
        self.assertEqual(
            module.successful_version_identity(
                0, module.AUDITED_CODEX_VERSION + "\r\n"
            ),
            module.AUDITED_CODEX_VERSION,
        )
        self.assertIsNone(
            module.successful_version_identity(
                1, module.AUDITED_CODEX_VERSION + "\n"
            )
        )

    def test_shared_codex_help_observation_normalizes_environment_and_exact_warning(self) -> None:
        module = load_runtime_module()
        contract = sys.modules[module.successful_version_identity.__module__]
        caller_environment = {
            "PATH": "/audited/bin",
            "TERM": "xterm-256color",
            "COLORTERM": "truecolor",
            "TERM_PROGRAM": "pty-host",
            "NO_COLOR": "caller-value",
            "CLICOLOR_FORCE": "1",
            "FORCE_COLOR": "3",
        }
        original = dict(caller_environment)

        normalized = contract.codex_probe_environment(caller_environment)
        probe_spec = contract.codex_probe_spec(caller_environment)

        self.assertEqual(caller_environment, original)
        self.assertEqual(normalized["PATH"], "/audited/bin")
        self.assertEqual(normalized["TERM"], "dumb")
        self.assertEqual(normalized["NO_COLOR"], "1")
        self.assertEqual(normalized["CLICOLOR"], "0")
        self.assertEqual(normalized["CLICOLOR_FORCE"], "0")
        self.assertEqual(normalized["FORCE_COLOR"], "0")
        self.assertNotIn("COLORTERM", normalized)
        self.assertNotIn("TERM_PROGRAM", normalized)
        self.assertEqual(probe_spec.environment, normalized)
        self.assertEqual(probe_spec.stdin, "")

        stdout = (
            "--config --strict-config\n",
            "--ignore-user-config --ignore-rules --dangerously-bypass-hook-trust "
            "--config --strict-config\n",
            "--config --strict-config --listen\n",
        )
        plain = tuple((0, surface, "") for surface in stdout)
        warned = tuple(
            (0, surface, contract.CODEX_PATH_ALIAS_PERMISSION_WARNING)
            for surface in stdout
        )
        plain_bytes, plain_digest = contract.canonical_codex_help_observation(plain)
        warned_bytes, warned_digest = contract.canonical_codex_help_observation(warned)
        self.assertEqual(plain_bytes, warned_bytes)
        self.assertEqual(plain_digest, warned_digest)

        semantic = list(plain)
        semantic[1] = (0, stdout[1] + "semantic-change\n", "")
        _, semantic_digest = contract.canonical_codex_help_observation(semantic)
        self.assertNotEqual(plain_digest, semantic_digest)

        rejected = (
            (0, stdout[0], contract.CODEX_PATH_ALIAS_PERMISSION_WARNING + "x"),
            (
                0,
                stdout[0],
                contract.CODEX_PATH_ALIAS_PERMISSION_WARNING + "second diagnostic\n",
            ),
            (0, stdout[0], "unknown diagnostic\n"),
            (0, "\x1b[31m" + stdout[0], ""),
            (0, "\u009b31m" + stdout[0], ""),
            (0, stdout[0] + "\r", ""),
            (0, stdout[0] + "\b", ""),
            (0, stdout[0] + "\x00", ""),
            (9, stdout[0], ""),
        )
        for replacement in rejected:
            with self.subTest(replacement=replacement), self.assertRaises(
                contract.CodexCliContractError
            ):
                contract.canonical_codex_help_observation(
                    (replacement, plain[1], plain[2])
                )
        for codepoint in (*range(0x20), *range(0x7F, 0xA0)):
            if codepoint == ord("\n"):
                continue
            with self.subTest(control_codepoint=codepoint), self.assertRaises(
                contract.CodexCliContractError
            ):
                contract.canonical_codex_help_observation(
                    ((0, stdout[0] + chr(codepoint), ""), plain[1], plain[2])
                )

    def test_audited_codex_help_observation_matches_real_pty_and_nonpty_parents(self) -> None:
        if not os.environ.get("SULDE_TEST_CODEX_EXECUTABLE"):
            self.skipTest("set SULDE_TEST_CODEX_EXECUTABLE for the real CLI gate")
        if not Path(os.environ["SULDE_TEST_CODEX_EXECUTABLE"]).is_file():
            self.skipTest("audited codex-cli 0.154.0 is not installed")

        nonpty = observe_audited_codex_help_from_parent(pseudo_terminal=False)
        try:
            pty = observe_audited_codex_help_from_parent(pseudo_terminal=True)
        except PermissionError as error:
            self.skipTest(f"managed environment denies real pseudo-terminal: {error}")

        self.assertEqual(nonpty["version"], "codex-cli 0.154.0")
        self.assertEqual(pty["version"], "codex-cli 0.154.0")
        self.assertEqual(nonpty, pty)

    def git(self, root: Path, *arguments: str) -> str:
        completed = subprocess.run(
            ["git", "-C", str(root), *arguments],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        self.assertEqual(
            completed.returncode,
            0,
            completed.stdout + completed.stderr,
        )
        return completed.stdout.strip()

    def prepare(self, directory: Path, slug: str) -> tuple[Path, Path]:
        worktree = directory / "worktree"
        state = worktree / ".codex-agent"
        state.mkdir(parents=True)
        (worktree / "base.txt").write_text("base\n", encoding="utf-8")
        brief = state / f"{slug}.md"
        brief.write_text("# Task\n\nDo the work.\n", encoding="utf-8")
        brief.chmod(0o400)
        return worktree, brief

    def fixture_task_v1(self, *, owned_paths: list[str] | None = None) -> dict[str, object]:
        return {
            "schema": "sulde-guardian-program-task-v1",
            "task_id": "T04",
            "title": "Fixture task",
            "owner": "test-runtime",
            "capability_tier": "light",
            "base_commit": "fixture",
            "depends_on": ["T00"],
            "supersedes": [],
            "owned_paths": owned_paths or ["base.txt"],
            "requirements": [],
            "acceptance": ["fixture provider completes"],
            "evidence_gates": {
                "implemented": ["task_report"],
                "task_verified": ["targeted_tests"],
                "integrated": ["integration_tests"],
                "system_verified": ["system_tests"],
            },
        }

    def authority_fixture(self, directory: Path, slug: str) -> dict[str, object]:
        worktree = directory / "worktree"
        worktree.mkdir()
        (worktree / "base.txt").write_text("base\n", encoding="utf-8")
        control = directory / "coordinator/guardian-program"
        (control / "briefs").mkdir(parents=True)
        (control / "task-definitions").mkdir()
        brief = control / "briefs/T04.md"
        brief.write_text("# Task\n\nDo the work.\n", encoding="utf-8")
        brief_digest = hashlib.sha256(brief.read_bytes()).hexdigest()
        task = control / "task-definitions/T04.json"
        task_value = self.fixture_task_v1()
        task.write_text(
            json.dumps(task_value, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        marker = directory / "provider-started"
        executable = directory / "codex"
        executable.write_text(
            textwrap.dedent(
                f"""\
                #!/usr/bin/python3
                import sys
                from pathlib import Path
                Path({str(marker)!r}).touch()
                args = sys.argv[1:]
                Path(args[args.index('--output-last-message') + 1]).write_text(
                    {REPORT!r}, encoding='utf-8'
                )
                print('{{"type":"done"}}')
                """
            ),
            encoding="utf-8",
        )
        executable.chmod(0o755)
        environment = os.environ.copy()
        environment.update(
            {"SULDE_AGENT_PROVIDER": "codex", "SULDE_CODEX_EXE": str(executable)}
        )
        return {
            "worktree": worktree,
            "control": control,
            "brief": brief,
            "brief_digest": brief_digest,
            "task": task,
            "task_value": task_value,
            "marker": marker,
            "environment": environment,
            "slug": slug,
        }

    def authority_run_command(self, fixture: dict[str, object]) -> list[str]:
        task = Path(fixture["task"])
        return [
            sys.executable,
            str(RUNTIME),
            "run",
            str(fixture["worktree"]),
            str(fixture["slug"]),
            str(fixture["brief"]),
            "--control-root",
            str(fixture["control"]),
            "--brief-sha256",
            str(fixture["brief_digest"]),
            "--task-definition",
            str(task),
            "--task-definition-sha256",
            hashlib.sha256(task.read_bytes()).hexdigest(),
            "--task-id",
            "T04",
            "--timeout",
            "5",
        ]

    def run_authority_fixture(self, fixture: dict[str, object]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            self.authority_run_command(fixture),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=dict(fixture["environment"]),
            check=False,
        )

    def run_and_verify(
        self, provider: str, executable: Path, worktree: Path, brief: Path, slug: str
    ) -> None:
        environment = os.environ.copy()
        environment.update(
            {
                "SULDE_AGENT_PROVIDER": provider,
                "SULDE_CLAUDE_EXE" if provider == "claude" else "SULDE_CODEX_EXE": str(executable),
            }
        )
        run = subprocess.run(
            [
                sys.executable,
                str(RUNTIME),
                "run",
                str(worktree),
                slug,
                str(brief),
                "--owned-path",
                f"{provider}-change.txt",
                "--timeout",
                "10",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=environment,
            check=False,
        )
        self.assertEqual(run.returncode, 0, run.stderr)
        status = (worktree / ".codex-agent" / f"{slug}.status").read_text(encoding="utf-8")
        self.assertIn(f"provider={provider}", status)
        self.assertIn("stop=completed", status)
        self.assertIn("quiescent=true", status)
        run_rows = [
            json.loads(line)
            for line in (
                worktree / ".codex-agent" / f"{slug}.run.jsonl"
            ).read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual(
            [row["type"] for row in run_rows],
            [
                "execution.requested",
                "execution.started",
                "execution.result",
                "execution.disposed",
            ],
        )
        event_log = worktree / ".codex-agent" / f"{slug}.events.jsonl"
        event_cursor = json.loads(
            (
                worktree / ".codex-agent" / f"{slug}.events.cursor.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(event_cursor["schema"], "sulde-audit-cursor-v2")
        self.assertTrue(event_cursor["prefix_checkpoint"]["segments"])
        self.assertEqual(event_cursor["offset"], event_log.stat().st_size)
        self.assertTrue(event_cursor["runtime_generation"])
        guardian = json.loads(
            (
                worktree / ".codex-agent" / f"{slug}.guardian.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(guardian["execution"]["stop_reason"], "completed")
        self.assertTrue(guardian["execution"]["cleanup_quiescent"])
        verify = subprocess.run(
            [
                sys.executable,
                str(RUNTIME),
                "verify",
                str(worktree),
                slug,
                "--allowed-paths",
                ".*",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        self.assertEqual(verify.returncode, 0, verify.stdout + verify.stderr)
        self.assertIn("VERIFY: PASS", verify.stdout)

    def test_claude_can_execute_without_codex(self) -> None:
        with self.temporary_directory() as directory_name:
            directory = Path(directory_name)
            worktree, brief = self.prepare(directory, "claude-only")
            executable = directory / "claude"
            executable.write_text(
                "#!/usr/bin/python3\n"
                "import json\n"
                "from pathlib import Path\n"
                "Path('claude-change.txt').write_text('changed\\n')\n"
                f"print(json.dumps({{'type': 'result', 'result': {REPORT!r}}}, ensure_ascii=False))\n",
                encoding="utf-8",
            )
            executable.chmod(0o755)
            self.run_and_verify("claude", executable, worktree, brief, "claude-only")

    def test_codex_can_execute_without_claude(self) -> None:
        with self.temporary_directory() as directory_name:
            directory = Path(directory_name)
            worktree, brief = self.prepare(directory, "codex-only")
            executable = directory / "codex"
            executable.write_text(
                textwrap.dedent(
                    f"""\
                    #!/usr/bin/python3
                    import sys
                    from pathlib import Path
                    args = sys.argv[1:]
                    report = Path(args[args.index('--output-last-message') + 1])
                    Path('codex-change.txt').write_text('changed\\n')
                    report.write_text({REPORT!r}, encoding='utf-8')
                    print('{{"type":"done"}}')
                    """
                ),
                encoding="utf-8",
            )
            executable.chmod(0o755)
            self.run_and_verify("codex", executable, worktree, brief, "codex-only")

    def test_fixture_critic_uses_shared_command_template_parser(self) -> None:
        module = load_runtime_module()
        with self.temporary_directory() as directory_name:
            root = Path(directory_name).resolve()
            (root / "owned.txt").write_text("increment\n", encoding="utf-8")
            contract = {
                "workspace_root": str(root),
                "critic": {
                    "timeout_seconds": 10,
                    "task_scope": {"owned_paths": ["owned.txt"]},
                },
            }
            event = {"write_targets": ["owned.txt"]}
            completed = subprocess.CompletedProcess(
                ["critic.exe", r"C:\Critic Config\policy.json"],
                0,
                "{}",
                "",
            )
            template = r'"C:\Program Files\critic.exe" "C:\Critic Config\policy.json"'
            with (
                mock.patch.dict(
                    os.environ, {"SULDE_GUARDIAN_CRITIC_CMD": template}
                ),
                mock.patch.object(
                    module,
                    "split_command_template",
                    return_value=list(completed.args),
                ) as split,
                mock.patch.object(module, "build_critic_prompt", return_value="prompt"),
                mock.patch.object(module, "critic_secret_matches", return_value=[]),
                mock.patch.object(
                    module.subprocess, "run", return_value=completed
                ) as run,
            ):
                self.assertEqual(
                    module._fixture_critic_result(
                        contract, event, provider="codex"
                    ),
                    {},
                )
            split.assert_called_once_with(template)
            self.assertEqual(run.call_args.args[0], list(completed.args))

    def test_managed_semantic_critic_runs_once_after_terminal_batch(self) -> None:
        with self.temporary_directory() as directory_name:
            directory = Path(directory_name)
            worktree, brief = self.prepare(directory, "terminal-critic")
            executable = directory / "codex"
            executable.write_text(
                textwrap.dedent(
                    f"""\
                    #!/usr/bin/python3
                    import sys
                    from pathlib import Path
                    args = sys.argv[1:]
                    report = Path(args[args.index('--output-last-message') + 1])
                    Path('one.txt').write_text('first artifact\\n', encoding='utf-8')
                    Path('name,with-comma.txt').write_text('second artifact\\n', encoding='utf-8')
                    report.write_text({REPORT!r}, encoding='utf-8')
                    print('{{"type":"done"}}')
                    """
                ),
                encoding="utf-8",
            )
            executable.chmod(0o755)
            critic_calls = worktree / "critic.calls"
            critic_prompt = worktree / "critic.prompt"
            critic = directory / "critic"
            critic.write_text(
                textwrap.dedent(
                    f"""\
                    #!/usr/bin/python3
                    import json
                    import sys
                    from pathlib import Path
                    prompt = sys.stdin.read()
                    Path({str(critic_prompt)!r}).write_text(prompt, encoding='utf-8')
                    counter = Path({str(critic_calls)!r})
                    previous = counter.read_text(encoding='utf-8') if counter.exists() else ''
                    counter.write_text(previous + 'call\\n', encoding='utf-8')
                    print(json.dumps({{
                        'verdict': 'aligned',
                        'confidence': 0.99,
                        'summary': 'terminal batch matches the task',
                        'violated_constraints': [],
                        'evidence': ['both artifacts were evaluated together'],
                        'next_action': 'continue',
                    }}))
                    """
                ),
                encoding="utf-8",
            )
            critic.chmod(0o755)
            environment = os.environ.copy()
            environment.update(
                {
                    "SULDE_AGENT_PROVIDER": "codex",
                    "SULDE_CODEX_EXE": str(executable),
                    "SULDE_GUARDIAN_CRITIC_CMD": str(critic),
                }
            )

            completed = subprocess.run(
                [
                    sys.executable,
                    str(RUNTIME),
                    "run",
                    str(worktree),
                    "terminal-critic",
                    str(brief),
                    "--semantic-critic",
                    "--owned-path",
                    "one.txt",
                    "--owned-path",
                    "name,with-comma.txt",
                    "--owned-path",
                    "critic.calls",
                    "--owned-path",
                    "critic.prompt",
                    "--timeout",
                    "10",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=environment,
                check=False,
                timeout=20,
            )

            self.assertEqual(
                completed.returncode,
                0,
                completed.stdout + completed.stderr,
            )
            contract_path = (
                worktree
                / ".codex-agent"
                / "terminal-critic.intent.json"
            )
            status_path = worktree / ".codex-agent" / "terminal-critic.status"
            audit_path = (
                worktree
                / ".codex-agent"
                / "terminal-critic.intent.events.jsonl"
            )
            provider_events_path = (
                worktree
                / ".codex-agent"
                / "terminal-critic.events.jsonl"
            )

            def terminal_evidence() -> str:
                evidence = {
                    "inherited_environment": {
                        "SULDE_TEST_MODE": environment.get("SULDE_TEST_MODE"),
                        "SULDE_AGENT_PROVIDER": environment.get("SULDE_AGENT_PROVIDER"),
                        "critic_command": environment.get("SULDE_GUARDIAN_CRITIC_CMD"),
                    },
                    "runtime_stdout": completed.stdout.splitlines(),
                    "runtime_stderr": completed.stderr.splitlines(),
                    "provider_terminal_stream": (
                        provider_events_path.read_text(encoding="utf-8").splitlines()
                        if provider_events_path.is_file()
                        else []
                    ),
                    "critic_calls_exists": critic_calls.is_file(),
                    "contract": (
                        json.loads(contract_path.read_text(encoding="utf-8"))
                        if contract_path.is_file()
                        else None
                    ),
                    "audit": (
                        [
                            json.loads(line)
                            for line in audit_path.read_text(encoding="utf-8").splitlines()
                        ]
                        if audit_path.is_file()
                        else []
                    ),
                    "status": (
                        status_path.read_text(encoding="utf-8")
                        if status_path.is_file()
                        else None
                    ),
                }
                return json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)

            self.assertTrue(critic_calls.is_file(), terminal_evidence())
            self.assertEqual(
                critic_calls.read_text(encoding="utf-8"),
                "call\n",
                terminal_evidence(),
            )
            duplicate_finalize = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    (
                        "import sys; from pathlib import Path; "
                        f"sys.path.insert(0, {str(RUNTIME.parent)!r}); "
                        "from intent_guardian import finalize_host_turn; "
                        "payload={'client':'codex',"
                        "'session_id':'managed:l3:terminal-critic',"
                        "'intent_contract':sys.argv[1]}; "
                        "finalize_host_turn(payload, provider='codex'); "
                        "finalize_host_turn(payload, provider='codex')"
                    ),
                    str(contract_path),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=environment,
                cwd=worktree,
                check=False,
                timeout=10,
            )
            self.assertEqual(
                duplicate_finalize.returncode,
                0,
                duplicate_finalize.stdout + duplicate_finalize.stderr,
            )
            self.assertEqual(
                critic_calls.read_text(encoding="utf-8"),
                "call\n",
                terminal_evidence(),
            )
            prompt = critic_prompt.read_text(encoding="utf-8")
            self.assertIn("TARGET: one.txt", prompt)
            self.assertIn("TARGET: name,with-comma.txt", prompt)
            contract = json.loads(contract_path.read_text(encoding="utf-8"))
            self.assertEqual(contract["runtime"]["critic_batches"], [])
            checkpoint = contract["runtime"]["critic_checkpoints"][-1]
            self.assertEqual(
                checkpoint["verdict"],
                "aligned",
            )
            self.assertEqual(
                checkpoint["session_id"],
                "managed:l3:terminal-critic",
            )
            self.assertEqual(checkpoint["completed_writes"], 2)
            self.assertEqual(checkpoint["target_count"], 2)
            self.assertTrue(checkpoint["batch_id"].startswith("cb-"))
            critic_audit = [
                row
                for row in (
                    json.loads(line)
                    for line in audit_path.read_text(encoding="utf-8").splitlines()
                )
                if row.get("schema") == "sulde-intent-critic-event-v1"
            ]
            self.assertEqual(len(critic_audit), 1)
            self.assertEqual(critic_audit[0]["batch_id"], checkpoint["batch_id"])
            self.assertEqual(critic_audit[0]["action"], "observe")
            status = status_path.read_text(encoding="utf-8")
            self.assertTrue(status.startswith("status=success "), status)

    def test_partial_provider_report_with_nonzero_exit_is_not_success(self) -> None:
        with self.temporary_directory() as directory_name:
            directory = Path(directory_name)
            worktree, brief = self.prepare(directory, "partial-error")
            executable = directory / "claude"
            executable.write_text(
                "#!/usr/bin/python3\n"
                "import json\n"
                f"print(json.dumps({{'type': 'result', 'result': {REPORT!r}}}, ensure_ascii=False))\n"
                "raise SystemExit(3)\n",
                encoding="utf-8",
            )
            executable.chmod(0o755)
            environment = os.environ.copy()
            environment.update(
                {"SULDE_AGENT_PROVIDER": "claude", "SULDE_CLAUDE_EXE": str(executable)}
            )

            completed = subprocess.run(
                [
                    sys.executable,
                    str(RUNTIME),
                    "run",
                    str(worktree),
                    "partial-error",
                    str(brief),
                    "--timeout",
                    "10",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=environment,
                check=False,
            )

            self.assertEqual(completed.returncode, 1, completed.stdout + completed.stderr)
            status = (worktree / ".codex-agent/partial-error.status").read_text()
            self.assertTrue(status.startswith("status=failed rc=3 "), status)
            self.assertIn("stop=error", status)
            guardian = json.loads(
                (worktree / ".codex-agent/partial-error.guardian.json").read_text()
            )
            self.assertTrue(guardian["execution"]["output_present"])
            self.assertEqual(guardian["execution"]["stop_reason"], "error")
            self.assertTrue(guardian["execution"]["cleanup_quiescent"])
            self.assertTrue(guardian["task_report_verdict"]["passed"])

    def test_agent_runtime_disposes_background_descendant_before_success(self) -> None:
        with self.temporary_directory() as directory_name:
            directory = Path(directory_name)
            worktree, brief = self.prepare(directory, "tree-cleanup")
            child_pid_file = worktree / ".codex-agent/child.pid"
            executable = directory / "codex"
            executable.write_text(
                textwrap.dedent(
                    f"""\
                    #!/usr/bin/python3
                    import subprocess
                    import sys
                    from pathlib import Path
                    args = sys.argv[1:]
                    report = Path(args[args.index('--output-last-message') + 1])
                    child = subprocess.Popen(
                        [sys.executable, '-c', 'import time; time.sleep(60)'],
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        close_fds=True,
                    )
                    Path({str(child_pid_file)!r}).write_text(str(child.pid))
                    report.write_text({REPORT!r}, encoding='utf-8')
                    print('{{"type":"done"}}')
                    """
                ),
                encoding="utf-8",
            )
            executable.chmod(0o755)
            environment = os.environ.copy()
            environment.update(
                {"SULDE_AGENT_PROVIDER": "codex", "SULDE_CODEX_EXE": str(executable)}
            )

            completed = subprocess.run(
                [
                    sys.executable,
                    str(RUNTIME),
                    "run",
                    str(worktree),
                    "tree-cleanup",
                    str(brief),
                    "--timeout",
                    "10",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=environment,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            child_pid = int(child_pid_file.read_text())
            deadline = time.monotonic() + 2
            alive = True
            while time.monotonic() < deadline:
                try:
                    os.kill(child_pid, 0)
                except ProcessLookupError:
                    alive = False
                    break
                time.sleep(0.02)
            self.assertFalse(alive, f"background descendant {child_pid} survived success")
            status = (worktree / ".codex-agent/tree-cleanup.status").read_text()
            self.assertIn("quiescent=true", status)

    def test_managed_correction_interrupts_the_full_process_tree_and_closes_ledger(self) -> None:
        with self.temporary_directory() as directory_name:
            directory = Path(directory_name)
            worktree, brief = self.prepare(directory, "managed-correction")
            child_pid_file = worktree / ".codex-agent/correction-child.pid"
            executable = directory / "codex"
            executable.write_text(
                textwrap.dedent(
                    f"""\
                    #!/usr/bin/python3
                    import json
                    import subprocess
                    import sys
                    import time
                    from pathlib import Path
                    child = subprocess.Popen(
                        [sys.executable, '-c', 'import time; time.sleep(60)'],
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        close_fds=True,
                    )
                    Path({str(child_pid_file)!r}).write_text(str(child.pid))
                    print(json.dumps({{'type': 'started'}}), flush=True)
                    time.sleep(60)
                    """
                ),
                encoding="utf-8",
            )
            executable.chmod(0o755)
            environment = os.environ.copy()
            environment.update(
                {
                    "SULDE_AGENT_PROVIDER": "codex",
                    "SULDE_CODEX_EXE": str(executable),
                }
            )
            running = subprocess.Popen(
                [
                    sys.executable,
                    str(RUNTIME),
                    "run",
                    str(worktree),
                    "managed-correction",
                    str(brief),
                    "--guardian-mode",
                    "enforce",
                    "--timeout",
                    "20",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=environment,
            )
            contract = worktree / ".codex-agent/managed-correction.intent.json"
            run_ledger = worktree / ".codex-agent/managed-correction.run.jsonl"
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                if (
                    contract.is_file()
                    and child_pid_file.is_file()
                    and run_ledger.is_file()
                    and "execution.started" in run_ledger.read_text(errors="replace")
                ):
                    break
                if running.poll() is not None:
                    break
                time.sleep(0.02)
            self.assertIsNone(running.poll(), "managed run ended before correction was queued")
            self.assertTrue(child_pid_file.is_file())

            message = "不是这个方向，请保留已经确认的表达"
            queued = subprocess.run(
                [
                    sys.executable,
                    str(GUARDIAN_CLI),
                    "correction-propose",
                    message,
                    "--provider",
                    "codex",
                    "--session-id",
                    "managed:l3:managed-correction",
                    "--contract",
                    str(contract),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            self.assertEqual(queued.returncode, 0, queued.stdout + queued.stderr)
            stdout, stderr = running.communicate(timeout=15)
            self.assertEqual(running.returncode, 1, stdout + stderr)

            child_pid = int(child_pid_file.read_text())
            deadline = time.monotonic() + 2
            alive = True
            while time.monotonic() < deadline:
                try:
                    os.kill(child_pid, 0)
                except ProcessLookupError:
                    alive = False
                    break
                time.sleep(0.02)
            self.assertFalse(alive, f"corrected run descendant {child_pid} survived")

            status = (worktree / ".codex-agent/managed-correction.status").read_text()
            self.assertTrue(status.startswith("status=paused "), status)
            self.assertIn("stop=policy_paused", status)
            self.assertIn("quiescent=true", status)
            guardian = json.loads(
                (worktree / ".codex-agent/managed-correction.guardian.json").read_text()
            )
            self.assertEqual(guardian["status"], "paused")
            self.assertEqual(guardian["corrections_queued"], 0)
            self.assertEqual(
                guardian["correction_interventions_by_state"]["applied"], 1
            )
            run_rows = [
                json.loads(line) for line in run_ledger.read_text().splitlines()
            ]
            self.assertTrue(
                any(
                    row.get("type") == "execution.interrupt_requested"
                    and row.get("reason") == "correction_intervention"
                    for row in run_rows
                )
            )
            correction_store = (
                worktree
                / ".codex-agent/managed-correction.intent.corrections.jsonl"
            )
            correction_rows = [
                json.loads(line) for line in correction_store.read_text().splitlines()
            ]
            self.assertEqual(
                [row.get("state", "proposed") for row in correction_rows],
                ["proposed", "queued", "applied"],
            )
            self.assertNotIn(message, correction_store.read_text())

    def test_provider_cannot_forge_a_correction_terminal_state(self) -> None:
        with self.temporary_directory() as directory_name:
            directory = Path(directory_name)
            worktree, brief = self.prepare(directory, "correction-tamper")
            executable = directory / "codex"
            executable.write_text(
                textwrap.dedent(
                    f"""\
                    #!/usr/bin/python3
                    import datetime
                    import hashlib
                    import json
                    import os
                    import sys
                    from pathlib import Path
                    contract = Path(os.environ['SULDE_INTENT_CONTRACT']).resolve()
                    store = contract.with_name(contract.name[:-5] + '.corrections.jsonl')
                    at = datetime.datetime.now(datetime.timezone.utc).isoformat()
                    contract_sha = hashlib.sha256(str(contract).encode()).hexdigest()
                    lane_sha = hashlib.sha256(b'codex\\0managed:l3:correction-tamper').hexdigest()
                    intervention_id = 'cor-' + 'a' * 24
                    base = {{
                        'schema': 'sulde-correction-intervention-event-v1',
                        'contract_sha256': contract_sha,
                        'at': at,
                        'intervention_id': intervention_id,
                    }}
                    rows = [
                        {{
                            **base,
                            'sequence': 1,
                            'type': 'correction.intervention_proposed',
                            'intent_id_sha256': hashlib.sha256(b'l3:correction-tamper').hexdigest(),
                            'intent_revision': 1,
                            'provider': 'codex',
                            'lane_sha256': lane_sha,
                            'actor': 'agent',
                            'source': 'agent_monitor',
                            'correction_sha256': hashlib.sha256(b'forged').hexdigest(),
                            'request_sha256': '',
                        }},
                        {{
                            **base,
                            'sequence': 2,
                            'type': 'correction.intervention_transitioned',
                            'state': 'queued',
                            'boundary': 'manual',
                            'reason_code': 'awaiting_safe_boundary',
                            'actor': 'system',
                        }},
                        {{
                            **base,
                            'sequence': 3,
                            'type': 'correction.intervention_transitioned',
                            'state': 'applied',
                            'boundary': 'managed_run_monitor',
                            'reason_code': 'forged_terminal',
                            'actor': 'system',
                        }},
                    ]
                    with store.open('a', encoding='utf-8') as handle:
                        handle.write(''.join(json.dumps(row, sort_keys=True) + '\\n' for row in rows))
                        handle.flush()
                        os.fsync(handle.fileno())
                    args = sys.argv[1:]
                    report = Path(args[args.index('--output-last-message') + 1])
                    report.write_text({REPORT!r}, encoding='utf-8')
                    print('{{"type":"done"}}', flush=True)
                    """
                ),
                encoding="utf-8",
            )
            executable.chmod(0o755)
            environment = os.environ.copy()
            environment.update(
                {
                    "SULDE_AGENT_PROVIDER": "codex",
                    "SULDE_CODEX_EXE": str(executable),
                }
            )
            completed = subprocess.run(
                [
                    sys.executable,
                    str(RUNTIME),
                    "run",
                    str(worktree),
                    "correction-tamper",
                    str(brief),
                    "--guardian-mode",
                    "enforce",
                    "--timeout",
                    "10",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=environment,
                check=False,
            )
            self.assertEqual(completed.returncode, 1, completed.stdout + completed.stderr)
            status = (worktree / ".codex-agent/correction-tamper.status").read_text()
            self.assertTrue(status.startswith("status=paused "), status)
            guardian = json.loads(
                (worktree / ".codex-agent/correction-tamper.guardian.json").read_text()
            )
            self.assertEqual(guardian["integrity_breaches"], 1)
            self.assertEqual(guardian["correction_interventions"], 0)
            store = worktree / ".codex-agent/correction-tamper.intent.corrections.jsonl"
            self.assertEqual(store.read_bytes(), b"")

    def test_hard_killed_parent_cleans_tree_and_next_run_recovers_append_only_prefix(self) -> None:
        with self.temporary_directory() as directory_name:
            directory = Path(directory_name)
            worktree, brief = self.prepare(directory, "hard-crash")
            provider_pid_file = worktree / ".codex-agent/provider.pid"
            child_pid_file = worktree / ".codex-agent/provider-child.pid"
            sleeper = directory / "codex-sleeper"
            sleeper.write_text(
                textwrap.dedent(
                    f"""\
                    #!/usr/bin/python3
                    import os
                    import subprocess
                    import sys
                    import time
                    from pathlib import Path
                    child = subprocess.Popen(
                        [sys.executable, '-c', 'import time; time.sleep(60)'],
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        close_fds=True,
                    )
                    Path({str(provider_pid_file)!r}).write_text(str(os.getpid()))
                    Path({str(child_pid_file)!r}).write_text(str(child.pid))
                    print('{{"type":"started"}}', flush=True)
                    time.sleep(60)
                    """
                ),
                encoding="utf-8",
            )
            sleeper.chmod(0o755)
            environment = os.environ.copy()
            environment.update(
                {
                    "SULDE_AGENT_PROVIDER": "codex",
                    "SULDE_CODEX_EXE": str(sleeper),
                }
            )
            running = subprocess.Popen(
                [
                    sys.executable,
                    str(RUNTIME),
                    "run",
                    str(worktree),
                    "hard-crash",
                    str(brief),
                    "--timeout",
                    "30",
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=environment,
            )
            ledger = worktree / ".codex-agent/hard-crash.run.jsonl"
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                if (
                    provider_pid_file.is_file()
                    and child_pid_file.is_file()
                    and ledger.is_file()
                    and "execution.started" in ledger.read_text(errors="replace")
                ):
                    break
                if running.poll() is not None:
                    break
                time.sleep(0.02)
            self.assertIsNone(running.poll(), "runtime ended before hard-kill injection")
            provider_pid = int(provider_pid_file.read_text())
            child_pid = int(child_pid_file.read_text())

            os.kill(running.pid, signal.SIGKILL)
            running.wait(timeout=5)
            for process_id in (provider_pid, child_pid):
                deadline = time.monotonic() + 4
                alive = True
                while time.monotonic() < deadline:
                    try:
                        os.kill(process_id, 0)
                    except ProcessLookupError:
                        alive = False
                        break
                    time.sleep(0.02)
                self.assertFalse(
                    alive,
                    f"managed process {process_id} survived parent hard crash",
                )

            finisher = directory / "codex-finisher"
            finisher.write_text(
                textwrap.dedent(
                    f"""\
                    #!/usr/bin/python3
                    import sys
                    from pathlib import Path
                    args = sys.argv[1:]
                    report = Path(args[args.index('--output-last-message') + 1])
                    Path('recovered-change.txt').write_text('finished after recovery\\n')
                    report.write_text({REPORT!r}, encoding='utf-8')
                    print('{{"type":"done"}}')
                    """
                ),
                encoding="utf-8",
            )
            finisher.chmod(0o755)
            environment["SULDE_CODEX_EXE"] = str(finisher)
            resumed = subprocess.run(
                [
                    sys.executable,
                    str(RUNTIME),
                    "run",
                    str(worktree),
                    "hard-crash",
                    str(brief),
                    "--timeout",
                    "10",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=environment,
                check=False,
            )
            self.assertEqual(resumed.returncode, 0, resumed.stdout + resumed.stderr)
            status = (worktree / ".codex-agent/hard-crash.status").read_text()
            self.assertTrue(status.startswith("status=success "), status)
            recovered_rows = [
                json.loads(line)
                for line in (
                    worktree / ".codex-agent/hard-crash.round1.run.jsonl"
                ).read_text().splitlines()
            ]
            self.assertEqual(
                [row["type"] for row in recovered_rows[-2:]],
                ["execution.result", "execution.disposed"],
            )
            self.assertTrue(recovered_rows[-1]["recovered_from_crash"])
            self.assertTrue(recovered_rows[-1]["quiescent"])

    def test_malformed_run_ledger_is_preserved_and_routes_to_human_without_launch(self) -> None:
        with self.temporary_directory() as directory_name:
            directory = Path(directory_name)
            worktree, brief = self.prepare(directory, "ledger-tail")
            marker = worktree / "provider-started.txt"
            executable = directory / "codex"
            executable.write_text(
                textwrap.dedent(
                    f"""\
                    #!/usr/bin/python3
                    from pathlib import Path
                    Path({str(marker)!r}).write_text('started')
                    """
                ),
                encoding="utf-8",
            )
            executable.chmod(0o755)
            ledger = worktree / ".codex-agent/ledger-tail.run.jsonl"
            malformed = b'{"schema":"sulde-run-event-v1","type":"execution.requested"'
            ledger.write_bytes(malformed)
            environment = os.environ.copy()
            environment.update(
                {
                    "SULDE_AGENT_PROVIDER": "codex",
                    "SULDE_CODEX_EXE": str(executable),
                }
            )

            completed = subprocess.run(
                [
                    sys.executable,
                    str(RUNTIME),
                    "run",
                    str(worktree),
                    "ledger-tail",
                    str(brief),
                    "--timeout",
                    "5",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=environment,
                check=False,
            )

            self.assertEqual(completed.returncode, 1)
            status = (worktree / ".codex-agent/ledger-tail.status").read_text()
            self.assertTrue(status.startswith("status=awaiting_human "), status)
            self.assertIn("recovery=inconclusive", status)
            self.assertEqual(ledger.read_bytes(), malformed)
            self.assertFalse(marker.exists())

    def test_enforce_report_rejects_out_of_scope_write_without_control_plane_pause(self) -> None:
        with self.temporary_directory() as directory_name:
            directory = Path(directory_name)
            worktree, brief = self.prepare(directory, "drift")
            brief.chmod(0o600)
            brief.write_text(
                "# Task\n\n## 目标\n只改 allowed.txt\n\n## 范围\n"
                "涉及路径：allowed.txt\n禁止改动：其他文件\n\n"
                "## 完成标准\n- allowed.txt 更新\n",
                encoding="utf-8",
            )
            brief.chmod(0o400)
            executable = directory / "codex"
            event = {
                "type": "item.completed",
                "item": {
                    "id": "call-1",
                    "type": "file_change",
                    "status": "completed",
                    "changes": [{"path": "forbidden.txt", "kind": "add"}],
                },
            }
            executable.write_text(
                textwrap.dedent(
                    f"""\
                    #!/usr/bin/python3
                    import json
                    print(json.dumps({event!r}))
                    """
                ),
                encoding="utf-8",
            )
            executable.chmod(0o755)
            environment = os.environ.copy()
            environment.update({"SULDE_AGENT_PROVIDER": "codex", "SULDE_CODEX_EXE": str(executable)})
            completed = subprocess.run(
                [
                    sys.executable,
                    str(RUNTIME),
                    "run",
                    str(worktree),
                    "drift",
                    str(brief),
                    "--guardian-mode",
                    "enforce",
                    "--timeout",
                    "10",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=environment,
                check=False,
            )
            self.assertEqual(completed.returncode, 1, completed.stdout + completed.stderr)
            status = (worktree / ".codex-agent/drift.status").read_text(encoding="utf-8")
            self.assertTrue(status.startswith("status=failed "), status)
            summary = json.loads((worktree / ".codex-agent/drift.guardian.json").read_text())
            self.assertEqual(summary["denials"], 0)
            self.assertEqual(summary["findings"], 0)
            self.assertFalse(summary["policy_enforcement"]["observed_denial"])
            self.assertFalse(summary["policy_enforcement"]["execution_prevented"])
            self.assertFalse(summary["task_report_verdict"]["passed"])

    def test_enforce_report_snapshot_catches_unreported_shell_side_effect(self) -> None:
        with self.temporary_directory() as directory_name:
            directory = Path(directory_name)
            worktree, brief = self.prepare(directory, "hidden-drift")
            brief.chmod(0o600)
            brief.write_text(
                "# Task\n\n## 目标\n只改 allowed.txt\n\n## 范围\n"
                "涉及路径：allowed.txt\n禁止改动：其他文件\n\n"
                "## 完成标准\n- allowed.txt 更新\n",
                encoding="utf-8",
            )
            brief.chmod(0o400)
            executable = directory / "codex"
            executable.write_text(
                textwrap.dedent(
                    """\
                    #!/usr/bin/python3
                    from pathlib import Path
                    Path('forbidden.txt').write_text('hidden side effect\\n')
                    print('{"type":"done"}')
                    """
                ),
                encoding="utf-8",
            )
            executable.chmod(0o755)
            environment = os.environ.copy()
            environment.update({"SULDE_AGENT_PROVIDER": "codex", "SULDE_CODEX_EXE": str(executable)})
            completed = subprocess.run(
                [
                    sys.executable,
                    str(RUNTIME),
                    "run",
                    str(worktree),
                    "hidden-drift",
                    str(brief),
                    "--guardian-mode",
                    "enforce",
                    "--timeout",
                    "10",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=environment,
                check=False,
            )
            self.assertEqual(completed.returncode, 1, completed.stdout + completed.stderr)
            status = (worktree / ".codex-agent/hidden-drift.status").read_text(encoding="utf-8")
            self.assertTrue(status.startswith("status=failed "), status)
            rows = (worktree / ".codex-agent/hidden-drift.intent.events.jsonl").read_text().splitlines()
            self.assertTrue(
                any(json.loads(row).get("event", {}).get("observation_source") == "worktree_snapshot" for row in rows)
            )

    def test_unmatched_external_completion_enters_awaiting_human_not_blind_failure(self) -> None:
        with self.temporary_directory() as directory_name:
            directory = Path(directory_name)
            worktree, brief = self.prepare(directory, "external-unknown")
            executable = directory / "codex"
            event = {
                "type": "item.completed",
                "item": {
                    "id": "remote-1",
                    "type": "mcp_tool_call",
                    "status": "failed",
                    "server": "docs",
                    "tool": "update_document",
                    "arguments": {"uri": "doc://resume", "content": "new"},
                },
            }
            executable.write_text(
                textwrap.dedent(
                    f"""\
                    #!/usr/bin/python3
                    import json
                    print(json.dumps({event!r}))
                    """
                ),
                encoding="utf-8",
            )
            executable.chmod(0o755)
            environment = os.environ.copy()
            environment.update(
                {"SULDE_AGENT_PROVIDER": "codex", "SULDE_CODEX_EXE": str(executable)}
            )
            completed = subprocess.run(
                [
                    sys.executable,
                    str(RUNTIME),
                    "run",
                    str(worktree),
                    "external-unknown",
                    str(brief),
                    "--guardian-mode",
                    "enforce",
                    "--timeout",
                    "10",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=environment,
                check=False,
            )
            self.assertEqual(completed.returncode, 1, completed.stdout + completed.stderr)
            status = (worktree / ".codex-agent/external-unknown.status").read_text()
            self.assertTrue(status.startswith("status=awaiting_human "), status)
            summary = json.loads(
                (worktree / ".codex-agent/external-unknown.guardian.json").read_text()
            )
            self.assertEqual(summary["interventions_open"], 1)
            self.assertEqual(summary["effect_unknown"], 1)
            self.assertTrue(
                (worktree / ".codex-agent/external-unknown.intent.interventions.jsonl").is_file()
            )
            ledger = [
                json.loads(line)
                for line in (
                    worktree / ".codex-agent/external-unknown.run.jsonl"
                ).read_text(encoding="utf-8").splitlines()
            ]
            for event_type in (
                "execution.started",
                "execution.interrupt_requested",
                "execution.result",
                "execution.disposed",
            ):
                self.assertEqual(
                    sum(row.get("type") == event_type for row in ledger),
                    1,
                    event_type,
                )
            self.assertTrue(all(row.get("provider") == "codex" for row in ledger))
            interrupt = next(
                row for row in ledger if row["type"] == "execution.interrupt_requested"
            )
            result = next(row for row in ledger if row["type"] == "execution.result")
            disposed = next(row for row in ledger if row["type"] == "execution.disposed")
            self.assertEqual(interrupt["reason"], "external_effect_outcome_unknown")
            self.assertEqual(result["stop_reason"], "awaiting_human")
            self.assertTrue(disposed["quiescent"])
            self.assertEqual(summary["effect_attempts"], 1)
            effect_rows = [
                json.loads(line)
                for line in (
                    worktree / ".codex-agent/external-unknown.intent.interventions.jsonl"
                ).read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(
                sum(row.get("type") == "effect.attempt_created" for row in effect_rows),
                1,
            )
            self.assertEqual(
                sum(row.get("type") == "intent.intervention_opened" for row in effect_rows),
                1,
            )
            attempt_ids = {
                row["attempt_id"] for row in effect_rows if row.get("attempt_id")
            }
            intervention_ids = {
                row["intervention_id"]
                for row in effect_rows
                if row.get("intervention_id")
            }
            self.assertEqual(len(attempt_ids), 1)
            self.assertEqual(len(intervention_ids), 1)
            forbidden_types = {
                "intent.intervention_resolved",
                "intent.intervention_retry_consumed",
                "intent.intervention_reprobe_consumed",
            }
            self.assertFalse(forbidden_types & {row.get("type") for row in effect_rows})
            terminal_surface = status + json.dumps(summary, sort_keys=True)
            for marker in (
                "post_terminal",
                "retry_authorized",
                "reprobe_authorized",
                "effect_replay",
                "human_decision",
            ):
                self.assertNotIn(marker, terminal_surface)

    def test_provider_cannot_tamper_with_authoritative_intent_contract(self) -> None:
        with self.temporary_directory() as directory_name:
            directory = Path(directory_name)
            worktree, brief = self.prepare(directory, "tamper")
            executable = directory / "codex"
            executable.write_text(
                textwrap.dedent(
                    f"""\
                    #!/usr/bin/python3
                    import json
                    import os
                    import sys
                    from pathlib import Path
                    contract_path = Path(os.environ['SULDE_INTENT_CONTRACT'])
                    contract = json.loads(contract_path.read_text())
                    contract['objective'] = 'provider widened its own authority'
                    contract_path.write_text(json.dumps(contract))
                    args = sys.argv[1:]
                    report = Path(args[args.index('--output-last-message') + 1])
                    report.write_text({REPORT!r}, encoding='utf-8')
                    print('{{"type":"done"}}')
                    """
                ),
                encoding="utf-8",
            )
            executable.chmod(0o755)
            environment = os.environ.copy()
            environment.update({"SULDE_AGENT_PROVIDER": "codex", "SULDE_CODEX_EXE": str(executable)})
            completed = subprocess.run(
                [
                    sys.executable,
                    str(RUNTIME),
                    "run",
                    str(worktree),
                    "tamper",
                    str(brief),
                    "--guardian-mode",
                    "enforce",
                    "--timeout",
                    "10",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=environment,
                check=False,
            )
            self.assertEqual(completed.returncode, 1, completed.stdout + completed.stderr)
            status = (worktree / ".codex-agent/tamper.status").read_text(encoding="utf-8")
            self.assertTrue(status.startswith("status=paused "), status)
            summary = json.loads((worktree / ".codex-agent/tamper.guardian.json").read_text())
            self.assertEqual(summary["integrity_breaches"], 1)
            contract = json.loads((worktree / ".codex-agent/tamper.intent.json").read_text())
            self.assertNotEqual(contract["objective"], "provider widened its own authority")
            self.assertEqual(contract["status"], "paused")

    def test_provider_cannot_forge_authoritative_external_effect_truth(self) -> None:
        with self.temporary_directory() as directory_name:
            directory = Path(directory_name)
            worktree, brief = self.prepare(directory, "effect-tamper")
            executable = directory / "codex"
            executable.write_text(
                textwrap.dedent(
                    f"""\
                    #!/usr/bin/python3
                    import os
                    import sys
                    from pathlib import Path
                    contract_path = Path(os.environ['SULDE_INTENT_CONTRACT'])
                    store = contract_path.with_name(contract_path.name[:-5] + '.interventions.jsonl')
                    store.write_text('{{"forged":true}}\\n', encoding='utf-8')
                    args = sys.argv[1:]
                    report = Path(args[args.index('--output-last-message') + 1])
                    report.write_text({REPORT!r}, encoding='utf-8')
                    print('{{"type":"done"}}')
                    """
                ),
                encoding="utf-8",
            )
            executable.chmod(0o755)
            environment = os.environ.copy()
            environment.update(
                {"SULDE_AGENT_PROVIDER": "codex", "SULDE_CODEX_EXE": str(executable)}
            )
            completed = subprocess.run(
                [
                    sys.executable,
                    str(RUNTIME),
                    "run",
                    str(worktree),
                    "effect-tamper",
                    str(brief),
                    "--guardian-mode",
                    "enforce",
                    "--timeout",
                    "10",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=environment,
                check=False,
            )
            self.assertEqual(completed.returncode, 1, completed.stdout + completed.stderr)
            status = (worktree / ".codex-agent/effect-tamper.status").read_text()
            self.assertTrue(
                status.startswith("status=paused "),
                status + completed.stdout + completed.stderr,
            )
            summary = json.loads(
                (worktree / ".codex-agent/effect-tamper.guardian.json").read_text()
            )
            self.assertEqual(summary["integrity_breaches"], 1)
            store = worktree / ".codex-agent/effect-tamper.intent.interventions.jsonl"
            self.assertEqual(store.read_bytes(), b"")

    def test_provider_cannot_forge_authoritative_approval_truth(self) -> None:
        with self.temporary_directory() as directory_name:
            directory = Path(directory_name)
            worktree, brief = self.prepare(directory, "approval-tamper")
            executable = directory / "codex"
            executable.write_text(
                textwrap.dedent(
                    f"""\
                    #!/usr/bin/python3
                    import os
                    import sys
                    from pathlib import Path
                    contract_path = Path(os.environ['SULDE_INTENT_CONTRACT'])
                    store = contract_path.with_name(contract_path.name[:-5] + '.approvals.jsonl')
                    store.write_text('{{"forged":true}}\\n', encoding='utf-8')
                    args = sys.argv[1:]
                    report = Path(args[args.index('--output-last-message') + 1])
                    report.write_text({REPORT!r}, encoding='utf-8')
                    print('{{"type":"done"}}')
                    """
                ),
                encoding="utf-8",
            )
            executable.chmod(0o755)
            environment = os.environ.copy()
            environment.update(
                {
                    "SULDE_AGENT_PROVIDER": "codex",
                    "SULDE_CODEX_EXE": str(executable),
                }
            )

            completed = subprocess.run(
                [
                    sys.executable,
                    str(RUNTIME),
                    "run",
                    str(worktree),
                    "approval-tamper",
                    str(brief),
                    "--guardian-mode",
                    "enforce",
                    "--timeout",
                    "10",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=environment,
                check=False,
            )

            self.assertEqual(
                completed.returncode, 1, completed.stdout + completed.stderr
            )
            status = (worktree / ".codex-agent/approval-tamper.status").read_text()
            self.assertTrue(status.startswith("status=paused "), status)
            guardian = json.loads(
                (worktree / ".codex-agent/approval-tamper.guardian.json").read_text()
            )
            self.assertEqual(guardian["integrity_breaches"], 1)
            store = worktree / ".codex-agent/approval-tamper.intent.approvals.jsonl"
            self.assertEqual(store.read_bytes(), b"")

    def test_external_brief_import_is_sha_bound_and_installed_as_0400(self) -> None:
        with self.temporary_directory() as directory_name:
            directory = Path(directory_name)
            worktree, _local_brief = self.prepare(directory, "external-brief")
            source_parent = worktree / "guardian-program" / "briefs"
            source_parent.mkdir(parents=True)
            source = source_parent / "approved.md"
            source.write_text("# Task\n\nDo the work.\n", encoding="utf-8")
            source.chmod(0o644)
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            executable = directory / "codex"
            executable.write_text(
                textwrap.dedent(
                    f"""\
                    #!/usr/bin/python3
                    import sys
                    from pathlib import Path
                    args = sys.argv[1:]
                    Path(args[args.index('--output-last-message') + 1]).write_text(
                        {REPORT!r}, encoding='utf-8'
                    )
                    print('{{"type":"done"}}')
                    """
                ),
                encoding="utf-8",
            )
            executable.chmod(0o755)
            environment = os.environ.copy()
            environment.update(
                {"SULDE_AGENT_PROVIDER": "codex", "SULDE_CODEX_EXE": str(executable)}
            )
            completed = subprocess.run(
                [
                    sys.executable,
                    str(RUNTIME),
                    "run",
                    str(worktree),
                    "external-brief",
                    str(source),
                    "--brief-sha256",
                    digest,
                    "--owned-path",
                    "base.txt",
                    "--timeout",
                    "10",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=environment,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            installed = worktree / ".codex-agent/external-brief.brief.md"
            self.assertEqual(installed.read_bytes(), source.read_bytes())
            self.assertEqual(installed.stat().st_mode & 0o777, 0o400)
            guardian = json.loads(
                (worktree / ".codex-agent/external-brief.guardian.json").read_text()
            )
            self.assertEqual(guardian["brief"]["origin"], "external_import")
            self.assertEqual(guardian["report_contract"]["schema"], "sulde-worker-report-v1")

    def test_external_and_local_unsafe_briefs_fail_before_provider_launch(self) -> None:
        cases = ("external-hardlink", "external-mode", "local-symlink", "local-mode")
        for case in cases:
            with self.subTest(case=case), self.temporary_directory() as directory_name:
                directory = Path(directory_name)
                worktree, local = self.prepare(directory, case)
                marker = worktree / "provider-started"
                executable = directory / "codex"
                executable.write_text(
                    "#!/usr/bin/python3\n"
                    "from pathlib import Path\n"
                    f"Path({str(marker)!r}).write_text('started')\n",
                    encoding="utf-8",
                )
                executable.chmod(0o755)
                command = [
                    sys.executable,
                    str(RUNTIME),
                    "run",
                    str(worktree),
                    case,
                ]
                if case.startswith("external"):
                    parent = worktree / "guardian-program/briefs"
                    parent.mkdir(parents=True)
                    source = parent / "approved.md"
                    source.write_text("# Task\n", encoding="utf-8")
                    if case == "external-hardlink":
                        os.link(source, parent / "alias.md")
                    else:
                        source.chmod(0o666)
                    command.extend(
                        [
                            str(source),
                            "--brief-sha256",
                            hashlib.sha256(source.read_bytes()).hexdigest(),
                        ]
                    )
                else:
                    if case == "local-symlink":
                        local.chmod(0o600)
                        local.unlink()
                        target = directory / "outside.md"
                        target.write_text("# Task\n", encoding="utf-8")
                        local.symlink_to(target)
                    else:
                        local.chmod(0o600)
                    command.append(str(local))
                environment = os.environ.copy()
                environment.update(
                    {
                        "SULDE_AGENT_PROVIDER": "codex",
                        "SULDE_CODEX_EXE": str(executable),
                    }
                )
                completed = subprocess.run(
                    [*command, "--owned-path", "base.txt", "--timeout", "5"],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    env=environment,
                    check=False,
                )

                self.assertEqual(completed.returncode, 2, completed.stdout + completed.stderr)
                self.assertFalse(marker.exists())
                self.assertFalse((worktree / f".codex-agent/{case}.status").exists())
                self.assertFalse((worktree / f".codex-agent/{case}.brief.md").exists())

    def test_synthetic_legacy_schema_is_separate_from_current_execution_authority(self) -> None:
        module = load_runtime_module()
        historical_payload = (
            json.dumps(SYNTHETIC_LEGACY_TASK_V1, ensure_ascii=False) + "\n"
        ).encode("utf-8")
        with mock.patch.object(
            module,
            "_expected_base_commit",
            return_value=SYNTHETIC_LEGACY_TASK_V1["base_commit"],
        ):
            historical, historical_owned = module._parse_task_definition(
                historical_payload,
                ROOT,
                expected_task_id="synthetic-legacy-task",
                test_mode=False,
            )
        self.assertEqual(historical["base_commit"], SYNTHETIC_LEGACY_TASK_V1["base_commit"])
        self.assertEqual(historical_owned, SYNTHETIC_LEGACY_TASK_V1["owned_paths"])

        with self.temporary_directory() as directory_name:
            current_root = Path(directory_name) / "current-worktree"
            (current_root / "scripts/kb").mkdir(parents=True)
            (current_root / "tests").mkdir()
            current_task = {
                **SYNTHETIC_LEGACY_TASK_V1,
                "task_id": "synthetic-current-task",
                "base_commit": SYNTHETIC_CURRENT_BASE_COMMIT,
                "depends_on": [],
                "owned_paths": [
                    "scripts/kb/agent-runtime.py",
                    "scripts/kb/native_agent_broker.py",
                    "tests/test_agent_runtime.py",
                    "tests/test_native_agent_broker.py",
                ],
            }
            current_payload = (
                json.dumps(current_task, ensure_ascii=False) + "\n"
            ).encode("utf-8")
            with mock.patch.object(
                module,
                "_expected_base_commit",
                return_value=SYNTHETIC_CURRENT_BASE_COMMIT,
            ):
                with self.assertRaisesRegex(
                    module.AgentRuntimeError,
                    "base commit does not match worktree HEAD",
                ):
                    module._parse_task_definition(
                        historical_payload,
                        current_root,
                        expected_task_id="synthetic-legacy-task",
                        test_mode=False,
                    )
                task, owned_paths = module._parse_task_definition(
                    current_payload,
                    current_root,
                    expected_task_id="synthetic-current-task",
                    test_mode=False,
                )
            binding = module.execution_binding_envelope(
                task_payload=current_payload,
                task=task,
                brief_relative_path="briefs/synthetic-current-brief.md",
                brief_sha256=SYNTHETIC_BRIEF_SHA256,
                root=current_root,
                owned_paths=owned_paths,
                test_mode=True,
            )
            artifact, digest = module.execution_binding_artifact(binding)

        self.assertEqual(owned_paths, current_task["owned_paths"])
        self.assertEqual(binding["base_commit"], SYNTHETIC_CURRENT_BASE_COMMIT)
        self.assertEqual(binding["worktree"]["path"], str(current_root.resolve()))
        self.assertEqual(module.parse_execution_binding_artifact(artifact)[1], digest)

    def test_control_root_freezes_task_authority_and_projects_guardian_paths(self) -> None:
        with self.temporary_directory() as directory_name:
            directory = Path(directory_name)
            worktree = directory / "worktree"
            worktree.mkdir()
            (worktree / "base.txt").write_text("base\n", encoding="utf-8")
            control = directory / "coordinator/guardian-program"
            briefs = control / "briefs"
            tasks = control / "task-definitions"
            briefs.mkdir(parents=True)
            tasks.mkdir()
            brief = briefs / "T04.md"
            brief.write_text("# Task\n\nDo the work.\n", encoding="utf-8")
            task = tasks / "T04.json"
            task.write_text(
                json.dumps(self.fixture_task_v1(), sort_keys=True)
                + "\n",
                encoding="utf-8",
            )
            executable = directory / "codex"
            executable.write_text(
                textwrap.dedent(
                    f"""\
                    #!/usr/bin/python3
                    import sys
                    from pathlib import Path
                    args = sys.argv[1:]
                    Path(args[args.index('--output-last-message') + 1]).write_text(
                        {REPORT!r}, encoding='utf-8'
                    )
                    print('{{"type":"done"}}')
                    """
                ),
                encoding="utf-8",
            )
            executable.chmod(0o755)
            environment = os.environ.copy()
            environment.update(
                {"SULDE_AGENT_PROVIDER": "codex", "SULDE_CODEX_EXE": str(executable)}
            )
            completed = subprocess.run(
                [
                    sys.executable,
                    str(RUNTIME),
                    "run",
                    str(worktree),
                    "authority",
                    str(brief),
                    "--control-root",
                    str(control),
                    "--brief-sha256",
                    hashlib.sha256(brief.read_bytes()).hexdigest(),
                    "--task-definition",
                    str(task),
                    "--task-definition-sha256",
                    hashlib.sha256(task.read_bytes()).hexdigest(),
                    "--task-id",
                    "T04",
                    "--timeout",
                    "5",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=environment,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            frozen = worktree / ".codex-agent/authority.task.json"
            self.assertEqual(frozen.stat().st_mode & 0o777, 0o400)
            frozen_binding = worktree / ".codex-agent/authority.task-binding.json"
            self.assertEqual(frozen_binding.stat().st_mode & 0o777, 0o400)
            guardian = json.loads(
                (worktree / ".codex-agent/authority.guardian.json").read_text()
            )
            self.assertEqual(guardian["task_authority"]["task_id"], "T04")
            self.assertEqual(
                guardian["execution_binding"]["sha256"],
                guardian["task_authority"]["execution_binding_sha256"],
            )
            self.assertEqual(guardian["policy_enforcement"]["owned_paths"], ["base.txt"])
            intent = json.loads(
                (worktree / ".codex-agent/authority.intent.json").read_text()
            )
            self.assertEqual(intent["constraints"]["allowed_paths"], ["base.txt"])
            verify = subprocess.run(
                [
                    sys.executable,
                    str(RUNTIME),
                    "verify",
                    str(worktree),
                    "authority",
                    "--brief-sha256",
                    hashlib.sha256(brief.read_bytes()).hexdigest(),
                    "--task-definition-sha256",
                    hashlib.sha256(task.read_bytes()).hexdigest(),
                    "--task-id",
                    "T04",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            self.assertEqual(verify.returncode, 0, verify.stdout + verify.stderr)

    def test_task_authority_mismatch_is_stateless_before_provider(self) -> None:
        with self.temporary_directory() as directory_name:
            directory = Path(directory_name)
            worktree = directory / "worktree"
            worktree.mkdir()
            (worktree / "base.txt").write_text("base\n", encoding="utf-8")
            control = directory / "guardian-program"
            (control / "briefs").mkdir(parents=True)
            (control / "task-definitions").mkdir()
            brief = control / "briefs/T04.md"
            brief.write_text("# Task\n", encoding="utf-8")
            task = control / "task-definitions/T04.json"
            task.write_text(
                json.dumps(self.fixture_task_v1()),
                encoding="utf-8",
            )
            marker = directory / "provider-started"
            executable = directory / "codex"
            executable.write_text(
                f"#!/usr/bin/python3\nfrom pathlib import Path\nPath({str(marker)!r}).touch()\n",
                encoding="utf-8",
            )
            executable.chmod(0o755)
            environment = os.environ.copy()
            environment.update(
                {"SULDE_AGENT_PROVIDER": "codex", "SULDE_CODEX_EXE": str(executable)}
            )
            completed = subprocess.run(
                [
                    sys.executable,
                    str(RUNTIME),
                    "run",
                    str(worktree),
                    "authority-fail",
                    str(brief),
                    "--control-root",
                    str(control),
                    "--brief-sha256",
                    hashlib.sha256(brief.read_bytes()).hexdigest(),
                    "--task-definition",
                    str(task),
                    "--task-definition-sha256",
                    hashlib.sha256(task.read_bytes()).hexdigest(),
                    "--task-id",
                    "WRONG",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=environment,
                check=False,
            )

            self.assertEqual(completed.returncode, 2, completed.stdout + completed.stderr)
            self.assertFalse(marker.exists())
            self.assertFalse((worktree / ".codex-agent").exists())

    def test_task_authority_rejects_bad_digest_schema_base_and_path_bindings(self) -> None:
        cases = (
            "missing-cli-digest",
            "zero-cli-digest",
            "unrelated-cli-digest",
            "missing-v1-field",
            "extra-v1-field",
            "invalid-dependency",
            "invalid-evidence-gates",
            "base-substitution",
            "path-schema",
        )
        for case in cases:
            with self.subTest(case=case), self.temporary_directory() as directory_name:
                fixture = self.authority_fixture(Path(directory_name), f"binding-{case}")
                task = Path(fixture["task"])
                if case in {
                    "missing-v1-field",
                    "extra-v1-field",
                    "invalid-dependency",
                    "invalid-evidence-gates",
                    "base-substitution",
                    "path-schema",
                }:
                    value = json.loads(task.read_text(encoding="utf-8"))
                    if case == "missing-v1-field":
                        del value["owner"]
                    elif case == "extra-v1-field":
                        value["worktree"] = str(fixture["worktree"])
                    elif case == "invalid-dependency":
                        value["depends_on"] = ["T04"]
                    elif case == "invalid-evidence-gates":
                        del value["evidence_gates"]["system_verified"]
                    elif case == "base-substitution":
                        value["base_commit"] = "f" * 40
                    else:
                        value["owned_paths"] = ["base.txt/../outside.txt"]
                    task.write_text(
                        json.dumps(value, sort_keys=True) + "\n",
                        encoding="utf-8",
                    )
                command = self.authority_run_command(fixture)
                digest_index = command.index("--brief-sha256") + 1
                if case == "missing-cli-digest":
                    del command[digest_index]
                    del command[digest_index - 1]
                elif case == "zero-cli-digest":
                    command[digest_index] = "0" * 64
                elif case == "unrelated-cli-digest":
                    command[digest_index] = "f" * 64
                completed = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    env=dict(fixture["environment"]),
                    check=False,
                )

                self.assertEqual(completed.returncode, 2, completed.stdout + completed.stderr)
                self.assertFalse(Path(fixture["marker"]).exists())
                self.assertFalse((Path(fixture["worktree"]) / ".codex-agent").exists())

    def test_local_retry_missing_binding_fails_before_provider_events(self) -> None:
        with self.temporary_directory() as directory_name:
            fixture = self.authority_fixture(Path(directory_name), "missing-retry-binding")
            first = self.run_authority_fixture(fixture)
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            worktree = Path(fixture["worktree"])
            state = worktree / ".codex-agent"
            marker = Path(fixture["marker"])
            marker.unlink()
            events = state / "missing-retry-binding.events.jsonl"
            event_bytes = events.read_bytes()
            frozen_brief = state / "missing-retry-binding.brief.md"
            frozen_task = state / "missing-retry-binding.task.json"
            (state / "missing-retry-binding.task-binding.json").unlink()

            retry = subprocess.run(
                [
                    sys.executable,
                    str(RUNTIME),
                    "run",
                    str(worktree),
                    "missing-retry-binding",
                    str(frozen_brief),
                    "--control-root",
                    str(fixture["control"]),
                    "--brief-sha256",
                    hashlib.sha256(frozen_brief.read_bytes()).hexdigest(),
                    "--task-definition",
                    str(frozen_task),
                    "--task-definition-sha256",
                    hashlib.sha256(frozen_task.read_bytes()).hexdigest(),
                    "--task-id",
                    "T04",
                    "--timeout",
                    "5",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=dict(fixture["environment"]),
                check=False,
            )

            self.assertEqual(retry.returncode, 2, retry.stdout + retry.stderr)
            self.assertFalse(marker.exists())
            self.assertEqual(events.read_bytes(), event_bytes)

    def test_strict_verify_rejects_missing_contract_empty_paths_and_substitution(self) -> None:
        cases = (
            "missing-frozen-task",
            "missing-frozen-binding",
            "absent-report-contract",
            "empty-allowed-paths",
            "task-substitution",
            "brief-substitution",
            "worktree-substitution",
            "common-dir-substitution",
            "binding-worktree-substitution",
            "binding-common-dir-substitution",
            "binding-digest-drift",
            "run-binding-drift",
        )
        for case in cases:
            with self.subTest(case=case), self.temporary_directory() as directory_name:
                fixture = self.authority_fixture(Path(directory_name), f"strict-{case}")
                run = self.run_authority_fixture(fixture)
                self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
                worktree = Path(fixture["worktree"])
                state = worktree / ".codex-agent"
                slug = str(fixture["slug"])
                frozen_task = state / f"{slug}.task.json"
                frozen_brief = state / f"{slug}.brief.md"
                frozen_binding = state / f"{slug}.task-binding.json"
                expected_task_digest = hashlib.sha256(frozen_task.read_bytes()).hexdigest()
                expected_brief_digest = hashlib.sha256(frozen_brief.read_bytes()).hexdigest()
                expected_task_id = "T04"

                if case == "missing-frozen-task":
                    frozen_task.unlink()
                elif case == "missing-frozen-binding":
                    frozen_binding.unlink()
                elif case == "absent-report-contract":
                    guardian_path = state / f"{slug}.guardian.json"
                    guardian = json.loads(guardian_path.read_text(encoding="utf-8"))
                    del guardian["report_contract"]
                    guardian_path.write_text(
                        json.dumps(guardian, sort_keys=True) + "\n",
                        encoding="utf-8",
                    )
                elif case == "empty-allowed-paths":
                    intent_path = state / f"{slug}.intent.json"
                    intent = json.loads(intent_path.read_text(encoding="utf-8"))
                    intent["constraints"]["allowed_paths"] = []
                    intent_path.write_text(
                        json.dumps(intent, sort_keys=True) + "\n",
                        encoding="utf-8",
                    )
                elif case == "task-substitution":
                    substituted = json.loads(frozen_task.read_text(encoding="utf-8"))
                    substituted["task_id"] = "T05"
                    frozen_task.chmod(0o600)
                    frozen_task.write_text(
                        json.dumps(substituted, sort_keys=True) + "\n",
                        encoding="utf-8",
                    )
                    frozen_task.chmod(0o400)
                    expected_task_digest = hashlib.sha256(frozen_task.read_bytes()).hexdigest()
                elif case == "brief-substitution":
                    frozen_brief.chmod(0o600)
                    frozen_brief.write_text("# Substituted task\n", encoding="utf-8")
                    frozen_brief.chmod(0o400)
                    expected_brief_digest = hashlib.sha256(frozen_brief.read_bytes()).hexdigest()
                elif case in {"worktree-substitution", "common-dir-substitution"}:
                    guardian_path = state / f"{slug}.guardian.json"
                    guardian = json.loads(guardian_path.read_text(encoding="utf-8"))
                    key = "worktree" if case == "worktree-substitution" else "git_common_dir"
                    guardian["task_authority"][key] = "/unrelated/authority"
                    guardian_path.write_text(
                        json.dumps(guardian, sort_keys=True) + "\n",
                        encoding="utf-8",
                    )
                elif case in {
                    "binding-worktree-substitution",
                    "binding-common-dir-substitution",
                    "binding-digest-drift",
                }:
                    frozen_binding.chmod(0o600)
                    artifact = json.loads(frozen_binding.read_text(encoding="utf-8"))
                    if case == "binding-digest-drift":
                        artifact["binding_sha256"] = "0" * 64
                    else:
                        key = (
                            "worktree"
                            if case == "binding-worktree-substitution"
                            else "git_common_dir"
                        )
                        artifact["binding"][key]["path"] = "/unrelated/identity"
                        canonical = json.dumps(
                            artifact["binding"],
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        ).encode("utf-8")
                        artifact["binding_sha256"] = hashlib.sha256(canonical).hexdigest()
                    frozen_binding.write_text(
                        json.dumps(artifact, sort_keys=True) + "\n",
                        encoding="utf-8",
                    )
                    frozen_binding.chmod(0o400)
                elif case == "run-binding-drift":
                    ledger_path = state / f"{slug}.run.jsonl"
                    rows = [
                        json.loads(line)
                        for line in ledger_path.read_text(encoding="utf-8").splitlines()
                    ]
                    rows[0]["execution_binding_sha256"] = "0" * 64
                    ledger_path.write_text(
                        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
                        encoding="utf-8",
                    )

                verify = subprocess.run(
                    [
                        sys.executable,
                        str(RUNTIME),
                        "verify",
                        str(worktree),
                        slug,
                        "--brief-sha256",
                        expected_brief_digest,
                        "--task-definition-sha256",
                        expected_task_digest,
                        "--task-id",
                        expected_task_id,
                    ],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    check=False,
                )

                self.assertNotEqual(verify.returncode, 0, verify.stdout + verify.stderr)
                if case == "absent-report-contract":
                    self.assertIn("report contract", verify.stdout)
                if case == "empty-allowed-paths":
                    self.assertIn("intent allowed_paths", verify.stdout)

    def test_report_contract_requires_sedimentation_heading_and_strict_evidence(self) -> None:
        module = load_runtime_module()
        contract = module.report_contract_for_brief(
            "最终报告必须列出沉淀候选。"
        )
        self.assertEqual(contract["headings"][-1], "沉淀候选")
        self.assertEqual(
            contract["coordinator_evidence_fields"],
            [
                "contract_schema",
                "headings",
                "checks",
                "command",
                "exit_code",
                "observable_result",
                "candidate_sha256",
                "execution_binding_sha256",
                "environment_sha256",
                "command_sha256",
                "count",
            ],
        )
        self.assertTrue(
            module.has_check_evidence(
                "✅ 定向测试：`python3 -m unittest tests.test_x`，exit 0；17 tests OK"
            )
        )
        self.assertFalse(
            module.has_check_evidence(
                "✅ 定向测试：`python3 -m unittest tests.test_x`，exit 1；失败"
            )
        )
        self.assertFalse(module.has_check_evidence("✅ 已完成"))

    def test_task_report_verdict_accepts_only_consistent_complete_reports(self) -> None:
        module = load_runtime_module()
        contract = module.report_contract_for_brief("# Task\n\nDo the work.\n")

        passing = module.task_report_verdict(REPORT, contract)
        self.assertTrue(passing["passed"], passing)
        self.assertEqual(passing["failures"], [])
        self.assertEqual(passing["check_count"], 1)

        cases = {
            "explicit-failure": (
                REPORT.replace(
                    "## 过程",
                    "❌ 必需测试：`python -m unittest` exit 1，1 failure\n## 过程",
                ),
                "report contains 1 explicit failure check(s)",
            ),
            "no-check": (
                REPORT.replace(next(line for line in REPORT.splitlines() if line.startswith("✅")) + "\n", ""),
                "report has no evidenced ✅ completion check",
            ),
            "forged-exit": (
                REPORT.replace("exit 0", "exit 7"),
                "report records non-zero exit code(s): 7",
            ),
            "duplicate-heading": (
                "## 结果\n重复总结。\n" + REPORT,
                "report heading '结果' count=2, expected=1",
            ),
            "missing-heading": (
                REPORT.replace("## 解决方式\n", ""),
                "report heading '解决方式' count=0, expected=1",
            ),
            "partial": (
                REPORT.replace("任务完成。", "任务完成。\nstatus: partial"),
                "report declares incomplete state(s): partial",
            ),
            "blocked": (
                REPORT.replace("任务完成。", "任务完成。\noutcome: blocked"),
                "report declares incomplete state(s): blocked",
            ),
            "contradictory-summary": (
                REPORT.replace("任务完成。", "总结：成功\n总结：失败"),
                "report contains contradictory success and failure summaries",
            ),
            "failed-check-description": (
                REPORT.replace("无。", "必需测试失败。", 1),
                "report states that a required check failed",
            ),
        }
        for case, (report, reason) in cases.items():
            with self.subTest(case=case):
                verdict = module.task_report_verdict(report, contract)
                self.assertFalse(verdict["passed"], verdict)
                self.assertIn(reason, verdict["failures"])

    def test_managed_run_and_strict_verify_share_report_failure_reasons(
        self,
    ) -> None:
        with self.temporary_directory() as directory_name:
            directory = Path(directory_name)
            fixture = self.authority_fixture(directory, "report-failure")
            executable = Path(fixture["environment"]["SULDE_CODEX_EXE"])
            launches = directory / "provider-launches.txt"
            failed_report = REPORT.replace(
                "## 过程",
                "❌ 必需测试：`python -m unittest` exit 1，1 failure\n## 过程",
            )
            executable.write_text(
                textwrap.dedent(
                    f"""\
                    #!/usr/bin/python3
                    import sys
                    from pathlib import Path
                    launches = Path({str(launches)!r})
                    launches.write_text(
                        (
                            launches.read_text() + 'launch\\n'
                            if launches.exists()
                            else 'launch\\n'
                        ),
                        encoding='utf-8',
                    )
                    args = sys.argv[1:]
                    Path(args[args.index('--output-last-message') + 1]).write_text(
                        {failed_report!r}, encoding='utf-8'
                    )
                    print('{{"type":"done"}}')
                    """
                ),
                encoding="utf-8",
            )
            executable.chmod(0o755)

            run = self.run_authority_fixture(fixture)
            self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
            state = Path(fixture["worktree"]) / ".codex-agent"
            status = (state / "report-failure.status").read_text(encoding="utf-8")
            self.assertTrue(status.startswith("status=failed rc=0 "), status)
            self.assertIn("report_verdict=failed", status)
            self.assertEqual(launches.read_text(encoding="utf-8"), "launch\n")
            self.assertEqual(
                (state / "report-failure.last.md").read_text(encoding="utf-8"),
                failed_report,
            )
            self.assertTrue((state / "report-failure.stderr.log").is_file())
            guardian = json.loads(
                (state / "report-failure.guardian.json").read_text(encoding="utf-8")
            )
            self.assertEqual(guardian["execution"]["returncode"], 0)
            self.assertTrue(guardian["execution"]["cleanup_quiescent"])
            self.assertFalse(guardian["task_report_verdict"]["passed"])
            self.assertEqual(guardian["approvals_open"], 0)
            report_reasons = guardian["task_report_verdict"]["failures"]
            self.assertTrue(report_reasons)
            ledger = [
                json.loads(line)
                for line in (state / "report-failure.run.jsonl").read_text(
                    encoding="utf-8"
                ).splitlines()
            ]
            provider_result = next(
                row for row in ledger if row["type"] == "execution.result"
            )
            provider_disposed = next(
                row for row in ledger if row["type"] == "execution.disposed"
            )
            self.assertEqual(provider_result["returncode"], 0)
            self.assertTrue(provider_disposed["quiescent"])

            task = Path(fixture["task"])
            verify = subprocess.run(
                [
                    sys.executable,
                    str(RUNTIME),
                    "verify",
                    str(fixture["worktree"]),
                    "report-failure",
                    "--brief-sha256",
                    str(fixture["brief_digest"]),
                    "--task-definition-sha256",
                    hashlib.sha256(task.read_bytes()).hexdigest(),
                    "--task-id",
                    "T04",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=dict(fixture["environment"]),
                check=False,
            )
            self.assertEqual(verify.returncode, 1, verify.stdout + verify.stderr)
            for reason in report_reasons:
                self.assertIn(f"REPORT VERDICT: FAIL: {reason}", run.stdout)
                self.assertIn(f"FAIL: {reason}", verify.stdout)
            self.assertEqual(launches.read_text(encoding="utf-8"), "launch\n")

    def test_strict_verify_rejects_missing_required_sedimentation_section(self) -> None:
        with self.temporary_directory() as directory_name:
            directory = Path(directory_name)
            worktree, brief = self.prepare(directory, "sedimentation-report")
            brief.chmod(0o600)
            brief.write_text(
                "# Task\n\n最终报告必须列出沉淀候选。\n",
                encoding="utf-8",
            )
            brief.chmod(0o400)
            executable = directory / "codex"
            executable.write_text(
                textwrap.dedent(
                    f"""\
                    #!/usr/bin/python3
                    import sys
                    from pathlib import Path
                    args = sys.argv[1:]
                    Path(args[args.index('--output-last-message') + 1]).write_text(
                        {REPORT!r}, encoding='utf-8'
                    )
                    print('{{"type":"done"}}')
                    """
                ),
                encoding="utf-8",
            )
            executable.chmod(0o755)
            environment = os.environ.copy()
            environment.update(
                {"SULDE_AGENT_PROVIDER": "codex", "SULDE_CODEX_EXE": str(executable)}
            )
            run = subprocess.run(
                [
                    sys.executable,
                    str(RUNTIME),
                    "run",
                    str(worktree),
                    "sedimentation-report",
                    str(brief),
                    "--owned-path",
                    "base.txt",
                    "--timeout",
                    "5",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=environment,
                check=False,
            )
            self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
            reason = "report heading '沉淀候选' count=0, expected=1"
            self.assertIn(f"REPORT VERDICT: FAIL: {reason}", run.stdout)
            verify = subprocess.run(
                [
                    sys.executable,
                    str(RUNTIME),
                    "verify",
                    str(worktree),
                    "sedimentation-report",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )

            self.assertEqual(verify.returncode, 1, verify.stdout + verify.stderr)
            self.assertIn(f"FAIL: {reason}", verify.stdout)

    def test_verify_rechecks_local_brief_security_before_reading_report(self) -> None:
        with self.temporary_directory() as directory_name:
            directory = Path(directory_name)
            worktree, brief = self.prepare(directory, "verify-brief")
            canonical = worktree / ".codex-agent/verify-brief.brief.md"
            canonical.write_bytes(brief.read_bytes())
            canonical.chmod(0o400)
            canonical.chmod(0o600)
            alias_target = directory / "replacement.md"
            alias_target.write_text("# replacement\n", encoding="utf-8")
            canonical.unlink()
            canonical.symlink_to(alias_target)
            verify = subprocess.run(
                [
                    sys.executable,
                    str(RUNTIME),
                    "verify",
                    str(worktree),
                    "verify-brief",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )

            self.assertEqual(verify.returncode, 2, verify.stdout + verify.stderr)
            self.assertIn("not a regular file", verify.stderr)
            self.assertTrue(canonical.is_symlink())

    def test_codex_profile_is_exact_and_never_composes_with_legacy_sandbox(self) -> None:
        module = load_runtime_module()
        command = module.codex_profile_command(
            ["codex", "exec", "--sandbox", "workspace-write", "--json", "-"],
            ["scripts/kb/agent-runtime.py", "scripts/kb/audit_cursor.py"],
        )
        rendered = " ".join(command)
        self.assertNotIn("--sandbox", command)
        self.assertNotIn("sandbox_mode", rendered)
        self.assertIn('default_permissions="sulde-owned-paths"', command)
        self.assertIn('":tmpdir"="deny"', rendered)
        self.assertIn('":slash_tmp"="deny"', rendered)
        self.assertIn("network={enabled=false}", rendered)
        self.assertIn('"scripts/kb/audit_cursor.py"="write"', rendered)
        self.assertNotIn('"tests/unowned.py"="write"', rendered)
        self.assertGreater(command.index("--ignore-user-config"), command.index("exec"))
        self.assertGreater(command.index("--strict-config"), command.index("exec"))
        with self.assertRaises(module.AgentRuntimeError):
            module._canonical_owned_path("scripts/kb/../outside.py")
        self.assertEqual(module._canonical_owned_path("scripts/kb/**"), "scripts/kb/**")
        with self.assertRaises(module.AgentRuntimeError):
            module._canonical_owned_path("scripts/*/owned.py")

    def test_runtime_and_broker_share_exact_profile_renderer_bytes(self) -> None:
        module = load_runtime_module()
        owned = ["scripts/kb/agent-runtime.py", "tests/test_agent_runtime.py"]
        self.assertEqual(
            module.codex_permission_config(owned),
            module.native_agent_broker.render_permission_profile_arguments(owned),
        )
        with self.temporary_directory() as directory_name:
            root = Path(directory_name).resolve()
            (root / ".git").mkdir()
            for relative in owned:
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.touch()
            self.assertEqual(
                module.permission_profile_bytes(
                    owned, worktree=root, git_common_dir=root / ".git"
                ),
                module.native_agent_broker.permission_profile_bytes(
                    owned, worktree=str(root)
                ),
            )

    def test_full_clone_profile_has_only_lexical_workspace_and_owned_writes(self) -> None:
        module = load_runtime_module()
        with self.temporary_directory() as directory_name:
            directory = Path(directory_name)
            worktree = (directory / "full-clone").resolve()
            common = worktree / ".git"
            worktree.mkdir()
            common.mkdir()
            (worktree / "owned.py").touch()
            rendered = " ".join(
                module.codex_permission_config(
                    ["owned.py"],
                    worktree=worktree,
                    git_common_dir=common,
                )
            )
        self.assertEqual(rendered.count('"."="read"'), 1)
        self.assertIn('"owned.py"="write"', rendered)
        self.assertNotIn(str(worktree), rendered)
        self.assertNotIn(str(common), rendered)

    def test_repository_full_clone_git_read_probe_remains_available(self) -> None:
        module = load_runtime_module()
        with self.temporary_directory() as directory_name, mock.patch.dict(
            os.environ,
            {
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_GLOBAL": "/dev/null",
                "XDG_CONFIG_HOME": str(Path(directory_name) / "xdg"),
            },
        ):
            common = module._git_common_directory(ROOT, test_mode=False)
            probe = subprocess.run(
                ["git", "-C", str(ROOT), "rev-parse", "--git-common-dir"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            self.assertEqual(probe.returncode, 0, probe.stderr)
            expected = Path(probe.stdout.strip())
            if not expected.is_absolute():
                expected = ROOT / expected
            self.assertEqual(common, str(expected.resolve()))
            self.assertEqual(
                module._git_probe(ROOT, "rev-parse", "--is-inside-work-tree"),
                "true",
            )

    def test_linked_or_external_git_common_dir_fails_once_before_codex(self) -> None:
        module = load_runtime_module()
        with self.temporary_directory() as directory_name:
            directory = Path(directory_name).resolve()
            worktree = directory / "linked"
            external = directory / "external-common"
            worktree.mkdir()
            external.mkdir()
            (worktree / "owned.py").touch()
            with (
                mock.patch.object(module.subprocess, "run") as provider,
                self.assertRaisesRegex(
                    module.CodexGitLayoutError,
                    "coordinator must create a full clone",
                ) as raised,
            ):
                module.codex_permission_config(
                    ["owned.py"],
                    worktree=worktree,
                    git_common_dir=external,
                )
        self.assertEqual(provider.call_count, 0)
        diagnostic = str(raised.exception)
        self.assertNotIn("policy_pause", diagnostic)
        self.assertNotIn("effect debt", diagnostic)
        self.assertNotIn("awaiting-human", diagnostic)

    def test_terminal_owned_subtree_may_be_created_but_missing_parent_and_alias_fail(self) -> None:
        module = load_runtime_module()
        with self.temporary_directory() as directory_name:
            root = Path(directory_name).resolve()
            (root / "scripts").mkdir()
            module._validate_owned_path_against_worktree(
                root, "scripts/generated/**"
            )
            with self.assertRaisesRegex(module.AgentRuntimeError, "parent is unavailable"):
                module._validate_owned_path_against_worktree(
                    root, "missing/generated/**"
                )
            (root / "outside").mkdir()
            (root / "scripts/alias").symlink_to(root / "outside")
            with self.assertRaisesRegex(module.AgentRuntimeError, "symlink"):
                module._validate_owned_path_against_worktree(
                    root, "scripts/alias/**"
                )

    def test_standard_diagnostic_devices_are_bounded_read_events_only(self) -> None:
        module = load_runtime_module()
        for target in ("/dev/stdout", "/dev/stderr", "/dev/fd/1", "/dev/fd/2"):
            event = module._bounded_diagnostic_stream_event(
                {"effect": "local_write", "write_targets": [target], "target": target}
            )
            self.assertEqual(event["effect"], "read")
            self.assertEqual(event["diagnostic_streams"], [target])
            self.assertNotIn("write_targets", event)
        for target in ("/dev/fd/3", "/dev/console", "/dev//stdout", "/dev/stdout/file"):
            event = {"effect": "local_write", "write_targets": [target], "target": target}
            self.assertEqual(module._bounded_diagnostic_stream_event(event), event)
        mixed = {
            "effect": "local_write",
            "write_targets": ["/dev/stdout", "outside.txt"],
        }
        self.assertEqual(module._bounded_diagnostic_stream_event(mixed), mixed)

    def test_runtime_tree_digest_matches_installer_path_length_algorithm(self) -> None:
        module = load_runtime_module()
        with self.temporary_directory() as directory_name:
            root = Path(directory_name)
            (root / "nested").mkdir()
            (root / "a.txt").write_bytes(b"alpha")
            (root / "nested/b.txt").write_bytes(b"beta")
            digest = hashlib.sha256()
            for path in sorted(root.rglob("*")):
                if not path.is_file():
                    continue
                relative = path.relative_to(root).as_posix().encode("utf-8")
                digest.update(len(relative).to_bytes(8, "big"))
                digest.update(relative)
                digest.update(path.read_bytes())
            self.assertEqual(
                module._installed_runtime_tree_sha256(root), digest.hexdigest()
            )

    def test_phase_heartbeat_rejects_duplicate_regression_and_expiry(self) -> None:
        module = load_runtime_module()

        def row(sequence, observed, *, terminal=False):
            expires = None if terminal else observed + 5_000_000_000
            return {
                "schema": module.HEARTBEAT_SCHEMA,
                "run_id": "run-heartbeat",
                "phase_sequence": sequence,
                "phase": "provider_running" if not terminal else "run_finalized",
                "reason": "",
                "observed_monotonic_ns": observed,
                "age_ns": 0,
                "expires_after_ns": None if terminal else 5_000_000_000,
                "expires_monotonic_ns": expires,
                "expired": False,
                "default_action": "none" if terminal else "interrupt_and_fail_closed",
                "terminal": terminal,
            }

        first = row(1, 10)
        second = row(2, 20)
        current = module.validate_phase_heartbeat_rows(
            [first, second], now_monotonic_ns=30
        )
        self.assertEqual(current["age_ns"], 10)
        with self.assertRaisesRegex(module.AgentRuntimeError, "sequence"):
            module.validate_phase_heartbeat_rows([first, {**second, "phase_sequence": 1}])
        with self.assertRaisesRegex(module.AgentRuntimeError, "monotonic"):
            module.validate_phase_heartbeat_rows(
                [first, {**second, "observed_monotonic_ns": 9, "expires_monotonic_ns": 5_000_000_009}]
            )
        with self.assertRaisesRegex(module.AgentRuntimeError, "expired"):
            module.validate_phase_heartbeat_rows(
                [first], now_monotonic_ns=5_000_000_010, require_live=True
            )
        terminal = row(2, 20, terminal=True)
        self.assertTrue(
            module.validate_phase_heartbeat_rows(
                [first, terminal], now_monotonic_ns=10_000_000_000
            )["terminal"]
        )

    def test_phase_heartbeat_persists_incrementing_result_disposed_terminal_order(self) -> None:
        module = load_runtime_module()
        with self.temporary_directory() as directory_name:
            root = Path(directory_name)
            heartbeat = module.PhaseHeartbeat(
                root / "current.json", root / "history.jsonl", run_id="run-order"
            )
            with mock.patch.object(
                module.time,
                "monotonic_ns",
                side_effect=[10, 20, 30, 40],
            ):
                heartbeat.publish("provider_running")
                heartbeat.publish("result_persisted", reason="policy_paused")
                heartbeat.publish("disposed", reason="quiescent")
                heartbeat.publish("run_finalized", reason="paused", terminal=True)
            rows = [
                json.loads(line)
                for line in (root / "history.jsonl").read_text(
                    encoding="utf-8"
                ).splitlines()
            ]
            current = json.loads((root / "current.json").read_text(encoding="utf-8"))
        self.assertEqual([row["phase_sequence"] for row in rows], [1, 2, 3, 4])
        self.assertLess(
            [row["phase"] for row in rows].index("result_persisted"),
            [row["phase"] for row in rows].index("disposed"),
        )
        self.assertTrue(current["terminal"])
        self.assertEqual(current["default_action"], "none")

    def test_local_interruption_ledger_requires_result_before_quiescent_disposed(self) -> None:
        module = load_runtime_module()
        with self.temporary_directory() as directory_name:
            path = Path(directory_name) / "run.jsonl"
            rows = [
                {"run_id": "run-one", "type": "execution.started"},
                {
                    "run_id": "run-one",
                    "type": "execution.interrupt_requested",
                    "reason": "paused",
                },
                {
                    "run_id": "run-one",
                    "type": "execution.result",
                    "stop_reason": "policy_paused",
                    "returncode": 0,
                },
                {
                    "run_id": "run-one",
                    "type": "execution.disposed",
                    "quiescent": True,
                },
            ]

            def write(candidate):
                path.write_text(
                    "".join(json.dumps(item) + "\n" for item in candidate),
                    encoding="utf-8",
                )

            write(rows)
            evidence = module._run_ledger_local_interruption_evidence(
                path, run_id="run-one"
            )
            self.assertTrue(evidence["result_before_disposed"])
            self.assertTrue(evidence["quiescent"])
            for candidate in (
                [rows[0], rows[1], rows[3]],
                [rows[0], rows[1], rows[3], rows[2]],
                [*rows[:-1], {**rows[-1], "quiescent": False}],
            ):
                write(candidate)
                with self.assertRaises(module.AgentRuntimeError):
                    module._run_ledger_local_interruption_evidence(
                        path, run_id="run-one"
                    )

    def test_canonical_provider_final_bytes_preserve_body_and_require_one_terminal_lf(self) -> None:
        module = load_runtime_module()
        self.assertEqual(module._canonical_provider_final_bytes("正文"), "正文\n".encode())
        self.assertEqual(module._canonical_provider_final_bytes("a\r\nb\n"), b"a\r\nb\n")
        for value in ("body\n\n", "body\r", "body\r\n", "body\n\n\n", "\ud800"):
            with self.subTest(value=repr(value)), self.assertRaises(module.AgentRuntimeError):
                module._canonical_provider_final_bytes(value)
        for value in (b"body", None, True):
            with self.subTest(value=value), self.assertRaises(module.AgentRuntimeError):
                module._canonical_provider_final_bytes(value)

    def test_production_settle_canonicalizes_before_run_ledger_output(self) -> None:
        module = load_runtime_module()

        class RecordingHandle:
            def __init__(self) -> None:
                self.calls = []

            def settle(self, *, stop_reason, output=""):
                self.calls.append((stop_reason, output))
                return module.SimpleNamespace(
                    output_present=bool(output),
                    output_sha256=hashlib.sha256(output.encode("utf-8")).hexdigest(),
                )

        with self.temporary_directory() as directory_name:
            root = Path(directory_name)
            state = root / ".codex-agent"
            state.mkdir()
            last = state / "canonical.last.md"
            last.write_bytes(b"body")
            handle = RecordingHandle()
            result, final_message = module._settle_provider_result(
                handle,
                provider="codex",
                test_mode=False,
                root=root,
                report=last,
                observed_status="running",
                returncode=0,
                streamed_final_message="stale",
            )
            self.assertEqual(final_message, "body\n")
            self.assertEqual(handle.calls, [("completed", "body\n")])
            self.assertEqual(result.output_sha256, hashlib.sha256(b"body\n").hexdigest())

    def test_production_local_interruption_allows_absent_output(self) -> None:
        module = load_runtime_module()

        class RecordingHandle:
            def __init__(self) -> None:
                self.calls = []

            def settle(self, *, stop_reason, output=""):
                self.calls.append((stop_reason, output))
                return module.SimpleNamespace(output_present=bool(output))

        with self.temporary_directory() as directory_name:
            root = Path(directory_name)
            (root / ".codex-agent").mkdir()
            handle = RecordingHandle()
            result, final_message = module._settle_provider_result(
                handle,
                provider="codex",
                test_mode=False,
                root=root,
                report=root / ".codex-agent/missing.last.md",
                observed_status="awaiting_human",
                returncode=0,
                streamed_final_message="partial provider stream",
            )
            self.assertFalse(result.output_present)
            self.assertEqual(final_message, "")
            self.assertEqual(handle.calls, [("awaiting_human", "")])

    def test_relative_reader_binds_root_dirfd_before_return(self) -> None:
        module = load_runtime_module()
        with self.temporary_directory() as directory_name:
            base = Path(directory_name)
            root = base / "root"
            parked = base / "parked"
            replacement = base / "replacement"
            (root / "parent").mkdir(parents=True)
            (replacement / "parent").mkdir(parents=True)
            (root / "parent/report.md").write_bytes(b"trusted")
            (replacement / "parent/report.md").write_bytes(b"attacker")
            real_open = module.os.open
            swapped = False

            def swap(path, flags, mode=0o777, *, dir_fd=None):
                nonlocal swapped
                if not swapped and dir_fd is None and Path(path) == root.resolve():
                    swapped = True
                    root.rename(parked)
                    replacement.rename(root)
                return real_open(path, flags, mode, dir_fd=dir_fd)

            with (
                mock.patch.object(module.os, "open", side_effect=swap),
                self.assertRaisesRegex(module.AgentRuntimeError, "root changed before open"),
            ):
                module._read_relative_regular_file(root, "parent/report.md", label="root swap")

    def test_default_tmpdir_alias_uses_one_physical_identity_layer(self) -> None:
        module = load_runtime_module()
        with self.temporary_directory() as directory_name:
            lexical_root = Path(directory_name)
            physical_root = lexical_root.resolve()
            state = physical_root / ".codex-agent"
            state.mkdir()
            last = state / "task.last.md"
            last.write_bytes(b"report\n")
            self.assertEqual(
                module._read_codex_output_last_message(lexical_root, last),
                "report\n",
            )
    def test_durable_report_authority_fails_closed_for_path_and_file_drift(self) -> None:
        module = load_runtime_module()
        relative = "guardian-r2-program/reports/task.md"

        for supported in (
            relative,
            "guardian-program/reports/task.md",
            "life-program/reports/task.md",
        ):
            with self.subTest(supported=supported):
                self.assertEqual(
                    module._durable_worker_report_relative_path(
                        ["owned.py", supported]
                    ),
                    supported,
                )
        with self.assertRaisesRegex(
            module.AgentRuntimeError, "exactly one supported program"
        ):
            module._durable_worker_report_relative_path(
                ["arbitrary-program/reports/task.md"]
            )

        with self.temporary_directory() as directory_name:
            root = Path(directory_name)
            report = root / relative
            report.parent.mkdir(parents=True)
            (root / ".codex-agent").mkdir()
            last = root / ".codex-agent/task.last.md"
            canonical = "## 结果\n完成。\n"
            report.write_text(canonical, encoding="utf-8")
            self.assertEqual(
                module._close_canonical_worker_report_authority(
                    root, ["owned.py", relative], canonical[:-1], last
                ),
                canonical.encode(),
            )
            self.assertEqual(last.read_bytes(), canonical.encode())

            report.write_text(canonical + "漂移\n", encoding="utf-8")
            with self.assertRaisesRegex(module.AgentRuntimeError, "does not equal"):
                module._close_canonical_worker_report_authority(
                    root, [relative], canonical, last
                )

            for owned in (
                [],
                ["owned.py"],
                [relative, "guardian-r2-program/reports/other.md"],
                ["/guardian-r2-program/reports/task.md"],
                ["guardian-r2-program/reports/../task.md"],
            ):
                with self.subTest(owned=owned), self.assertRaises(module.AgentRuntimeError):
                    module._durable_worker_report_relative_path(owned)

            report.unlink()
            with self.assertRaisesRegex(module.AgentRuntimeError, "cannot be opened"):
                module._read_durable_worker_report(root, [relative])
            report.mkdir()
            with self.assertRaises(module.AgentRuntimeError):
                module._read_durable_worker_report(root, [relative])
            report.rmdir()
            target = root / "target.md"
            target.write_text(canonical, encoding="utf-8")
            report.symlink_to(target)
            with self.assertRaisesRegex(module.AgentRuntimeError, "symlink"):
                module._read_durable_worker_report(root, [relative])

    def test_report_closure_visibility_race_is_bounded_and_stable(self) -> None:
        module = load_runtime_module()
        relative = "guardian-r2-program/reports/task.md"
        for scenario in ("settle", "persistent", "late", "replace", "symlink",
                         "parent", "mutate_after_match", "rewrite_same_bytes"):
            with self.subTest(scenario=scenario), self.temporary_directory() as directory:
                root = Path(directory)
                durable = root / relative
                durable.parent.mkdir(parents=True)
                durable.write_bytes(b"old\n")
                (root / ".codex-agent").mkdir()
                last = root / ".codex-agent/task.last.md"
                clock = [0.0]
                sleeps = []

                def tick(delay):
                    sleeps.append(delay)
                    clock[0] += delay
                    if len(sleeps) == 1:
                        if scenario == "settle":
                            durable.write_bytes(b"canonical\n")
                        elif scenario == "late":
                            clock[0] = 1.0
                            durable.write_bytes(b"canonical\n")
                        elif scenario == "replace":
                            durable.rename(durable.with_suffix(".old"))
                            durable.write_bytes(b"canonical\n")
                        elif scenario == "symlink":
                            target = root / "target.md"
                            target.write_bytes(b"canonical\n")
                            durable.unlink()
                            durable.symlink_to(target)
                        elif scenario == "parent":
                            durable.parent.rename(root / "old-reports")
                            durable.parent.mkdir()
                            durable.write_bytes(b"canonical\n")
                        elif scenario in ("mutate_after_match", "rewrite_same_bytes"):
                            durable.write_bytes(b"canonical\n")
                    elif len(sleeps) == 2:
                        if scenario == "mutate_after_match":
                            durable.write_bytes(b"drift\n")
                        elif scenario == "rewrite_same_bytes":
                            durable.write_bytes(b"canonical\n")
                            metadata = durable.stat()
                            os.utime(durable, ns=(metadata.st_atime_ns,
                                                 metadata.st_mtime_ns + 1_000_000))

                with (
                    mock.patch.object(module.time, "monotonic", side_effect=lambda: clock[0]),
                    mock.patch.object(module.time, "sleep", side_effect=tick),
                ):
                    if scenario == "settle":
                        self.assertEqual(module._close_canonical_worker_report_authority(
                            root, [relative], "canonical", last,
                        ), b"canonical\n")
                        self.assertEqual(last.read_bytes(), b"canonical\n")
                        self.assertEqual(durable.read_bytes(), b"canonical\n")
                        self.assertEqual(len(sleeps), 2)
                    else:
                        with self.assertRaises(module.AgentRuntimeError):
                            module._close_canonical_worker_report_authority(
                                root, [relative], "canonical", last,
                            )
                        self.assertFalse(last.exists())
                        if scenario == "persistent":
                            self.assertEqual(durable.read_bytes(), b"old\n")
                    self.assertLessEqual(len(sleeps), 10)
                    self.assertLessEqual(sum(sleeps), 0.201)

    def test_report_closure_does_not_retry_mutation_during_read(self) -> None:
        module = load_runtime_module()
        relative = "guardian-r2-program/reports/task.md"
        with self.temporary_directory() as directory:
            root = Path(directory)
            durable = root / relative
            durable.parent.mkdir(parents=True)
            durable.write_bytes(b"old\n")
            (root / ".codex-agent").mkdir()
            real_read = module.os.read

            def mutate(descriptor, size):
                data = real_read(descriptor, size)
                durable.write_bytes(b"canonical\n")
                return data

            with (
                mock.patch.object(module.os, "read", side_effect=mutate),
                mock.patch.object(module.time, "sleep") as sleep,
                self.assertRaisesRegex(module.AgentRuntimeError, "changed while being read"),
            ):
                module._close_canonical_worker_report_authority(
                    root, [relative], "canonical", root / ".codex-agent/task.last.md",
                )
            sleep.assert_not_called()

    def test_report_closure_rejects_identical_replacement_after_persist(self) -> None:
        module = load_runtime_module()
        relative = "guardian-r2-program/reports/task.md"
        with self.temporary_directory() as directory:
            root = Path(directory)
            durable = root / relative
            durable.parent.mkdir(parents=True)
            durable.write_bytes(b"canonical\n")
            (root / ".codex-agent").mkdir()
            real_persist = module._persist_canonical_worker_report

            def replace(*args):
                result = real_persist(*args)
                durable.rename(durable.with_suffix(".old"))
                durable.write_bytes(result)
                return result

            with (
                mock.patch.object(module, "_persist_canonical_worker_report", side_effect=replace),
                self.assertRaisesRegex(module.AgentRuntimeError, "changed during closure"),
            ):
                module._close_canonical_worker_report_authority(
                    root, [relative], "canonical", root / ".codex-agent/task.last.md",
                )

    def test_canonical_report_atomic_write_readback_detects_drift(self) -> None:
        module = load_runtime_module()
        with self.temporary_directory() as directory_name:
            root = Path(directory_name)
            report = root / "guardian-r2-program/reports/task.md"
            report.parent.mkdir(parents=True)
            report.write_bytes(b"report\n")
            (root / ".codex-agent").mkdir()
            last = root / ".codex-agent/task.last.md"

            real_rename = module.os.rename

            def replace_after_rename(
                source, target, *, src_dir_fd=None, dst_dir_fd=None
            ):
                result = real_rename(
                    source,
                    target,
                    src_dir_fd=src_dir_fd,
                    dst_dir_fd=dst_dir_fd,
                )
                os.unlink(target, dir_fd=dst_dir_fd)
                descriptor = os.open(
                    target,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o600,
                    dir_fd=dst_dir_fd,
                )
                os.write(descriptor, b"drift")
                os.close(descriptor)
                return result

            with (
                mock.patch.object(module.os, "rename", side_effect=replace_after_rename),
                self.assertRaisesRegex(module.AgentRuntimeError, "replaced after rename"),
            ):
                module._close_canonical_worker_report_authority(
                    root,
                    ["guardian-r2-program/reports/task.md"],
                    "report",
                    last,
                )


    def test_canonical_writer_parent_swap_has_no_external_write(self) -> None:
        module = load_runtime_module()
        with self.temporary_directory() as directory_name:
            root = Path(directory_name)
            state = root / ".codex-agent"
            state.mkdir()
            outside = root / "outside"
            outside.mkdir()
            real_open = module.os.open
            swapped = False

            def swap(path, flags, mode=0o777, *, dir_fd=None):
                nonlocal swapped
                if not swapped and dir_fd is not None and path == ".codex-agent":
                    swapped = True
                    state.rename(root / "parked-state")
                    state.symlink_to(outside, target_is_directory=True)
                return real_open(path, flags, mode, dir_fd=dir_fd)

            with (
                mock.patch.object(module.os, "open", side_effect=swap),
                self.assertRaises(module.AgentRuntimeError),
            ):
                module._persist_canonical_worker_report(
                    root,
                    state / "task.last.md",
                    b"canonical\n",
                )
            self.assertEqual(list(outside.iterdir()), [])

    def test_durable_report_replacement_during_closure_fails(self) -> None:
        module = load_runtime_module()
        relative = "guardian-r2-program/reports/task.md"
        with self.temporary_directory() as directory_name:
            root = Path(directory_name)
            durable = root / relative
            durable.parent.mkdir(parents=True)
            durable.write_bytes(b"report\n")
            state = root / ".codex-agent"
            state.mkdir()
            last = state / "task.last.md"
            real_persist = module._persist_canonical_worker_report

            def replace_durable(*args, **kwargs):
                result = real_persist(*args, **kwargs)
                durable.unlink()
                durable.write_bytes(b"attacker\n")
                return result

            with (
                mock.patch.object(
                    module,
                    "_persist_canonical_worker_report",
                    side_effect=replace_durable,
                ),
                self.assertRaisesRegex(
                    module.AgentRuntimeError,
                    "durable worker report changed",
                ),
            ):
                module._close_canonical_worker_report_authority(
                    root,
                    [relative],
                    "report",
                    last,
                )
    def test_provider_jsonl_allows_zero_only_for_later_local_domain_and_rejects_multiple(self) -> None:
        module = load_runtime_module()
        with self.temporary_directory() as directory_name:
            path = Path(directory_name) / "events.jsonl"
            path.write_text('{"type":"item.completed"}\n', encoding="utf-8")
            summary = module._broker_jsonl_summary(path)
            self.assertEqual(summary["terminal_event"], "none")
            self.assertEqual(summary["terminal_event_count"], 0)
            path.write_text(
                '{"type":"turn.completed"}\n{"type":"turn.failed"}\n',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(module.AgentRuntimeError, "contradictory"):
                module._broker_jsonl_summary(path)

    def test_app_server_initialize_waits_for_response_before_notification(self) -> None:
        module = load_runtime_module()
        with self.temporary_directory() as directory_name:
            executable = Path(directory_name) / "app-server-fixture"
            executable.write_text(
                textwrap.dedent(
                    """\
                    #!/usr/bin/env python3
                    import json
                    import sys
                    request = json.loads(sys.stdin.readline())
                    print(json.dumps({"id": request["id"], "result": {"ready": True}}), flush=True)
                    notification = json.loads(sys.stdin.readline())
                    if notification.get("method") != "initialized":
                        raise SystemExit(3)
                    """
                ),
                encoding="utf-8",
            )
            executable.chmod(0o755)
            completed = module._codex_app_server_initialize(
                [str(executable)],
                initialize_request=(
                    '{"method":"initialize","id":0,"params":{}}\n'
                ),
                initialized_notification=(
                    '{"method":"initialized","params":{}}\n'
                ),
                cwd=Path(directory_name),
                environment=os.environ.copy(),
                timeout=3,
            )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn('"id": 0', completed.stdout)

    def test_codex_preflight_requires_profile_parse_and_app_server_handshake(self) -> None:
        module = load_runtime_module()
        responses = [
            subprocess.CompletedProcess(
                ["codex", "--version"], 0, module.AUDITED_CODEX_VERSION + "\n", ""
            ),
            subprocess.CompletedProcess(
                ["codex", "--help"],
                0,
                "--config --strict-config\n",
                sys.modules[
                    module.successful_version_identity.__module__
                ].CODEX_PATH_ALIAS_PERMISSION_WARNING,
            ),
            subprocess.CompletedProcess(
                ["codex", "exec", "--help"],
                0,
                "--ignore-user-config --ignore-rules --dangerously-bypass-hook-trust "
                "--config --strict-config\n",
                "",
            ),
            subprocess.CompletedProcess(
                ["codex", "app-server", "--help"],
                0,
                "--config --strict-config --listen\n",
                "",
            ),
            subprocess.CompletedProcess(["codex", "exec"], 0, "", ""),
            subprocess.CompletedProcess(
                ["codex", "app-server"],
                0,
                '{"id":0,"result":{"platformFamily":"unix"}}\n',
                "",
            ),
        ]
        bootstrap_response = responses.pop()
        with (
            mock.patch.object(module.subprocess, "run", side_effect=responses) as run,
            mock.patch.object(
                module,
                "_codex_app_server_initialize",
                return_value=bootstrap_response,
            ) as initialize,
        ):
            with mock.patch.dict(
                os.environ,
                {"TERM": "xterm-256color", "CLICOLOR_FORCE": "1"},
                clear=False,
            ):
                caller_term = os.environ["TERM"]
                caller_force_color = os.environ["CLICOLOR_FORCE"]
                result = self.synthetic_preflight(module,
                    str(self.codex_path),
                    module.codex_permission_config(["owned.py"]),
                    test_mode=False,
                )
                self.assertEqual(os.environ["TERM"], caller_term)
                self.assertEqual(os.environ["CLICOLOR_FORCE"], caller_force_color)

        self.assertTrue(result["supported"])
        self.assertIn("app-server-initialize", result["evidence"])
        for probe_call in run.call_args_list[:5]:
            self.assertEqual(probe_call.kwargs["input"], "")
            self.assertEqual(probe_call.kwargs["env"]["TERM"], "dumb")
            self.assertEqual(probe_call.kwargs["env"]["NO_COLOR"], "1")
            self.assertEqual(probe_call.kwargs["env"]["CLICOLOR_FORCE"], "0")
        exec_probe = run.call_args_list[4]
        self.assertEqual(
            exec_probe.args[0][:2],
            [str(self.codex_path), "exec"],
        )
        self.assertGreater(
            exec_probe.args[0].index("--ignore-user-config"),
            exec_probe.args[0].index("exec"),
        )
        bootstrap = initialize.call_args
        self.assertEqual(run.call_count, 5)
        self.assertEqual(initialize.call_count, 1)
        self.assertIn("app-server", bootstrap.args[0])
        self.assertEqual(
            bootstrap.args[0][:2],
            [str(self.codex_path), "app-server"],
        )
        self.assertNotIn("--ignore-user-config", bootstrap.args[0])
        self.assertIn(
            '"method":"initialize"',
            bootstrap.kwargs["initialize_request"],
        )
        self.assertIn(
            '"method":"initialized"',
            bootstrap.kwargs["initialized_notification"],
        )

        failed_bootstrap = subprocess.CompletedProcess(
            ["codex", "app-server"], 1, "", "Operation not permitted\n"
        )
        with (
            mock.patch.object(
                module.subprocess,
                "run",
                side_effect=responses,
            ) as failed_run,
            mock.patch.object(
                module,
                "_codex_app_server_initialize",
                side_effect=[failed_bootstrap] * 3,
            ) as failed_initialize,
            self.assertRaisesRegex(
                module.AgentRuntimeError, "bootstrap/IPC capability is unavailable"
            ) as raised,
        ):
            self.synthetic_preflight(module,
                str(self.codex_path),
                module.codex_permission_config(["owned.py"]),
                test_mode=False,
            )
        self.assertEqual(failed_run.call_count, 5)
        self.assertEqual(failed_initialize.call_count, 3)
        self.assertEqual(len(raised.exception.initialize_attempts), 3)
        self.assertTrue(
            all(not row["initialized"] for row in raised.exception.initialize_attempts)
        )

    def test_codex_initialize_retries_are_bounded_and_stop_at_first_success(self) -> None:
        module = load_runtime_module()
        prefix = [
            subprocess.CompletedProcess([], 0, module.AUDITED_CODEX_VERSION + "\n", ""),
            subprocess.CompletedProcess([], 0, "--config --strict-config\n", ""),
            subprocess.CompletedProcess(
                [], 0,
                "--ignore-user-config --ignore-rules --dangerously-bypass-hook-trust "
                "--config --strict-config\n", ""
            ),
            subprocess.CompletedProcess([], 0, "--config --strict-config --listen\n", ""),
            subprocess.CompletedProcess([], 0, "", ""),
        ]
        failed = subprocess.CompletedProcess([], 1, "", "transient\n")
        succeeded = subprocess.CompletedProcess(
            [], 0, '{"id":0,"result":{"platformFamily":"unix"}}\n', ""
        )
        with (
            mock.patch.object(
                module.subprocess,
                "run",
                side_effect=prefix,
            ) as run,
            mock.patch.object(
                module,
                "_codex_app_server_initialize",
                side_effect=[failed, failed, succeeded],
            ) as initialize,
        ):
            result = self.synthetic_preflight(module,
                str(self.codex_path),
                module.codex_permission_config(["owned.py"]),
                test_mode=False,
            )
        self.assertEqual(run.call_count, 5)
        self.assertEqual(initialize.call_count, 3)
        self.assertEqual(
            [row["attempt"] for row in result["initialize_attempts"]],
            [1, 2, 3],
        )
        self.assertTrue(result["initialize_attempts"][-1]["initialized"])

    def test_persistent_initialize_failure_is_durable_before_provider_launch(self) -> None:
        module = load_runtime_module()
        attempts = [
            {
                "attempt": index,
                "returncode": 1,
                "initialized": False,
                "stdout_sha256": hashlib.sha256(b"").hexdigest(),
                "stderr_sha256": hashlib.sha256(str(index).encode()).hexdigest(),
            }
            for index in (1, 2, 3)
        ]
        error = module.CodexPreflightError("exhausted", attempts)
        with self.temporary_directory() as directory_name:
            state = Path(directory_name)
            evidence = module._persist_codex_preflight_failure(
                state, "bounded-preflight", error
            )
            durable = json.loads(
                (state / "bounded-preflight.preflight.json").read_text(
                    encoding="utf-8"
                )
            )
        self.assertEqual(durable, evidence)
        self.assertTrue(durable["provider_launch_prevented"])
        self.assertEqual(
            [row["attempt"] for row in durable["initialize_attempts"]],
            [1, 2, 3],
        )

    def test_audited_codex_real_cli_contract(self) -> None:
        from tests.test_codex_plugin_install import (
            exercise_audited_codex_native_authority_roundtrip,
        )

        evidence = exercise_audited_codex_native_authority_roundtrip()
        authority = evidence["authority"]
        result = evidence["preflight"]
        self.assertEqual(
            set(authority),
            load_runtime_module()._NATIVE_AUTHORITY_FIELDS,
        )
        self.assertTrue(result["supported"])
        self.assertEqual(
            result["help_observation_sha256"],
            authority["codex_help_observation_sha256"],
        )
        self.assertFalse(result["execution_prevented"])
        self.assertEqual(
            evidence["staged_runtime"],
            "marketplace/plugins/sulde/runtime/scripts/kb/agent-runtime.py",
        )
        self.assertTrue(evidence["field_drift_rejected"])

    def test_synthetic_incompatible_codex_help_fails_closed(self) -> None:
        module = load_runtime_module()
        responses = [
            subprocess.CompletedProcess(
                ["codex", "--version"], 0, module.AUDITED_CODEX_VERSION + "\n", ""
            ),
            subprocess.CompletedProcess(
                ["codex", "--help"], 0, "--config --strict-config\n", ""
            ),
            subprocess.CompletedProcess(
                ["codex", "exec", "--help"],
                0,
                "--ignore-rules --config --strict-config\n",
                "",
            ),
            subprocess.CompletedProcess(
                ["codex", "app-server", "--help"],
                0,
                "--config --strict-config --listen\n",
                "",
            ),
        ]
        with (
            mock.patch.object(module.subprocess, "run", side_effect=responses) as run,
            self.assertRaisesRegex(module.AgentRuntimeError, "help surface"),
        ):
            self.synthetic_preflight(module,
                str(self.codex_path),
                module.codex_permission_config(["owned.py"]),
                test_mode=False,
            )
        self.assertEqual(run.call_count, 4)

    def test_codex_preflight_rejects_help_diagnostic_stderr_drift(self) -> None:
        module = load_runtime_module()
        help_stdout = (
            "--config --strict-config\n",
            "--ignore-user-config --ignore-rules --dangerously-bypass-hook-trust "
            "--config --strict-config\n",
            "--config --strict-config --listen\n",
        )
        authority = {
            "codex_help_observation_sha256": sys.modules[
                module.successful_version_identity.__module__
            ].canonical_codex_help_observation(
                tuple((0, surface, "") for surface in help_stdout)
            )[1]
        }
        responses = [
            subprocess.CompletedProcess(
                ["codex", "--version"],
                0,
                module.AUDITED_CODEX_VERSION + "\n",
                "version diagnostic is not identity\n",
            ),
            subprocess.CompletedProcess(
                ["codex", "--help"], 0, help_stdout[0], "diagnostic drift\n"
            ),
            subprocess.CompletedProcess(
                ["codex", "exec", "--help"], 0, help_stdout[1], ""
            ),
            subprocess.CompletedProcess(
                ["codex", "app-server", "--help"], 0, help_stdout[2], ""
            ),
        ]
        with (
            mock.patch.object(module.subprocess, "run", side_effect=responses) as run,
            self.assertRaisesRegex(module.AgentRuntimeError, "help bytes drifted"),
        ):
            self.synthetic_preflight(module,
                str(self.codex_path),
                module.codex_permission_config(["owned.py"]),
                test_mode=False,
                installed_authority=authority,
            )
        self.assertEqual(run.call_count, 4)

    def test_codex_preflight_rejects_path_alias_future_and_substring_versions(self) -> None:
        module = load_runtime_module()
        with self.assertRaisesRegex(
            module.AgentRuntimeError,
            "installation-bound audited codex-cli 0.154.0 target",
        ):
            self.synthetic_preflight(module,
                "codex",
                module.codex_permission_config(["owned.py"]),
                test_mode=False,
            )
        for surface in (
            "codex-cli 0.149.1\n",
            "codex-cli 0.151.0\n",
            "codex-cli 0.152.0\n",
            "codex-cli 0.153.0\n",
            "codex-cli 0.153.4\n",
            "codex-cli 0.155.0\n",
            "wrapper codex-cli 0.154.0\n",
            "codex-cli 0.154.0 future\n",
            " codex-cli 0.154.0\n",
            "codex-cli 0.154.0\n\n",
        ):
            with (
                self.subTest(surface=surface),
                mock.patch.object(
                    module.subprocess,
                    "run",
                    return_value=subprocess.CompletedProcess(
                        [str(self.codex_path), "--version"],
                        0,
                        surface,
                        "",
                    ),
                ) as run,
                self.assertRaisesRegex(
                    module.AgentRuntimeError,
                    "exactly audited codex-cli 0.154.0",
                ),
            ):
                self.synthetic_preflight(module,
                    str(self.codex_path),
                    module.codex_permission_config(["owned.py"]),
                    test_mode=False,
                )
            self.assertEqual(run.call_count, 1)

    def test_installed_native_authority_digest_binds_profile_broker_and_generation(self) -> None:
        module = load_runtime_module()
        authority = {
            "schema": module.NATIVE_AUTHORITY_SCHEMA,
            "spec_version": 1,
            "provider": "codex",
            "production_codex_executable": str(self.codex_path),
            "broker_sha256": hashlib.sha256(b"broker").hexdigest(),
            "runtime_generation": "0.2.5:runtime",
            "permission_profile_spec_sha256": module.permission_profile_spec_sha256(),
        }
        digest = module.native_authority_sha256(authority)
        authority["authority_sha256"] = digest
        self.assertEqual(module.native_authority_sha256(authority), digest)
        for field, value in (
            ("broker_sha256", hashlib.sha256(b"drifted broker").hexdigest()),
            ("runtime_generation", "rollback:generation"),
            ("permission_profile_spec_sha256", hashlib.sha256(b"drifted spec").hexdigest()),
        ):
            changed = dict(authority)
            changed[field] = value
            self.assertNotEqual(module.native_authority_sha256(changed), digest)
        with self.temporary_directory() as directory_name:
            root = Path(directory_name).resolve()
            (root / ".git").mkdir()
            (root / "owned.py").touch()
            (root / "other.py").touch()
            profile = module.permission_profile_bytes(
                ["owned.py"], worktree=root, git_common_dir=root / ".git"
            )
            self.assertEqual(
                hashlib.sha256(profile).hexdigest(),
                hashlib.sha256(
                    module.permission_profile_bytes(
                        ["owned.py"], worktree=root, git_common_dir=root / ".git"
                    )
                ).hexdigest(),
            )
            self.assertNotEqual(
                hashlib.sha256(profile).hexdigest(),
                hashlib.sha256(
                    module.permission_profile_bytes(
                        ["other.py"], worktree=root, git_common_dir=root / ".git"
                    )
                ).hexdigest(),
            )

    def test_entrypoint_disables_bytecode_before_installed_sibling_imports(self) -> None:
        source = RUNTIME.read_text(encoding="utf-8")
        guard = source.index("sys.dont_write_bytecode = True")
        self.assertLess(guard, source.index("from codex_cli_contract import"))
        self.assertLess(guard, source.index("from audit_cursor import"))
        self.assertLess(guard, source.index("from execution_backend import"))
        self.assertLess(guard, source.index("import native_agent_broker"))
        self.assertIn(
            'os.environ["PYTHONDONTWRITEBYTECODE"] = "1"',
            source[: source.index("from audit_cursor import")],
        )

    def test_installed_native_authority_readback_rejects_generation_profile_and_broker_drift(self) -> None:
        module = load_runtime_module()
        with self.temporary_directory() as directory_name:
            directory = Path(directory_name).resolve()
            fake_codex = directory / "codex"
            fake_codex.write_bytes(b"sealed codex executable")
            runtime_root = Path(module.__file__).resolve().parents[2]
            generation = "0.2.5+fixture:runtime"
            runtime_tree = hashlib.sha256(b"runtime tree").hexdigest()
            authority = {
                "schema": module.NATIVE_AUTHORITY_SCHEMA,
                "spec_version": module.NATIVE_AUTHORITY_SPEC_VERSION,
                "provider": "codex",
                "production_codex_executable": str(fake_codex),
                "production_codex_resolved_executable": str(fake_codex.resolve()),
                "codex_version": module.AUDITED_CODEX_VERSION,
                "codex_executable_sha256": hashlib.sha256(fake_codex.read_bytes()).hexdigest(),
                "codex_help_contract_sha256": module.codex_help_contract_sha256(),
                "codex_help_observation_sha256": hashlib.sha256(b"help").hexdigest(),
                "permission_profile_spec_version": module.PERMISSION_PROFILE_SPEC_VERSION,
                "permission_profile_spec_sha256": module.permission_profile_spec_sha256(),
                "broker_protocol_spec_version": module.BROKER_PROTOCOL_SPEC_VERSION,
                "broker_path": str(runtime_root / "scripts/kb/native_agent_broker.py"),
                "broker_sha256": hashlib.sha256(
                    (runtime_root / "scripts/kb/native_agent_broker.py").read_bytes()
                ).hexdigest(),
                "agent_runtime_path": str(runtime_root / "scripts/kb/agent-runtime.py"),
                "agent_runtime_sha256": hashlib.sha256(
                    (runtime_root / "scripts/kb/agent-runtime.py").read_bytes()
                ).hexdigest(),
                "codex_cli_contract_path": str(
                    runtime_root / "scripts/kb/codex_cli_contract.py"
                ),
                "codex_cli_contract_sha256": hashlib.sha256(
                    (runtime_root / "scripts/kb/codex_cli_contract.py").read_bytes()
                ).hexdigest(),
                "runtime_generation": generation,
                "runtime_tree_sha256": runtime_tree,
            }
            authority["authority_sha256"] = module.native_authority_sha256(authority)
            deployment = {
                "schema": module.DEPLOYMENT_GENERATION_SCHEMA,
                "schema_version": 1,
                "provider": "codex",
                "generation": generation,
                "runtime_tree_sha256": runtime_tree,
                "runtime_root": str(runtime_root),
                "native_runtime_authority": authority,
                "native_runtime_authority_sha256": authority["authority_sha256"],
            }
            descriptor = directory / module.DEPLOYMENT_GENERATION_NAME

            def write(value):
                descriptor.write_text(json.dumps(value), encoding="utf-8")

            write(deployment)
            with (
                mock.patch.object(
                    module,
                    "_installed_runtime_tree_sha256",
                    return_value=runtime_tree,
                ),
                mock.patch.object(
                    module,
                    "_regular_file_sha256",
                    side_effect=lambda _path, *, label: {
                        "agent runtime": authority["agent_runtime_sha256"],
                        "Codex CLI contract": authority[
                            "codex_cli_contract_sha256"
                        ],
                        "native broker": authority["broker_sha256"],
                        "Codex executable": authority["codex_executable_sha256"],
                    }[label],
                ),
                mock.patch.dict(os.environ, {"SULDE_KB_HOME": str(directory)}),
            ):
                with mock.patch.dict(os.environ, {
                    "SULDE_CODEX_EXE": "untrusted-override", "PATH": "",
                }):
                    self.assertEqual(module.load_installed_native_authority(), authority)
                for field, value in (
                    ("runtime_generation", "rollback:generation"),
                    ("permission_profile_spec_sha256", hashlib.sha256(b"profile drift").hexdigest()),
                    ("broker_sha256", hashlib.sha256(b"broker drift").hexdigest()),
                ):
                    changed = json.loads(json.dumps(deployment))
                    changed["native_runtime_authority"][field] = value
                    write(changed)
                    with self.assertRaisesRegex(module.AgentRuntimeError, "drift"):
                        module.load_installed_native_authority()
                write(deployment)
                # v1 pinned a machine-specific compiled alias. Re-seal through
                # installation; never silently reinterpret that old authority.
                legacy = json.loads(json.dumps(deployment))
                legacy_authority = legacy["native_runtime_authority"]
                legacy_authority["spec_version"] = 1
                legacy_authority["authority_sha256"] = module.native_authority_sha256(legacy_authority)
                legacy["native_runtime_authority_sha256"] = legacy_authority["authority_sha256"]
                write(legacy)
                with self.assertRaisesRegex(module.AgentRuntimeError, "drift"):
                    module.load_installed_native_authority()

    def test_native_boundary_injects_all_owned_path_escape_classes(self) -> None:
        self.assertEqual(sys.platform, "darwin", "native macOS profile runner required")
        self.assertIsNotNone(shutil.which("sandbox-exec"), "sandbox-exec is required")
        module = load_runtime_module()
        with self.temporary_directory() as directory_name:
            root = Path(directory_name)
            (root / ".git").mkdir()
            evidence_path = root / "native-evidence.json"
            frozen = {
                "task_id": "T20-native-proof",
                "base_commit": "a" * 40,
                "task_definition_sha256": hashlib.sha256(b"task").hexdigest(),
                "brief_sha256": hashlib.sha256(b"brief").hexdigest(),
                "worktree_canonical_path": str(root),
                "git_common_dir_canonical_path": str(root / ".git"),
                "owned_paths": ["owned-existing", "owned-new"],
                "report_relative_path": "native.last.md",
                "model_reasoning_effort": "high",
                "codex_executable": str(self.codex_path),
                "codex_version": module.AUDITED_CODEX_VERSION,
                "codex_executable_sha256": hashlib.sha256(b"codex").hexdigest(),
                "broker_generation": 1,
                "broker_sha256": hashlib.sha256(
                    Path(module.native_agent_broker.__file__).read_bytes()
                ).hexdigest(),
                "provider_generation": 1,
                "permission_profile_name": "sulde-owned-paths",
                "permission_profile_bytes_sha256": hashlib.sha256(
                    module.permission_profile_bytes(
                        ["owned-existing", "owned-new"],
                        worktree=root,
                        git_common_dir=root / ".git",
                    )
                ).hexdigest(),
                "permission_profile_spec_sha256": module.permission_profile_spec_sha256(),
                "installed_descriptor_sha256": hashlib.sha256(b"descriptor").hexdigest(),
                "runtime_generation": "t20:fixture",
                "runtime_tree_sha256": hashlib.sha256(b"runtime").hexdigest(),
                "agent_runtime_sha256": hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest(),
                "nonce": hashlib.sha256(b"native-proof").hexdigest(),
            }
            request = module.native_agent_broker.build_request(frozen)
            try:
                evidence = module.native_agent_broker.execute_native_profile_probe(
                    request,
                    frozen,
                    evidence_path=str(evidence_path),
                    sandbox_executable=shutil.which("sandbox-exec") or "/usr/bin/sandbox-exec",
                )
            except module.native_agent_broker.ProtocolError as error:
                durable = json.loads(evidence_path.read_text(encoding="utf-8"))
                self.assertTrue(durable["policy_pause"])
                self.assertTrue(durable["provider_launch_prevented"])
                self.assertFalse(durable["execution_prevented"])
                self.assertEqual(
                    durable["failure_domain"], "nested_sandbox_interference"
                )
                self.assertTrue(durable["nested_sandbox_interference"])
                if os.environ.get("SULDE_REQUIRE_NATIVE_OS_EVIDENCE") == "1":
                    self.fail(f"formal native broker evidence blocked: {error}; {durable}")
                return
            durable = json.loads(evidence_path.read_text(encoding="utf-8"))
            self.assertEqual(durable, evidence)
            self.assertTrue(durable["observed_denial"])
            self.assertFalse(durable["policy_pause"])
            self.assertTrue(durable["execution_prevented"])
            probes = {row["probe_id"]: row for row in durable["probe_receipt"]["probes"]}
            for target in (
                "system_tmp",
                "owned_parent_escape",
                "owned_sibling_escape",
                "git_common_write",
                "scope_outside_pycache",
                "network_socket",
                "nonowned_unlink_file",
                "nonowned_unlink_empty_dir",
                "nonowned_unlink_symlink",
                "git_control_unlink",
                "codex_agent_control_unlink",
                "owned_adjacent_unlink",
                "nonowned_move",
                "nonowned_replace",
            ):
                if probes[target]["operation"] in {"unlink", "rename", "replace"}:
                    self.assertTrue(probes[target]["pre_exists"])
                    self.assertTrue(probes[target]["post_exists"])
                else:
                    self.assertFalse(probes[target]["pre_exists"])
                    self.assertFalse(probes[target]["post_exists"])
                self.assertTrue(probes[target]["observed_denial"])
                self.assertTrue(probes[target]["execution_prevented"])

    def test_unsupported_codex_profile_fails_before_task_provider_launch(self) -> None:
        module = load_runtime_module()
        old = subprocess.CompletedProcess(
            ["codex", "--version"], 0, "codex-cli 0.137.0\n", ""
        )
        with (
            mock.patch.object(module.subprocess, "run", return_value=old) as run,
            self.assertRaisesRegex(
                module.AgentRuntimeError,
                "exactly audited codex-cli 0.154.0",
            ),
        ):
            self.synthetic_preflight(module,
                str(self.codex_path),
                module.codex_permission_config(["base.txt"]),
                test_mode=False,
            )
        self.assertEqual(run.call_count, 1)

    def test_missing_selected_provider_writes_terminal_failure(self) -> None:
        with self.temporary_directory() as directory_name:
            directory = Path(directory_name)
            worktree, brief = self.prepare(directory, "missing")
            environment = os.environ.copy()
            environment.update(
                {
                    "SULDE_AGENT_PROVIDER": "codex",
                    "SULDE_CODEX_EXE": str(directory / "missing-codex"),
                    "PATH": "",
                }
            )
            completed = subprocess.run(
                [
                    sys.executable,
                    str(RUNTIME),
                    "run",
                    str(worktree),
                    "missing",
                    str(brief),
                    "--timeout",
                    "2",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=environment,
                check=False,
            )
            self.assertEqual(completed.returncode, 2)
            self.assertFalse((worktree / ".codex-agent/missing.status").exists())

    def test_resume_context_refuses_provider_switch_and_writes_terminal_failure(self) -> None:
        with self.temporary_directory() as directory_name:
            directory = Path(directory_name)
            worktree, brief = self.prepare(directory, "resume-provider")
            executable = directory / "codex"
            executable.write_text("#!/usr/bin/python3\n", encoding="utf-8")
            executable.chmod(0o755)
            context = worktree / ".codex-agent/resume-provider.resume-context.json"
            context.write_text(
                json.dumps(
                    {
                        "schema": "sulde-intervention-resume-context-v1",
                        "slug": "resume-provider",
                        "interventions": [
                            {
                                "intervention_id": "int-" + "1" * 24,
                                "attempt_id": "att-" + "2" * 24,
                                "decision": "retry_authorized",
                                "provider": "claude",
                                "capability": "mcp:docs:update_document",
                                "target_sha256": "3" * 64,
                                "evidence_sha256": "4" * 64,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            environment = os.environ.copy()
            environment.update(
                {"SULDE_AGENT_PROVIDER": "codex", "SULDE_CODEX_EXE": str(executable)}
            )
            completed = subprocess.run(
                [
                    sys.executable,
                    str(RUNTIME),
                    "run",
                    str(worktree),
                    "resume-provider",
                    str(brief),
                    "--resume-context",
                    str(context),
                    "--timeout",
                    "10",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=environment,
                check=False,
            )
            self.assertEqual(completed.returncode, 1, completed.stdout + completed.stderr)
            self.assertIn("does not match", completed.stderr)
            status = (worktree / ".codex-agent/resume-provider.status").read_text()
            self.assertTrue(status.startswith("status=failed "), status)

    def test_structured_git_lifecycle_provisions_commits_and_fast_forwards(self) -> None:
        with self.temporary_directory() as directory_name:
            repository = Path(directory_name) / "repository"
            repository.mkdir()
            self.git(repository, "init", "-b", "main")
            self.git(repository, "config", "user.name", "Sulde Test")
            self.git(repository, "config", "user.email", "sulde@example.invalid")
            (repository / ".gitignore").write_text(".worktrees/\n", encoding="utf-8")
            (repository / "feature.txt").write_text("base\n", encoding="utf-8")
            completion = repository / "guardian-program" / "completion-evidence"
            blobs = completion / "blobs"
            snapshots = completion / "snapshots"
            prepared = completion / "prepared"
            for directory in (blobs, snapshots, prepared):
                directory.mkdir(parents=True, exist_ok=True)
            blob_payload = b"verified evidence\n"
            blob_digest = hashlib.sha256(blob_payload).hexdigest()
            (blobs / f"{blob_digest}.blob").write_bytes(blob_payload)
            snapshot_payload = b'{"schema":"fixture"}\n'
            snapshot_digest = hashlib.sha256(snapshot_payload).hexdigest()
            (snapshots / f"{snapshot_digest}.json").write_bytes(snapshot_payload)
            authority = "a" * 64
            (prepared / f"{authority}.json").write_text(
                json.dumps(
                    {
                        "schema": "sulde-guardian-program-prepared-completion-v1",
                        "program_id": "fixture-program",
                        "authority_event_sha256": authority,
                        "final_gate_sha256": "b" * 64,
                        "evidence_snapshot_path": (
                            f"completion-evidence/snapshots/{snapshot_digest}.json"
                        ),
                        "evidence_snapshot_sha256": snapshot_digest,
                    },
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            self.git(repository, "add", "--", ".gitignore", "feature.txt", "guardian-program")
            self.git(repository, "commit", "-m", "initial")
            base = self.git(repository, "rev-parse", "HEAD")
            self.git(repository, "branch", "dev", base)
            worktrees = repository / ".worktrees"
            worktrees.mkdir()
            dev = worktrees / "dev"
            self.git(repository, "worktree", "add", str(dev), "dev")
            task = worktrees / "task-one"
            (repository / "unrelated-primary.tmp").write_text(
                "coordinator preparation\n", encoding="utf-8"
            )
            (dev / "unrelated-dev.tmp").write_text(
                "parallel dev work\n", encoding="utf-8"
            )

            provision = subprocess.run(
                [
                    sys.executable,
                    str(RUNTIME),
                    "provision",
                    str(repository),
                    str(task),
                    "--branch",
                    "fix/task-one",
                    "--base-ref",
                    "dev",
                    "--base-commit",
                    base,
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            self.assertEqual(provision.returncode, 0, provision.stdout + provision.stderr)
            provision_result = json.loads(provision.stdout)
            self.assertEqual(provision_result["head"], base)
            self.assertEqual(
                provision_result["git_layout"], "full-clone-internal-git"
            )
            self.assertEqual(self.git(task, "branch", "--show-current"), "fix/task-one")
            self.assertTrue((task / ".git").is_dir())
            self.assertEqual(
                (task / self.git(task, "rev-parse", "--git-common-dir")).resolve(),
                (task / ".git").resolve(),
            )
            module = load_runtime_module()
            self.assertEqual(
                module.validate_codex_git_layout(
                    task, task / ".git", ["feature.txt"]
                ),
                (str(task.resolve()), str((task / ".git").resolve())),
            )
            self.assertEqual(
                module.coordinator_control_root(
                    task,
                    repository / "guardian-program",
                    test_mode=False,
                ),
                (repository / "guardian-program").resolve(),
            )
            self.assertEqual(
                module.coordinator_control_root(
                    task,
                    dev / "guardian-program",
                    test_mode=False,
                ),
                (dev / "guardian-program").resolve(),
            )
            self.git(task, "remote", "set-url", "sulde-source", str(directory))
            with self.assertRaisesRegex(
                module.AgentRuntimeError, "not authenticated"
            ):
                module.coordinator_control_root(
                    task,
                    repository / "guardian-program",
                    test_mode=False,
                )
            self.git(
                task,
                "remote",
                "set-url",
                "sulde-source",
                str(repository),
            )
            task_completion = task / "guardian-program" / "completion-evidence"
            self.assertTrue(
                all(
                    (path.stat().st_mode & 0o777) == 0o400
                    for path in task_completion.rglob("*")
                    if path.is_file()
                )
            )
            self.assertTrue(
                all(
                    (path.stat().st_mode & 0o777) == 0o700
                    for path in [
                        task_completion,
                        *(path for path in task_completion.iterdir() if path.is_dir()),
                    ]
                )
            )

            (task / "feature.txt").write_text("task change\n", encoding="utf-8")
            self.git(task, "add", "--", "feature.txt")
            committed = subprocess.run(
                [
                    sys.executable,
                    str(RUNTIME),
                    "commit",
                    str(task),
                    "--expected-head",
                    base,
                    "--message",
                    "verified task change",
                    "--path",
                    "feature.txt",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            self.assertEqual(committed.returncode, 0, committed.stdout + committed.stderr)
            commit_result = json.loads(committed.stdout)
            task_head = commit_result["head"]
            self.assertEqual(commit_result["parent"], base)
            self.assertEqual(commit_result["paths"], ["feature.txt"])

            self.git(
                repository,
                "fetch",
                str(task),
                "refs/heads/fix/task-one:refs/heads/fix/task-one",
            )
            (dev / "unrelated-dev.tmp").unlink()
            merged = subprocess.run(
                [
                    sys.executable,
                    str(RUNTIME),
                    "merge",
                    str(dev),
                    "--target-branch",
                    "dev",
                    "--source-ref",
                    "fix/task-one",
                    "--expected-target-head",
                    base,
                    "--expected-source-head",
                    task_head,
                    "--path",
                    "feature.txt",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            self.assertEqual(merged.returncode, 0, merged.stdout + merged.stderr)
            merge_result = json.loads(merged.stdout)
            self.assertEqual(merge_result["head"], task_head)
            self.assertEqual(self.git(dev, "rev-parse", "HEAD"), task_head)
            self.assertEqual(self.git(dev, "status", "--porcelain=v1"), "")
            self.assertTrue((repository / "unrelated-primary.tmp").is_file())

    def test_provision_fails_closed_for_conflict_drift_and_git_metadata_alias(self) -> None:
        def fixture(root: Path) -> tuple[Path, str]:
            repository = root / "repository"
            repository.mkdir()
            self.git(repository, "init", "-b", "main")
            self.git(repository, "config", "user.name", "Sulde Test")
            self.git(repository, "config", "user.email", "sulde@example.invalid")
            (repository / "tracked.txt").write_bytes(b"base")
            (repository / ".gitignore").write_bytes(b".worktrees/")
            self.git(repository, "add", "--", "tracked.txt", ".gitignore")
            self.git(repository, "commit", "-m", "base")
            base = self.git(repository, "rev-parse", "HEAD")
            self.git(repository, "branch", "dev", base)
            (repository / ".worktrees").mkdir()
            return repository, base

        with self.temporary_directory() as directory_name:
            root = Path(directory_name)
            repository, base = fixture(root)
            target = repository / ".worktrees/task"
            command = [
                sys.executable,
                str(RUNTIME),
                "provision",
                str(repository),
                str(target),
                "--branch",
                "task/task",
                "--base-ref",
                "dev",
                "--base-commit",
            ]
            drifted = subprocess.run(
                [*command, "0" * 40],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            self.assertEqual(drifted.returncode, 2)
            self.assertIn("base changed", drifted.stderr)
            self.assertFalse(target.exists())

            target.mkdir()
            conflicted = subprocess.run(
                [*command, base],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            self.assertEqual(conflicted.returncode, 2)
            self.assertIn("path must be absent", conflicted.stderr)
            target.rmdir()

            git_directory = repository / ".git"
            parked_git = root / "parked.git"
            git_directory.rename(parked_git)
            git_directory.symlink_to(parked_git, target_is_directory=True)
            metadata_alias = subprocess.run(
                [*command, base],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            self.assertEqual(metadata_alias.returncode, 2)
            self.assertIn("git common directory", metadata_alias.stderr)
            self.assertFalse(target.exists())

    def test_structured_commit_rejects_an_unsealed_staged_path(self) -> None:
        with self.temporary_directory() as directory_name:
            worktree = Path(directory_name) / "worktree"
            worktree.mkdir()
            self.git(worktree, "init", "-b", "fix/task")
            self.git(worktree, "config", "user.name", "Sulde Test")
            self.git(worktree, "config", "user.email", "sulde@example.invalid")
            (worktree / "one.txt").write_text("base\n", encoding="utf-8")
            (worktree / "two.txt").write_text("base\n", encoding="utf-8")
            self.git(worktree, "add", "--", "one.txt", "two.txt")
            self.git(worktree, "commit", "-m", "initial")
            head = self.git(worktree, "rev-parse", "HEAD")
            (worktree / "one.txt").write_text("one\n", encoding="utf-8")
            (worktree / "two.txt").write_text("two\n", encoding="utf-8")
            self.git(worktree, "add", "--", "one.txt", "two.txt")

            completed = subprocess.run(
                [
                    sys.executable,
                    str(RUNTIME),
                    "commit",
                    str(worktree),
                    "--expected-head",
                    head,
                    "--message",
                    "incomplete seal",
                    "--path",
                    "one.txt",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            self.assertEqual(completed.returncode, 2)
            self.assertIn("staged paths do not match", completed.stderr)
            self.assertEqual(self.git(worktree, "rev-parse", "HEAD"), head)


class H06HSelfContainedEvidenceTests(unittest.TestCase):
    def broker_fixture(self, broker, workspace):
        (workspace / ".git").mkdir()
        (workspace / "owned.py").write_text("owned\n", encoding="utf-8")
        owned_paths = ["owned.py"]
        frozen = {
            "task_id": "H06H",
            "base_commit": "a" * 40,
            "task_definition_sha256": hashlib.sha256(b"task").hexdigest(),
            "brief_sha256": hashlib.sha256(b"brief").hexdigest(),
            "worktree_canonical_path": str(workspace),
            "git_common_dir_canonical_path": str(workspace / ".git"),
            "owned_paths": owned_paths,
            "report_relative_path": ".codex-agent/h06h.last.md",
            "model_reasoning_effort": "high",
            "codex_executable": "/opt/codex/bin/codex",
            "codex_version": "codex-cli 0.154.0",
            "codex_executable_sha256": hashlib.sha256(b"codex").hexdigest(),
            "broker_generation": 2,
            "broker_sha256": hashlib.sha256(b"broker").hexdigest(),
            "provider_generation": 1,
            "permission_profile_name": "sulde-owned-paths",
            "permission_profile_bytes_sha256": hashlib.sha256(
                broker.permission_profile_bytes(owned_paths, worktree=str(workspace))
            ).hexdigest(),
            "permission_profile_spec_sha256": hashlib.sha256(b"profile").hexdigest(),
            "installed_descriptor_sha256": hashlib.sha256(b"descriptor").hexdigest(),
            "runtime_generation": "fixture:runtime",
            "runtime_tree_sha256": hashlib.sha256(b"runtime").hexdigest(),
            "agent_runtime_sha256": hashlib.sha256(b"agent-runtime").hexdigest(),
            "nonce": hashlib.sha256(b"nonce").hexdigest(),
        }
        request = broker.build_request(frozen)
        plan = broker.build_profile_probe_plan(request, frozen)
        results = []
        for row in plan["probes"]:
            pre = hashlib.sha256((row["probe_id"] + ":pre").encode()).hexdigest()
            post = (
                pre
                if row["expected_execution_prevented"]
                else hashlib.sha256((row["probe_id"] + ":post").encode()).hexdigest()
            )
            results.append(
                {
                    "probe_id": row["probe_id"],
                    "operation": row["operation"],
                    "pre_exists": row["pre_exists"],
                    "post_exists": row["post_exists"],
                    "pre_observation_sha256": pre,
                    "post_observation_sha256": post,
                    "observed_denial": row["expected_execution_prevented"],
                    "execution_prevented": row["expected_execution_prevented"],
                }
            )
        probe = broker.build_probe_receipt(
            request,
            frozen,
            results,
            probe_run_id="probe-run-h06h-0001",
        )
        launch = broker.build_launch_plan(request, probe, frozen)
        return frozen, request, probe, launch

    def receipt_kwargs(self, evidence):
        empty_summary = {
            "present": False,
            "raw_byte_count": 0,
            "sha256": hashlib.sha256(b"").hexdigest(),
        }
        return {
            "started_at": "2000-01-01T00:00:00Z",
            "terminated_at": "2000-01-01T00:00:04Z",
            "provider_pid": 4242,
            "provider_run_id": "run-111111111111111111111111",
            "terminal_status": "interrupted",
            "termination_domain": "local_interruption",
            "termination_reason": "awaiting_human",
            "local_interruption_evidence": evidence,
            "exit_code": 0,
            "quiescence_confirmed": True,
            "stderr_path": ".codex-agent/h06h.stderr.log",
            "stderr_raw_bytes": H06H_STDERR,
            "stderr_fsync_completed": True,
            "jsonl_summary": dict(H06H_EVENTS_SUMMARY),
            "output_summary": dict(empty_summary),
            "report_summary": dict(empty_summary),
            "observed_denial": False,
            "execution_prevented": False,
        }

    def test_synthetic_interruption_runtime_to_production_broker_round_trip(self) -> None:
        self.assertEqual(len(H06H_RUN_LEDGER), 1399)
        self.assertEqual(H06H_RUN_LEDGER.count(b"\n"), 5)
        self.assertEqual(
            hashlib.sha256(H06H_RUN_LEDGER).hexdigest(),
            "057d6dc1da4b89c3ae59ce2ecb34b920a5ae2b39623601cc725b9b668d67a30c",
        )
        self.assertEqual(len(H06H_STDERR), 136)
        self.assertEqual(H06H_STDERR.count(b"\n"), 2)
        self.assertEqual(
            hashlib.sha256(H06H_STDERR).hexdigest(),
            "b38d2df3d6d0624e798a39de46f6b72ef8ebce83bc023ee6c3593b22d1ce61d3",
        )
        self.assertEqual(H06H_EVENTS_SUMMARY["line_count"], 48)
        self.assertEqual(H06H_EVENTS_SUMMARY["valid_json_line_count"], 48)
        self.assertEqual(H06H_EVENTS_SUMMARY["terminal_event_count"], 0)
        self.assertRegex(H06H_EVENTS_SUMMARY["sha256"], r"^[0-9a-f]{64}$")
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SULDE_TEST_MODE", None)
            self.assertNotIn("SULDE_TEST_MODE", os.environ)

            module = load_runtime_module()
            broker = module.native_agent_broker
            with tempfile.TemporaryDirectory() as directory_name:
                directory = Path(directory_name).resolve()
                ledger = directory / "run.jsonl"
                ledger.write_bytes(H06H_RUN_LEDGER)
                evidence = module._run_ledger_local_interruption_evidence(
                    ledger,
                    run_id="run-111111111111111111111111",
                )
                workspace = directory / "workspace"
                workspace.mkdir()
                frozen, request, probe, launch = self.broker_fixture(broker, workspace)
                receipt = broker.build_provider_receipt(
                    request,
                    probe,
                    launch,
                    frozen,
                    **self.receipt_kwargs(evidence),
                )
                self.assertEqual(receipt["termination_reason"], "awaiting_human")
                self.assertEqual(receipt["local_interruption_evidence"], evidence)
                self.assertEqual(
                    broker.validate_provider_receipt(
                        receipt,
                        request,
                        probe,
                        launch,
                        frozen,
                    ),
                    receipt,
                )

    def test_codex_output_last_message_is_authoritative_before_settle(self) -> None:
        module = load_runtime_module()
        broker = module.native_agent_broker
        for stale_result in (False, True):
            with self.subTest(stale_result=stale_result), tempfile.TemporaryDirectory() as name:
                workspace = Path(name).resolve() / "workspace"
                workspace.mkdir()
                frozen, request, probe, launch = self.broker_fixture(broker, workspace)
                state = workspace / ".codex-agent"
                state.mkdir()
                durable_relative = "guardian-r2-program/reports/task.md"
                durable = workspace / durable_relative
                durable.parent.mkdir(parents=True)
                durable.write_bytes(REPORT.encode("utf-8"))
                last = state / "h06h.last.md"
                ledger = state / "h06h.run.jsonl"
                events = state / "h06h.events.jsonl"
                rows = [
                    {"type": "thread.started", "thread_id": "thread-fixture"},
                    {"type": "turn.started"},
                    {
                        "type": "item.started",
                        "item": {"id": "item_3", "type": "agent_message", "text": ""},
                    },
                    {
                        "type": "item.completed",
                        "item": {
                            "id": "item_3",
                            "type": "agent_message",
                            "text": REPORT,
                        },
                    },
                ]
                if stale_result:
                    rows.append({"type": "result", "result": "stale JSONL result"})
                rows.append(
                    {
                        "type": "turn.completed",
                        "usage": {
                            "input_tokens": 10,
                            "cached_input_tokens": 0,
                            "output_tokens": 20,
                        },
                    }
                )
                source = (
                    "import json, pathlib, sys\n"
                    "pathlib.Path(sys.argv[1]).write_text(sys.argv[2], encoding='utf-8')\n"
                    f"rows = {rows!r}\n"
                    "for row in rows: print(json.dumps(row, ensure_ascii=False), flush=True)\n"
                )
                handle = module.ExecutionBackend().start(
                    [sys.executable, "-c", source, str(last), REPORT],
                    cwd=workspace,
                    ledger_path=ledger,
                    provider="codex",
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                stdout, stderr = handle.process.communicate(timeout=5)
                self.assertEqual(handle.process.returncode, 0, stderr)
                events.write_text(stdout, encoding="utf-8")
                streamed = "stale JSONL result" if stale_result else ""
                result, final_message = module._settle_provider_result(
                    handle,
                    provider="codex",
                    test_mode=False,
                    root=workspace,
                    report=last,
                    observed_status="running",
                    returncode=0,
                    streamed_final_message=streamed,
                )
                cleanup = handle.dispose()

                self.assertEqual(final_message, REPORT)
                self.assertTrue(result.output_present)
                self.assertEqual(
                    result.output_sha256,
                    hashlib.sha256(REPORT.encode("utf-8")).hexdigest(),
                )
                event_types = [json.loads(line)["type"] for line in stdout.splitlines()]
                self.assertEqual(event_types[-1], "turn.completed")
                self.assertEqual(event_types.count("result"), int(stale_result))
                ledger_rows = [
                    json.loads(line)
                    for line in ledger.read_text(encoding="utf-8").splitlines()
                ]
                ledger_result = next(
                    row for row in ledger_rows if row["type"] == "execution.result"
                )
                self.assertTrue(ledger_result["output_present"])
                self.assertEqual(ledger_result["output_sha256"], result.output_sha256)
                self.assertTrue(cleanup.quiescent)

                canonical = module._close_canonical_worker_report_authority(
                    workspace,
                    ["owned.py", durable_relative],
                    final_message,
                    last,
                )
                summary = module._broker_blob_summary(canonical)
                receipt = broker.build_provider_receipt(
                    request,
                    probe,
                    launch,
                    frozen,
                    started_at="2026-08-28T00:00:00Z",
                    terminated_at="2026-08-28T00:00:01Z",
                    provider_pid=handle.process.pid,
                    provider_run_id=result.run_id,
                    terminal_status="succeeded",
                    termination_domain="provider_natural",
                    termination_reason="provider_completed",
                    local_interruption_evidence=None,
                    exit_code=0,
                    quiescence_confirmed=True,
                    stderr_path=".codex-agent/h06h.stderr.log",
                    stderr_raw_bytes=stderr.encode("utf-8"),
                    stderr_fsync_completed=True,
                    jsonl_summary=module._broker_jsonl_summary(events),
                    output_summary=dict(summary),
                    report_summary=dict(summary),
                    observed_denial=False,
                    execution_prevented=False,
                )
                self.assertEqual(receipt["output_summary"], receipt["report_summary"])
                self.assertEqual(last.read_bytes(), canonical)
                self.assertEqual(durable.read_bytes(), canonical)
                self.assertEqual(
                    broker.validate_provider_receipt(
                        receipt,
                        request,
                        probe,
                        launch,
                        frozen,
                    ),
                    receipt,
                )

    def test_codex_output_last_message_unsafe_shapes_fail_before_settle(self) -> None:
        module = load_runtime_module()

        class RecordingHandle:
            def __init__(self) -> None:
                self.calls = []

            def settle(self, *, stop_reason, output=""):
                self.calls.append((stop_reason, output))
                return object()

        cases = (
            "missing",
            "symlink",
            "non-file",
            "hardlink",
            "oversize",
            "invalid-utf8",
            "empty",
        )
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as name:
                workspace = Path(name).resolve()
                state = workspace / ".codex-agent"
                state.mkdir()
                report = state / "unsafe.last.md"
                if case == "symlink":
                    target = state / "target.md"
                    target.write_text(REPORT, encoding="utf-8")
                    report.symlink_to(target)
                elif case == "non-file":
                    report.mkdir()
                elif case == "hardlink":
                    target = state / "target.md"
                    target.write_text(REPORT, encoding="utf-8")
                    os.link(target, report)
                elif case == "oversize":
                    report.write_bytes(b"x" * (module._MAX_CONTROL_BYTES + 1))
                elif case == "invalid-utf8":
                    report.write_bytes(b"\xff")
                elif case == "empty":
                    report.write_bytes(b"")
                handle = RecordingHandle()
                with self.assertRaises(module.AgentRuntimeError):
                    module._settle_provider_result(
                        handle,
                        provider="codex",
                        test_mode=False,
                        root=workspace,
                        report=report,
                        observed_status="running",
                        returncode=0,
                        streamed_final_message="forged JSONL result",
                    )
                self.assertEqual(handle.calls, [])
                self.assertFalse((state / "unsafe.native-receipt.json").exists())

        with tempfile.TemporaryDirectory() as name:
            workspace = Path(name).resolve()
            state = workspace / ".codex-agent"
            state.mkdir()
            report = state / "drift.last.md"
            report.write_text(REPORT, encoding="utf-8")
            metadata = report.stat()
            before = mock.Mock(
                st_mode=metadata.st_mode,
                st_nlink=metadata.st_nlink,
                st_size=metadata.st_size,
                st_dev=metadata.st_dev,
                st_ino=metadata.st_ino,
                st_mtime_ns=metadata.st_mtime_ns,
                st_ctime_ns=metadata.st_ctime_ns,
            )
            after = mock.Mock(
                st_mode=metadata.st_mode,
                st_nlink=metadata.st_nlink,
                st_size=metadata.st_size,
                st_dev=metadata.st_dev,
                st_ino=metadata.st_ino,
                st_mtime_ns=metadata.st_mtime_ns,
                st_ctime_ns=metadata.st_ctime_ns + 1,
            )
            handle = RecordingHandle()
            with (
                mock.patch.object(module.os, "fstat", side_effect=[state.stat(), before, after]),
                self.assertRaisesRegex(module.AgentRuntimeError, "changed while being read"),
            ):
                module._settle_provider_result(
                    handle,
                    provider="codex",
                    test_mode=False,
                    root=workspace,
                    report=report,
                    observed_status="running",
                    returncode=0,
                    streamed_final_message="forged JSONL result",
                )
            self.assertEqual(handle.calls, [])
            self.assertFalse((state / "drift.native-receipt.json").exists())

    def test_h06h_hostile_runtime_and_broker_variants_fail_closed(self) -> None:
        module = load_runtime_module()
        broker = module.native_agent_broker
        rows = [json.loads(line) for line in H06H_RUN_LEDGER.splitlines()]
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name).resolve()
            ledger = directory / "run.jsonl"
            ledger.write_bytes(H06H_RUN_LEDGER)
            valid = module._run_ledger_local_interruption_evidence(
                ledger,
                run_id="run-111111111111111111111111",
            )
            workspace = directory / "workspace"
            workspace.mkdir()
            frozen, request, probe, launch = self.broker_fixture(broker, workspace)

            runtime_cases = {
                "missing": rows[:3] + rows[4:],
                "duplicate": rows[:3] + [rows[2]] + rows[3:],
                "out-of-order-3-2-4": [rows[0], rows[1], rows[3], rows[2], rows[4]],
                "reason-drift": [*rows[:3], {**rows[3], "stop_reason": "policy_paused"}, rows[4]],
                "unknown-reason": [*rows[:2], {**rows[2], "reason": "unknown"}, *rows[3:]],
                "non-string-reason": [*rows[:2], {**rows[2], "reason": True}, *rows[3:]],
                "blank-reason": [*rows[:2], {**rows[2], "reason": " "}, *rows[3:]],
                "case-drift": [*rows[:2], {**rows[2], "reason": "External_Effect_Outcome_Unknown"}, *rows[3:]],
                "string-returncode": [*rows[:3], {**rows[3], "returncode": "0"}, rows[4]],
                "bool-returncode": [*rows[:3], {**rows[3], "returncode": True}, rows[4]],
                "non-quiescent": [*rows[:4], {**rows[4], "quiescent": False}],
            }
            for name, candidate in runtime_cases.items():
                with self.subTest(runtime=name):
                    ledger.write_bytes(
                        b"".join(
                            json.dumps(row, separators=(",", ":")).encode() + b"\n"
                            for row in candidate
                        )
                    )
                    with self.assertRaises(module.AgentRuntimeError):
                        module._run_ledger_local_interruption_evidence(
                            ledger,
                            run_id="run-111111111111111111111111",
                        )

            broker_cases = {}
            missing = dict(valid)
            missing.pop("result_event_index")
            broker_cases["missing"] = missing
            duplicate = dict(valid)
            duplicate["result_event_index"] = duplicate["interrupt_event_index"]
            broker_cases["duplicate"] = duplicate
            out_of_order = dict(valid)
            out_of_order.update(
                {
                    "interrupt_event_index": 3,
                    "result_event_index": 2,
                    "disposed_event_index": 4,
                }
            )
            broker_cases["out-of-order-3-2-4"] = out_of_order
            for name, value in (
                ("reason-drift", "paused"),
                ("unknown-reason", "unknown"),
                ("non-string-reason", True),
                ("blank-reason", " "),
                ("case-drift", "External_Effect_Outcome_Unknown"),
            ):
                changed = dict(valid)
                changed["interrupt_reason"] = value
                broker_cases[name] = changed
            for name, value in (("string-returncode", "0"), ("bool-returncode", True)):
                changed = dict(valid)
                changed["result_returncode"] = value
                broker_cases[name] = changed
            changed = dict(valid)
            changed["quiescent"] = False
            broker_cases["non-quiescent"] = changed
            for name, candidate in broker_cases.items():
                with self.subTest(broker=name), self.assertRaises(broker.ProtocolError):
                    broker.build_provider_receipt(
                        request,
                        probe,
                        launch,
                        frozen,
                        **self.receipt_kwargs(candidate),
                    )



    def test_newer_stronger_same_scope_success_supersedes_structured_diagnostic(self) -> None:
        module = load_runtime_module()
        contract = module.report_contract_for_brief("# Task\n\nDo the work.\n")
        success = {
            "candidate_sha256": "a" * 64,
            "execution_binding_sha256": "b" * 64,
            "environment_sha256": "c" * 64,
            "command_sha256": hashlib.sha256(
                "python -m unittest".encode("utf-8")
            ).hexdigest(),
            "count": 1,
        }
        diagnostic = {
            "schema": "sulde-worker-diagnostic-v1",
            "diagnostic_id": "nested-seatbelt-run",
            "scope_sha256": "d" * 64,
            "observed_at": "2026-09-04T01:00:00Z",
            "source": "nested_host",
            "outcome": "failed",
            "summary": "required test failed; exit 1; status: blocked",
        }
        supersession = {
            "schema": "sulde-worker-diagnostic-supersession-v1",
            "diagnostic_id": diagnostic["diagnostic_id"],
            "scope_sha256": diagnostic["scope_sha256"],
            "observed_at": "2026-09-04T02:00:00Z",
            "source": "coordinator",
            "success": success,
        }

        def rendered(
            diagnostic_row: dict[str, object],
            supersession_row: dict[str, object],
        ) -> str:
            records = "\n".join(
                (
                    "historical_diagnostic="
                    + json.dumps(
                        diagnostic_row, sort_keys=True, separators=(",", ":")
                    ),
                    "diagnostic_supersession="
                    + json.dumps(
                        supersession_row, sort_keys=True, separators=(",", ":")
                    ),
                )
            )
            return REPORT.replace("## 过程", records + "\n## 过程")

        report = rendered(diagnostic, supersession)
        verdict = module.task_report_verdict(report, contract)

        self.assertTrue(verdict["passed"], verdict)
        projection = verdict["diagnostic_projection"]
        self.assertEqual(projection["active_count"], 0)
        self.assertEqual(projection["invalid_count"], 0)
        self.assertEqual(projection["superseded_count"], 1)
        self.assertEqual(
            projection["report_sha256"],
            hashlib.sha256(report.encode("utf-8")).hexdigest(),
        )
        self.assertIn("required test failed; exit 1; status: blocked", report)

        cases = {
            "different-scope": {
                **supersession,
                "scope_sha256": "e" * 64,
            },
            "not-newer": {
                **supersession,
                "observed_at": diagnostic["observed_at"],
            },
            "not-stronger": {
                **supersession,
                "source": "worker",
            },
            "unbound-success": {
                **supersession,
                "success": {**success, "count": 2},
            },
        }
        for case, candidate in cases.items():
            with self.subTest(case=case):
                rejected = module.task_report_verdict(
                    rendered(diagnostic, candidate), contract
                )
                self.assertFalse(rejected["passed"], rejected)
                self.assertEqual(
                    rejected["diagnostic_projection"]["superseded_count"], 0
                )
                self.assertEqual(
                    rejected["diagnostic_projection"]["active_count"], 1
                )
                self.assertGreaterEqual(
                    rejected["diagnostic_projection"]["invalid_count"], 1
                )

    def test_task_report_verdict_rejects_duplicate_conflicting_or_unbound_success(self) -> None:
        module = load_runtime_module()
        contract = module.report_contract_for_brief("# Task\n\nDo the work.\n")
        contract["execution_binding_sha256"] = "b" * 64
        contract["enforce_current_execution_binding"] = True
        check = next(line for line in REPORT.splitlines() if line.startswith("✅"))

        duplicate = REPORT.replace(check, check + "\n" + check)
        verdict = module.task_report_verdict(duplicate, contract)
        self.assertFalse(verdict["passed"], verdict)
        self.assertIn("report repeats current-success command(s)", verdict["failures"])

        conflicting = REPORT.replace(
            check,
            check + "\n" + check.replace("count=1", "count=2"),
        )
        verdict = module.task_report_verdict(conflicting, contract)
        self.assertFalse(verdict["passed"], verdict)
        self.assertIn(
            "report records conflicting counts for repeated command(s)",
            verdict["failures"],
        )

        for field in (
            "candidate_sha256",
            "execution_binding_sha256",
            "environment_sha256",
            "command_sha256",
            "count",
        ):
            with self.subTest(missing=field):
                unbound = re.sub(rf"；{field}=[^；\n]+", "", REPORT)
                verdict = module.task_report_verdict(unbound, contract)
                self.assertFalse(verdict["passed"], verdict)
                self.assertIn(
                    "1 ✅ current-success check(s) lack candidate/execution/environment/command/count binding",
                    verdict["failures"],
                )

        drifted = REPORT.replace(
            "execution_binding_sha256=" + "b" * 64,
            "execution_binding_sha256=" + "d" * 64,
        )
        verdict = module.task_report_verdict(drifted, contract)
        self.assertFalse(verdict["passed"], verdict)
        self.assertIn(
            "report current-success execution binding does not match the run",
            verdict["failures"],
        )


if __name__ == "__main__":
    unittest.main()
