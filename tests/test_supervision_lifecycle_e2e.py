from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
import venv


ROOT = Path(__file__).resolve().parents[1]
STAGER = ROOT / "scripts" / "release" / "stage_plugin.py"

REPORT = """## 结果
任务完成。
✅ 验证通过：`python -m unittest`，exit 0；输出 OK；candidate_sha256=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa；execution_binding_sha256=bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb；environment_sha256=cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc；command_sha256=88d1e4ef3a5e210c702e32c1f294a637fcac036aae538cf3e0500c2c054b49c7；count=1
## 过程
按批准后的修订意图只修改 allowed.txt。
## 遇到的问题
首轮纠正触发暂停，人工重新确认后恢复。
## 解决方式
保留纠正事实并在新 revision 下重新执行。
## 遗留风险与建议
无已知风险。
"""


@unittest.skipIf(os.name == "nt", "the full process-tree journey requires POSIX")
class SupervisionLifecycleE2ETests(unittest.TestCase):
    """One staged-artifact vertical slice through every supervision subsystem."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.codex_stage = self.root / "codex-stage"
        self.claude_stage = self.root / "claude-stage"
        self.kb_home = self.root / "kb-home"
        self.workspace = self.root / "project"
        self.kb_home.mkdir()
        self.workspace.mkdir()
        venv.EnvBuilder(with_pip=False).create(self.kb_home / "venv")
        self._stage("codex", self.codex_stage, platform="posix")
        self._stage("claude", self.claude_stage)
        self.plugin = self.codex_stage / "plugins" / "sulde"
        self.runtime = self.plugin / "runtime"
        self.kb_scripts = self.runtime / "scripts" / "kb"
        self.guardian_cli = self.kb_scripts / "intent-guardian.py"
        self.observer_cli = self.kb_scripts / "event-observer.py"
        self.agent_runtime = self.kb_scripts / "agent-runtime.py"
        self.environment = os.environ.copy()
        for inherited_name in tuple(self.environment):
            if (
                inherited_name.startswith("SULDE_GUARDIAN_STREAM_")
                or inherited_name.startswith("SULDE_MANAGED_")
                or inherited_name
                in {"SULDE_INTENT_CONTRACT", "SULDE_KB_HOME"}
            ):
                self.environment.pop(inherited_name, None)
        self.environment.pop("SULDE_RELEASE_GIT_INDEX_FILE", None)
        self.environment.update(
            {
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_CONFIG_NOSYSTEM": "1",
                "SULDE_KB_HOME": str(self.kb_home),
                "SULDE_TEST_MODE": "1",
                "PYTHONDONTWRITEBYTECODE": "1",
                "SULDE_HOOK_OBSERVATION_SOURCE": "live_host_hook",
            }
        )
        self._git("init", "-q")
        self._git("config", "user.email", "e2e@example.invalid")
        self._git("config", "user.name", "Sulde E2E")
        (self.workspace / "allowed.txt").write_text("baseline\n", encoding="utf-8")
        self._git("add", "allowed.txt")
        self._git("commit", "-qm", "baseline")
        self.state = self.workspace / ".codex-agent"
        self.state.mkdir()
        self.slug = "supervision-e2e"
        self.brief = self.state / f"{self.slug}.md"
        self.brief.write_text(
            "# Task\n\n"
            "## 目标\n只在意图一致时更新 allowed.txt。\n\n"
            "## 范围\n涉及路径：allowed.txt\n禁止改动：其他产品文件。\n\n"
            "## 完成标准\n- allowed.txt 包含 approved。\n",
            encoding="utf-8",
        )
        self.brief.chmod(0o400)
        self.seed_contract = self.root / "approved-l3.intent.json"
        created = self._run(
            self.guardian_cli,
            "create-from-brief",
            str(self.brief),
            "--slug",
            self.slug,
            "--workspace",
            str(self.workspace),
            "--output",
            str(self.seed_contract),
            "--mode",
            "enforce",
        )
        self.assertEqual(created.returncode, 0, created.stdout + created.stderr)
        self.seed_contract.chmod(0o400)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _stage(self, target: str, output: Path, *, platform: str | None = None) -> None:
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
        environment = os.environ.copy()
        environment["GIT_CONFIG_GLOBAL"] = os.devnull
        environment["GIT_CONFIG_NOSYSTEM"] = "1"
        release_index = environment.pop("SULDE_RELEASE_GIT_INDEX_FILE", "")
        if release_index:
            environment["GIT_INDEX_FILE"] = release_index
        completed = subprocess.run(
            command,
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=environment,
            timeout=60,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def _git(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment["GIT_CONFIG_GLOBAL"] = os.devnull
        environment["GIT_CONFIG_NOSYSTEM"] = "1"
        return subprocess.run(
            ["git", *arguments],
            cwd=self.workspace,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
            env=environment,
        )

    def _run(
        self,
        script: Path,
        *arguments: str,
        environment: dict[str, str] | None = None,
        input_text: str | None = None,
        timeout: float = 30,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(script), *arguments],
            cwd=self.workspace,
            input=input_text,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=environment or self.environment,
            timeout=timeout,
            check=False,
        )

    def _observer(self, action: str, *arguments: str) -> dict:
        completed = self._run(
            self.observer_cli,
            action,
            *arguments,
            "--home",
            str(self.kb_home),
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        return json.loads(completed.stdout)

    def _codex_prompt(self, prompt: str, contract: Path, session: str) -> str:
        payload = {
            "sessionId": session,
            "cwd": str(self.workspace),
            "intent_contract": str(contract),
            "prompt": prompt,
        }
        environment = dict(self.environment)
        environment["SULDE_INTENT_CONTRACT"] = str(contract)
        completed = subprocess.run(
            ["bash", str(self.plugin / "scripts" / "run-hook.sh"), "user-prompt-submit"],
            cwd=self.workspace,
            input=json.dumps(payload, ensure_ascii=False),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=environment,
            timeout=30,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        value = json.loads(completed.stdout.strip().splitlines()[-1])
        return value["hookSpecificOutput"]["additionalContext"]

    def _wait_for(self, predicate, message: str, timeout: float = 8) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.02)
        self.fail(message)

    def _assert_dead(self, process_id: int) -> None:
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            try:
                os.kill(process_id, 0)
            except ProcessLookupError:
                return
            time.sleep(0.02)
        self.fail(f"managed descendant {process_id} survived quiescence")

    def test_staged_dual_host_correction_resume_observe_and_privacy_journey(self) -> None:
        # Publication parity: both host artifacts carry byte-identical shared organs.
        codex_kb = self.kb_scripts
        claude_kb = self.claude_stage / "scripts" / "kb"
        for name in (
            "host_capabilities.py",
            "execution_backend.py",
            "correction_intervention.py",
            "approval_invariant.py",
            "terminal_invariants.py",
            "event_observer.py",
            "event_projection_cache.py",
            "observation_privacy.py",
        ):
            with self.subTest(shared_runtime=name):
                self.assertEqual(
                    hashlib.sha256((codex_kb / name).read_bytes()).hexdigest(),
                    hashlib.sha256((claude_kb / name).read_bytes()).hexdigest(),
                )

        # Round 1: a live managed process is corrected, interrupted, and fully disposed.
        child_pid = self.state / "correction-child.pid"
        blocking_provider = self.root / "codex-blocking"
        blocking_provider.write_text(
            textwrap.dedent(
                f"""\
                #!/usr/bin/env python3
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
                Path({str(child_pid)!r}).write_text(str(child.pid), encoding='utf-8')
                time.sleep(60)
                """
            ),
            encoding="utf-8",
        )
        blocking_provider.chmod(0o755)
        run_environment = dict(self.environment)
        run_environment.update(
            {
                "SULDE_AGENT_PROVIDER": "codex",
                "SULDE_CODEX_EXE": str(blocking_provider),
            }
        )
        running = subprocess.Popen(
            [
                sys.executable,
                str(self.agent_runtime),
                "run",
                str(self.workspace),
                self.slug,
                str(self.brief),
                "--owned-path",
                "allowed.txt",
                "--guardian-mode",
                "enforce",
                "--intent-contract",
                str(self.seed_contract),
                "--timeout",
                "20",
            ],
            cwd=self.workspace,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=run_environment,
        )
        contract = self.state / f"{self.slug}.intent.json"
        run_ledger = self.state / f"{self.slug}.run.jsonl"
        run_status = self.state / f"{self.slug}.status"

        def provider_started() -> bool:
            if (
                contract.is_file()
                and child_pid.is_file()
                and run_ledger.is_file()
                and "execution.started" in run_ledger.read_text(errors="replace")
            ):
                return True
            if running.poll() is not None:
                stdout, stderr = running.communicate()
                self.fail(
                    "managed provider exited before the observable started boundary: "
                    + stdout
                    + stderr
                )
            if run_status.is_file():
                status_text = run_status.read_text(errors="replace")
                if not status_text.startswith("status=running"):
                    self.fail(
                        "managed provider stopped before the observable started boundary: "
                        + status_text
                        + (run_ledger.read_text(errors="replace") if run_ledger.is_file() else "")
                    )
            return False

        self._wait_for(
            provider_started,
            "managed provider did not reach the observable started boundary",
            timeout=20,
        )
        correction = self._run(
            self.guardian_cli,
            "correction-propose",
            "不是这个方向，请保留已经确认的表达",
            "--provider",
            "codex",
            "--session-id",
            f"managed:l3:{self.slug}",
            "--contract",
            str(contract),
        )
        self.assertEqual(correction.returncode, 0, correction.stdout + correction.stderr)
        stdout, stderr = running.communicate(timeout=15)
        self.assertEqual(running.returncode, 1, stdout + stderr)
        self._assert_dead(int(child_pid.read_text(encoding="utf-8")))
        paused_status = (self.state / f"{self.slug}.status").read_text(encoding="utf-8")
        self.assertTrue(
            paused_status.startswith("status=paused "),
            paused_status + stdout + stderr,
        )
        paused_guardian = json.loads(
            (self.state / f"{self.slug}.guardian.json").read_text(encoding="utf-8")
        )
        self.assertTrue(paused_guardian["execution"]["cleanup_quiescent"])
        self.assertEqual(paused_guardian["correction_interventions_by_state"]["applied"], 1)

        # A readable live-host decision revises the paused intent; no digest is copied by a human.
        proposed = self._run(
            self.guardian_cli,
            "propose-revision",
            str(contract),
            "--objective",
            "只按已确认的表达更新 allowed.txt",
            "--accept",
            "allowed.txt 包含 approved 且其他产品文件不变",
            "--preserve",
            "已经确认的表达",
            "--reject",
            "扩大到其他文件",
            "--allow-path",
            "allowed.txt",
            "--mode",
            "enforce",
            "--decision-route",
            "human",
            "--provider",
            "codex",
            "--session-id",
            "codex-review-thread",
        )
        self.assertEqual(proposed.returncode, 0, proposed.stdout + proposed.stderr)
        review = json.loads(proposed.stdout)
        self.assertNotIn("approval_prompt", review)
        self.assertNotIn("human_choices", review)
        self.assertEqual(review["decision_surface"]["type"], "PermissionRequest")
        previewed = self._run(
            self.guardian_cli,
            "native-decision-preview",
            "proposal",
            "--decision",
            "approve",
            "--target",
            "current",
            "--provider",
            "codex",
            "--session-id",
            "codex-review-thread",
            "--contract",
            str(contract),
        )
        self.assertEqual(previewed.returncode, 0, previewed.stdout + previewed.stderr)
        preview = json.loads(previewed.stdout)
        permission_payload = {
            "sessionId": "codex-review-thread",
            "cwd": str(self.workspace),
            "intent_contract": str(contract),
            "permissionMode": "default",
            "toolName": "Bash",
            "toolInput": {
                "command": shlex.join(preview["command_argv"]),
                "description": preview["description"],
            },
        }
        permission_environment = dict(self.environment)
        permission_environment["SULDE_INTENT_CONTRACT"] = str(contract)
        permission = subprocess.run(
            ["bash", str(self.plugin / "scripts" / "run-hook.sh"), "permission-request"],
            cwd=self.workspace,
            input=json.dumps(permission_payload, ensure_ascii=False),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=permission_environment,
            timeout=30,
            check=False,
        )
        self.assertEqual(permission.returncode, 0, permission.stdout + permission.stderr)
        self.assertFalse(permission.stdout.strip())
        applied = self._run(
            self.guardian_cli,
            *preview["argv"],
        )
        self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
        self.assertEqual(json.loads(applied.stdout)["status"], "applied")

        # Round 2: the same task/contract succeeds and the one terminal gate accepts it.
        successful_provider = self.root / "codex-success"
        successful_provider.write_text(
            textwrap.dedent(
                f"""\
                #!/usr/bin/env python3
                import sys
                from pathlib import Path
                args = sys.argv[1:]
                report = Path(args[args.index('--output-last-message') + 1])
                Path('allowed.txt').write_text('approved\\n', encoding='utf-8')
                report.write_text({REPORT!r}, encoding='utf-8')
                """
            ),
            encoding="utf-8",
        )
        successful_provider.chmod(0o755)
        run_environment["SULDE_CODEX_EXE"] = str(successful_provider)
        resumed = self._run(
            self.agent_runtime,
            "run",
            str(self.workspace),
            self.slug,
            str(self.brief),
            "--owned-path",
            "allowed.txt",
            "--guardian-mode",
            "enforce",
            "--intent-contract",
            str(self.seed_contract),
            "--timeout",
            "10",
            environment=run_environment,
        )
        self.assertEqual(
            resumed.returncode,
            0,
            resumed.stdout
            + resumed.stderr
            + (run_status.read_text(errors="replace") if run_status.is_file() else "")
            + (
                (self.state / f"{self.slug}.guardian.json").read_text(
                    errors="replace"
                )
                if (self.state / f"{self.slug}.guardian.json").is_file()
                else ""
            ),
        )
        verified = self._run(
            self.agent_runtime,
            "verify",
            str(self.workspace),
            self.slug,
            "--allowed-paths",
            r"allowed\.txt",
        )
        self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)
        self.assertIn("VERIFY: PASS", verified.stdout)
        final_guardian = json.loads(
            (self.state / f"{self.slug}.guardian.json").read_text(encoding="utf-8")
        )
        run_rows = [
            json.loads(line)
            for line in run_ledger.read_text(encoding="utf-8").splitlines()
        ]
        final_results = [
            row for row in run_rows if row.get("type") == "execution.result"
        ]
        final_disposals = [
            row for row in run_rows if row.get("type") == "execution.disposed"
        ]
        self.assertEqual(len(final_results), 1)
        self.assertEqual(final_results[0]["returncode"], 0)
        self.assertEqual(final_results[0]["stop_reason"], "completed")
        self.assertEqual(len(final_disposals), 1)
        self.assertTrue(final_disposals[0]["quiescent"])
        self.assertEqual(final_guardian["execution"]["returncode"], 0)
        self.assertEqual(final_guardian["execution"]["stop_reason"], "completed")
        self.assertTrue(final_guardian["execution"]["cleanup_quiescent"])
        self.assertTrue(
            run_status.read_text(encoding="utf-8").startswith(
                "status=success rc=0 "
            )
        )
        self.assertTrue(final_guardian["terminal_invariants"]["quiescent"])
        self.assertEqual(final_guardian["approvals_open"], 0)
        self.assertEqual(final_guardian["corrections_open"], 0)

        # A different host/session starts from a private shadow contract.  It
        # must not inherit even the completed Codex lane's task description.
        claude_hook = self.claude_stage / "hooks" / "user_prompt_submit.py"
        claude_environment = dict(self.environment)
        claude_environment["SULDE_INTENT_CONTRACT"] = str(contract)
        claude = self._run(
            claude_hook,
            environment=claude_environment,
            input_text=json.dumps(
                {
                    "client": "claude",
                    "session_id": "claude-shared-thread",
                    "cwd": str(self.workspace),
                    "intent_contract": str(contract),
                    "prompt": "检查已经完成的状态",
                },
                ensure_ascii=False,
            ),
        )
        self.assertEqual(claude.returncode, 0, claude.stdout + claude.stderr)
        self.assertIn("[sulde intent] ACTIVE", claude.stdout)
        self.assertIn("/intent/sessions/claude-", claude.stdout)
        self.assertNotIn("完成标准", claude.stdout)

        # Staged projection cache performs cold replay, exact reuse, then tail replay.
        notify_log = self.kb_home / "notify-log.jsonl"
        notify_log.write_text(
            json.dumps(
                {
                    "ts": "2026-08-15T10:00:00+08:00",
                    "message": "e2e initial",
                    "cwd": str(self.workspace),
                }
            )
            + "\n",
            encoding="utf-8",
        )
        observed = self._observer(
            "events", "--workspace", str(self.workspace), "--limit", "200"
        )
        approval_sources = [
            source
            for source in observed["sources"]
            if source.get("kind") == "approval-pair"
        ]
        self.assertEqual(len(approval_sources), 1)
        self.assertEqual(approval_sources[0]["invalid_rows"], 0)
        self.assertEqual(approval_sources[0]["unsupported_rows"], 0)
        self.assertTrue(
            all(
                source.get("status") == "healthy"
                for source in observed["sources"]
            ),
            json.dumps(observed["sources"], ensure_ascii=False, indent=2),
        )
        self.assertEqual(final_guardian["approval_outcomes"]["allow"], 1)
        self.assertEqual(final_guardian["approval_outcomes"]["approved"], 0)
        self.assertTrue(
            {"execution", "intent"}
            <= set(observed["summary"]["by_domain"])
        )
        cached = self._observer("summary", "--workspace", str(self.workspace))
        self.assertEqual(cached["projectionCache"]["status"], "hit")
        self.assertGreater(cached["projectionCache"]["sourcesReused"], 0)
        with notify_log.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "ts": "2026-08-15T10:00:01+08:00",
                        "message": "e2e tail",
                        "cwd": str(self.workspace),
                    }
                )
                + "\n"
            )
        tailed = self._observer("summary", "--workspace", str(self.workspace))
        self.assertEqual(tailed["projectionCache"]["status"], "tail_replay")
        self.assertGreater(tailed["projectionCache"]["sourcesTailReplayed"], 0)

        # One readable live approval exports the exact frozen redacted cut once.
        privacy = self._observer(
            "set-privacy", "--mode", "approved-export"
        )
        self.assertTrue(privacy["portableExportEnabled"])
        export_file = self.root / "portable-observation.json"
        card = self._observer(
            "prepare-export",
            "--contract",
            str(contract),
            "--workspace",
            str(self.workspace),
            "--limit",
            "200",
            "--output",
            str(export_file),
        )
        self.assertEqual(
            card["decisionSurface"]["codex"]["type"],
            "PermissionRequest",
        )
        export_previewed = self._run(
            self.guardian_cli,
            "native-decision-preview",
            "observation-export",
            "--decision",
            "approve",
            "--target",
            "current",
            "--provider",
            "codex",
            "--session-id",
            "codex-review-thread",
            "--contract",
            str(contract),
        )
        self.assertEqual(
            export_previewed.returncode,
            0,
            export_previewed.stdout + export_previewed.stderr,
        )
        export_preview = json.loads(export_previewed.stdout)
        export_permission_payload = {
            "sessionId": "codex-review-thread",
            "cwd": str(self.workspace),
            "intent_contract": str(contract),
            "permissionMode": "default",
            "toolName": "Bash",
            "toolInput": {
                "command": shlex.join(export_preview["command_argv"]),
                "description": export_preview["description"],
            },
        }
        export_permission_environment = dict(self.environment)
        export_permission_environment["SULDE_INTENT_CONTRACT"] = str(contract)
        export_permission = subprocess.run(
            ["bash", str(self.plugin / "scripts" / "run-hook.sh"), "permission-request"],
            cwd=self.workspace,
            input=json.dumps(export_permission_payload, ensure_ascii=False),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=export_permission_environment,
            timeout=30,
            check=False,
        )
        self.assertEqual(
            export_permission.returncode,
            0,
            export_permission.stdout + export_permission.stderr,
        )
        self.assertFalse(export_permission.stdout.strip())
        export_decision = self._run(
            self.guardian_cli,
            *export_preview["argv"],
        )
        self.assertEqual(
            export_decision.returncode,
            0,
            export_decision.stdout + export_decision.stderr,
        )
        self.assertEqual(json.loads(export_decision.stdout)["status"], "recorded")
        exported = self._observer(
            "export",
            "--contract",
            str(contract),
            "--proposal",
            card["proposalDigest"],
        )
        self.assertEqual(exported["status"], "completed")
        portable = json.loads(export_file.read_text(encoding="utf-8"))
        self.assertEqual(portable["sourceRevision"], card["dataCut"]["sourceRevision"])
        self.assertEqual(len(portable["events"]), card["dataCut"]["returnedEvents"])
        rendered_portable = json.dumps(portable, ensure_ascii=False)
        self.assertNotIn("不是这个方向", rendered_portable)
        self.assertNotIn(str(self.workspace), rendered_portable)

        # Disabled means no source scan/cache, not deleted authority or a healthy zero.
        authority_paths = (
            contract,
            self.state / f"{self.slug}.run.jsonl",
            self.state / f"{self.slug}.intent.events.jsonl",
            self.state / f"{self.slug}.intent.corrections.jsonl",
            self.state / f"{self.slug}.intent.approvals.jsonl",
        )
        authority_before = {
            str(path): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in authority_paths
            if path.is_file()
        }
        disabled = self._observer("set-privacy", "--mode", "disabled")
        self.assertFalse(disabled["observationEnabled"])
        unavailable = self._run(
            self.observer_cli,
            "verify",
            "--home",
            str(self.kb_home),
        )
        self.assertEqual(unavailable.returncode, 3, unavailable.stderr)
        disabled_snapshot = json.loads(unavailable.stdout)
        self.assertIsNone(disabled_snapshot["summary"]["events_total"])
        self.assertEqual(
            authority_before,
            {
                str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in authority_paths
                if path.is_file()
            },
        )

        # The packaged MCP observes the same disabled policy through its real launcher.
        requests = [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "e2e", "version": "1"},
                },
            },
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "event_observe",
                    "arguments": {"include_events": True},
                },
            },
        ]
        mcp = self._run(
            self.kb_scripts / "kb-mcp",
            input_text="".join(json.dumps(row) + "\n" for row in requests),
        )
        self.assertEqual(mcp.returncode, 0, mcp.stdout + mcp.stderr)
        responses = [json.loads(line) for line in mcp.stdout.splitlines() if line.strip()]
        mcp_payload = json.loads(responses[-1]["result"]["content"][0]["text"])
        self.assertEqual(mcp_payload["privacy"]["mode"], "disabled")
        self.assertEqual(mcp_payload["events"], [])

        restored = self._observer("set-privacy", "--mode", "local")
        self.assertTrue(restored["observationEnabled"])
        rebuilt = self._observer("summary", "--workspace", str(self.workspace))
        self.assertGreater(rebuilt["summary"]["events_total"], 0)
        self.assertEqual(rebuilt["projectionCache"]["status"], "full_rebuild")


if __name__ == "__main__":
    unittest.main()
